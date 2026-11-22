import tempfile
import unittest
from pathlib import Path

from app.services.accounts import AccountLedger


class TestBusinessAccounts(unittest.TestCase):

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)

        database = Path(temp.name) / "accounts.db"
        self.app = AccountLedger(database)

        self.owner_a = self.app.register_owner(
            "Abuja Shop A",
            "owner-a@example.test",
            "SecurePassword123!"
        )

        self.owner_b = self.app.register_owner(
            "Abuja Shop B",
            "owner-b@example.test",
            "AnotherSecurePassword456!"
        )

        self.token_a = self.app.login(
            "owner-a@example.test",
            "SecurePassword123!"
        )

        self.token_b = self.app.login(
            "owner-b@example.test",
            "AnotherSecurePassword456!"
        )

    def test_owner_registration(self):
        self.assertNotEqual(
            self.owner_a["business_id"],
            self.owner_b["business_id"]
        )

    def test_password_not_stored_in_plaintext(self):
        with self.app.connect() as db:
            row = db.execute(
                "SELECT password_hash FROM users LIMIT 1"
            ).fetchone()

        self.assertNotEqual(
            row["password_hash"],
            "SecurePassword123!"
        )

    def test_wrong_password_rejected(self):
        with self.assertRaises(ValueError):
            self.app.login(
                "owner-a@example.test", "WrongPassword!"
            )

    def test_duplicate_email_rejected(self):
        with self.assertRaises(ValueError):
            self.app.register_owner(
                "Duplicate Shop",
                "OWNER-A@example.test",
                "SecurePassword789!"
            )

    def test_authorized_customer_and_sale(self):
        business = self.owner_a["business_id"]

        customer = self.app.add_customer(
            self.token_a, business, "Musa"
        )

        self.app.add_sale(
            self.token_a, business, customer,
            "SALE-001", "15000", "10000",
            confirmed=True
        )

        self.assertEqual(
            self.app.get_balance(
                self.token_a, business, customer
            ),
            5000
        )

    def test_cross_business_access_denied(self):
        business_a = self.owner_a["business_id"]

        customer = self.app.add_customer(
            self.token_a, business_a, "Musa"
        )

        with self.assertRaises(PermissionError):
            self.app.get_balance(
                self.token_b, business_a, customer
            )

        with self.assertRaises(PermissionError):
            self.app.add_sale(
                self.token_b, business_a, customer,
                "SALE-001", "15000", "10000",
                confirmed=True
            )

        with self.assertRaises(PermissionError):
            self.app.add_repayment(
                self.token_b, business_a, customer,
                "PAY-001", "1000",
                confirmed=True
            )

    def test_logout_revokes_access(self):
        business = self.owner_a["business_id"]

        self.app.logout(self.token_a)

        with self.assertRaises(PermissionError):
            self.app.add_customer(
                self.token_a, business, "Musa"
            )

    def test_unauthenticated_access_rejected(self):
        with self.assertRaises(PermissionError):
            self.app.add_customer(
                "", self.owner_a["business_id"], "Musa"
            )


if __name__ == "__main__":
    unittest.main()
