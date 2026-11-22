import hashlib
import tempfile
import time
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.api.main import create_app
from app.services.accounts import AccountLedger


class TestSessionSecurity(unittest.TestCase):

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)

        database = Path(temporary.name) / "security.db"

        self.ledger = AccountLedger(database)
        self.client = TestClient(create_app(database))

        self.owner_a = self.ledger.register_owner(
            "Test Abuja Shop A",
            "security-a@example.test",
            "SecurityPassword123!"
        )

        self.owner_b = self.ledger.register_owner(
            "Test Abuja Shop B",
            "security-b@example.test",
            "AnotherSecurityPassword456!"
        )

        self.token_a = self.ledger.login(
            "security-a@example.test",
            "SecurityPassword123!"
        )

        self.token_b = self.ledger.login(
            "security-b@example.test",
            "AnotherSecurityPassword456!"
        )

    def headers(self, token):
        return {
            "Authorization": f"Bearer {token}"
        }

    def customer_url(self):
        business = self.owner_a["business_id"]
        return f"/api/v1/businesses/{business}/customers"

    def test_valid_token_allows_access(self):
        response = self.client.post(
            self.customer_url(),
            json={"name": "Musa"},
            headers=self.headers(self.token_a),
        )

        self.assertEqual(response.status_code, 201)

    def test_invalid_token_returns_401(self):
        response = self.client.post(
            self.customer_url(),
            json={"name": "Musa"},
            headers=self.headers("invalid-token"),
        )

        self.assertEqual(response.status_code, 401)

    def test_expired_token_returns_401(self):
        token_hash = hashlib.sha256(
            self.token_a.encode("utf-8")
        ).hexdigest()

        with self.ledger.connect() as db:
            db.execute(
                """UPDATE sessions
                   SET expires_at = ?
                   WHERE token_hash = ?""",
                (int(time.time()) - 60, token_hash),
            )

        response = self.client.post(
            self.customer_url(),
            json={"name": "Musa"},
            headers=self.headers(self.token_a),
        )

        self.assertEqual(response.status_code, 401)

    def test_other_business_owner_returns_403(self):
        response = self.client.post(
            self.customer_url(),
            json={"name": "Musa"},
            headers=self.headers(self.token_b),
        )

        self.assertEqual(response.status_code, 403)


if __name__ == "__main__":
    unittest.main()
