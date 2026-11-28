import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.api.main import create_app
from app.db.migrations import migrate_legacy_database
from app.db.staff_migration import migrate_staff_invitations
from app.db.staff_permissions_migration import migrate_staff_permissions
from app.services.authorization import active_user, require_branch_permission
from app.services.telemetry import StagingLedger


class TestStaffManagement(unittest.TestCase):
    password = "SyntheticStaffManagement123!"

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / "staff.sqlite"
        self.ledger = StagingLedger(self.path)
        self.owner = self.ledger.register_owner("Synthetic Market", "owner@example.test", self.password)
        self.other = self.ledger.register_owner("Other Market", "other@example.test", self.password)
        self.owner_token = self.ledger.login("owner@example.test", self.password)
        self.other_token = self.ledger.login("other@example.test", self.password)
        migrate_legacy_database(self.path)
        migrate_staff_invitations(self.path)
        migrate_staff_permissions(self.path)
        self.default = self.owner["business_id"]
        self.foreign_branch = self.other["business_id"]
        self.branch = self.ledger.create_business("Second Branch")
        with self.ledger.connect() as db:
            mappings = dict(db.execute("SELECT id, organization_id FROM branches"))
            self.org, self.foreign_org = mappings[self.default], mappings[self.foreign_branch]
            db.execute("INSERT INTO branches VALUES (?, ?, 0)", (self.branch, self.org))
        self.staff = self.create_staff("staff@example.test", "CASHIER")
        self.app = create_app(self.path, require_https=False)
        self.client = TestClient(self.app, raise_server_exceptions=False)
        self.addCleanup(self.client.close)

    def create_staff(self, email, role):
        _, secret = self.ledger.issue_staff_invitation(self.owner_token, self.org, email, [(self.default, role)])
        self.ledger.accept_staff_invitation(secret, password=self.password)
        return self.ledger.login(email, self.password)

    def user_for(self, token):
        with self.ledger.connect() as db:
            return active_user(db, token)

    def request(self, method, suffix="", *, token=None, org=None, payload=None):
        url = f"/api/v1/organizations/{org or self.org}/staff{suffix}"
        return self.client.request(method, url, headers={"Authorization": f"Bearer {token or self.owner_token}"},
                                   json=payload)

    def rows(self, sql, params=()):
        with self.ledger.connect() as db:
            return [tuple(row) for row in db.execute(sql, params)]

    def test_owner_list_change_assign_move_and_revoke(self):
        user = self.user_for(self.staff)
        path = f"/{user}/branches"
        result = self.request("GET")
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.headers["cache-control"], "no-store")
        self.assertEqual(result.json(), [{"user_id": user, "email": "staff@example.test",
                                         "branch_id": self.default, "role": "CASHIER"}])
        self.assertEqual(self.request("PATCH", f"{path}/{self.default}", payload={"role": "MANAGER"}).status_code, 204)
        self.assertEqual(self.request("POST", f"{path}/{self.default}/reassign",
                                      payload={"branch_id": self.branch, "role": "ACCOUNTANT"}).status_code, 204)
        self.assertEqual(self.request("POST", path,
                                      payload={"branch_id": self.default, "role": "CASHIER"}).status_code, 204)
        self.assertEqual(self.request("DELETE", f"{path}/{self.branch}").status_code, 204)
        self.assertEqual(self.rows("SELECT branch_id, role FROM branch_assignments"), [(self.default, "CASHIER")])
        self.assertEqual(self.rows(
            """SELECT actor_user_id, organization_id, affected_user_id, branch_id, action,
                      previous_role, resulting_role FROM staff_permission_audit ORDER BY id"""
        ), [(self.owner["user_id"], self.org, user, branch, action, old, new)
            for branch, action, old, new in [
                (self.default, "role_changed", "CASHIER", "MANAGER"),
                (self.default, "assignment_revoked", "MANAGER", None),
                (self.branch, "assigned", None, "ACCOUNTANT"),
                (self.default, "assigned", None, "CASHIER"),
                (self.branch, "assignment_revoked", "ACCOUNTANT", None),
            ]])

    def test_staff_denial_and_cross_scope_substitution(self):
        user = self.user_for(self.staff)
        branch_path = f"/{user}/branches/{self.default}"
        for token in (self.staff, self.create_staff("manager@example.test", "MANAGER"),
                      self.create_staff("accountant@example.test", "ACCOUNTANT")):
            for method, path, payload in (
                ("POST", f"/{user}/branches", {"branch_id": self.default, "role": "CASHIER"}),
                ("PATCH", branch_path, {"role": "MANAGER"}),
                ("DELETE", branch_path, None),
                ("POST", branch_path + "/reassign", {"branch_id": self.branch, "role": "ACCOUNTANT"}),
                ("DELETE", f"/{user}", None),
            ):
                self.assertEqual(self.request(method, path, token=token, payload=payload).status_code, 403)
            self.assertEqual(self.request("GET", token=token).status_code, 403)
        self.assertEqual(self.request("GET", org=self.foreign_org).status_code, 403)
        self.assertEqual(self.request("DELETE", f"/{user}", org=self.foreign_org).status_code, 403)
        self.assertEqual(self.request("DELETE", f"/{self.other['user_id']}").status_code, 403)
        foreign = {"branch_id": self.foreign_branch, "role": "MANAGER"}
        self.assertEqual(self.request("POST", f"/{user}/branches", payload=foreign).status_code, 400)
        self.assertEqual(self.request("POST", branch_path + "/reassign", payload=foreign).status_code, 400)
        self.assertEqual(self.rows("SELECT branch_id, role FROM branch_assignments WHERE user_id = ?", (user,)),
                         [(self.default, "CASHIER")])
        self.assertEqual(self.rows("SELECT count(*) FROM staff_permission_audit WHERE outcome='denied' "
                                   "AND organization_id=? AND affected_user_id IS NULL AND branch_id IS NULL",
                                   (self.org,)), [(15,)])
        self.assertEqual(self.rows("SELECT count(*) FROM staff_permission_audit"), [(15,)])

    def test_revocation_is_live_and_cancels_pending_grants_without_affecting_other_org(self):
        user = self.user_for(self.staff)
        _, other_link = self.ledger.issue_staff_invitation(
            self.other_token, self.foreign_org, "staff@example.test", [(self.foreign_branch, "ACCOUNTANT")],
        )
        self.ledger.accept_staff_invitation(other_link, token=self.staff)
        _, pending = self.ledger.issue_staff_invitation(
            self.owner_token, self.org, "staff@example.test", [(self.branch, "MANAGER")],
        )
        self.ledger.assign_staff_branch(self.owner_token, self.org, user, self.branch, "MANAGER")
        self.assertEqual(self.request("DELETE", f"/{user}/branches/{self.branch}").status_code, 204)
        with self.ledger.connect() as db, self.assertRaises(PermissionError):
            require_branch_permission(db, active_user(db, self.staff), self.org, self.branch, "record")
        with self.assertRaisesRegex(ValueError, "unavailable"):
            self.ledger.accept_staff_invitation(pending, token=self.staff)
        _, pending = self.ledger.issue_staff_invitation(
            self.owner_token, self.org, "staff@example.test", [(self.branch, "CASHIER")],
        )
        self.assertEqual(self.request("DELETE", f"/{user}").status_code, 204)
        with self.ledger.connect() as db:
            self.assertEqual(active_user(db, self.staff), user)
            with self.assertRaises(PermissionError):
                require_branch_permission(db, user, self.org, self.default, "read")
            self.assertEqual(require_branch_permission(db, user, self.foreign_org, self.foreign_branch, "read"),
                             "ACCOUNTANT")
        with self.assertRaisesRegex(ValueError, "unavailable"):
            self.ledger.accept_staff_invitation(pending, token=self.staff)
        self.assertEqual(self.request("GET").json(), [])
        self.assertEqual(self.rows("SELECT action FROM staff_permission_audit ORDER BY id")[-2:],
                         [("assignment_revoked",), ("membership_revoked",)])

    def test_only_member_targets_and_audit_is_append_only(self):
        owner = self.owner["user_id"]
        for method, path, payload in (
            ("POST", f"/{owner}/branches", {"branch_id": self.branch, "role": "CASHIER"}),
            ("PATCH", f"/{owner}/branches/{self.default}", {"role": "CASHIER"}),
            ("DELETE", f"/{owner}/branches/{self.default}", None),
            ("POST", f"/{owner}/branches/{self.default}/reassign", {"branch_id": self.branch, "role": "CASHIER"}),
            ("DELETE", f"/{owner}", None),
        ):
            self.assertEqual(self.request(method, path, payload=payload).status_code, 403)
        self.assertEqual(self.request("GET").status_code, 200)
        self.assertEqual(self.rows("SELECT role FROM organization_memberships WHERE organization_id=? AND user_id=?",
                                   (self.org, owner)), [("OWNER",)])
        self.assertEqual(self.rows("SELECT role FROM memberships WHERE business_id=? AND user_id=?",
                                   (self.default, owner)), [("OWNER",)])
        user = self.user_for(self.staff)
        assignment = f"/{user}/branches/{self.default}"
        self.assertEqual(self.request("PATCH", assignment, payload={"role": "OWNER"}).status_code, 422)
        self.assertEqual(self.request("PATCH", assignment, payload={"role": "CASHIER"}).status_code, 400)
        self.assertEqual(self.request("PATCH", assignment, payload={"role": "MANAGER"}).status_code, 204)
        with self.ledger.connect() as db:
            for statement in (
                "UPDATE staff_permission_audit SET created_at = 0",
                "DELETE FROM staff_permission_audit",
                "INSERT OR REPLACE INTO staff_permission_audit SELECT * FROM staff_permission_audit",
            ):
                with self.assertRaisesRegex(sqlite3.IntegrityError, "immutable"):
                    db.execute(statement)

    def test_concurrent_duplicate_and_failed_audit_rollback(self):
        user = self.user_for(self.staff)
        path = f"/{user}/branches"
        payload = {"branch_id": self.branch, "role": "MANAGER"}
        with ThreadPoolExecutor(max_workers=2) as workers:
            outcomes = list(workers.map(lambda _: self.request("POST", path, payload=payload).status_code, range(2)))
        self.assertCountEqual(outcomes, [204, 400])
        self.assertEqual(self.rows("SELECT action FROM staff_permission_audit"), [("assigned",)])
        with self.ledger.connect() as db:
            db.execute("""CREATE TRIGGER synthetic_audit_failure BEFORE INSERT ON staff_permission_audit
                          BEGIN SELECT RAISE(ABORT, 'fixture'); END""")
        self.assertEqual(self.request("DELETE", f"/{user}").status_code, 500)
        self.assertEqual(self.rows("SELECT count(*) FROM branch_assignments"), [(2,)])
        self.assertEqual(self.rows("SELECT count(*) FROM staff_permission_audit"), [(1,)])

    def test_explicit_migration_and_denial_when_version_three_is_missing(self):
        path = self.path.with_name("v2.sqlite")
        ledger = StagingLedger(path)
        account = ledger.register_owner("Synthetic V2", "v2@example.test", self.password)
        migrate_legacy_database(path)
        with self.assertRaisesRegex(ValueError, "staff invitation"):
            migrate_staff_permissions(path)
        migrate_staff_invitations(path)
        token = ledger.login("v2@example.test", self.password)
        with ledger.connect() as db:
            organization = db.execute("SELECT organization_id FROM branches WHERE id=?",
                                      (account["business_id"],)).fetchone()[0]
        self.assertFalse(migrate_staff_permissions(path, dry_run=True)["applied"])
        with self.assertRaises(PermissionError):
            ledger.list_organization_staff(token, organization)
        with patch("app.db.staff_permissions_migration.AUDIT_STATEMENTS", ("CREATE TABLE throwaway (id)", "invalid sql")):
            with self.assertRaises(sqlite3.Error):
                migrate_staff_permissions(path)
        self.assertTrue(migrate_staff_permissions(path)["applied"])
        self.assertFalse(migrate_staff_permissions(path)["applied"])
        with ledger.connect() as db:
            self.assertIsNone(db.execute("SELECT 1 FROM sqlite_schema WHERE name='throwaway'").fetchone())
        self.assertEqual(ledger.list_organization_staff(token, organization), [])
