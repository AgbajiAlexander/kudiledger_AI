import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.api.main import create_app
from app.services.reports import ReportLedger


class TestBusinessIdentityAPI(unittest.TestCase):

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)

        self.path = Path(temp.name) / "identity.db"
        self.ledger = ReportLedger(self.path)
        self.client = TestClient(create_app(self.path))

        owner = self.ledger.register_owner(
            "Abuja Market Shop",
            "identity-owner@example.test",
            "SecureTestPassword123!",
        )
        self.business = owner["business_id"]
        self.token = self.ledger.login(
            "identity-owner@example.test",
            "SecureTestPassword123!",
        )

    def headers(self, token=None):
        return {
            "Authorization": f"Bearer {token or self.token}"
        }

    def test_owner_discovers_registered_business(self):
        response = self.client.get(
            "/api/v1/auth/businesses",
            headers=self.headers(),
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()), 1)

        business = response.json()[0]
        self.assertEqual(business["id"], self.business)
        self.assertEqual(business["name"], "Abuja Market Shop")
        self.assertEqual(business["role"], "OWNER")

    def test_missing_token_rejected(self):
        response = self.client.get(
            "/api/v1/auth/businesses"
        )
        self.assertEqual(response.status_code, 401)

    def test_invalid_token_rejected(self):
        response = self.client.get(
            "/api/v1/auth/businesses",
            headers={"Authorization": "Bearer invalid-token"},
        )
        self.assertEqual(response.status_code, 401)

    def test_other_owner_business_not_exposed(self):
        other = self.ledger.register_owner(
            "Other Market Shop",
            "other-identity@example.test",
            "AnotherSecurePassword456!",
        )
        other_token = self.ledger.login(
            "other-identity@example.test",
            "AnotherSecurePassword456!",
        )

        response = self.client.get(
            "/api/v1/auth/businesses",
            headers=self.headers(),
        )
        ids = [item["id"] for item in response.json()]
        self.assertNotIn(other["business_id"], ids)

        other_response = self.client.get(
            "/api/v1/auth/businesses",
            headers=self.headers(other_token),
        )
        self.assertEqual(other_response.status_code, 200)
        self.assertEqual(
            other_response.json()[0]["id"],
            other["business_id"],
        )

    def test_logged_out_token_rejected(self):
        self.ledger.logout(self.token)

        response = self.client.get(
            "/api/v1/auth/businesses",
            headers=self.headers(),
        )
        self.assertEqual(response.status_code, 401)


if __name__ == "__main__":
    unittest.main()
