import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.api.main import create_app
from app.services.adjustments import AdjustmentLedger


class TestAdjustmentAPI(unittest.TestCase):

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)

        path = Path(temporary.name) / "adjustment_api.db"
        self.ledger = AdjustmentLedger(path)
        self.client = TestClient(create_app(path))

        owner = self.ledger.register_owner(
            "Abuja Test Shop",
            "owner@example.test",
            "SafeTestPassword123!"
        )
        self.business = owner["business_id"]

        other = self.ledger.register_owner(
            "Other Abuja Shop",
            "other@example.test",
            "AnotherSafePassword456!"
        )
        self.other_business = other["business_id"]

        self.token = self.ledger.login(
            "owner@example.test",
            "SafeTestPassword123!"
        )
        self.other_token = self.ledger.login(
            "other@example.test",
            "AnotherSafePassword456!"
        )

        self.customer = self.ledger.add_customer(
            self.token, self.business, "Musa"
        )

        self.ledger.add_sale(
            self.token,
            self.business,
            self.customer,
            "SALE-001",
            "15000",
            "10000",
            confirmed=True,
        )

    def headers(self, token=None):
        if token is None:
            token = self.token
        return {"Authorization": f"Bearer {token}"}

    def adjustment_url(self):
        return f"/api/v1/businesses/{self.business}/adjustments"

    def balance_url(self):
        return (
            f"/api/v1/businesses/{self.business}/customers/"
            f"{self.customer}/balance"
        )

    def history_url(self):
        return (
            f"/api/v1/businesses/{self.business}/customers/"
            f"{self.customer}/adjustments"
        )

    def payload(self, amount="-1000", confirmed=True):
        return {
            "customer_id": self.customer,
            "reference": "ADJ-001",
            "amount": amount,
            "reason": "Correction verified against shop records",
            "confirmed": confirmed,
        }

    def test_adjustment_updates_balance(self):
        response = self.client.post(
            self.adjustment_url(),
            json=self.payload(),
            headers=self.headers(),
        )
        self.assertEqual(response.status_code, 201)

        balance = self.client.get(
            self.balance_url(),
            headers=self.headers(),
        )
        self.assertEqual(balance.status_code, 200)
        self.assertEqual(
            balance.json()["balance_naira"], "4000.00"
        )

    def test_history_contains_adjustment(self):
        response = self.client.post(
            self.adjustment_url(),
            json=self.payload(),
            headers=self.headers(),
        )
        self.assertEqual(response.status_code, 201)

        history = self.client.get(
            self.history_url(),
            headers=self.headers(),
        )
        self.assertEqual(history.status_code, 200)
        self.assertEqual(len(history.json()), 1)
        self.assertEqual(
            history.json()[0]["amount"], "-1000.00"
        )

    def test_unconfirmed_adjustment_rejected(self):
        response = self.client.post(
            self.adjustment_url(),
            json=self.payload(confirmed=False),
            headers=self.headers(),
        )
        self.assertEqual(response.status_code, 400)

    def test_over_adjustment_rejected(self):
        response = self.client.post(
            self.adjustment_url(),
            json=self.payload(amount="-6000"),
            headers=self.headers(),
        )
        self.assertEqual(response.status_code, 400)

    def test_duplicate_adjustment_rejected(self):
        first = self.client.post(
            self.adjustment_url(),
            json=self.payload(),
            headers=self.headers(),
        )
        self.assertEqual(first.status_code, 201)

        second = self.client.post(
            self.adjustment_url(),
            json=self.payload(),
            headers=self.headers(),
        )
        self.assertEqual(second.status_code, 400)

    def test_other_business_denied(self):
        response = self.client.post(
            self.adjustment_url(),
            json=self.payload(),
            headers=self.headers(self.other_token),
        )
        self.assertEqual(response.status_code, 403)

        history = self.client.get(
            self.history_url(),
            headers=self.headers(self.other_token),
        )
        self.assertEqual(history.status_code, 403)

    def test_unauthenticated_request_rejected(self):
        response = self.client.post(
            self.adjustment_url(),
            json=self.payload(),
        )
        self.assertEqual(response.status_code, 401)

    def test_repayment_respects_adjusted_balance(self):
        adjustment = self.client.post(
            self.adjustment_url(),
            json=self.payload(),
            headers=self.headers(),
        )
        self.assertEqual(adjustment.status_code, 201)

        payment = self.client.post(
            f"/api/v1/businesses/{self.business}/repayments",
            json={
                "customer_id": self.customer,
                "reference": "PAY-001",
                "amount": "3000",
                "confirmed": True,
            },
            headers=self.headers(),
        )
        self.assertEqual(payment.status_code, 201)

        balance = self.client.get(
            self.balance_url(),
            headers=self.headers(),
        )
        self.assertEqual(
            balance.json()["balance_naira"], "1000.00"
        )


if __name__ == "__main__":
    unittest.main()
