import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.api.main import create_app
from app.services.reports import ReportLedger


class TestTransactionLookup(unittest.TestCase):

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)

        path = Path(temporary.name) / "lookup.db"
        self.ledger = ReportLedger(path)
        self.client = TestClient(create_app(path))

        owner = self.ledger.register_owner(
            "Lookup Demo Shop",
            "lookup@example.test",
            "SecureTestPassword123!",
        )
        self.business = owner["business_id"]
        self.token = self.ledger.login(
            "lookup@example.test",
            "SecureTestPassword123!",
        )
        self.headers = {
            "Authorization": f"Bearer {self.token}"
        }
        self.base = f"/api/v1/businesses/{self.business}"

        customer = self.client.post(
            self.base + "/customers",
            headers=self.headers,
            json={"name": "Musa"},
        )
        self.assertEqual(customer.status_code, 201)
        self.customer = customer.json()["id"]

    def lookup(self, kind, reference, business=None, headers=None):
        target = business or self.business
        return self.client.get(
            f"/api/v1/businesses/{target}/transactions/lookup",
            params={"kind": kind, "reference": reference},
            headers=self.headers if headers is None else headers,
        )

    def test_existing_sale_lookup(self):
        response = self.client.post(
            self.base + "/sales",
            headers=self.headers,
            json={
                "customer_id": self.customer,
                "reference": "LOOKUP-SALE-001",
                "total": "15000",
                "paid": "5000",
                "confirmed": True,
            },
        )
        self.assertEqual(response.status_code, 201)

        found = self.lookup("sale", "LOOKUP-SALE-001")
        self.assertEqual(found.status_code, 200)
        self.assertTrue(found.json()["found"])
        self.assertEqual(found.json()["total"], "15000")
        self.assertEqual(found.json()["paid"], "5000")
        self.assertEqual(
            found.json()["customer_id"], self.customer
        )

    def test_existing_repayment_lookup(self):
        sale = self.client.post(
            self.base + "/sales",
            headers=self.headers,
            json={
                "customer_id": self.customer,
                "reference": "LOOKUP-SALE-002",
                "total": "10000",
                "paid": "0",
                "confirmed": True,
            },
        )
        self.assertEqual(sale.status_code, 201)

        payment = self.client.post(
            self.base + "/repayments",
            headers=self.headers,
            json={
                "customer_id": self.customer,
                "reference": "LOOKUP-PAY-001",
                "amount": "2000",
                "confirmed": True,
            },
        )
        self.assertEqual(payment.status_code, 201)

        found = self.lookup("repayment", "LOOKUP-PAY-001")
        self.assertEqual(found.status_code, 200)
        self.assertTrue(found.json()["found"])
        self.assertEqual(found.json()["amount"], "2000")

    def test_existing_expense_lookup(self):
        expense = self.client.post(
            self.base + "/expenses",
            headers=self.headers,
            json={
                "reference": "LOOKUP-EXP-001",
                "category": "Transport",
                "description": "Transporting market goods",
                "amount": "1500",
                "confirmed": True,
            },
        )
        self.assertEqual(expense.status_code, 201)

        found = self.lookup("expense", "LOOKUP-EXP-001")
        self.assertEqual(found.status_code, 200)
        self.assertTrue(found.json()["found"])
        self.assertEqual(found.json()["amount"], "1500")
        self.assertEqual(found.json()["category"], "Transport")

    def test_unknown_reference(self):
        response = self.lookup("sale", "UNKNOWN-REF")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["found"])

    def test_invalid_kind(self):
        response = self.lookup("invalid", "REFERENCE-001")
        self.assertEqual(response.status_code, 400)

    def test_missing_authentication(self):
        response = self.client.get(
            f"{self.base}/transactions/lookup",
            params={
                "kind": "sale",
                "reference": "LOOKUP-SALE-001",
            },
        )
        self.assertEqual(response.status_code, 401)

    def test_other_business_cannot_lookup(self):
        other = self.ledger.register_owner(
            "Other Shop",
            "other-lookup@example.test",
            "AnotherSecurePassword456!",
        )

        response = self.lookup(
            "sale", "ANY-REFERENCE",
            business=other["business_id"],
        )
        self.assertEqual(response.status_code, 403)


if __name__ == "__main__":
    unittest.main()
