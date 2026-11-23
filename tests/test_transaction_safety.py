import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
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

    def test_competing_repayments_cannot_overpay(self):
        sale = self.post("/sales", {
            "customer_id": self.customer, "reference": "RACE-SALE",
            "total": "100", "paid": "0", "confirmed": True,
        })
        self.assertEqual(sale.status_code, 201)
        payments = [
            {
                "customer_id": self.customer, "reference": reference,
                "amount": "60", "confirmed": True,
            }
            for reference in ("RACE-1", "RACE-2")
        ]
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(
                lambda data: self.post("/repayments", data), payments
            ))
        self.assertCountEqual(
            [result.status_code for result in results], [201, 400]
        )

        for result, payment in zip(results, payments):
            if result.status_code == 201:
                duplicate = self.post("/repayments", payment)
                self.assertEqual(duplicate.status_code, 400)
                self.assertEqual(
                    duplicate.json()["detail"], "Duplicate repayment reference"
                )
            else:
                self.assertEqual(
                    result.json()["detail"], "Repayment exceeds outstanding balance"
                )

        balance = self.client.get(
            self.base + "/customers/" + self.customer + "/balance",
            headers=self.headers,
        )
        self.assertEqual(balance.status_code, 200)
        self.assertEqual(balance.json()["balance_naira"], "40.00")

    def test_out_of_range_money_is_a_validation_error(self):
        response = self.post("/sales", {
            "customer_id": self.customer, "reference": "OUT-OF-RANGE",
            "total": "1e1000000", "paid": "0", "confirmed": True,
        })
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "Amount exceeds supported limit")

    def test_validation_response_omits_input_values(self):
        credential = "SyntheticSecretValue"
        response = self.client.post("/api/v1/auth/login", json=[
            {"email": "owner@example.test", "password": credential},
        ])
        self.assertEqual(response.status_code, 422)
        self.assertNotIn(credential, response.text)
        self.assertNotIn("input", response.json()["detail"][0])

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
