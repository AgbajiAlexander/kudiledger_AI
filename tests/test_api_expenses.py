import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.api.main import create_app
from app.services.expenses import ExpenseLedger


class TestExpenseAPI(unittest.TestCase):

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)

        path = Path(temporary.name) / "expense_api.db"
        self.ledger = ExpenseLedger(path)
        self.client = TestClient(create_app(path))

        owner = self.ledger.register_owner(
            "Abuja Test Shop",
            "expense-api@example.test",
            "SecureTestPassword123!",
        )
        self.business = owner["business_id"]
        self.token = self.ledger.login(
            "expense-api@example.test",
            "SecureTestPassword123!",
        )

        other = self.ledger.register_owner(
            "Other Test Shop",
            "other-expense-api@example.test",
            "AnotherSecurePassword456!",
        )
        self.other_business = other["business_id"]
        self.other_token = self.ledger.login(
            "other-expense-api@example.test",
            "AnotherSecurePassword456!",
        )

    def url(self, business=None):
        return (
            f"/api/v1/businesses/"
            f"{business or self.business}/expenses"
        )

    def headers(self, token=None):
        return {
            "Authorization": f"Bearer {token or self.token}"
        }

    def payload(self, reference="EXP-001", amount="2500",
                confirmed=True):
        return {
            "reference": reference,
            "category": "Transport",
            "description": "Transporting goods to the market",
            "amount": amount,
            "confirmed": confirmed,
        }

    def post_expense(self, reference="EXP-001", amount="2500"):
        return self.client.post(
            self.url(),
            json=self.payload(reference, amount),
            headers=self.headers(),
        )

    def test_expense_created(self):
        response = self.post_expense()

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["status"], "CONFIRMED")
        self.assertTrue(response.json()["id"])

    def test_expense_history(self):
        self.assertEqual(self.post_expense().status_code, 201)

        response = self.client.get(
            self.url(),
            headers=self.headers(),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()), 1)
        self.assertEqual(response.json()[0]["amount"], "2500")
        self.assertEqual(
            response.json()[0]["category"], "Transport"
        )

    def test_expense_summary(self):
        self.post_expense()
        self.post_expense("EXP-002", "1500")

        response = self.client.get(
            self.url() + "/summary",
            headers=self.headers(),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["expense_count"], 2
        )
        self.assertEqual(
            response.json()["total_expenses"], "4000"
        )

    def test_duplicate_reference_rejected(self):
        self.assertEqual(self.post_expense().status_code, 201)
        self.assertEqual(self.post_expense().status_code, 400)

    def test_unconfirmed_expense_rejected(self):
        response = self.client.post(
            self.url(),
            json=self.payload(confirmed=False),
            headers=self.headers(),
        )
        self.assertEqual(response.status_code, 400)

    def test_invalid_amount_rejected(self):
        for amount in ("0", "-500", "100.001", "NaN"):
            with self.subTest(amount=amount):
                response = self.client.post(
                    self.url(),
                    json=self.payload(amount=amount),
                    headers=self.headers(),
                )
                self.assertEqual(response.status_code, 400)

    def test_missing_authentication_rejected(self):
        response = self.client.get(self.url())
        self.assertEqual(response.status_code, 401)

        response = self.client.post(
            self.url(), json=self.payload()
        )
        self.assertEqual(response.status_code, 401)

        response = self.client.get(
            self.url() + "/summary"
        )
        self.assertEqual(response.status_code, 401)

    def test_other_business_owner_rejected(self):
        response = self.client.post(
            self.url(),
            json=self.payload(),
            headers=self.headers(self.other_token),
        )
        self.assertEqual(response.status_code, 403)

        response = self.client.get(
            self.url(),
            headers=self.headers(self.other_token),
        )
        self.assertEqual(response.status_code, 403)

        response = self.client.get(
            self.url() + "/summary",
            headers=self.headers(self.other_token),
        )
        self.assertEqual(response.status_code, 403)

        own_response = self.client.get(
            self.url(self.other_business),
            headers=self.headers(self.other_token),
        )
        self.assertEqual(own_response.status_code, 200)
        self.assertEqual(own_response.json(), [])


if __name__ == "__main__":
    unittest.main()
