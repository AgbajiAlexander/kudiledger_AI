import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient
from app.api.main import create_app


class TestTraderDashboard(unittest.TestCase):

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        path = Path(temporary.name) / "dashboard.db"
        self.client = TestClient(create_app(path))

    def test_dashboard_available(self):
        response = self.client.get("/app")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response.headers["content-type"])
        self.assertIn("KudiLedger AI", response.text)

    def test_dashboard_has_login_form(self):
        response = self.client.get("/app")
        self.assertIn('id="login-form"', response.text)
        self.assertNotIn('id="business-id"', response.text)
        self.assertIn('/api/v1/auth/businesses', response.text)

    def test_dashboard_has_reporting_sections(self):
        response = self.client.get("/app")
        self.assertIn('id="customers"', response.text)
        self.assertIn('id="expense-list"', response.text)
        self.assertIn('id="gross-sales"', response.text)

    def test_dashboard_requires_no_credentials_to_load(self):
        response = self.client.get("/app")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.headers.get("cache-control"), "no-store"
        )

    def test_financial_api_still_requires_authentication(self):
        response = self.client.get(
            "/api/v1/businesses/demo/customers"
        )
        self.assertEqual(response.status_code, 401)

    def test_health_endpoint_unchanged(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["application"], "KudiLedger AI"
        )


if __name__ == "__main__":
    unittest.main()
