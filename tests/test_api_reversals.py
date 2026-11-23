import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.api.main import create_app
from app.services.reversals import ReversalLedger


class TestReversalAPI(unittest.TestCase):

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)

        db_path = Path(temporary.name) / "reversal_api.db"
        self.ledger = ReversalLedger(db_path)
        self.client = TestClient(create_app(db_path))

        owner = self.ledger.register_owner(
            "Test Shop A",
            "reversal-owner@example.test",
            "SafeTestPassword123!",
        )
        self.business = owner["business_id"]
        self.token = self.ledger.login(
            "reversal-owner@example.test",
            "SafeTestPassword123!",
        )

        other = self.ledger.register_owner(
            "Test Shop B",
            "reversal-other@example.test",
            "AnotherSafePassword456!",
        )
        self.other_token = self.ledger.login(
            "reversal-other@example.test",
            "AnotherSafePassword456!",
        )

        self.customer = self.ledger.add_customer(
            self.token, self.business, "Musa"
        )

        self.sale = self.ledger.add_sale(
            self.token, self.business, self.customer,
            "SALE-001", "15000", "0", confirmed=True,
        )

    def headers(self, token=None):
        return {
            "Authorization": f"Bearer {token or self.token}"
        }

    def reversal_url(self):
        return (
            f"/api/v1/businesses/{self.business}/"
            "sale-reversals"
        )

    def balance_url(self):
        return (
            f"/api/v1/businesses/{self.business}/customers/"
            f"{self.customer}/balance"
        )

    def payload(self, confirmed=True, sale_id=None):
        return {
            "sale_id": sale_id or self.sale,
            "reference": "REV-001",
            "reason": "Duplicate unpaid sale entered by mistake",
            "confirmed": confirmed,
        }

    def reverse(self):
        return self.client.post(
            self.reversal_url(),
            json=self.payload(),
            headers=self.headers(),
        )

    def test_reversal_updates_api_balance(self):
        response = self.reverse()
        self.assertEqual(response.status_code, 201)

        balance = self.client.get(
            self.balance_url(),
            headers=self.headers(),
        )
        self.assertEqual(balance.status_code, 200)
        self.assertEqual(
            balance.json()["balance_naira"], "0.00"
        )

    def test_reversal_history(self):
        self.assertEqual(self.reverse().status_code, 201)

        response = self.client.get(
            self.reversal_url(),
            headers=self.headers(),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()), 1)
        self.assertEqual(
            response.json()[0]["amount"], "15000.00"
        )
        self.assertEqual(
            response.json()[0]["sale_id"], self.sale
        )

    def test_confirmation_required(self):
        response = self.client.post(
            self.reversal_url(),
            json=self.payload(confirmed=False),
            headers=self.headers(),
        )
        self.assertEqual(response.status_code, 400)

    def test_duplicate_reversal_rejected(self):
        self.assertEqual(self.reverse().status_code, 201)
        self.assertEqual(self.reverse().status_code, 400)

    def test_paid_sale_rejected(self):
        paid_sale = self.ledger.add_sale(
            self.token, self.business, self.customer,
            "SALE-002", "5000", "2000", confirmed=True,
        )

        response = self.client.post(
            self.reversal_url(),
            json=self.payload(sale_id=paid_sale),
            headers=self.headers(),
        )
        self.assertEqual(response.status_code, 400)

    def test_other_owner_denied(self):
        response = self.client.post(
            self.reversal_url(),
            json=self.payload(),
            headers=self.headers(self.other_token),
        )
        self.assertEqual(response.status_code, 403)

        history = self.client.get(
            self.reversal_url(),
            headers=self.headers(self.other_token),
        )
        self.assertEqual(history.status_code, 403)

    def test_unauthenticated_request_denied(self):
        response = self.client.post(
            self.reversal_url(),
            json=self.payload(),
        )
        self.assertEqual(response.status_code, 401)

    def test_reversal_does_not_change_original_sale(self):
        self.assertEqual(self.reverse().status_code, 201)

        with self.ledger.connect() as db:
            row = db.execute(
                """SELECT total_kobo, paid_kobo
                   FROM sales WHERE id = ?""",
                (self.sale,),
            ).fetchone()

        self.assertEqual(row["total_kobo"], 1500000)
        self.assertEqual(row["paid_kobo"], 0)

    def test_existing_adjustment_api_still_works(self):
        another = self.ledger.add_customer(
            self.token, self.business, "Amina"
        )
        self.ledger.add_sale(
            self.token, self.business, another,
            "SALE-003", "5000", "0", confirmed=True,
        )

        response = self.client.post(
            f"/api/v1/businesses/{self.business}/adjustments",
            json={
                "customer_id": another,
                "reference": "ADJ-001",
                "amount": "-1000",
                "reason": "Verified customer balance correction",
                "confirmed": True,
            },
            headers=self.headers(),
        )

        self.assertEqual(response.status_code, 201)


if __name__ == "__main__":
    unittest.main()
