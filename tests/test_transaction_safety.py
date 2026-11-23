import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.api.main import create_app
from app.services.reports import ReportLedger


class TestTransactionSafety(unittest.TestCase):

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)

        path = Path(temp.name) / "safety.db"
        self.client = TestClient(create_app(path))
        ledger = ReportLedger(path)

        owner = ledger.register_owner(
            "Transaction Safety Test Shop",
            "safety@example.test",
            "SecureTestPassword123!",
        )

        self.business = owner["business_id"]
        token = ledger.login(
            "safety@example.test",
            "SecureTestPassword123!",
        )

        self.headers = {
            "Authorization": f"Bearer {token}"
        }
        self.base = f"/api/v1/businesses/{self.business}"

        customer = self.client.post(
            self.base + "/customers",
            headers=self.headers,
            json={"name": "Musa"},
        )
        self.assertEqual(customer.status_code, 201)
        self.customer = customer.json()["id"]

    def post(self, endpoint, payload):
        return self.client.post(
            self.base + endpoint,
            headers=self.headers,
            json=payload,
        )

    def test_duplicate_sale_same_payload(self):
        payload = {
            "customer_id": self.customer,
            "reference": "SAFE-SALE-001",
            "total": "15000",
            "paid": "5000",
            "confirmed": True,
        }

        self.assertEqual(
            self.post("/sales", payload).status_code, 201
        )
        self.assertEqual(
            self.post("/sales", payload).status_code, 400
        )

        balance = self.client.get(
            self.base + f"/customers/{self.customer}/balance",
            headers=self.headers,
        )
        self.assertEqual(
            balance.json()["balance_naira"], "10000.00"
        )

    def test_duplicate_sale_changed_amount(self):
        payload = {
            "customer_id": self.customer,
            "reference": "SAFE-SALE-002",
            "total": "15000",
            "paid": "5000",
            "confirmed": True,
        }

        self.assertEqual(
            self.post("/sales", payload).status_code, 201
        )

        changed = dict(payload, total="30000")
        self.assertEqual(
            self.post("/sales", changed).status_code, 400
        )

    def test_duplicate_repayment_same_payload(self):
        sale = {
            "customer_id": self.customer,
            "reference": "SAFE-SALE-003",
            "total": "15000",
            "paid": "0",
            "confirmed": True,
        }
        self.assertEqual(
            self.post("/sales", sale).status_code, 201
        )

        payment = {
            "customer_id": self.customer,
            "reference": "SAFE-PAY-001",
            "amount": "2000",
            "confirmed": True,
        }

        self.assertEqual(
            self.post("/repayments", payment).status_code, 201
        )
        self.assertEqual(
            self.post("/repayments", payment).status_code, 400
        )

        balance = self.client.get(
            self.base + f"/customers/{self.customer}/balance",
            headers=self.headers,
        )
        self.assertEqual(
            balance.json()["balance_naira"], "13000.00"
        )

    def test_duplicate_repayment_changed_amount(self):
        sale = {
            "customer_id": self.customer,
            "reference": "SAFE-SALE-004",
            "total": "15000",
            "paid": "0",
            "confirmed": True,
        }
        self.assertEqual(
            self.post("/sales", sale).status_code, 201
        )

        payment = {
            "customer_id": self.customer,
            "reference": "SAFE-PAY-002",
            "amount": "2000",
            "confirmed": True,
        }
        self.assertEqual(
            self.post("/repayments", payment).status_code, 201
        )

        changed = dict(payment, amount="3000")
        self.assertEqual(
            self.post("/repayments", changed).status_code, 400
        )

    def test_duplicate_expense_same_payload(self):
        payload = {
            "reference": "SAFE-EXP-001",
            "category": "Transport",
            "description": "Transporting goods",
            "amount": "1500",
            "confirmed": True,
        }

        self.assertEqual(
            self.post("/expenses", payload).status_code, 201
        )
        self.assertEqual(
            self.post("/expenses", payload).status_code, 400
        )

        summary = self.client.get(
            self.base + "/expenses/summary",
            headers=self.headers,
        )
        self.assertEqual(
            summary.json()["expense_count"], 1
        )
        self.assertEqual(
            summary.json()["total_expenses"], "1500"
        )

    def test_duplicate_expense_changed_amount(self):
        payload = {
            "reference": "SAFE-EXP-002",
            "category": "Transport",
            "description": "Transporting goods",
            "amount": "1500",
            "confirmed": True,
        }

        self.assertEqual(
            self.post("/expenses", payload).status_code, 201
        )

        changed = dict(payload, amount="3000")
        self.assertEqual(
            self.post("/expenses", changed).status_code, 400
        )


if __name__ == "__main__":
    unittest.main()
