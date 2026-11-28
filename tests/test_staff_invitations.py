import json
import sqlite3
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.api.main import create_app
from app.db.migrations import migrate_legacy_database
from app.db.staff_migration import migrate_staff_invitations
from app.operations.pilot import backup_database, restore_database
from app.services.account_mail import AccountMail
from app.services.identity import digest
from app.services.telemetry import StagingLedger


class TestStaffInvitations(unittest.TestCase):
    password = "SyntheticStaffFixture123!"

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.path = self.root / "legacy.sqlite"
        self.capture = self.root / "capture"
        self.capture.mkdir(mode=0o700)
        self.ledger = StagingLedger(self.path)
        self.owner = self.ledger.register_owner("Synthetic Owner", "owner@example.test", self.password)
        self.other = self.ledger.register_owner("Synthetic Other", "other@example.test", self.password)
        self.business, self.other_branch = self.owner["business_id"], self.other["business_id"]
        self.token = self.ledger.login("owner@example.test", self.password)
        self.other_token = self.ledger.login("other@example.test", self.password)
        migrate_legacy_database(self.path)
        migrate_staff_invitations(self.path)
        self.branch = self.ledger.create_business("Synthetic Secondary Branch")
        with self.ledger.connect() as db:
            orgs = dict(db.execute("SELECT id, organization_id FROM branches"))
            self.org, self.other_org = orgs[self.business], orgs[self.other_branch]
            db.execute("INSERT INTO branches VALUES (?, ?, 0)", (self.branch, self.org))
        self.mail = AccountMail(mode="capture", origin="http://localhost", directory=self.capture)
        self.app = create_app(self.path, require_https=False, account_mail=self.mail)
        self.client = TestClient(self.app, raise_server_exceptions=False)
        self.addCleanup(self.client.close)

    @staticmethod
    def headers(token):
        return {"Authorization": f"Bearer {token}"} if token else {}

    def issue(self, email="new@example.test", *, token=None, org=None, grants=None):
        return self.client.post(f"/api/v1/organizations/{org or self.org}/staff-invitations",
                                headers=self.headers(token or self.token), json={
            "email": email, "branches": grants or [{"branch_id": self.business, "role": "CASHIER"}],
        })

    def issued(self, email="new@example.test", **kwargs):
        response = self.issue(email, **kwargs)
        self.assertEqual(response.status_code, 201, response.text)
        messages = [json.loads(file.read_text()) for file in self.capture.glob("*.json")]
        self.assertEqual(set(response.json()), {"id"})
        return response.json()["id"], next(item["link"].split("#staff-invite=")[1]
                                           for item in messages if item["to"] == email)

    def accept(self, secret, *, token=None, password=None):
        return self.client.post("/api/v1/auth/staff-invitations/accept", headers=self.headers(token),
                                json={"token": secret, "password": password})

    def revoke(self, invitation_id, *, org=None, token=None):
        return self.client.delete(f"/api/v1/organizations/{org or self.org}/staff-invitations/{invitation_id}",
                                  headers=self.headers(token or self.token))

    def test_explicit_migration_rolls_back_and_is_idempotent(self):
        branch = self.root / "new.sqlite"
        StagingLedger(branch)
        with self.assertRaisesRegex(ValueError, "legacy mapping"):
            migrate_staff_invitations(branch)
        migrate_legacy_database(branch)
        self.assertFalse(migrate_staff_invitations(branch, dry_run=True)["applied"])
        with StagingLedger(branch).connect() as db:
            self.assertEqual([row[0] for row in db.execute("SELECT version FROM kudiledger_schema_versions")], [1])
            self.assertIsNone(db.execute("SELECT 1 FROM sqlite_schema WHERE name = 'staff_invitations'").fetchone())
        with patch("app.db.staff_migration.STATEMENTS", ("CREATE TABLE synthetic_throwaway(id)", "invalid sql")):
            with self.assertRaises(sqlite3.Error):
                migrate_staff_invitations(branch)
        self.assertTrue(migrate_staff_invitations(branch)["applied"])
        self.assertFalse(migrate_staff_invitations(branch)["applied"])
        with StagingLedger(branch).connect() as db:
            self.assertIsNone(db.execute("SELECT 1 FROM sqlite_schema WHERE name = 'synthetic_throwaway'").fetchone())

    def test_owner_issue_rejects_unauthorized_and_cross_scope_input(self):
        self.assertEqual(self.issue(token=self.other_token).status_code, 403)
        self.assertEqual(self.issue(org=self.other_org).status_code, 403)
        self.assertEqual(self.issue(grants=[{"branch_id": self.other_branch, "role": "CASHIER"}]).status_code, 400)
        self.assertEqual(self.issue(grants=[{"branch_id": self.business, "role": "OWNER"}]).status_code, 422)
        self.assertEqual(self.issue("live@example.com").status_code, 400)
        invitation, secret = self.issued()
        self.assertEqual(self.issue("NEW@example.test").status_code, 400)
        self.assertEqual(self.revoke(invitation, org=self.other_org, token=self.other_token).status_code, 400)
        with self.ledger.connect() as db:
            row = db.execute("SELECT * FROM staff_invitations").fetchone()
            self.assertEqual((row["id"], row["token_hash"], row["expires_at"] - row["created_at"]),
                             (invitation, digest(secret), 86400))
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("INSERT INTO staff_invitation_branches VALUES (?, ?, ?, 'CASHIER')",
                           (invitation, self.org, self.other_branch))
            audit = db.execute("SELECT * FROM staff_invitation_audit").fetchall()
            self.assertEqual([row["event"] for row in audit], ["issued"])
            self.assertNotIn(secret, repr([tuple(row) for row in audit]))
        with TestClient(create_app(self.path, account_mail=AccountMail(mode="smtp", origin="https://example.test"))) as client:
            response = client.post(f"/api/v1/organizations/{self.org}/staff-invitations",
                                   headers=self.headers(self.token), json={"email": "smtp@example.test",
                                       "branches": [{"branch_id": self.business, "role": "MANAGER"}]})
            self.assertEqual(response.status_code, 403)

    def test_existing_identity_requires_matching_active_session(self):
        invitation, secret = self.issued("other@example.test")
        self.assertEqual(self.accept(secret, password=self.password).status_code, 403)
        self.assertEqual(self.accept(secret, token=self.token).status_code, 403)
        self.assertEqual(self.accept(secret, token=self.other_token).status_code, 200)
        self.assertEqual(self.accept(secret, token=self.other_token).status_code, 400)
        self.assertEqual(self.revoke(invitation).status_code, 400)
        self.assertEqual(self.issue("other@example.test").status_code, 400)
        with self.ledger.connect() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM users").fetchone()[0], 2)
            self.assertEqual(db.execute("SELECT role FROM organization_memberships WHERE organization_id=? AND user_id=?",
                                        (self.org, self.other["user_id"])).fetchone()[0], "MEMBER")
        self.assertEqual(self.ledger.list_my_businesses(self.other_token)[0]["id"], self.other_branch)

    def test_revoked_expired_and_issuer_revocation_are_denied(self):
        revoked, revoked_secret = self.issued("revoked@example.test")
        self.assertEqual(self.revoke(revoked).status_code, 204)
        self.assertEqual(self.accept(revoked_secret, password=self.password).status_code, 400)
        expired, expired_secret = self.issued("expired@example.test")
        now = int(time.time())
        with self.ledger.connect() as db:
            db.execute("UPDATE staff_invitations SET created_at=?, expires_at=? WHERE id=?",
                       (now - 100, now - 1, expired))
        self.assertEqual(self.accept(expired_secret, password=self.password).status_code, 400)
        _, active = self.issued("blocked@example.test")
        with self.ledger.connect() as db:
            db.execute("DELETE FROM memberships WHERE business_id=? AND user_id=?",
                       (self.business, self.owner["user_id"]))
        self.assertEqual(self.accept(active, password=self.password).status_code, 403)
        self.assertEqual(self.issue().status_code, 403)
        with self.ledger.connect() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM branch_assignments").fetchone()[0], 0)

    def test_concurrent_acceptance_and_atomic_rollback(self):
        invitation, secret = self.issued(grants=[{"branch_id": self.business, "role": "MANAGER"},
                                                 {"branch_id": self.branch, "role": "ACCOUNTANT"}])
        with self.ledger.connect() as db:
            db.execute("""CREATE TRIGGER injected_failure BEFORE INSERT ON staff_invitation_audit
                          WHEN NEW.event = 'accepted' BEGIN SELECT RAISE(ABORT, 'fixture'); END""")
        self.assertEqual(self.accept(secret, password=self.password).status_code, 500)
        with self.ledger.connect() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM users WHERE email='new@example.test'").fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT count(*) FROM branch_assignments").fetchone()[0], 0)
            self.assertIsNone(db.execute("SELECT accepted_at FROM staff_invitations WHERE id=?",
                                         (invitation,)).fetchone()[0])
            db.execute("DROP TRIGGER injected_failure")
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(lambda _: self.accept(secret, password=self.password).status_code, range(2)))
        self.assertCountEqual(outcomes, [200, 400])
        token = self.ledger.login("new@example.test", self.password)
        self.assertEqual(self.ledger.list_my_businesses(token), [])
        with self.ledger.connect() as db:
            self.assertEqual({row[0] for row in db.execute("SELECT role FROM branch_assignments")},
                             {"MANAGER", "ACCOUNTANT"})
            self.assertEqual(db.execute("SELECT count(*) FROM staff_invitation_audit WHERE event='accepted'").fetchone()[0], 1)
            self.assertEqual(db.execute("SELECT count(*) FROM account_security_audit WHERE event='email_verified'").fetchone()[0], 1)
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("DELETE FROM staff_invitation_audit")
        self.assertEqual(self.issue(token=token).status_code, 403)
        self.assertEqual(self.issue(grants=[{"branch_id": self.business, "role": "CASHIER"}] * 2).status_code, 400)

    def test_accepted_staff_cannot_use_any_legacy_financial_route(self):
        prefix = "/api/v1/businesses/{business_id}"
        financial = [route for route in self.app.routes if route.path.startswith(prefix)]
        self.assertTrue(financial)
        reason = "Synthetic access denial fixture"
        payload = {
            "name": "Synthetic", "customer_id": "customer", "sale_id": "sale", "reference": "REF",
            "total": "10.01", "paid": "0", "amount": "0.01", "confirmed": True, "kind": "sale",
            "reason": reason, "category": "Transport", "description": reason, "transaction_id": "sale",
            "decision": "retain_uncertain", "evidence_type": "inconclusive",
            "evidence_reference": "CASE", "evidence_notes": reason,
        }
        for role in ("MANAGER", "CASHIER", "ACCOUNTANT"):
            email = role.lower() + "@example.test"
            _, secret = self.issued(email, grants=[{"branch_id": self.business, "role": role}])
            self.assertEqual(self.accept(secret, password=self.password).status_code, 200)
            token = self.ledger.login(email, self.password)
            self.assertEqual(self.issue(token=token).status_code, 403)
            for route in financial:
                url = route.path.format(business_id=self.business, customer_id="customer", attempt_id="attempt")
                for method in route.methods:
                    with self.subTest(role=role, method=method, path=route.path):
                        result = self.client.request(
                            method, url, headers=self.headers(token), json=payload if method == "POST" else None,
                            params={"kind": "sale", "reference": "REF", "report_date": "2026-11-28", "action": "cancel"},
                        )
                        self.assertEqual(result.status_code, 403, result.text)

    def test_capture_failure_revokes_without_returning_credentials(self):
        with patch.object(self.mail, "send", side_effect=OSError("Synthetic capture failure")):
            response = self.issue()
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"detail": "Could not capture the invitation"})
        with self.ledger.connect() as db:
            self.assertIsNotNone(db.execute("SELECT revoked_at FROM staff_invitations").fetchone()[0])
            self.assertEqual([row[0] for row in db.execute("SELECT event FROM staff_invitation_audit ORDER BY id")],
                             ["issued", "delivery_failed"])

    def test_restore_revokes_pending_invitation_and_preserves_audit(self):
        invitation, secret = self.issued()
        snapshot, restored = self.root / "snapshot.sqlite", self.root / "restored.sqlite"
        backup = backup_database(self.path, snapshot)
        restore_database(snapshot, restored, backup["sha256"])
        replica = StagingLedger(restored)
        with self.assertRaisesRegex(ValueError, "unavailable"):
            replica.accept_staff_invitation(secret, password=self.password)
        with replica.connect() as db:
            events = db.execute("SELECT event FROM staff_invitation_audit WHERE invitation_id=? ORDER BY id",
                                (invitation,)).fetchall()
            self.assertEqual([row[0] for row in events], ["issued", "restore_revoked"])
