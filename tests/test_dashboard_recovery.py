import unittest
from pathlib import Path


PAGE = (
    Path(__file__).resolve().parents[1]
    / "app" / "web" / "index.html"
)


class TestDashboardRecovery(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.page = PAGE.read_text(encoding="utf-8-sig")

    def test_transaction_lookup_is_connected(self):
        self.assertIn("/transactions/lookup?", self.page)
        self.assertIn("URLSearchParams", self.page)

    def test_original_transaction_details_are_compared(self):
        self.assertIn("function sameTransaction(", self.page)
        self.assertIn("saved.customer_id", self.page)
        self.assertIn("saved.reference", self.page)
        self.assertIn("cents(saved.amount)", self.page)

    def test_uncertain_submission_blocks_resubmission(self):
        self.assertIn(
            "button.disabled = busy || Boolean(pending)",
            self.page,
        )
        self.assertIn(
            "if (busy || pending)",
            self.page,
        )
        self.assertIn("await verifyPending()", self.page)

    def test_manual_verification_button_exists(self):
        self.assertIn(
            "Check saved transaction",
            self.page,
        )
        self.assertIn(
            'checkButton.addEventListener("click", verifyPending)',
            self.page,
        )


if __name__ == "__main__":
    unittest.main()
