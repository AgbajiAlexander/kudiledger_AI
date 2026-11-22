import sqlite3
import tempfile
import unittest
from pathlib import Path

from app.db.repayments import RepaymentLedger


class TestRepayments(unittest.TestCase):

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)

        self.path = Path(temporary.name) / "test.db"
        self.ledger = RepaymentLedger(self.path)

        self.business = self.ledger.create_business(
            "KudiLedger Test Shop"
        )
        self.customer = self.ledger.create_customer(
            self.business, "Musa"
        )

        self.ledger.record_sale(
            self.business,
            self.customer,
            "SALE-001",
            "15000",
            "10000",
            confirmed=True,
        )

    def test_initial_balance(self):
        self.assertEqual(
            self.ledger.customer_balance(
                self.business, self.customer
            ),
            5000,
        )

    def test_partial_repayment(self):
        self.ledger.record_repayment(
            self.business,
            self.customer,
            "PAY-001",
            "3000",
            confirmed=True,
        )

        self.assertEqual(
            self.ledger.customer_balance(
                self.business, self.customer
            ),
            2000,
        )

    def test_full_repayment(self):
        self.ledger.record_repayment(
            self.business,
            self.customer,
            "PAY-001",
            "5000",
            confirmed=True,
        )

        self.assertEqual(
            self.ledger.customer_balance(
                self.business, self.customer
            ),
            0,
        )

    def test_overpayment_rejected(self):
        with self.assertRaises(ValueError):
            self.ledger.record_repayment(
                self.business,
                self.customer,
                "PAY-001",
                "6000",
                confirmed=True,
            )

        self.assertEqual(
            self.ledger.customer_balance(
                self.business, self.customer
            ),
            5000,
        )

    def test_confirmation_required(self):
        with self.assertRaises(ValueError):
            self.ledger.record_repayment(
                self.business,
                self.customer,
                "PAY-001",
                "3000",
            )

    def test_duplicate_repayment_rejected(self):
        self.ledger.record_repayment(
            self.business,
            self.customer,
            "PAY-001",
            "1000",
            confirmed=True,
        )

        with self.assertRaises(ValueError):
            self.ledger.record_repayment(
                self.business,
                self.customer,
                "PAY-001",
                "1000",
                confirmed=True,
            )

        self.assertEqual(
            self.ledger.customer_balance(
                self.business, self.customer
            ),
            4000,
        )

    def test_repayment_survives_restart(self):
        self.ledger.record_repayment(
            self.business,
            self.customer,
            "PAY-001",
            "3000",
            confirmed=True,
        )

        reopened = RepaymentLedger(self.path)

        self.assertEqual(
            reopened.customer_balance(
                self.business, self.customer
            ),
            2000,
        )

    def test_business_separation(self):
        other_business = self.ledger.create_business(
            "Other Test Shop"
        )

        with self.assertRaises(ValueError):
            self.ledger.record_repayment(
                other_business,
                self.customer,
                "PAY-001",
                "1000",
                confirmed=True,
            )

        with self.assertRaises(ValueError):
            self.ledger.list_repayments(
                other_business, self.customer
            )

    def test_repayment_history_immutable(self):
        repayment_id = self.ledger.record_repayment(
            self.business,
            self.customer,
            "PAY-001",
            "3000",
            confirmed=True,
        )

        with self.assertRaises(sqlite3.IntegrityError):
            with self.ledger.connect() as db:
                db.execute(
                    """UPDATE repayments SET amount_kobo = 100
                       WHERE id = ?""",
                    (repayment_id,),
                )

        with self.assertRaises(sqlite3.IntegrityError):
            with self.ledger.connect() as db:
                db.execute(
                    "DELETE FROM repayments WHERE id = ?",
                    (repayment_id,),
                )

        self.assertEqual(
            self.ledger.customer_balance(
                self.business, self.customer
            ),
            2000,
        )


if __name__ == "__main__":
    unittest.main()
