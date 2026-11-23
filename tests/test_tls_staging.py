import base64
import hashlib
import http.client
import json
import os
import shutil
import socket
import ssl
import subprocess
import tempfile
import threading
import time
import unittest
from contextlib import ExitStack, closing
from pathlib import Path

import uvicorn

from app.api.main import create_app
from app.operations.staging import invite, monitor
from app.services.account_mail import AccountMail
from tests.test_dashboard_recovery import find_chromium


ROOT = Path(__file__).resolve().parents[1]


def find_caddy():
    return os.environ.get("KUDILEDGER_CADDY") or shutil.which("caddy")


def find_openssl():
    git = Path("C:/Program Files/Git/usr/bin/openssl.exe")
    return shutil.which("openssl") or (str(git) if git.is_file() else None)


def free_port():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def wait_for(check):
    for _ in range(100):
        try:
            result = check()
            if result:
                return result
        except OSError:
            pass
        time.sleep(0.1)
    raise AssertionError("The loopback staging service did not become ready")


def shutdown(process):
    if process.poll() is None:
        process.terminate()
        process.wait(timeout=10)


class TestTLSStaging(unittest.TestCase):
    @unittest.skipUnless(find_caddy(), "Set KUDILEDGER_CADDY to run the loopback TLS staging test")
    def test_real_tls_proxy_headers_csp_and_browser(self):
        with tempfile.TemporaryDirectory() as folder, ExitStack() as cleanup:
            root = Path(folder)
            database = root / "staging.sqlite"
            outbox = root / "mail"
            outbox.mkdir()
            tls_port, http_port = free_port(), free_port()
            origin = f"https://localhost:{tls_port}"
            mail = AccountMail(mode="capture", origin=origin, directory=outbox)
            backend = cleanup.enter_context(socket.socket())
            backend.bind(("127.0.0.1", 0))
            backend_port = backend.getsockname()[1]
            server = uvicorn.Server(uvicorn.Config(
                create_app(database, require_https=True, account_mail=mail), log_level="warning",
                access_log=False, proxy_headers=True, forwarded_allow_ips="127.0.0.1",
            ))
            worker = threading.Thread(target=server.run, kwargs={"sockets": [backend]}, daemon=True)
            worker.start()
            cleanup.callback(worker.join, 10)
            cleanup.callback(setattr, server, "should_exit", True)
            wait_for(lambda: server.started)

            proxy_log = cleanup.enter_context((root / "caddy.log").open("wb"))
            proxy = subprocess.Popen(
                [find_caddy(), "run", "--config", str(ROOT / "deploy/staging/Caddyfile"),
                 "--adapter", "caddyfile"],
                stdout=proxy_log, stderr=subprocess.STDOUT,
                env={**os.environ, "XDG_DATA_HOME": str(root / "data"), "XDG_CONFIG_HOME": str(root / "config"),
                     "KUDILEDGER_UPSTREAM": f"127.0.0.1:{backend_port}",
                     "KUDILEDGER_SITE": origin, "KUDILEDGER_HTTP_PORT": str(http_port),
                     "KUDILEDGER_BIND": "127.0.0.1"},
            )
            cleanup.callback(shutdown, proxy)
            ca = root / "data/caddy/pki/authorities/local/root.crt"
            try:
                wait_for(ca.is_file)
            except AssertionError:
                self.fail((root / "caddy.log").read_text(encoding="utf-8", errors="replace"))
            context = ssl.create_default_context(cafile=str(ca))

            def https(path, *, method="GET", headers=None, body=None):
                conn = http.client.HTTPSConnection("localhost", tls_port, context=context, timeout=3)
                with closing(conn):
                    conn.request(method, path, body=body, headers=headers or {})
                    response = conn.getresponse()
                    response.read()
                    return response.status, dict(response.getheaders())

            status, headers = wait_for(lambda: https("/app", headers={"X-Forwarded-Proto": "http"}))
            self.assertEqual(status, 200)
            headers = {key.lower(): value for key, value in headers.items()}
            self.assertIn("max-age=31536000", headers["strict-transport-security"])
            self.assertEqual(headers["x-frame-options"], "DENY")
            self.assertIn("script-src 'sha256-", headers["content-security-policy"])
            self.assertEqual(headers["cache-control"], "no-store")
            self.assertEqual(monitor(database, origin, str(ca))["alerts"], [])

            clear = http.client.HTTPConnection("127.0.0.1", backend_port, timeout=3)
            with closing(clear):
                clear.request("GET", "/app")
                self.assertEqual(clear.getresponse().status, 400)
            redirect = http.client.HTTPConnection("localhost", http_port, timeout=3)
            with closing(redirect):
                redirect.request("GET", "/app")
                response = redirect.getresponse()
                self.assertEqual(response.status, 308)
                self.assertEqual(response.getheader("Location"), origin + "/app")

            if find_chromium() and find_openssl() and shutil.which("node"):
                self.browser(cleanup, root, context, tls_port, database, outbox, mail)
            elif os.environ.get("KUDILEDGER_REQUIRE_STAGING_BROWSER") == "1":
                self.fail("Chromium, Node and OpenSSL are required for the staging browser test")

            # The edge must replace client-supplied addresses before rate limiting.
            browser_ran = bool(find_chromium() and find_openssl() and shutil.which("node"))
            available = 7 if browser_ran else 8
            for index in range(available + 1):
                status, _ = https("/api/v1/auth/password-reset", method="POST", headers={
                    "Content-Type": "application/json", "X-Forwarded-For": f"192.0.2.{index + 1}",
                }, body=json.dumps({"email": f"unknown-{index}@example.test"}))
                self.assertEqual(status, 202 if index < available else 429)

    def browser(self, cleanup, root, context, port, database, outbox, mail):
        with socket.create_connection(("localhost", port), timeout=3) as connection:
            with context.wrap_socket(connection, server_hostname="localhost") as tls:
                cert = tls.getpeercert(binary_form=True)
        public_key = subprocess.check_output(
            [find_openssl(), "x509", "-inform", "DER", "-pubkey", "-noout"], input=cert,
        )
        spki = subprocess.check_output([find_openssl(), "pkey", "-pubin", "-outform", "DER"], input=public_key)
        pin = base64.b64encode(hashlib.sha256(spki).digest()).decode()
        email = "tls@example.test"
        invite(database, email, "TLS Synthetic Pilot", mail)
        captured = json.loads(next(outbox.glob("*.json")).read_text(encoding="utf-8"))
        profile = root / "chrome"
        chrome = subprocess.Popen(
            [find_chromium(), "--headless", "--no-first-run", "--disable-background-networking",
             "--remote-debugging-port=0", f"--user-data-dir={profile}",
             f"--ignore-certificate-errors-spki-list={pin}", "about:blank"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        cleanup.callback(shutdown, chrome)
        debugger = profile / "DevToolsActivePort"
        details = wait_for(lambda: debugger.read_text().splitlines())
        result = subprocess.run(
            ["node", str(Path(__file__).with_suffix(".js"))],
            input=json.dumps({"debugPort": details[0], "invitation": captured["link"], "email": email,
                              "outbox": str(outbox), "screenshots": os.environ.get("KUDILEDGER_RC_SCREENSHOTS", "")}),
            capture_output=True, text=True, encoding="utf-8", timeout=45, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("390 px and 1440 px", result.stdout)
        print(result.stdout.strip())
