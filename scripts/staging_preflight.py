"""Read-only, redacted checks for approved Linux staging hosts and their HTTPS edge."""

import argparse
import http.client
import os
import re
import ssl
import stat
from contextlib import closing
from pathlib import Path
from urllib.parse import urlsplit


class PreflightError(ValueError):
    pass


def require(condition, label):
    if not condition:
        raise PreflightError(label)


def private(path, owner, *, directory=False):
    require(path.is_absolute() and path.resolve() == path and
            not path.is_relative_to(Path(__file__).resolve().parents[1]), "private path location")
    metadata = path.stat()
    expected = stat.S_ISDIR if directory else stat.S_ISREG
    require(expected(metadata.st_mode) and metadata.st_uid == owner and
            metadata.st_mode & 0o077 == 0 and
            metadata.st_mode & (0o700 if directory else 0o400) == (0o700 if directory else 0o400),
            "private path type, owner and mode")


def origin_url(value):
    try:
        url = urlsplit(value)
        require(url.scheme == "https" and url.hostname and not url.username and
                url.netloc == url.hostname + (f":{url.port}" if url.port else "") and
                not url.path and not url.query and not url.fragment and
                re.fullmatch(r"[a-z0-9][a-z0-9.-]*", url.hostname) and
                value == f"https://{url.netloc}", "bare HTTPS origin")
    except ValueError:
        raise PreflightError("bare HTTPS origin") from None
    return url


def check_config(path, service_uid, expected_origin):
    private(path, 0)
    settings = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        name, sep, value = line.partition("=")
        # Match the simple unquoted assignments documented for this deployment.
        require(sep and re.fullmatch(r"[A-Z][A-Z0-9_]*", name) and name not in settings and
                re.fullmatch(r"[A-Za-z0-9_./:@+%,-]+", value), "environment assignment syntax")
        settings[name] = value

    require(settings.get("KUDILEDGER_REQUIRE_HTTPS") == "1", "HTTPS environment enforcement")
    origin_url(settings.get("KUDILEDGER_PUBLIC_ORIGIN", ""))
    require(settings["KUDILEDGER_PUBLIC_ORIGIN"] == expected_origin, "configured HTTPS origin")
    mode = settings.get("KUDILEDGER_MAIL_MODE")
    require(mode in {"capture", "smtp"}, "account mail mode")
    database = Path(settings.get("KUDILEDGER_DB", ""))
    backup = Path(settings.get("KUDILEDGER_BACKUP_DIR", ""))
    require(database.parent == Path("/var/lib/kudiledger") and backup == Path("/var/backups/kudiledger"),
            "systemd writable path alignment")
    private(database.parent, service_uid, directory=True)
    private(database, service_uid)
    require(database.stat().st_mode & 0o200, "database writable by service owner")
    for suffix in ("-wal", "-shm", "-journal"):
        sidecar = database.with_name(database.name + suffix)
        if os.path.lexists(sidecar):
            private(sidecar, service_uid)
    private(backup, service_uid, directory=True)
    if mode == "capture":
        capture = Path(settings.get("KUDILEDGER_MAIL_CAPTURE_DIR", ""))
        require(capture.is_relative_to(database.parent) and capture != database.parent,
                "capture directory alignment")
        private(capture, service_uid, directory=True)
    else:
        require(all(settings.get("KUDILEDGER_SMTP_" + key) for key in ("HOST", "USER", "FROM")),
                "SMTP sender settings")
        port = settings.get("KUDILEDGER_SMTP_PORT", "465")
        require(port.isdecimal() and len(port) <= 5 and 1 <= int(port) <= 65535, "SMTP port")
        secret = Path(settings.get("KUDILEDGER_SMTP_PASSWORD_FILE", ""))
        require(secret != path and secret != database, "separate SMTP secret file")
        private(secret, service_uid)


def reply(connection, path, headers=None):
    with closing(connection):
        connection.request("GET", path, headers=headers or {})
        response = connection.getresponse()
        return response.status, response.headers


def check_edge(origin, *, http_port=80, context=None):
    url = origin_url(origin)
    context = context or ssl.create_default_context()
    require(context.check_hostname and context.verify_mode == ssl.CERT_REQUIRED, "verified TLS context")
    status, headers = reply(http.client.HTTPSConnection(url.hostname, url.port, timeout=8, context=context),
                            "/app", {"X-Forwarded-Proto": "http", "Forwarded": "proto=http"})
    require(status == 200, "HTTPS dashboard with conflicting client proxy headers")
    require(headers.get("Strict-Transport-Security", "").split(";")[0] == "max-age=31536000" and
            headers.get("X-Frame-Options") == "DENY" and headers.get("X-Content-Type-Options") == "nosniff" and
            headers.get("Referrer-Policy") == "no-referrer" and headers.get("Cache-Control") == "no-store",
            "HTTPS dashboard security headers")
    directives = headers.get("Content-Security-Policy", "").split(";")
    csp = {part.strip().split(" ", 1)[0]: part.strip() for part in directives}
    require(csp.get("default-src") == "default-src 'none'" and csp.get("frame-ancestors") == "frame-ancestors 'none'"
            and csp.get("connect-src") == "connect-src 'self'" and len(directives) == len(csp)
            and re.fullmatch(r"script-src 'sha256-[A-Za-z0-9+/]{43}='", csp.get("script-src", "")),
            "dashboard content security policy")
    status, headers = reply(http.client.HTTPConnection(url.hostname, http_port, timeout=8), "/app",
                            {"X-Forwarded-Proto": "https", "Forwarded": "proto=https"})
    require(status in (301, 308) and headers.get("Location") == origin + "/app",
            "HTTP redirect with conflicting client proxy headers")
    status, _ = reply(http.client.HTTPSConnection(url.hostname, url.port, timeout=8, context=context), "/health")
    require(status == 200, "HTTPS health endpoint")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("origin", help="Approved bare HTTPS origin")
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument("--edge", action="store_true", help="Probe from an independent network")
    choice.add_argument("--env-file", type=Path, help="Check the approved host environment and private files")
    args = parser.parse_args()
    try:
        origin_url(args.origin)
        if args.edge:
            check_edge(args.origin)
            print("PASS HTTPS edge, redirect, conflicting scheme headers and dashboard headers")
        else:
            if os.name != "posix":
                raise PreflightError("host file inspection requires Linux")
            import pwd

            check_config(args.env_file, pwd.getpwnam("kudiledger").pw_uid, args.origin)
            print("PASS private file ownership, modes and staging environment")
    except PreflightError as error:
        parser.exit(1, f"FAIL {error}\n")
    except (OSError, KeyError, ValueError, RuntimeError, http.client.HTTPException):
        parser.exit(1, "FAIL required host account, file or verified endpoint unavailable; inspect locally\n")


if __name__ == "__main__":
    main()
