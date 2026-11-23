import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from app.services.reports import LAGOS, ReportLedger


class TestDailyReports(unittest.TestCase):

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)

        self.path = Path(temporary.name) / "reports.db"
        self.ledger = ReportLedger(self.path)

        owner = self.ledger.register_owner(
            "Test Abuja Shop",
            "reports@example.test",
            "SecureTestPassword123!",
        )
        self.business = owner["business_id"]
        self.token = self.ledger.login(
            "reports@example.test",
            "SecureTestPassword123!",
        )
        self.customer = self.ledger.add_customer(
            self.token, self.business, "Musa"
        )
        self.today = datetime.now(LAGOS).date().isoformat()

    def report(self):
        return self.ledger.daily_summary(
            self.token, self.business, self.today
        )

    def sale(self, reference="SALE-001", paid="5000"):
        return self.ledger.add_sale(
            self.token, self.business, self.customer,
            reference, "15000", paid, confirmed=True,
        )

    def test_empty_day(self):
        result = self.report()
        self.assertEqual(result["gross_sales"], "0")
        self.assertEqual(result["recorded_cash_received"], "0")
        self.assertEqual(result["operating_expenses"], "0")
        self.assertEqual(result["current_outstanding_debt"], "0")

    def test_sale_separates_cash_and_credit(self):
        self.sale()
        result = self.report()
        self.assertEqual(result["sales_count"], 1)
        self.assertEqual(result["gross_sales"], "15000")
        self.assertEqual(result["paid_at_sale"], "5000")
        self.assertEqual(result["recorded_cash_received"], "5000")
        self.assertEqual(result["current_outstanding_debt"], "10000")

    def test_repayment_increases_recorded_receipts(self):
        self.sale()
        self.ledger.add_repayment(
            self.token, self.business, self.customer,
            "PAY-001", "2000", confirmed=True,
        )
        result = self.report()
        self.assertEqual(result["repayments_received"], "2000")
        self.assertEqual(result["recorded_cash_received"], "7000")
        self.assertEqual(result["current_outstanding_debt"], "8000")

    def test_expenses_are_separate_from_sales(self):
        self.sale()
        self.ledger.record_expense(
            self.token, self.business,
            "EXP-001", "Transport",
            "Transporting goods to the market",
            "1500", confirmed=True,
        )
        result = self.report()
        self.assertEqual(result["operating_expenses"], "1500")
        self.assertEqual(result["gross_sales"], "15000")
        self.assertEqual(result["expenses_count"], 1)

    def test_unpaid_sale_reversal(self):
        sale_id = self.sale(paid="0")
        self.ledger.reverse_unpaid_sale(
            self.token, self.business, sale_id,
            "REV-001",
            "Duplicate unpaid sale entered in error",
            confirmed=True,
        )
        result = self.report()
        self.assertEqual(result["gross_sales"], "15000")
        self.assertEqual(result["reversed_sale_value"], "15000")
        self.assertEqual(result["current_outstanding_debt"], "0")

    def test_invalid_date_rejected(self):
        for value in ("2026-02-30", "23-11-2026", "abc", "0001-01-01", "9999-12-31"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    self.ledger.daily_summary(
                        self.token, self.business, value
                    )

    def test_other_business_cannot_read_report(self):
        other = self.ledger.register_owner(
            "Other Shop",
            "other-reports@example.test",
            "AnotherSecurePassword456!",
        )
        other_token = self.ledger.login(
            "other-reports@example.test",
            "AnotherSecurePassword456!",
        )
        self.sale()

        with self.assertRaises(PermissionError):
            self.ledger.daily_summary(
                other_token, self.business, self.today
            )

        result = self.ledger.daily_summary(
            other_token, other["business_id"], self.today
        )
        self.assertEqual(result["gross_sales"], "0")

    def test_previous_day_excludes_todays_activity(self):
        self.sale()
        result = self.ledger.daily_summary(
            self.token, self.business, "2020-01-01"
        )
        self.assertEqual(result["gross_sales"], "0")
        self.assertEqual(result["paid_at_sale"], "0")
        self.assertEqual(result["current_outstanding_debt"], "10000")

    def insert_utc_activity(self, stamp, price_kobo):
        with self.ledger.connect() as db:
            for sale_type, paid in (("credit", price_kobo // 4), ("reversed", 0)):
                sale_id = f"{stamp}-{sale_type}"
                db.execute(
                    """INSERT INTO sales
                       (id, business_id, customer_id, sale_reference,
                        total_kobo, paid_kobo, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (sale_id, self.business, self.customer, sale_id, price_kobo, paid, stamp),
                )
            db.execute(
                """INSERT INTO repayments
                   (id, business_id, customer_id, repayment_reference, amount_kobo, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (stamp, self.business, self.customer, stamp, price_kobo // 10, stamp),
            )
            db.execute(
                """INSERT INTO expenses
                   (id, business_id, expense_reference, category, description, amount_kobo, created_at)
                   VALUES (?, ?, ?, 'Transport', 'Synthetic delivery', ?, ?)""",
                (stamp, self.business, stamp, price_kobo // 5, stamp),
            )
            db.execute(
                """INSERT INTO sale_reversals
                   (id, business_id, sale_id, reversal_reference, amount_kobo, reason, created_at)
                   VALUES (?, ?, ?, ?, ?, 'Synthetic correction', ?)""",
                (stamp, self.business, f"{stamp}-reversed", stamp, price_kobo, stamp),
            )

    def test_all_activity_at_lagos_calendar_boundaries(self):
        cases = (
            ("2026-04-30", "2026-05-01"),
            ("2025-12-31", "2026-01-01"),
            ("2024-02-28", "2024-02-29"),
            ("2020-02-29", "2020-03-01"),
        )
        for before_day, after_day in cases:
            with self.subTest(before=before_day, after=after_day):
                before = f"{before_day} 22:59:59"
                boundary = f"{before_day} 23:00:00"
                self.insert_utc_activity(before, 10000)
                self.insert_utc_activity(boundary, 20000)
                self.insert_utc_activity(f"{before_day} 23:00:01", 20000)

                earlier = self.ledger.daily_summary(self.token, self.business, before_day)
                later = self.ledger.daily_summary(self.token, self.business, after_day)
                expected = {
                    "sales_count": (2, 4), "repayments_count": (1, 2),
                    "expenses_count": (1, 2), "reversals_count": (1, 2),
                    "gross_sales": ("200", "800"), "repayments_received": ("10", "40"),
                    "recorded_cash_received": ("35", "140"),
                    "operating_expenses": ("20", "80"),
                    "reversed_sale_value": ("100", "400"),
                }
                for key, values in expected.items():
                    self.assertEqual((earlier[key], later[key]), values, key)
                self.assertEqual(earlier["current_outstanding_debt"], later["current_outstanding_debt"])
                saved = self.ledger.lookup_transaction(
                    self.token, self.business, "sale", f"{boundary}-credit",
                )
                self.assertEqual(saved["created_at"], boundary)


if __name__ == "__main__":
    unittest.main()
