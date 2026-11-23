import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from app.api.main import create_app
from app.services.reports import ReportLedger


class TestDailyReportAPI(unittest.TestCase):

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)

        path = Path(temporary.name) / "daily_api.db"
        self.ledger = ReportLedger(path)
        self.client = TestClient(create_app(path))

        owner = self.ledger.register_owner(
            "Abuja Test Shop",
            "daily-api@example.test",
            "SecureTestPassword123!",
        )
        self.business = owner["business_id"]
        self.token = self.ledger.login(
            "daily-api@example.test",
            "SecureTestPassword123!",
        )

        other = self.ledger.register_owner(
            "Other Test Shop",
            "other-daily@example.test",
            "AnotherSecurePassword456!",
        )
        self.other_business = other["business_id"]
        self.other_token = self.ledger.login(
            "other-daily@example.test",
            "AnotherSecurePassword456!",
        )

        self.customer = self.ledger.add_customer(
            self.token, self.business, "Musa"
        )
        self.today = datetime.now(
            timezone.utc
        ).date().isoformat()

    def url(self, business=None, day=None):
        business = business or self.business
        day = day or self.today
        return (
            f"/api/v1/businesses/{business}"
            f"/reports/daily?report_date={day}"
        )

    def headers(self, token=None):
        return {
            "Authorization": f"Bearer {token or self.token}"
        }

    def sale(self, paid="5000"):
        return self.ledger.add_sale(
            self.token, self.business, self.customer,
            "SALE-001", "15000", paid,
            confirmed=True,
        )

    def test_empty_day_report(self):
        response = self.client.get(
            self.url(), headers=self.headers()
        )
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result["gross_sales"], "0")
        self.assertEqual(result["recorded_cash_received"], "0")
        self.assertEqual(result["timezone"], "UTC")

    def test_credit_sale_and_cash_are_separate(self):
        self.sale()

        response = self.client.get(
            self.url(), headers=self.headers()
        )

        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result["gross_sales"], "15000")
        self.assertEqual(result["paid_at_sale"], "5000")
        self.assertEqual(
            result["current_outstanding_debt"], "10000"
        )

    def test_repayments_and_expenses(self):
        self.sale()

        self.ledger.add_repayment(
            self.token, self.business, self.customer,
            "PAY-001", "2000", confirmed=True,
        )

        self.ledger.record_expense(
            self.token, self.business,
            "EXP-001", "Transport",
            "Transporting goods to market",
            "1500", confirmed=True,
        )

        response = self.client.get(
            self.url(), headers=self.headers()
        )

        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result["repayments_received"], "2000")
        self.assertEqual(
            result["recorded_cash_received"], "7000"
        )
        self.assertEqual(result["operating_expenses"], "1500")
        self.assertEqual(
            result["current_outstanding_debt"], "8000"
        )

    def test_unpaid_sale_reversal(self):
        sale_id = self.sale(paid="0")

        self.ledger.reverse_unpaid_sale(
            self.token, self.business, sale_id,
            "REV-001",
            "Duplicate unpaid sale recorded in error",
            confirmed=True,
        )

        response = self.client.get(
            self.url(), headers=self.headers()
        )

        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(
            result["reversed_sale_value"], "15000"
        )
        self.assertEqual(
            result["current_outstanding_debt"], "0"
        )

    def test_invalid_report_date_rejected(self):
        response = self.client.get(
            self.url(day="2026-02-30"),
            headers=self.headers(),
        )
        self.assertEqual(response.status_code, 400)

    def test_missing_or_invalid_token_rejected(self):
        response = self.client.get(self.url())
        self.assertEqual(response.status_code, 401)

        response = self.client.get(
            self.url(),
            headers={
                "Authorization": "Bearer invalid-token"
            },
        )
        self.assertEqual(response.status_code, 401)

    def test_other_business_owner_is_denied(self):
        self.sale()

        response = self.client.get(
            self.url(),
            headers=self.headers(self.other_token),
        )
        self.assertEqual(response.status_code, 403)

        response = self.client.get(
            self.url(self.other_business),
            headers=self.headers(self.other_token),
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["gross_sales"], "0"
        )


if __name__ == "__main__":
    unittest.main()
