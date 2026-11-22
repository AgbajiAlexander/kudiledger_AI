import sqlite3
import tempfile
import unittest
from pathlib import Path

from app.services.adjustments import AdjustmentLedger


class TestDebtAdjustments(unittest.TestCase):

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)

        self.path = Path(temporary.name) / "adjustments.db"
        self.ledger = AdjustmentLedger(self.path)

        owner = self.ledger.register_owner(
            "Abuja Test Shop",
            "owner@example.test",
            "SafeTestPassword123!"
        )

        self.business = owner["business_id"]

        self.token = self.ledger.login(
            "owner@example.test",
            "SafeTestPassword123!"
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

    def balance(self):
        return self.ledger.get_balance(
            self.token, self.business, self.customer
        )

    def adjust(self, amount, reference="ADJ-001"):
        return self.ledger.adjust_customer_balance(
            self.token,
            self.business,
            self.customer,
            reference,
            amount,
            "Correction verified against shop records",
            confirmed=True,
        )

    def test_debt_reduction(self):
        self.adjust("-1000")
        self.assertEqual(self.balance(), 4000)

    def test_debt_increase_and_repayment(self):
        self.adjust("1000")

        self.ledger.add_repayment(
            self.token,
            self.business,
            self.customer,
            "PAY-001",
            "3000",
            confirmed=True,
        )

        self.assertEqual(self.balance(), 3000)

    def test_adjustment_cannot_create_negative_balance(self):
        with self.assertRaises(ValueError):
            self.adjust("-6000")

        self.assertEqual(self.balance(), 5000)

    def test_duplicate_adjustment_rejected(self):
        self.adjust("-1000")

        with self.assertRaises(ValueError):
            self.adjust("-1000")

        self.assertEqual(self.balance(), 4000)

    def test_confirmation_required(self):
        with self.assertRaises(ValueError):
            self.ledger.adjust_customer_balance(
                self.token,
                self.business,
                self.customer,
                "ADJ-001",
                "-1000",
                "Correction verified against shop records",
                confirmed=False,
            )

        self.assertEqual(self.balance(), 5000)

    def test_adjustment_is_immutable(self):
        adjustment_id = self.adjust("-1000")

        with self.assertRaises(sqlite3.IntegrityError):
            with self.ledger.connect() as db:
                db.execute(
                    """UPDATE debt_adjustments
                       SET delta_kobo = 0 WHERE id = ?""",
                    (adjustment_id,),
                )

        with self.assertRaises(sqlite3.IntegrityError):
            with self.ledger.connect() as db:
                db.execute(
                    "DELETE FROM debt_adjustments WHERE id = ?",
                    (adjustment_id,),
                )

        self.assertEqual(self.balance(), 4000)

    def test_other_business_cannot_adjust_debt(self):
        other = self.ledger.register_owner(
            "Another Abuja Shop",
            "other@example.test",
            "AnotherSafePassword456!"
        )
        other_token = self.ledger.login(
            "other@example.test",
            "AnotherSafePassword456!"
        )

        with self.assertRaises(PermissionError):
            self.ledger.adjust_customer_balance(
                other_token,
                self.business,
                self.customer,
                "ADJ-002",
                "-1000",
                "Attempt from another business",
                confirmed=True,
            )

        with self.assertRaises(PermissionError):
            self.ledger.get_adjustments(
                other_token, self.business, self.customer
            )

    def test_adjustment_survives_restart(self):
        self.adjust("-1000")

        reopened = AdjustmentLedger(self.path)

        self.assertEqual(
            reopened.get_balance(
                self.token, self.business, self.customer
            ),
            4000,
        )

        history = reopened.get_adjustments(
            self.token, self.business, self.customer
        )

        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["amount"], -1000)
        self.assertTrue(history[0]["reason"])


if __name__ == "__main__":
    unittest.main()
