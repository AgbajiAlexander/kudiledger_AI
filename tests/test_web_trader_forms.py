import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.api.main import create_app
from app.services.reports import ReportLedger


class TestTraderForms(unittest.TestCase):

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)

        path = Path(temporary.name) / "forms.db"
        self.ledger = ReportLedger(path)
        self.client = TestClient(create_app(path))

        owner = self.ledger.register_owner(
            "Test Trader Shop",
            "forms-owner@example.test",
            "SecureTestPassword123!",
        )
        self.business = owner["business_id"]
        self.token = self.ledger.login(
            "forms-owner@example.test",
            "SecureTestPassword123!",
        )
        self.headers = {
            "Authorization": f"Bearer {self.token}"
        }
        self.base = f"/api/v1/businesses/{self.business}"

    def test_all_four_forms_are_present(self):
        response = self.client.get("/app")
        self.assertEqual(response.status_code, 200)

        for form_id in (
            "customer-form",
            "sale-form",
            "expense-form",
            "repayment-form",
        ):
            with self.subTest(form_id=form_id):
                self.assertIn(f'id="{form_id}"', response.text)

    def test_dashboard_uses_existing_endpoints(self):
        page = self.client.get("/app").text

        for endpoint in (
            '"/customers"',
            '"/sales"',
            '"/expenses"',
            '"/repayments"',
        ):
            with self.subTest(endpoint=endpoint):
                self.assertIn(endpoint, page)

    def test_financial_forms_include_confirmation(self):
        page = self.client.get("/app").text
        self.assertIn("window.confirm(", page)
        self.assertIn("confirmed: true", page)

    def test_customer_selection_is_dynamic(self):
        page = self.client.get("/app").text
        self.assertIn("populateCustomerSelects(", page)
        self.assertIn("directory.customers", page)

    def test_api_rejects_unconfirmed_sale(self):
        customer = self.ledger.add_customer(
            self.token, self.business, "Musa"
        )
        response = self.client.post(
            self.base + "/sales",
            json={
                "customer_id": customer,
                "reference": "SALE-UNCONFIRMED",
                "total": "15000",
                "paid": "5000",
                "confirmed": False,
            },
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 400)

    def test_complete_trader_recording_journey(self):
        customer_response = self.client.post(
            self.base + "/customers",
            json={"name": "Musa"},
            headers=self.headers,
        )
        self.assertEqual(customer_response.status_code, 201)
        customer = customer_response.json()["id"]

        sale_response = self.client.post(
            self.base + "/sales",
            json={
                "customer_id": customer,
                "reference": "WEB-SALE-001",
                "total": "15000",
                "paid": "5000",
                "confirmed": True,
            },
            headers=self.headers,
        )
        self.assertEqual(sale_response.status_code, 201)

        repayment_response = self.client.post(
            self.base + "/repayments",
            json={
                "customer_id": customer,
                "reference": "WEB-REPAY-001",
                "amount": "2000",
                "confirmed": True,
            },
            headers=self.headers,
        )
        self.assertEqual(repayment_response.status_code, 201)

        expense_response = self.client.post(
            self.base + "/expenses",
            json={
                "reference": "WEB-EXP-001",
                "category": "Transport",
                "description": "Transported goods to the market",
                "amount": "1500",
                "confirmed": True,
            },
            headers=self.headers,
        )
        self.assertEqual(expense_response.status_code, 201)

        directory = self.client.get(
            self.base + "/customers", headers=self.headers
        )
        self.assertEqual(directory.status_code, 200)
        self.assertEqual(
            directory.json()["total_outstanding"], "8000"
        )

        expenses = self.client.get(
            self.base + "/expenses/summary",
            headers=self.headers,
        )
        self.assertEqual(expenses.status_code, 200)
        self.assertEqual(
            expenses.json()["total_expenses"], "1500"
        )


if __name__ == "__main__":
    unittest.main()
