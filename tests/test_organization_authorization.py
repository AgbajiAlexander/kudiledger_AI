import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.api.main import create_app
from app.db.migrations import migrate_legacy_database
from app.services.authorization import LegacyScope, require_branch_permission
from app.services.telemetry import StagingLedger


class TestOrganizationAuthorization(unittest.TestCase):
    password = "SyntheticAuthorization123!"

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / "authorization.sqlite"
        self.ledger = StagingLedger(self.path)
        self.owner = self.register("owner")
        self.other = self.register("other")
        self.staff = {role: self.register(role.lower())[0] for role in
                      ("MANAGER", "CASHIER", "ACCOUNTANT", "UNASSIGNED")}
        with self.ledger.connect() as db:
            for account in self.staff.values():
                db.execute("DELETE FROM memberships WHERE business_id = ?", (account["business_id"],))
                db.execute("DELETE FROM businesses WHERE id = ?", (account["business_id"],))
        self.business = self.owner[0]["business_id"]
        self.other_business = self.other[0]["business_id"]
        migrate_legacy_database(self.path)
        self.branch = self.ledger.create_business("Synthetic non-default branch")
        with self.ledger.connect() as db:
            orgs = dict(db.execute("SELECT id, organization_id FROM branches"))
            self.org, self.other_org = orgs[self.business], orgs[self.other_business]
            db.execute("INSERT INTO branches VALUES (?, ?, 0)", (self.branch, self.org))
            for role, account in self.staff.items():
                db.execute("INSERT INTO organization_memberships VALUES (?, ?, 'MEMBER')",
                           (self.org, account["user_id"]))
                if role != "UNASSIGNED":
                    db.execute("INSERT INTO branch_assignments VALUES (?, ?, ?, ?)",
                               (self.org, self.branch, account["user_id"], role))
            # This cashier can separately be an organization owner elsewhere.
            db.execute("INSERT INTO organization_memberships VALUES (?, ?, 'OWNER')",
                       (self.other_org, self.staff["CASHIER"]["user_id"]))
            db.execute("INSERT INTO memberships VALUES (?, ?, 'OWNER')",
                       (self.staff["CASHIER"]["user_id"], self.other_business))
        self.app = create_app(self.path)
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)

    def register(self, name):
        email = f"{name}@example.test"
        return self.ledger.register_owner(name, email, self.password), self.ledger.login(email, self.password)

    def request(self, token, method, path, **kwargs):
        return self.client.request(method, "/api/v1" + path,
                                   headers={"Authorization": f"Bearer {token}"}, **kwargs)

    def test_discovery_is_owner_only_and_live(self):
        _, token = self.owner
        result = self.request(token, "GET", "/auth/organizations")
        self.assertEqual(result.headers["cache-control"], "no-store")
        self.assertEqual([entry["id"] for entry in result.json()], [self.org])
        branches = self.request(token, "GET", f"/organizations/{self.org}/branches")
        self.assertEqual([entry["id"] for entry in branches.json()], [self.business, self.branch])
        self.assertEqual(self.request(token, "GET", f"/organizations/{self.other_org}/branches").status_code, 403)
        cashier = self.ledger.login("cashier@example.test", self.password)
        result = self.request(cashier, "GET", "/auth/organizations").json()
        self.assertNotIn(self.org, [entry["id"] for entry in result])
        self.assertIn(self.other_org, [entry["id"] for entry in result])
        self.assertEqual(self.request(cashier, "GET", f"/organizations/{self.org}/branches").status_code, 403)

    def test_discovery_and_legacy_access_require_both_owner_records(self):
        account, token = self.owner
        user = account["user_id"]
        with self.ledger.connect() as db:
            db.execute("INSERT INTO memberships VALUES (?, ?, 'OWNER')", (user, self.other_business))
            db.execute("INSERT INTO organization_memberships VALUES (?, ?, 'OWNER')", (self.other_org, user))

        for table, scope_column, scope_id, values in (
            ("memberships", "business_id", self.business, (user, self.business)),
            ("organization_memberships", "organization_id", self.org, (self.org, user)),
        ):
            with self.subTest(revoked_table=table):
                self.assertEqual({entry["id"] for entry in self.request(token, "GET", "/auth/organizations").json()},
                                 {self.org, self.other_org})
                self.assertEqual(self.request(token, "GET", f"/organizations/{self.org}/branches").status_code, 200)
                with self.ledger.connect() as db:
                    db.execute(f"DELETE FROM {table} WHERE {scope_column} = ? AND user_id = ?", (scope_id, user))
                self.assertEqual([entry["id"] for entry in self.request(token, "GET", "/auth/organizations").json()],
                                 [self.other_org])
                self.assertEqual(self.request(token, "GET", f"/organizations/{self.org}/branches").status_code, 403)
                self.assertEqual(self.request(token, "GET", f"/organizations/{self.other_org}/branches").status_code, 200)
                self.assertEqual(self.request(token, "GET", f"/businesses/{self.business}/customers").status_code, 403)
                self.assertEqual([entry["id"] for entry in self.request(token, "GET", "/auth/businesses").json()],
                                 [self.other_business])
                with self.ledger.connect() as db:
                    db.execute(f"INSERT INTO {table} VALUES (?, ?, 'OWNER')", values)

    def test_legacy_provisioning_after_migration_and_partial_schema(self):
        registered, token = self.register("unmapped")
        business = registered["business_id"]
        self.assertEqual(self.request(token, "GET", "/auth/organizations").json(), [])
        self.assertEqual(self.request(token, "POST", f"/businesses/{business}/customers",
                                      json={"name": "Synthetic customer"}).status_code, 201)
        self.assertEqual([entry["id"] for entry in self.request(token, "GET", "/auth/businesses").json()], [business])
        with patch.object(StagingLedger, "legacy_scope", LegacyScope.MAPPED_ONLY):
            self.assertEqual(self.request(token, "GET", "/auth/businesses").json(), [])
            self.assertEqual(self.request(token, "POST", f"/businesses/{business}/customers",
                                          json={"name": "Blocked customer"}).status_code, 403)
            owner = self.owner[1]
            self.assertEqual(self.request(owner, "GET", f"/businesses/{self.business}/customers").status_code, 200)
            self.assertEqual(self.request(owner, "GET", f"/businesses/{self.other_business}/customers").status_code, 403)
            self.assertEqual(self.request(owner, "GET", f"/businesses/{self.branch}/customers").status_code, 403)
        with self.ledger.connect() as db:
            db.execute("DROP TABLE branch_assignments")
        for mode in LegacyScope:
            with self.subTest(mode=mode), patch.object(StagingLedger, "legacy_scope", mode):
                self.assertEqual(self.request(token, "POST", f"/businesses/{business}/customers",
                                              json={"name": "Blocked customer"}).status_code, 403)
                self.assertEqual(self.request(self.owner[1], "GET", "/auth/organizations").status_code, 403)

    def test_role_matrix_wrong_pairs_and_live_revocation(self):
        with self.ledger.connect() as db:
            self.assertEqual(require_branch_permission(db, self.owner[0]["user_id"],
                                                       self.org, self.branch, "correct"), "OWNER")
            for role, allowed in {
                "MANAGER": {"read", "record", "report"}, "CASHIER": {"read", "record"},
                "ACCOUNTANT": {"read", "report", "export"}, "UNASSIGNED": set(),
            }.items():
                user = self.staff[role]["user_id"]
                for action in ("read", "record", "report", "export", "correct", "manage", "unknown"):
                    with self.subTest(role=role, action=action):
                        if action in allowed:
                            self.assertEqual(require_branch_permission(db, user, self.org, self.branch, action), role)
                        else:
                            with self.assertRaises(PermissionError):
                                require_branch_permission(db, user, self.org, self.branch, action)
                for org, branch in ((self.other_org, self.branch), (self.org, self.business)):
                    with self.assertRaises(PermissionError):
                        require_branch_permission(db, user, org, branch, "read")
            cashier = self.staff["CASHIER"]["user_id"]
            self.assertEqual(require_branch_permission(db, cashier, self.other_org,
                                                       self.other_business, "correct"), "OWNER")
            db.execute("DELETE FROM branch_assignments WHERE user_id = ?", (cashier,))
            with self.assertRaises(PermissionError):
                require_branch_permission(db, cashier, self.org, self.branch, "read")
            manager = self.staff["MANAGER"]["user_id"]
            db.execute("DELETE FROM branch_assignments WHERE user_id = ?", (manager,))
            db.execute("DELETE FROM organization_memberships WHERE organization_id = ? AND user_id = ?",
                       (self.org, manager))
            with self.assertRaises(PermissionError):
                require_branch_permission(db, manager, self.org, self.branch, "discover")

    def test_all_business_mutations_deny_other_owner_and_staff(self):
        with self.ledger.connect() as db:
            db.executemany("INSERT INTO memberships VALUES (?, ?, 'OWNER')", (
                (self.owner[0]["user_id"], self.branch),
                (self.staff["CASHIER"]["user_id"], self.business),
                (self.staff["CASHIER"]["user_id"], self.branch),
            ))
        reason = "Synthetic authorized-reversal fixture"
        sale = {"customer_id": "foreign-customer", "reference": "SYNTH-1",
                "total": "10.01", "paid": "0", "confirmed": True}
        mutations = [
            ("POST", "/customers", {"name": "Synthetic"}),
            ("POST", "/sales", sale),
            ("POST", "/repayments", {**sale, "amount": "0.01"}),
            ("POST", "/expenses", {"reference": "EXP-1", "category": "Transport",
                                   "description": "Synthetic expense", "amount": "0.01", "confirmed": True}),
            ("POST", "/adjustments", {**sale, "amount": "0.01", "reason": reason}),
            ("POST", "/sale-reversals", {"sale_id": "foreign-sale", "reference": "REV-1",
                                          "reason": reason, "confirmed": True}),
            ("POST", "/recovery", {**sale, "kind": "sale"}),
            ("POST", "/recovery/{attempt_id}/submit", None),
            ("POST", "/recovery/{attempt_id}/check", None),
            ("POST", "/recovery/{attempt_id}/acknowledge", {"transaction_id": "foreign-sale"}),
            ("DELETE", "/recovery/{attempt_id}", None),
            ("POST", "/operator/recovery/{attempt_id}/decisions", {
                "decision": "retain_uncertain", "evidence_type": "inconclusive",
                "evidence_reference": "SYNTH-CASE", "evidence_notes": "Synthetic test without an operator grant",
                "confirmed": True,
            }),
        ]
        prefix = "/api/v1/businesses/{business_id}"
        self.assertEqual({(method, route.path.removeprefix(prefix)) for route in self.app.routes
                          if route.path.startswith(prefix) for method in route.methods & {"POST", "DELETE", "PATCH", "PUT"}},
                         {(method, path) for method, path, _ in mutations})
        cashier = self.ledger.login("cashier@example.test", self.password)
        for token, target in ((self.other[1], self.business), (cashier, self.branch),
                              (cashier, self.business), (self.owner[1], self.branch)):
            for method, path, payload in mutations:
                suffix = path.replace("{attempt_id}", "unknown-attempt")
                if method == "DELETE":
                    suffix += "?action=cancel"
                with self.subTest(branch=target, method=method, path=path):
                    result = self.request(token, method, f"/businesses/{target}{suffix}", json=payload)
                    self.assertEqual(result.status_code, 403, result.text)

    def test_mapped_owner_financial_and_recovery_routes_recheck_after_revocation(self):
        _, token = self.owner
        customer = self.ledger.add_customer(token, self.business, "Synthetic")
        base = f"/businesses/{self.business}"
        sale = {"customer_id": customer, "reference": "SALE-1", "total": "100.01",
                "paid": "20.00", "confirmed": True}
        response = self.request(token, "POST", base + "/sales", json=sale)
        self.assertEqual(response.status_code, 201)
        receipt = self.request(token, "GET", base + "/receipts", params={"kind": "sale", "reference": "SALE-1"})
        self.assertEqual(receipt.json()["amount"], "100.01")
        report = self.request(token, "GET", base + "/reports/daily", params={"report_date": "2026-11-28"})
        self.assertEqual(report.json()["current_outstanding_debt"], "80.01")
        prepared = self.request(token, "POST", base + "/recovery", json={**sale, "reference": "SALE-2", "kind": "sale"})
        self.assertEqual(prepared.status_code, 201)
        attempt = prepared.json()["id"]
        # Simulate an out-of-band revocation; the application exposes no owner mutation.
        with self.ledger.connect() as db:
            db.execute("DELETE FROM organization_memberships WHERE organization_id = ? AND user_id = ?",
                       (self.org, self.owner[0]["user_id"]))
        self.assertEqual(self.request(token, "GET", "/auth/organizations").json(), [])
        self.assertEqual(self.request(token, "GET", "/auth/businesses").json(), [])
        self.assertEqual(self.request(token, "GET", base + "/reports/daily",
                                      params={"report_date": "2026-11-28"}).status_code, 403)
        self.assertEqual(self.request(token, "POST", base + f"/recovery/{attempt}/submit").status_code, 403)
        with self.ledger.connect() as db:
            self.assertEqual(db.execute("SELECT stage FROM recovery_attempts WHERE id = ?", (attempt,)).fetchone()[0], "prepared")
            self.assertEqual(db.execute("SELECT count(*) FROM sales WHERE business_id = ?", (self.business,)).fetchone()[0], 1)
