import base64
import hashlib
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.api.main import create_app


class TestPilotSecurity(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.database = Path(folder.name) / "pilot-security.db"

    def test_pilot_rejects_http_and_accepts_https(self):
        app = create_app(self.database, require_https=True)
        with TestClient(app) as http_client:
            self.assertEqual(http_client.get("/app").status_code, 400)
            refused = http_client.get("/api/v1/auth/businesses")
            self.assertEqual(refused.status_code, 400)
            self.assertEqual(refused.headers["cache-control"], "no-store")
            self.assertNotIn("strict-transport-security", refused.headers)
        with TestClient(app, base_url="https://testserver") as https_client:
            page = https_client.get("/app")
            self.assertEqual(page.status_code, 200)
            self.assertEqual(page.headers["strict-transport-security"], "max-age=31536000")
            self.assertEqual(page.headers["x-frame-options"], "DENY")
            self.assertEqual(page.headers["x-content-type-options"], "nosniff")
            self.assertEqual(page.headers["referrer-policy"], "no-referrer")
            auth = https_client.get("/api/v1/auth/businesses")
            self.assertEqual(auth.status_code, 401)
            self.assertEqual(auth.headers["cache-control"], "no-store")

    def test_dashboard_csp_authorizes_exact_embedded_scripts_and_styles(self):
        with TestClient(create_app(self.database, require_https=False)) as client:
            page = client.get("/app")
        policy = page.headers["content-security-policy"]
        self.assertIn("default-src 'none'", policy)
        self.assertIn("frame-ancestors 'none'", policy)
        self.assertNotIn("unsafe-inline", policy)
        for element in ("script", "style"):
            blocks = re.findall(rf"<{element}\b[^>]*>(.*?)</{element}>", page.text, re.DOTALL)
            self.assertTrue(blocks)
            for block in blocks:
                digest = base64.b64encode(hashlib.sha256(block.encode()).digest()).decode()
                self.assertIn("'sha256-" + digest + "'", policy)

    def test_environment_setting_rejects_typos(self):
        with patch.dict("os.environ", {"KUDILEDGER_REQUIRE_HTTPS": "yes"}):
            with self.assertRaisesRegex(ValueError, "must be 0 or 1"):
                create_app(self.database)
