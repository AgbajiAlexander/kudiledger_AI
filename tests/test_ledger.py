import tempfile
import unittest
from pathlib import Path

from app.db.ledger import Ledger, to_kobo


class TestLedger(unittest.TestCase):

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

        self.path = Path(self.temp.name) / "test.db"
        self.ledger = Ledger(self.path)

        self.business = self.ledger.create_business(
            "KudiLedger Test Shop"
        )
        self.customer = self.ledger.create_customer(
            self.business, "Musa"
        )

    def test_money_precision(self):
        self.assertEqual(to_kobo("100.25"), 10025)
        self.assertEqual(to_kobo("0.01"), 1)

        with self.assertRaises(ValueError):
            to_kobo("100.001")

    def test_sale_and_balance(self):
        self.ledger.record_sale(
            self.business,
            self.customer,
            "SALE-001",
            "15000",
            "10000",
            confirmed=True,
        )

        self.assertEqual(
            str(self.ledger.customer_balance(
                self.business, self.customer
            )),
            "5000",
        )

    def test_persists_after_restart(self):
        self.ledger.record_sale(
            self.business,
            self.customer,
            "SALE-001",
            "15000",
            "10000",
            confirmed=True,
        )

        reopened = Ledger(self.path)

        self.assertEqual(
            reopened.customer_balance(
                self.business, self.customer
            ),
            5000,
        )

    def test_confirmation_required(self):
        with self.assertRaises(ValueError):
            self.ledger.record_sale(
                self.business,
                self.customer,
                "SALE-001",
                "15000",
                "10000",
            )

        self.assertEqual(
            self.ledger.customer_balance(
                self.business, self.customer
            ),
            0,
        )

    def test_duplicate_sale_rejected(self):
        for attempt in range(2):
            if attempt == 0:
                self.ledger.record_sale(
                    self.business,
                    self.customer,
                    "SALE-001",
                    "15000",
                    "10000",
                    confirmed=True,
                )
            else:
                with self.assertRaises(ValueError):
                    self.ledger.record_sale(
                        self.business,
                        self.customer,
                        "SALE-001",
                        "15000",
                        "10000",
                        confirmed=True,
                    )

        self.assertEqual(
            self.ledger.customer_balance(
                self.business, self.customer
            ),
            5000,
        )

    def test_business_separation(self):
        other_business = self.ledger.create_business(
            "Other Shop"
        )

        with self.assertRaises(ValueError):
            self.ledger.record_sale(
                other_business,
                self.customer,
                "SALE-001",
                "15000",
                "10000",
                confirmed=True,
            )

        with self.assertRaises(ValueError):
            self.ledger.customer_balance(
                other_business,
                self.customer,
            )

    def test_overpayment_rejected(self):
        with self.assertRaises(ValueError):
            self.ledger.record_sale(
                self.business,
                self.customer,
                "SALE-001",
                "15000",
                "16000",
                confirmed=True,
            )


if __name__ == "__main__":
    unittest.main()
