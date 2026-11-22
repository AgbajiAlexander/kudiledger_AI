import sqlite3
import tempfile
import unittest
from pathlib import Path

from app.db.repayments import RepaymentLedger


class TestSaleIntegrity(unittest.TestCase):

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)

        path = Path(temp.name) / "integrity.db"
        self.ledger = RepaymentLedger(path)

        self.business = self.ledger.create_business(
            "Test Abuja Shop"
        )
        self.customer = self.ledger.create_customer(
            self.business, "Musa"
        )

        self.sale = self.ledger.record_sale(
            self.business,
            self.customer,
            "SALE-001",
            "15000",
            "10000",
            confirmed=True,
        )

    def test_confirmed_sale_amount_cannot_change(self):
        with self.assertRaises(sqlite3.IntegrityError):
            with self.ledger.connect() as db:
                db.execute(
                    """UPDATE sales
                       SET total_kobo = 2000000
                       WHERE id = ?""",
                    (self.sale,),
                )

        self.assertEqual(
            self.ledger.customer_balance(
                self.business, self.customer
            ),
            5000,
        )

    def test_confirmed_payment_cannot_change(self):
        with self.assertRaises(sqlite3.IntegrityError):
            with self.ledger.connect() as db:
                db.execute(
                    """UPDATE sales
                       SET paid_kobo = 1500000
                       WHERE id = ?""",
                    (self.sale,),
                )

        self.assertEqual(
            self.ledger.customer_balance(
                self.business, self.customer
            ),
            5000,
        )

    def test_confirmed_sale_cannot_be_deleted(self):
        with self.assertRaises(sqlite3.IntegrityError):
            with self.ledger.connect() as db:
                db.execute(
                    "DELETE FROM sales WHERE id = ?",
                    (self.sale,),
                )

        with self.ledger.connect() as db:
            count = db.execute(
                "SELECT COUNT(*) FROM sales WHERE id = ?",
                (self.sale,),
            ).fetchone()[0]

        self.assertEqual(count, 1)

    def test_new_sale_can_still_be_recorded(self):
        self.ledger.record_sale(
            self.business,
            self.customer,
            "SALE-002",
            "5000",
            "2000",
            confirmed=True,
        )

        self.assertEqual(
            self.ledger.customer_balance(
                self.business, self.customer
            ),
            8000,
        )


if __name__ == "__main__":
    unittest.main()
