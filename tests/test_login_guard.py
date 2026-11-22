import tempfile
import time
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.api.main import create_app
from app.services.accounts import AccountLedger
from app.services.login_guard import LoginGuard


class TestLoginGuard(unittest.TestCase):

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)

        path = Path(temporary.name) / "login.db"
        self.ledger = AccountLedger(path)
        self.guard = LoginGuard(self.ledger)
        self.client = TestClient(create_app(path))

        self.email = "owner@example.test"
        self.password = "SecureTestPassword123!"

        self.ledger.register_owner(
            "Test Provision Shop",
            self.email,
            self.password,
        )

    def attempt(self, password):
        return self.client.post(
            "/api/v1/auth/login",
            json={
                "email": self.email,
                "password": password,
            },
        )

    def test_valid_login(self):
        response = self.attempt(self.password)
        self.assertEqual(response.status_code, 200)

    def test_five_failed_attempts_trigger_lockout(self):
        for _ in range(5):
            response = self.attempt("IncorrectPassword")
            self.assertEqual(response.status_code, 401)

        response = self.attempt("IncorrectPassword")
        self.assertEqual(response.status_code, 429)

    def test_correct_password_rejected_during_lockout(self):
        for _ in range(5):
            self.attempt("IncorrectPassword")

        response = self.attempt(self.password)
        self.assertEqual(response.status_code, 429)

    def test_successful_login_clears_failures(self):
        self.attempt("IncorrectPassword")
        self.attempt("IncorrectPassword")

        response = self.attempt(self.password)
        self.assertEqual(response.status_code, 200)

        key = self.guard._key(self.email)

        with self.ledger.connect() as db:
            row = db.execute(
                """SELECT * FROM login_attempts
                   WHERE identifier_hash = ?""",
                (key,),
            ).fetchone()

        self.assertIsNone(row)

    def test_lockout_expires(self):
        for _ in range(5):
            self.attempt("IncorrectPassword")

        key = self.guard._key(self.email)

        with self.ledger.connect() as db:
            db.execute(
                """UPDATE login_attempts
                   SET locked_until = ?
                   WHERE identifier_hash = ?""",
                (int(time.time()) - 1, key),
            )

        response = self.attempt(self.password)
        self.assertEqual(response.status_code, 200)


if __name__ == "__main__":
    unittest.main()
