import hashlib
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.api.main import create_app
from app.services.reports import ReportLedger


class TestTransactionReceipts(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        path = Path(temp.name) / "receipts.db"
        self.ledger = ReportLedger(path)
        self.client = TestClient(create_app(path))
        self.addCleanup(self.client.close)
        self.business, self.token = self.owner("Receipt Test Shop", "owner")
        self.customer = self.ledger.add_customer(self.token, self.business, "Musa")
        self.reference = "REC / #1"

    def owner(self, name, account):
        email = f"{account}@example.test"
        password = "SyntheticReceiptPassword123"
        business = self.ledger.register_owner(name, email, password)["business_id"]
        return business, self.ledger.login(email, password)

    def receipt(self, kind="sale", *, business=None, token=None, **identifier):
        return self.client.get(
            f"/api/v1/businesses/{business or self.business}/receipts",
            params={"kind": kind, **identifier},
            headers={"Authorization": f"Bearer {token or self.token}"},
        )

    def sale(self, total="100.01", paid="0.01"):
        return self.ledger.add_sale(
            self.token, self.business, self.customer, self.reference,
            total, paid, confirmed=True,
        )

    def test_three_types_share_reference_but_keep_distinct_receipts(self):
        sale = self.sale()
        repayment = self.ledger.add_repayment(
            self.token, self.business, self.customer, self.reference,
            "0.01", confirmed=True,
        )
        expense = self.ledger.record_expense(
            self.token, self.business, self.reference,
            "Transport", "Receipt delivery", "89999999999999.99", confirmed=True,
        )
        cases = [
            ("sale", sale, "100.01", {"customer_name": "Musa",
                                     "paid_at_sale": "0.01", "due_at_sale": "100.00",
                                     "reversed": False}),
            ("repayment", repayment, "0.01", {"customer_name": "Musa"}),
            ("expense", expense, "89999999999999.99",
             {"category": "Transport", "description": "Receipt delivery"}),
        ]
        for kind, transaction_id, amount, expected in cases:
            with self.subTest(kind=kind):
                by_ref = self.receipt(kind, reference=self.reference)
                by_id = self.receipt(kind, transaction_id=transaction_id)
                self.assertEqual(by_ref.status_code, 200)
                self.assertEqual(by_id.status_code, 200)
                self.assertEqual(by_id.headers["cache-control"], "no-store")
                result = by_id.json()
                self.assertEqual(result, by_ref.json())
                self.assertEqual(result["id"], transaction_id)
                self.assertEqual(result["kind"], kind)
                self.assertEqual(result["business_name"], "Receipt Test Shop")
                self.assertEqual(result["reference"], self.reference)
                self.assertEqual(result["amount"], amount)
                self.assertEqual(result["currency"], "NGN")
                self.assertIs(result["external_payment_verified"], False)
                self.assertNotIn("customer_id", result)
                if kind == "expense":
                    self.assertNotIn("customer_name", result)
                for key, value in expected.items():
                    self.assertEqual(result[key], value)

    def test_duplicate_does_not_change_original_receipt(self):
        original_id = self.sale()
        endpoint = f"/api/v1/businesses/{self.business}/sales"
        duplicate = self.client.post(
            endpoint, json={"customer_id": self.customer, "reference": self.reference,
                            "total": "999", "paid": "0", "confirmed": True},
            headers={"Authorization": f"Bearer {self.token}"},
        )
        self.assertEqual(duplicate.status_code, 400)
        result = self.receipt(reference=self.reference).json()
        self.assertEqual(result["id"], original_id)
        self.assertEqual(result["amount"], "100.01")

    def test_missing_and_foreign_receipts(self):
        original_id = self.sale()
        other_business, other_token = self.owner("Other Shop", "other")
        self.assertEqual(self.receipt(reference="missing").status_code, 404)
        self.assertEqual(self.receipt("expense", transaction_id=original_id).status_code, 404)
        for selector in ({"transaction_id": original_id}, {"reference": self.reference}):
            denied = self.receipt(token=other_token, **selector)
            self.assertEqual(denied.status_code, 403)
            absent = self.receipt(business=other_business, token=other_token, **selector)
            self.assertEqual(absent.status_code, 404)
            self.assertNotIn("Musa", denied.text + absent.text)

        other_customer = self.ledger.add_customer(other_token, other_business, "Amina")
        other_id = self.ledger.add_sale(
            other_token, other_business, other_customer, self.reference,
            "75", "0", confirmed=True,
        )
        own = self.receipt(
            business=other_business, token=other_token, reference=self.reference,
        )
        self.assertEqual(own.status_code, 200)
        self.assertEqual(own.json()["id"], other_id)
        self.assertEqual(own.json()["customer_name"], "Amina")
        self.assertEqual(self.receipt(transaction_id=other_id).status_code, 404)
        self.assertEqual(self.receipt(reference=self.reference).json()["id"], original_id)

    def test_authentication_required_and_expired_token_denied(self):
        self.sale()
        url = f"/api/v1/businesses/{self.business}/receipts"
        anonymous = self.client.get(url, params={"kind": "sale", "reference": self.reference})
        self.assertEqual(anonymous.status_code, 401)
        with self.ledger.connect() as db:
            db.execute(
                "UPDATE sessions SET expires_at = 0 WHERE token_hash = ?",
                (hashlib.sha256(self.token.encode()).hexdigest(),),
            )
        self.assertEqual(self.receipt(reference=self.reference).status_code, 401)

    def test_selector_validation(self):
        self.assertEqual(self.receipt().status_code, 400)
        self.assertEqual(self.receipt(reference="R1", transaction_id="1").status_code, 400)
        self.assertEqual(self.receipt("reversal", reference="R1").status_code, 400)
        self.assertEqual(self.receipt(reference="  ").status_code, 400)

    def test_lagos_rollover_from_stored_utc(self):
        with self.ledger.connect() as db:
            db.execute(
                """INSERT INTO expenses (
                       id, business_id, expense_reference, category, description,
                       amount_kobo, created_at
                   ) VALUES ('legacy', ?, ?, 'Transport', 'Delivery', 1, '2024-02-28 23:00:00')""",
                (self.business, self.reference),
            )
        result = self.receipt("expense", reference=self.reference).json()
        self.assertEqual(result["recorded_at_utc"], "2024-02-28T23:00:00+00:00")
        self.assertEqual(result["recorded_at_local"], "2024-02-29T00:00:00+01:00")
        self.assertEqual(result["timezone"], "Africa/Lagos")
        self.assertEqual(result["amount"], "0.01")

    def test_lagos_rollover_from_offset_aware_timestamps(self):
        for stamp in ("2024-02-28T23:00:00Z", "2024-02-29T01:00:00+02:00"):
            with self.subTest(stamp=stamp):
                with self.ledger.connect() as db:
                    db.execute(
                        """INSERT INTO expenses (
                               id, business_id, expense_reference, category, description,
                               amount_kobo, created_at
                           ) VALUES (?, ?, ?, 'Transport', 'Delivery', 1, ?)""",
                        (stamp, self.business, stamp, stamp),
                    )
                response = self.receipt("expense", transaction_id=stamp)
                self.assertEqual(response.status_code, 200)
                result = response.json()
                self.assertEqual(result["recorded_at_utc"], "2024-02-28T23:00:00+00:00")
                self.assertEqual(result["recorded_at_local"], "2024-02-29T00:00:00+01:00")

    def test_reversed_sale_receipt_identifies_reversal(self):
        sale_id = self.sale(paid="0")
        self.ledger.reverse_unpaid_sale(
            self.token, self.business, sale_id, "REV-1",
            "Duplicate sale entered in error", confirmed=True,
        )
        result = self.receipt(transaction_id=sale_id).json()
        self.assertTrue(result["reversed"])
        self.assertEqual(result["amount"], "100.01")
        self.assertEqual(result["paid_at_sale"], "0.00")
