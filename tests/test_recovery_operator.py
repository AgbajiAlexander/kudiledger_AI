import sqlite3
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.api.main import create_app
from app.services.operators import PilotLedger


class TestRecoveryOperator(unittest.TestCase):
    password = "SyntheticOperatorPassword123!"

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        path = Path(folder.name) / "operator.db"
        self.ledger = PilotLedger(path)
        self.client = TestClient(create_app(path))
        self.addCleanup(self.client.close)
        self.owner, self.owner_token = self.register("owner")
        self.operator, self.operator_token = self.register("reviewer")
        self.business = self.owner["business_id"]
        self.customer = self.ledger.add_customer(self.owner_token, self.business, "Amina")
        with self.ledger.connect() as db:
            db.execute(
                "INSERT INTO memberships (user_id, business_id, role) VALUES (?, ?, 'OWNER')",
                (self.operator["user_id"], self.business),
            )
        self.ledger.set_recovery_operator(self.business, "reviewer@example.test", enabled=True)
        self.attempt = self.ledger.prepare_recovery(self.owner_token, self.business, "sale", {
            "customer_id": self.customer, "reference": "OPERATOR-1",
            "total": "100.01", "paid": "20.01", "confirmed": True,
        })["id"]
        # A B4 worker can have committed a standalone claim before upgrading.
        with self.ledger.connect() as db:
            db.execute("UPDATE recovery_attempts SET stage = 'sending' WHERE id = ?", (self.attempt,))

    def register(self, account):
        email = f"{account}@example.test"
        owner = self.ledger.register_owner(account + " shop", email, self.password)
        return owner, self.ledger.login(email, self.password)

    def request(self, method, suffix="", *, token=None, business=None, **kwargs):
        headers = {} if token == "" else {"Authorization": "Bearer " + (token or self.operator_token)}
        return self.client.request(
            method, f"/api/v1/businesses/{business or self.business}/operator/recovery{suffix}",
            headers=headers, **kwargs,
        )

    def decision(self, **changes):
        return {
            "decision": "retain_uncertain",
            "evidence_type": "inconclusive",
            "evidence_reference": "INC-SYNTHETIC-1",
            "evidence_notes": "Reviewed protected records; the evidence is incomplete.",
            "confirmed": True,
        } | changes

    def test_permission_grant_is_separate_from_membership(self):
        self.assertEqual(self.request("GET", token="").status_code, 401)
        self.assertEqual(self.request("GET", token=self.owner_token).status_code, 403)
        self.assertEqual(self.request("POST", f"/{self.attempt}/decisions",
                                      token=self.owner_token, json=self.decision()).status_code, 403)
        allowed = self.request("GET", params={"reference": "OPERATOR-1"})
        self.assertEqual(allowed.status_code, 200)
        self.assertEqual([entry["id"] for entry in allowed.json()], [self.attempt])
        self.assertNotIn("payload", allowed.json()[0])
        private = self.client.get(
            f"/api/v1/businesses/{self.business}/recovery",
            headers={"Authorization": "Bearer " + self.operator_token},
        )
        self.assertEqual(private.json(), [])

        other, other_token = self.register("external")
        self.ledger.set_recovery_operator(other["business_id"], "external@example.test", enabled=True)
        self.assertEqual(self.request("GET", token=other_token).status_code, 403)
        denied = self.request("POST", f"/{self.attempt}/decisions", token=other_token,
                              business=other["business_id"], json=self.decision())
        self.assertEqual(denied.status_code, 404)
        self.assertEqual(self.request("GET", f"/{self.attempt}/audit", token=other_token,
                                      business=other["business_id"]).json(), [])
        self.ledger.set_recovery_operator(self.business, "reviewer@example.test", enabled=False)
        self.assertEqual(self.request("GET").status_code, 403)

    def test_release_needs_confirmation_and_evidence_and_preserves_audit(self):
        endpoint = f"/{self.attempt}/decisions"
        attempt = self.decision(decision="release_failed")
        self.assertEqual(self.request("POST", endpoint, json=attempt).status_code, 409)
        attempt = self.decision(
            decision="release_failed", evidence_type="prewrite_failure",
            evidence_notes="Verified pre-write termination from the protected worker incident record.",
        )
        self.assertEqual(self.request("POST", endpoint, json={**attempt, "confirmed": False}).status_code, 400)
        self.assertEqual(self.request("POST", endpoint, json={**attempt, "evidence_reference": " "}).status_code, 400)
        retained = self.request("POST", endpoint, json=self.decision())
        self.assertEqual(retained.status_code, 201)
        self.assertEqual(retained.json()["status"], "unresolved")
        released = self.request("POST", endpoint, json=attempt)
        self.assertEqual(released.status_code, 201)
        self.assertEqual(released.json()["status"], "rejected")

        self.ledger.clear_recovery(self.owner_token, self.business, self.attempt)
        audit = self.request("GET", f"/{self.attempt}/audit")
        self.assertEqual(audit.status_code, 200)
        self.assertEqual(audit.headers["cache-control"], "no-store")
        entries = audit.json()
        self.assertEqual([event["decision"] for event in entries], ["retain_uncertain", "release_failed"])
        item = entries[-1]
        self.assertEqual(item["subject_user_id"], self.owner["user_id"])
        self.assertEqual(item["operator_user_id"], self.operator["user_id"])
        self.assertEqual(item["business_id"], self.business)
        self.assertEqual(item["evidence_reference"], attempt["evidence_reference"])
        self.assertEqual(item["evidence_notes"], attempt["evidence_notes"])
        self.assertEqual((item["previous_stage"], item["resulting_stage"]), ("sending", "rejected"))
        self.assertTrue(item["created_at"])
        self.assertFalse(self.ledger.lookup_transaction(
            self.owner_token, self.business, "sale", "OPERATOR-1",
        )["found"])
        with self.ledger.connect() as db:
            for command in (
                "UPDATE recovery_operator_audit SET evidence_notes = 'replace'",
                "DELETE FROM recovery_operator_audit",
            ):
                with self.subTest(command=command), self.assertRaises(sqlite3.IntegrityError):
                    db.execute(command)

    def test_operator_cannot_release_matching_committed_record(self):
        sale = self.ledger.add_sale(
            self.owner_token, self.business, self.customer, "OPERATOR-1", "100.01", "20.01", True,
        )
        endpoint = f"/{self.attempt}/decisions"
        for evidence in ("prewrite_failure", "ledger_conflict"):
            with self.subTest(evidence=evidence):
                response = self.request("POST", endpoint, json=self.decision(
                    decision="release_failed", evidence_type=evidence,
                ))
                self.assertEqual(response.status_code, 409)
        result = self.request("POST", endpoint, json=self.decision(
            decision="confirm_committed", evidence_type="ledger_match",
        ))
        self.assertEqual(result.status_code, 201)
        self.assertEqual(result.json()["status"], "committed")
        audited = self.request("GET", f"/{self.attempt}/audit").json()
        self.assertEqual(audited[0]["transaction_id"], sale)
        receipt = self.ledger.check_recovery(self.owner_token, self.business, self.attempt)
        self.assertEqual(receipt["transaction_id"], sale)
        self.assertEqual(str(self.ledger.get_balance(self.owner_token, self.business, self.customer)), "80")

    def test_operator_can_release_authoritative_reference_conflict(self):
        sale = self.ledger.add_sale(
            self.owner_token, self.business, self.customer, "OPERATOR-1", "100.01", "20.00", True,
        )
        conflict = self.ledger.check_recovery(self.owner_token, self.business, self.attempt)
        self.assertEqual(conflict["status"], "conflict")
        response = self.request("POST", f"/{self.attempt}/decisions", json=self.decision(
            decision="release_failed", evidence_type="ledger_conflict",
        ))
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["status"], "rejected")
        original = self.ledger.lookup_transaction(self.owner_token, self.business, "sale", "OPERATOR-1")
        self.assertEqual(original["id"], sale)
        self.assertEqual(original["paid"], "20")
