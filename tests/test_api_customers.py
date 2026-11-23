import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.api.main import create_app
from app.services.statements import StatementLedger


class TestCustomerDirectoryAPI(unittest.TestCase):

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)

        path = Path(temporary.name) / "customers.db"
        self.ledger = StatementLedger(path)
        self.client = TestClient(create_app(path))

        owner = self.ledger.register_owner(
            "Abuja Test Shop",
            "directory@example.test",
            "SecureTestPassword123!",
        )
        self.business = owner["business_id"]
        self.token = self.ledger.login(
            "directory@example.test",
            "SecureTestPassword123!",
        )

        other = self.ledger.register_owner(
            "Another Test Shop",
            "other-directory@example.test",
            "AnotherSecurePassword456!",
        )
        self.other_business = other["business_id"]
        self.other_token = self.ledger.login(
            "other-directory@example.test",
            "AnotherSecurePassword456!",
        )

    def url(self, business_id=None):
        business = business_id or self.business
        return f"/api/v1/businesses/{business}/customers"

    def headers(self, token=None):
        return {"Authorization": f"Bearer {token or self.token}"}

    def add_customer(self, name):
        return self.ledger.add_customer(
            self.token, self.business, name
        )

    def test_empty_directory(self):
        response = self.client.get(
            self.url(), headers=self.headers()
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["customer_count"], 0)
        self.assertEqual(response.json()["total_outstanding"], "0")

    def test_customers_listed_alphabetically(self):
        self.add_customer("Musa")
        self.add_customer("Amina")

        response = self.client.get(
            self.url(), headers=self.headers()
        )
        self.assertEqual(response.status_code, 200)

        names = [
            row["name"] for row in response.json()["customers"]
        ]
        self.assertEqual(names, ["Amina", "Musa"])

    def test_directory_calculates_outstanding_debt(self):
        customer = self.add_customer("Musa")

        self.ledger.add_sale(
            self.token, self.business, customer,
            "SALE-001", "15000", "10000",
            confirmed=True,
        )

        response = self.client.get(
            self.url(), headers=self.headers()
        )
        result = response.json()

        self.assertEqual(result["customer_count"], 1)
        self.assertEqual(result["total_outstanding"], "5000")
        self.assertEqual(
            result["customers"][0]["outstanding_balance"],
            "5000",
        )

    def test_repayments_and_adjustments_affect_totals(self):
        customer = self.add_customer("Musa")

        self.ledger.add_sale(
            self.token, self.business, customer,
            "SALE-001", "15000", "10000",
            confirmed=True,
        )
        self.ledger.add_repayment(
            self.token, self.business, customer,
            "PAY-001", "2000", confirmed=True,
        )
        self.ledger.adjust_customer_balance(
            self.token, self.business, customer,
            "ADJ-001", "-500",
            "Verified customer debt correction",
            confirmed=True,
        )

        response = self.client.get(
            self.url(), headers=self.headers()
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["total_outstanding"], "2500"
        )

    def test_sale_reversal_affects_totals(self):
        customer = self.add_customer("Musa")

        sale = self.ledger.add_sale(
            self.token, self.business, customer,
            "SALE-001", "15000", "0",
            confirmed=True,
        )
        self.ledger.reverse_unpaid_sale(
            self.token, self.business, sale,
            "REV-001",
            "Duplicate unpaid sale recorded in error",
            confirmed=True,
        )

        response = self.client.get(
            self.url(), headers=self.headers()
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["total_outstanding"], "0"
        )

    def test_other_business_cannot_view_directory(self):
        response = self.client.get(
            self.url(), headers=self.headers(self.other_token)
        )
        self.assertEqual(response.status_code, 403)

        own = self.client.get(
            self.url(self.other_business),
            headers=self.headers(self.other_token),
        )
        self.assertEqual(own.status_code, 200)

    def test_missing_authentication_is_rejected(self):
        response = self.client.get(self.url())
        self.assertEqual(response.status_code, 401)


if __name__ == "__main__":
    unittest.main()
