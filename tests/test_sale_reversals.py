import sqlite3
import tempfile
import unittest
from pathlib import Path

from app.services.reversals import ReversalLedger


class TestSaleReversals(unittest.TestCase):

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)

        self.path = Path(temporary.name) / "reversals.db"
        self.ledger = ReversalLedger(self.path)

        owner = self.ledger.register_owner(
            "Abuja Test Shop",
            "owner@example.test",
            "SecureTestPassword123!"
        )

        self.business = owner["business_id"]
        self.token = self.ledger.login(
            "owner@example.test",
            "SecureTestPassword123!"
        )

        self.customer = self.ledger.add_customer(
            self.token, self.business, "Musa"
        )

        self.sale = self.ledger.add_sale(
            self.token, self.business, self.customer,
            "SALE-001", "15000", "0", confirmed=True
        )

    def balance(self):
        return self.ledger.get_balance(
            self.token, self.business, self.customer
        )

    def reverse(self, sale_id=None, confirmed=True):
        return self.ledger.reverse_unpaid_sale(
            self.token,
            self.business,
            sale_id or self.sale,
            "REV-001",
            "Duplicate sale entered in error",
            confirmed=confirmed,
        )

    def test_unpaid_sale_reversal(self):
        self.reverse()
        self.assertEqual(self.balance(), 0)

    def test_original_sale_is_preserved(self):
        self.reverse()

        with self.ledger.connect() as db:
            sale = db.execute(
                "SELECT total_kobo FROM sales WHERE id = ?",
                (self.sale,),
            ).fetchone()

        self.assertEqual(sale["total_kobo"], 1500000)

    def test_duplicate_reversal_rejected(self):
        self.reverse()

        with self.assertRaises(ValueError):
            self.reverse()

        self.assertEqual(self.balance(), 0)

    def test_confirmation_required(self):
        with self.assertRaises(ValueError):
            self.reverse(confirmed=False)

        self.assertEqual(self.balance(), 15000)

    def test_paid_sale_cannot_be_reversed(self):
        paid_sale = self.ledger.add_sale(
            self.token, self.business, self.customer,
            "SALE-002", "5000", "2000", confirmed=True
        )

        with self.assertRaises(ValueError):
            self.reverse(paid_sale)

    def test_repayment_requires_reconciliation(self):
        self.ledger.add_repayment(
            self.token, self.business, self.customer,
            "PAY-001", "1000", confirmed=True
        )

        with self.assertRaises(ValueError):
            self.reverse()

    def test_other_business_cannot_reverse_sale(self):
        other = self.ledger.register_owner(
            "Another Abuja Shop",
            "other@example.test",
            "AnotherSecurePassword456!"
        )
        other_token = self.ledger.login(
            "other@example.test",
            "AnotherSecurePassword456!"
        )

        with self.assertRaises(PermissionError):
            self.ledger.reverse_unpaid_sale(
                other_token, self.business, self.sale,
                "REV-001",
                "Unauthorized reversal attempt",
                confirmed=True,
            )

    def test_reversal_is_immutable(self):
        reversal_id = self.reverse()

        with self.assertRaises(sqlite3.IntegrityError):
            with self.ledger.connect() as db:
                db.execute(
                    """UPDATE sale_reversals
                       SET amount_kobo = 1 WHERE id = ?""",
                    (reversal_id,),
                )

        with self.assertRaises(sqlite3.IntegrityError):
            with self.ledger.connect() as db:
                db.execute(
                    "DELETE FROM sale_reversals WHERE id = ?",
                    (reversal_id,),
                )

    def test_reversal_survives_restart(self):
        self.reverse()

        reopened = ReversalLedger(self.path)
        self.assertEqual(
            reopened.get_balance(
                self.token, self.business, self.customer
            ),
            0,
        )

        history = reopened.list_sale_reversals(
            self.token, self.business
        )
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["sale_id"], self.sale)


if __name__ == "__main__":
    unittest.main()
