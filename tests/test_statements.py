import tempfile
import unittest
from pathlib import Path

from app.services.statements import StatementLedger


class TestCustomerStatements(unittest.TestCase):

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)

        self.path = Path(temp.name) / "statements.db"
        self.ledger = StatementLedger(self.path)

        owner = self.ledger.register_owner(
            "Test Abuja Shop",
            "statement-owner@example.test",
            "SafeTestPassword123!",
        )
        self.business = owner["business_id"]
        self.token = self.ledger.login(
            "statement-owner@example.test",
            "SafeTestPassword123!",
        )
        self.customer = self.ledger.add_customer(
            self.token, self.business, "Musa"
        )

    def statement(self):
        return self.ledger.customer_statement(
            self.token, self.business, self.customer
        )

    def sale(self, reference="SALE-001", paid="10000"):
        return self.ledger.add_sale(
            self.token, self.business, self.customer,
            reference, "15000", paid, confirmed=True,
        )

    def test_empty_statement(self):
        result = self.statement()
        self.assertEqual(result["transaction_count"], 0)
        self.assertEqual(result["closing_balance"], "0")
        self.assertTrue(result["reconciled"])

    def test_sale_appears_in_statement(self):
        self.sale()
        result = self.statement()

        self.assertEqual(result["transaction_count"], 1)
        self.assertEqual(
            result["transactions"][0]["type"], "SALE"
        )
        self.assertEqual(
            result["transactions"][0]["debt_change"], "5000"
        )
        self.assertEqual(result["closing_balance"], "5000")
        self.assertTrue(result["reconciled"])

    def test_repayments_and_adjustments_reconcile(self):
        self.sale()

        self.ledger.add_repayment(
            self.token, self.business, self.customer,
            "PAY-001", "2000", confirmed=True,
        )

        self.ledger.adjust_customer_balance(
            self.token, self.business, self.customer,
            "ADJ-001", "-500",
            "Correction verified against shop records",
            confirmed=True,
        )

        result = self.statement()

        self.assertEqual(result["transaction_count"], 3)
        self.assertEqual(result["closing_balance"], "2500")
        self.assertTrue(result["reconciled"])

        kinds = {
            item["type"] for item in result["transactions"]
        }
        self.assertEqual(
            kinds, {"SALE", "REPAYMENT", "ADJUSTMENT"}
        )

    def test_sale_reversal_reconciles(self):
        sale_id = self.sale(paid="0")

        self.ledger.reverse_unpaid_sale(
            self.token, self.business, sale_id,
            "REV-001",
            "Duplicate unpaid sale entered in error",
            confirmed=True,
        )

        result = self.statement()

        self.assertEqual(result["transaction_count"], 2)
        self.assertEqual(result["closing_balance"], "0")
        self.assertTrue(result["reconciled"])

        kinds = [t["type"] for t in result["transactions"]]
        self.assertIn("SALE_REVERSAL", kinds)

    def test_other_business_cannot_read_statement(self):
        other = self.ledger.register_owner(
            "Other Test Shop",
            "other-statement@example.test",
            "OtherSafePassword456!",
        )
        other_token = self.ledger.login(
            "other-statement@example.test",
            "OtherSafePassword456!",
        )

        with self.assertRaises(PermissionError):
            self.ledger.customer_statement(
                other_token, self.business, self.customer
            )

        with self.assertRaises(ValueError):
            self.ledger.customer_statement(
                other_token, other["business_id"], self.customer
            )

    def test_customer_data_is_separated(self):
        other_customer = self.ledger.add_customer(
            self.token, self.business, "Amina"
        )

        self.sale()
        self.ledger.add_sale(
            self.token, self.business, other_customer,
            "SALE-002", "5000", "0", confirmed=True,
        )

        result = self.statement()
        self.assertEqual(result["transaction_count"], 1)
        self.assertEqual(result["closing_balance"], "5000")
        self.assertTrue(result["reconciled"])

    def test_statement_survives_restart(self):
        self.sale()
        reopened = StatementLedger(self.path)

        result = reopened.customer_statement(
            self.token, self.business, self.customer
        )

        self.assertEqual(result["closing_balance"], "5000")
        self.assertTrue(result["reconciled"])


if __name__ == "__main__":
    unittest.main()
