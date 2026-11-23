import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from app.services.reports import ReportLedger


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
        self.today = datetime.now(timezone.utc).date().isoformat()

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
        for value in ("2026-02-30", "23-11-2026", "abc"):
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


if __name__ == "__main__":
    unittest.main()
