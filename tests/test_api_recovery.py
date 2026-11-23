import hashlib
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi.testclient import TestClient

from app.api.main import create_app
from app.services.recovery import RecoveryLedger


class TestRecoveryAPI(unittest.TestCase):
    password = "SyntheticRecoveryPassword123!"

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        path = Path(temp.name) / "recovery.db"
        self.ledger = RecoveryLedger(path)
        self.client = TestClient(create_app(path), raise_server_exceptions=False)
        self.addCleanup(self.client.close)
        self.owner = self.ledger.register_owner("Recovery Shop", "owner@example.test", self.password)
        self.business = self.owner["business_id"]
        self.token = self.ledger.login("owner@example.test", self.password)
        self.customer = self.ledger.add_customer(self.token, self.business, "Amina")
        self.payload = {
            "kind": "sale", "reference": "REC-1", "total": "100.01",
            "paid": "25.01", "customer_id": self.customer, "confirmed": True,
        }

    def request(self, method, path="", *, token=None, business=None, **kwargs):
        return self.client.request(
            method, f"/api/v1/businesses/{business or self.business}/recovery" + path,
            headers={"Authorization": f"Bearer {token or self.token}"}, **kwargs,
        )

    def prepared(self, **changes):
        response = self.request("POST", json={**self.payload, **changes})
        self.assertEqual(response.status_code, 201)
        return "/" + response.json()["id"]

    def test_prepared_cancel_is_atomic_and_does_not_write(self):
        attempt = self.prepared()
        listed = self.request("GET")
        self.assertEqual(listed.headers["cache-control"], "no-store")
        self.assertEqual(listed.json()[0]["status"], "prepared")
        self.assertNotIn("customer_id", listed.json()[0])
        self.assertNotIn("payload", listed.json()[0])
        self.assertEqual(self.request("POST", attempt + "/check").json()["status"], "prepared")
        self.assertEqual(self.request("DELETE", attempt + "?action=cancel").status_code, 200)
        self.assertEqual(self.request("POST", attempt + "/submit").status_code, 404)
        self.assertEqual(self.ledger.daily_summary(
            self.token, self.business, "2024-01-01",
        )["current_outstanding_debt"], "0")

    def test_competing_prepares_writes_and_checks(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            prepared = list(pool.map(
                lambda ref: self.request("POST", json={**self.payload, "reference": ref}),
                ("RACE-1", "RACE-2"),
            ))
        self.assertCountEqual([result.status_code for result in prepared], [201, 409])
        recovery = next(result.json() for result in prepared if result.status_code == 201)
        attempt = "/" + recovery["id"]

        with ThreadPoolExecutor(max_workers=2) as pool:
            writes = list(pool.map(lambda _: self.request("POST", attempt + "/submit"), range(2)))
        self.assertCountEqual([result.status_code for result in writes], [200, 409])
        saved = next(result.json() for result in writes if result.status_code == 200)
        self.assertEqual(saved["status"], "saved")
        self.assertEqual(self.request("GET").json()[0]["status"], "unresolved")
        self.assertEqual(self.request("DELETE", attempt + "?action=cancel").status_code, 409)
        with ThreadPoolExecutor(max_workers=2) as pool:
            checked = list(pool.map(lambda _: self.request("POST", attempt + "/check"), range(2)))
        for result in checked:
            self.assertEqual(result.status_code, 200)
            self.assertEqual(result.json()["status"], "committed")
            self.assertEqual(result.json()["transaction_id"], saved["transaction_id"])
        with self.ledger.connect() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM sales").fetchone()[0], 1)

    def test_missing_lookup_after_uncertain_write_remains_blocked(self):
        attempt = self.prepared()
        # KLD-006B4 could persist a claim before its financial write.
        with self.ledger.connect() as db:
            db.execute("UPDATE recovery_attempts SET stage = 'sending' WHERE id = ?", (attempt[1:],))
        self.assertEqual(self.request("POST", attempt + "/check").json()["status"], "unresolved")
        self.assertEqual(self.request("POST", attempt + "/submit").status_code, 409)
        self.assertEqual(self.request("DELETE", attempt + "?action=dismiss").status_code, 409)
        self.assertEqual(self.request("POST", json={**self.payload, "reference": "NEW"}).status_code, 409)

    def test_acknowledgement_keeps_a_recent_record_without_exposing_receipt_id(self):
        attempt = self.prepared()
        saved = self.request("POST", attempt + "/submit").json()
        self.assertEqual(self.request("DELETE", attempt + "?action=dismiss").status_code, 409)
        denied = self.request("POST", attempt + "/acknowledge", json={"transaction_id": "wrong"})
        self.assertEqual(denied.status_code, 409)
        self.assertEqual(self.request("GET").json()[0]["status"], "unresolved")
        result = self.request("POST", attempt + "/acknowledge", json={
            "transaction_id": saved["transaction_id"],
        })
        self.assertEqual(result.status_code, 200)
        recent = self.request("GET").json()[0]
        self.assertEqual(recent["status"], "recent")
        self.assertIsNone(recent["transaction_id"])
        verified = self.request("POST", attempt + "/check").json()
        self.assertEqual(verified["transaction_id"], saved["transaction_id"])
        self.assertEqual(self.request("DELETE", attempt + "?action=dismiss").status_code, 200)
        self.assertEqual(self.request("GET").json(), [])
        with self.ledger.connect() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM sales").fetchone()[0], 1)

    def test_conflict_and_rejection_are_distinct(self):
        result = self.request("POST", self.prepared(paid="120") + "/submit").json()
        self.assertEqual(result["status"], "rejected")
        self.assertEqual(self.request("POST", "/" + result["id"] + "/check").json()["status"], "rejected")
        self.ledger.add_sale(
            self.token, self.business, self.customer, "CLASH", "100.01", "25.00", confirmed=True,
        )
        attempt = self.prepared(reference="CLASH")
        result = self.request("POST", attempt + "/submit").json()
        self.assertEqual(result["status"], "conflict")
        self.assertIsNone(result["transaction_id"])
        self.assertEqual(self.request("POST", attempt + "/check").json()["status"], "conflict")
        self.assertEqual(self.request("DELETE", attempt + "?action=dismiss").status_code, 409)

    def test_prepare_requires_explicit_confirmation(self):
        self.assertEqual(self.request("POST", json={**self.payload, "confirmed": False}).status_code, 400)
        self.assertEqual(self.request("GET").json(), [])

    def test_expense_and_repayment_keep_original_values(self):
        self.ledger.add_sale(
            self.token, self.business, self.customer, "SEED", "100.01", "0", confirmed=True,
        )
        repayment = self.prepared(kind="repayment", reference="PAY", amount="1.01")
        expense = self.prepared(
            kind="expense", reference="EXP", amount="0.01", category="Transport",
            description="Stock delivery",
        )
        for attempt, kind, amount in ((repayment, "repayment", "1.01"), (expense, "expense", "0.01")):
            with self.subTest(kind=kind):
                # A supplied submit body cannot override the stored fields.
                response = self.request("POST", attempt + "/submit", json={"amount": "77"})
                self.assertEqual(response.status_code, 200)
                result = self.request("POST", attempt + "/check").json()
                self.assertEqual(result["status"], "committed")
                receipt = self.ledger.transaction_receipt(
                    self.token, self.business, kind, result["transaction_id"], None,
                )
                self.assertEqual(receipt["amount"], amount)

    def test_journal_is_private_to_account_and_business_and_requires_active_session(self):
        attempt = self.prepared()
        peer = self.ledger.register_owner("Other Shop", "peer@example.test", self.password)
        peer_token = self.ledger.login("peer@example.test", self.password)
        self.assertEqual(self.request("GET", token=peer_token).status_code, 403)
        self.assertEqual(self.request("POST", attempt + "/check", token=peer_token,
                                      business=peer["business_id"]).status_code, 404)
        with self.ledger.connect() as db:
            db.execute(
                "INSERT INTO memberships (user_id, business_id, role) VALUES (?, ?, 'OWNER')",
                (peer["user_id"], self.business),
            )
        self.assertEqual(self.request("GET", token=peer_token).json(), [])
        for method, suffix in (("POST", "/check"), ("POST", "/submit"), ("DELETE", "?action=cancel")):
            self.assertEqual(self.request(method, attempt + suffix, token=peer_token).status_code, 404)

        with self.ledger.connect() as db:
            token_hash = hashlib.sha256(self.token.encode()).hexdigest()
            db.execute("UPDATE sessions SET expires_at = 0 WHERE token_hash = ?", (token_hash,))
        self.assertEqual(self.request("GET").status_code, 401)
        self.assertEqual(self.request("POST", attempt + "/check").status_code, 401)
        self.token = self.ledger.login("owner@example.test", self.password)
        self.assertEqual(self.request("GET").json()[0]["reference"], "REC-1")
