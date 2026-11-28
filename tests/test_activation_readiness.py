import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, contextmanager
from pathlib import Path
from threading import Event
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.api.main import create_app
from app.db.migrations import migrate_legacy_database
from app.operations.pilot import backup_database
from app.operations.tenant_readiness import verify_tenant_readiness
from app.services.authorization import LegacyScope, require_branch_permission
from app.services.telemetry import StagingLedger


class TestActivationReadiness(unittest.TestCase):
    password = "SyntheticReadinessFixture123!"

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.path = self.root / "fixture.sqlite"
        self.ledger = StagingLedger(self.path)
        self.owner = self.ledger.register_owner("Synthetic Shop", "one@example.test", self.password)
        self.other = self.ledger.register_owner("Another Shop", "two@example.test", self.password)
        self.business = self.owner["business_id"]
        self.other_branch = self.other["business_id"]
        self.token = self.ledger.login("one@example.test", self.password)
        self.other_token = self.ledger.login("two@example.test", self.password)
        migrate_legacy_database(self.path)
        self.branch = self.ledger.create_business("Second Branch")
        with self.ledger.connect() as db:
            orgs = dict(db.execute("SELECT id, organization_id FROM branches"))
            self.org, self.other_org = orgs[self.business], orgs[self.other_branch]
            db.execute("INSERT INTO branches VALUES (?, ?, 0)", (self.branch, self.org))
        self.customer = self.ledger.add_customer(self.token, self.business, "Initial Synthetic Customer")
        self.ledger.add_sale(self.token, self.business, self.customer, "SALE-1", "95.01", "0", confirmed=True)
        self.app = create_app(self.path)
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)
        self.headers = {"Authorization": f"Bearer {self.token}"}
        self.base = f"/api/v1/businesses/{self.business}"

    def revoke(self, db):
        db.execute("DELETE FROM organization_memberships WHERE organization_id=? AND user_id=?",
                   (self.org, self.owner["user_id"]))

    def test_inflight_read_uses_pre_revocation_snapshot_and_new_reads_fail(self):
        with self.ledger.connect() as db:
            self.assertEqual(db.execute("PRAGMA journal_mode = WAL").fetchone()[0], "wal")
        entered, resume = Event(), Event()
        authorize = StagingLedger._authorize

        def pause_once(ledger, token, branch, *, _db=None):
            result = authorize(ledger, token, branch, _db=_db)
            if token == self.token and not entered.is_set():
                self.assertTrue(_db.in_transaction)
                entered.set()
                if not resume.wait(10):
                    raise RuntimeError("Synthetic read barrier timed out")
            return result

        with patch.object(StagingLedger, "_authorize", pause_once), ThreadPoolExecutor(max_workers=1) as worker:
            inflight = worker.submit(self.client.get, self.base + "/customers", headers=self.headers)
            try:
                self.assertTrue(entered.wait(5))
                with self.ledger.connect() as db:
                    self.revoke(db)
                    db.execute("UPDATE customers SET name='Changed after revocation' WHERE id=?", (self.customer,))
                self.assertEqual(self.client.get(self.base + "/customers", headers=self.headers).status_code, 403)
            finally:
                resume.set()
            response = inflight.result(timeout=10)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["customers"][0]["name"], "Initial Synthetic Customer")

    def test_every_protected_business_read_denies_after_commit(self):
        with self.ledger.connect() as db:
            self.revoke(db)
        prefix = "/api/v1/businesses/{business_id}"
        routes = [route for route in self.app.routes if route.path.startswith(prefix) and "GET" in route.methods]
        self.assertGreater(len(routes), 10)
        for route in routes:
            path = route.path.format(business_id=self.business, customer_id=self.customer, attempt_id="synthetic")
            with self.subTest(path=path):
                response = self.client.get(path, headers=self.headers, params={
                    "kind": "sale", "reference": "SALE-1", "report_date": "2026-11-28",
                })
                self.assertEqual(response.status_code, 403, response.text)
        self.assertEqual(self.client.get(f"/api/v1/organizations/{self.org}/branches",
                                         headers=self.headers).status_code, 403)
        self.assertEqual(self.client.get("/api/v1/auth/organizations", headers=self.headers).json(), [])
        with self.ledger.connect() as db, self.assertRaises(PermissionError):
            require_branch_permission(db, self.owner["user_id"], self.org, self.branch, "manage")

    def test_queued_financial_write_rechecks_authority_after_revocation(self):
        waiting = Event()
        use_connection = StagingLedger._using_connection

        @contextmanager
        def observe_writer(ledger, connection=None, *, immediate=False):
            if immediate and connection is None:
                waiting.set()
            with use_connection(ledger, connection, immediate=immediate) as db:
                yield db

        with patch.object(StagingLedger, "_using_connection", observe_writer), ThreadPoolExecutor(max_workers=1) as worker:
            with self.ledger.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                self.revoke(db)
                inflight = worker.submit(self.client.post, self.base + "/sales", headers=self.headers, json={
                    "customer_id": self.customer, "reference": "DENIED-SALE", "total": "1.01",
                    "paid": "0", "confirmed": True,
                })
                self.assertTrue(waiting.wait(5))
            self.assertEqual(inflight.result(timeout=10).status_code, 403)
        with self.ledger.connect() as db:
            self.assertEqual([tuple(row) for row in db.execute("SELECT sale_reference, total_kobo FROM sales")],
                             [("SALE-1", 9501)])

    def test_mapped_only_provisions_atomically_and_fails_closed(self):
        unmapped = self.ledger.register_owner("Still Compatible", "legacy@example.test", self.password)
        token = self.ledger.login("legacy@example.test", self.password)
        self.assertEqual([item["id"] for item in self.ledger.list_my_businesses(token)], [unmapped["business_id"]])
        invitation = self.ledger.create_invite("new@example.test", "New Mapped Shop")
        with patch.object(StagingLedger, "legacy_scope", LegacyScope.MAPPED_ONLY):
            self.assertEqual(self.ledger.list_my_businesses(token), [])
            with self.assertRaises(PermissionError):
                self.ledger.add_customer(token, unmapped["business_id"], "Denied customer")
            with self.assertRaises(PermissionError):
                self.ledger.create_business("Ownerless branch")
            with self.ledger.connect() as db:
                db.execute("""CREATE TRIGGER synthetic_mapping_failure BEFORE INSERT ON branches
                              BEGIN SELECT RAISE(ABORT, 'fixture'); END""")
            with self.assertRaisesRegex(ValueError, "could not be registered"):
                self.ledger.consume_account_link("invite", invitation, self.password)
            with self.ledger.connect() as db:
                self.assertEqual(db.execute("SELECT count(*) FROM users WHERE email='new@example.test'").fetchone()[0], 0)
                self.assertEqual(db.execute("SELECT count(*) FROM organizations").fetchone()[0], 2)
                self.assertEqual(db.execute("SELECT count(*) FROM businesses").fetchone()[0], 4)
                self.assertEqual(db.execute("SELECT count(*) FROM account_links").fetchone()[0], 1)
                db.execute("DROP TRIGGER synthetic_mapping_failure")
            self.ledger.consume_account_link("invite", invitation, self.password)
            new_token = self.ledger.login("new@example.test", self.password)
            [business] = self.ledger.list_my_businesses(new_token)
            [organization] = self.ledger.list_my_organizations(new_token)
            self.assertNotEqual(organization["id"], business["id"])
            self.assertEqual(self.ledger.list_organization_branches(new_token, organization["id"])[0]["id"], business["id"])
            self.assertEqual(self.ledger.list_my_businesses(self.token)[0]["id"], self.business)
            with self.ledger.connect() as db:
                db.execute("DROP TABLE branch_assignments")
            with self.assertRaises(PermissionError):
                self.ledger.register_owner("Partial Schema", "partial@example.test", self.password)

    def test_readiness_reports_drift_and_foreign_assignments_without_mutating_snapshot(self):
        snapshot = self.root / "snapshot.sqlite"
        backup_database(self.path, snapshot)
        original = snapshot.read_bytes()
        healthy = verify_tenant_readiness(snapshot)
        self.assertTrue(healthy["passed"], healthy)
        self.assertEqual(healthy["counts"]["businesses"], 3)
        self.assertEqual(snapshot.read_bytes(), original)
        self.assertNotIn(self.owner["user_id"], str(healthy))
        with closing(sqlite3.connect(snapshot)) as db, db:
            db.execute("DELETE FROM organization_memberships WHERE organization_id=? AND user_id=?",
                       (self.org, self.owner["user_id"]))
            db.execute("UPDATE branches SET is_default=0 WHERE id=?", (self.business,))
            db.execute("INSERT INTO businesses VALUES ('synthetic-unmapped', 'Synthetic')")
            db.execute("INSERT INTO branch_assignments VALUES (?, ?, ?, 'CASHIER')",
                       (self.org, self.other_branch, self.other["user_id"]))
        drift = verify_tenant_readiness(snapshot)
        self.assertFalse(drift["passed"])
        for issue in ("unmapped_businesses", "wrong_default_counts", "legacy_owners_on_nondefault_branches",
                      "organizations_without_effective_owner", "orphaned_assignments",
                      "cross_organization_assignments", "foreign_key_violations"):
            self.assertGreater(drift["issues"][issue], 0, issue)
        with closing(sqlite3.connect(snapshot)) as db, db:
            db.execute("UPDATE branches SET is_default=1 WHERE id=?", (self.business,))
            db.execute("DELETE FROM memberships WHERE business_id=?", (self.other_branch,))
        drift = verify_tenant_readiness(snapshot)
        self.assertEqual(drift["issues"]["legacy_owner_drift"], 1)
        self.assertEqual(drift["issues"]["organization_owner_drift"], 1)
