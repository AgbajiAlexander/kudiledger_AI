import sqlite3
import tempfile
import unittest
from pathlib import Path

from app.services.expenses import ExpenseLedger


class TestExpenses(unittest.TestCase):

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)

        self.path = Path(temp.name) / "expenses.db"
        self.ledger = ExpenseLedger(self.path)

        owner = self.ledger.register_owner(
            "Abuja Test Shop",
            "expense-owner@example.test",
            "SecureTestPassword123!",
        )
        self.business = owner["business_id"]

        self.token = self.ledger.login(
            "expense-owner@example.test",
            "SecureTestPassword123!",
        )

    def add_expense(self, reference="EXP-001", amount="2500"):
        return self.ledger.record_expense(
            self.token,
            self.business,
            reference,
            "Transport",
            "Transporting goods to the market",
            amount,
            confirmed=True,
        )

    def test_record_expense(self):
        self.add_expense()

        records = self.ledger.list_expenses(
            self.token, self.business
        )

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["amount"], "2500")
        self.assertEqual(records[0]["category"], "Transport")

    def test_expense_summary(self):
        self.add_expense()
        self.add_expense("EXP-002", "1500")

        result = self.ledger.expense_summary(
            self.token, self.business
        )

        self.assertEqual(result["expense_count"], 2)
        self.assertEqual(result["total_expenses"], "4000")

    def test_duplicate_reference_rejected(self):
        self.add_expense()

        with self.assertRaises(ValueError):
            self.add_expense()

        self.assertEqual(
            self.ledger.expense_summary(
                self.token, self.business
            )["expense_count"],
            1,
        )

    def test_invalid_amount_rejected(self):
        for amount in ("0", "-500", "100.001", "NaN"):
            with self.subTest(amount=amount):
                with self.assertRaises(ValueError):
                    self.add_expense(amount=amount)

    def test_confirmation_required(self):
        with self.assertRaises(ValueError):
            self.ledger.record_expense(
                self.token, self.business,
                "EXP-001", "Transport",
                "Transporting goods to the market",
                "2500", confirmed=False,
            )

    def test_recorded_expense_is_immutable(self):
        expense_id = self.add_expense()

        with self.assertRaises(sqlite3.IntegrityError):
            with self.ledger.connect() as db:
                db.execute(
                    "UPDATE expenses SET amount_kobo = 1 WHERE id = ?",
                    (expense_id,),
                )

        with self.assertRaises(sqlite3.IntegrityError):
            with self.ledger.connect() as db:
                db.execute(
                    "DELETE FROM expenses WHERE id = ?",
                    (expense_id,),
                )

    def test_business_isolation(self):
        other = self.ledger.register_owner(
            "Other Test Shop",
            "other-expense@example.test",
            "AnotherSecurePassword456!",
        )
        other_token = self.ledger.login(
            "other-expense@example.test",
            "AnotherSecurePassword456!",
        )

        self.add_expense()

        with self.assertRaises(PermissionError):
            self.ledger.list_expenses(
                other_token, self.business
            )

        with self.assertRaises(PermissionError):
            self.ledger.record_expense(
                other_token, self.business,
                "EXP-002", "Transport",
                "Unauthorized business expense entry",
                "1000", confirmed=True,
            )

        self.assertEqual(
            self.ledger.expense_summary(
                other_token, other["business_id"]
            )["expense_count"],
            0,
        )


if __name__ == "__main__":
    unittest.main()
