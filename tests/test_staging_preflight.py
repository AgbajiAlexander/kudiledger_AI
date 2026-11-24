import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.staging_preflight import PreflightError, check_config, check_edge, origin_url, private


ORIGIN = "https://staging.example.test"
SETTINGS = """KUDILEDGER_REQUIRE_HTTPS=1
KUDILEDGER_PUBLIC_ORIGIN=https://staging.example.test
KUDILEDGER_DB=/var/lib/kudiledger/staging.sqlite
KUDILEDGER_BACKUP_DIR=/var/backups/kudiledger
KUDILEDGER_MAIL_MODE=smtp
KUDILEDGER_SMTP_HOST=mail.example.test
KUDILEDGER_SMTP_PORT=2465
KUDILEDGER_SMTP_USER=synthetic
KUDILEDGER_SMTP_FROM=demo@example.test
KUDILEDGER_SMTP_PASSWORD_FILE=/etc/kudiledger/mail.secret
"""


class TestStagingPreflight(unittest.TestCase):
    def test_rejects_non_https_and_origins_with_credentials_paths_or_query(self):
        for origin in ("http://example.test", ORIGIN + "/app", ORIGIN + "?x=1",
                       "https://user@example.test", ORIGIN + ":"):
            with self.subTest(origin=origin), self.assertRaises(PreflightError):
                origin_url(origin)

    def test_private_file_rejects_group_read_and_symlink(self):
        if os.name != "posix":
            path = Path(tempfile.gettempdir()).resolve() / "private"
            with patch.object(Path, "stat") as info:
                info.return_value.st_mode = 0o100640
                info.return_value.st_uid = 1000
                with self.assertRaisesRegex(PreflightError, "type, owner and mode"):
                    private(path, 1000)
            return
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "private"
            path.touch(mode=0o600)
            private(path, os.getuid())
            link = path.with_name("linked")
            link.symlink_to(path)
            with self.assertRaises(PreflightError):
                private(link, os.getuid())
            path.chmod(0o640)
            with self.assertRaises(PreflightError):
                private(path, os.getuid())

    def test_environment_matches_units_and_never_echoes_invalid_values(self):
        with tempfile.TemporaryDirectory() as folder:
            env = Path(folder) / "staging.env"
            env.write_text(SETTINGS, encoding="utf-8")
            with patch("scripts.staging_preflight.private") as inspect, patch.object(Path, "stat") as info:
                info.return_value.st_mode = 0o600
                check_config(env, 1000, ORIGIN)
                inspect.assert_any_call(Path("/etc/kudiledger/mail.secret"), 1000)
                cases = (
                    (SETTINGS.replace("HTTPS=1", "HTTPS=0"), "HTTPS environment enforcement"),
                    (SETTINGS + "KUDILEDGER_SMTP_USER=do-not-print\n", "environment assignment syntax"),
                    (SETTINGS.replace("/var/backups/kudiledger", "/tmp/backup"), "systemd writable path alignment"),
                    (SETTINGS.replace("2465", "99999"), "SMTP port"),
                )
                for content, reason in cases:
                    env.write_text(content, encoding="utf-8")
                    with self.subTest(reason=reason), self.assertRaisesRegex(PreflightError, "^" + reason + "$"):
                        check_config(env, 1000, ORIGIN)

    def test_edge_rejects_missing_headers_and_nonmatching_redirect(self):
        with patch("scripts.staging_preflight.reply", return_value=(200, {})):
            with self.assertRaisesRegex(PreflightError, "security headers"):
                check_edge(ORIGIN)
        dashboard = {
            "Strict-Transport-Security": "max-age=31536000",
            "X-Frame-Options": "DENY", "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer", "Cache-Control": "no-store",
            "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'; "
                                       "connect-src 'self'; script-src 'sha256-" + "A" * 43 + "='",
        }
        with patch("scripts.staging_preflight.reply", side_effect=[
            (200, dashboard), (308, {"Location": "https://wrong.example.test/app"}),
        ]):
            with self.assertRaisesRegex(PreflightError, "HTTP redirect"):
                check_edge(ORIGIN)
        dashboard["Content-Security-Policy"] += "; script-src 'unsafe-inline'"
        with patch("scripts.staging_preflight.reply", return_value=(200, dashboard)):
            with self.assertRaisesRegex(PreflightError, "content security policy"):
                check_edge(ORIGIN)
