import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.api.main import create_app
from app.services.statements import StatementLedger


class TestStatementAPI(unittest.TestCase):

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)

        db_path = Path(temp.name) / "statement_api.db"
        self.ledger = StatementLedger(db_path)
        self.client = TestClient(create_app(db_path))

        owner = self.ledger.register_owner(
            "Abuja Test Shop",
            "statement-api@example.test",
            "SecureTestPassword123!",
        )
        self.business = owner["business_id"]

        self.token = self.ledger.login(
            "statement-api@example.test",
            "SecureTestPassword123!",
        )

        self.customer = self.ledger.add_customer(
            self.token, self.business, "Musa"
        )

        other = self.ledger.register_owner(
            "Other Test Shop",
            "other-api@example.test",
            "AnotherSecurePassword456!",
        )
        self.other_business = other["business_id"]
        self.other_token = self.ledger.login(
            "other-api@example.test",
            "AnotherSecurePassword456!",
        )

    def url(self, business=None, customer=None):
        business = business or self.business
        customer = customer or self.customer

        return (
            f"/api/v1/businesses/{business}/customers/"
            f"{customer}/statement"
        )

    def headers(self, token=None):
        return {
            "Authorization": f"Bearer {token or self.token}"
        }

    def add_sale(self, paid="10000"):
        return self.ledger.add_sale(
            self.token,
            self.business,
            self.customer,
            "SALE-001",
            "15000",
            paid,
            confirmed=True,
        )

    def test_empty_statement(self):
        response = self.client.get(
            self.url(), headers=self.headers()
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["transaction_count"], 0
        )
        self.assertEqual(
            response.json()["closing_balance"], "0"
        )

    def test_sale_statement(self):
        self.add_sale()

        response = self.client.get(
            self.url(), headers=self.headers()
        )

        self.assertEqual(response.status_code, 200)
        result = response.json()

        self.assertEqual(result["closing_balance"], "5000")
        self.assertTrue(result["reconciled"])
        self.assertEqual(
            result["transactions"][0]["type"], "SALE"
        )

    def test_repayment_and_adjustment_statement(self):
        self.add_sale()

        self.ledger.add_repayment(
            self.token,
            self.business,
            self.customer,
            "PAY-001",
            "2000",
            confirmed=True,
        )

        self.ledger.adjust_customer_balance(
            self.token,
            self.business,
            self.customer,
            "ADJ-001",
            "-500",
            "Correction verified against shop records",
            confirmed=True,
        )

        response = self.client.get(
            self.url(), headers=self.headers()
        )

        self.assertEqual(response.status_code, 200)
        result = response.json()

        self.assertEqual(result["transaction_count"], 3)
        self.assertEqual(result["closing_balance"], "2500")
        self.assertTrue(result["reconciled"])

    def test_reversed_sale_statement(self):
        sale_id = self.add_sale(paid="0")

        self.ledger.reverse_unpaid_sale(
            self.token,
            self.business,
            sale_id,
            "REV-001",
            "Duplicate unpaid sale entered in error",
            confirmed=True,
        )

        response = self.client.get(
            self.url(), headers=self.headers()
        )

        self.assertEqual(response.status_code, 200)
        result = response.json()

        self.assertEqual(result["closing_balance"], "0")
        self.assertTrue(result["reconciled"])
        self.assertEqual(result["transaction_count"], 2)

    def test_unauthenticated_request_rejected(self):
        response = self.client.get(self.url())
        self.assertEqual(response.status_code, 401)

    def test_other_business_owner_rejected(self):
        response = self.client.get(
            self.url(),
            headers=self.headers(self.other_token),
        )
        self.assertEqual(response.status_code, 403)

    def test_foreign_customer_rejected(self):
        response = self.client.get(
            self.url(
                business=self.other_business,
                customer=self.customer,
            ),
            headers=self.headers(self.other_token),
        )
        self.assertEqual(response.status_code, 400)

    def test_invalid_token_rejected(self):
        response = self.client.get(
            self.url(),
            headers={
                "Authorization": "Bearer invalid-token"
            },
        )
        self.assertEqual(response.status_code, 401)


if __name__ == "__main__":
    unittest.main()
