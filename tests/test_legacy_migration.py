import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.api.main import create_app
from app.db.migrations import migrate_legacy_database
from app.operations.pilot import backup_database, restore_database
from app.services.telemetry import StagingLedger


class TestLegacyMigration(unittest.TestCase):
    password = "SyntheticMigrationFixture123!"

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.source = self.root / "legacy.sqlite"
        self.db = StagingLedger(self.source)
        self.owner = self.db.register_owner("Synthetic Market", "one@example.test", self.password)
        self.other = self.db.register_owner("Other Market", "two@example.test", self.password)
        self.business = self.owner["business_id"]
        self.other_business = self.other["business_id"]
        self.token = self.db.login("one@example.test", self.password)
        self.other_token = self.db.login("two@example.test", self.password)
        # One account may own two separate legacy businesses.
        with self.db.connect() as db:
            db.execute("INSERT INTO memberships VALUES (?, ?, 'OWNER')",
                       (self.owner["user_id"], self.other_business))
        self.customer = self.db.add_customer(self.token, self.business, "Synthetic Customer")
        other_customer = self.db.add_customer(self.other_token, self.other_business, "Another Customer")
        self.sale = {
            "reference": "SYNTH-SALE-1", "customer_id": self.customer,
            "total": "100.01", "paid": "20.01", "confirmed": True,
        }
        sale_id = self.db.prepare_recovery(self.token, self.business, "sale", self.sale)["id"]
        self.receipt_id = self.db.submit_recovery(self.token, self.business, sale_id)["transaction_id"]
        self.db.check_recovery(self.token, self.business, sale_id)
        collision = self.db.prepare_recovery(self.token, self.business, "sale",
                                             {**self.sale, "total": "101.01"})["id"]
        self.db.submit_recovery(self.token, self.business, collision)
        self.db.set_recovery_operator(self.business, "one@example.test", enabled=True)
        self.db.decide_recovery(
            self.token, self.business, collision, decision="release_failed",
            evidence_type="ledger_conflict", evidence_reference="SYNTH-MIGRATION-1",
            evidence_notes="Compared the original receipt with the synthetic conflicting sale.",
            confirmed=True,
        )
        self.db.add_repayment(self.token, self.business, self.customer, "REPAY-1", "5.01", confirmed=True)
        self.db.record_expense(self.token, self.business, "EXP-1", "Transport", "Synthetic delivery",
                               "1.01", confirmed=True)
        pending = self.db.prepare_recovery(self.other_token, self.other_business, "sale",
                                           {**self.sale, "customer_id": other_customer})
        self.db.submit_recovery(self.other_token, self.other_business, pending["id"])
        self.pending_id = pending["id"]
        reversed_sale = self.db.add_sale(
            self.other_token, self.other_business, other_customer, "REVERSIBLE-1", "7.01", "0", confirmed=True,
        )
        self.db.reverse_unpaid_sale(self.other_token, self.other_business, reversed_sale, "REV-1",
                                    "Synthetic cancelled order", confirmed=True)
        self.db.adjust_customer_balance(self.other_token, self.other_business, other_customer, "ADJ-1", "-0.01",
                                        "Synthetic one-kobo correction", confirmed=True)
        self.other_customer = other_customer
        self.db.create_invite("unclaimed@example.test", "Synthetic Invite")
        self.db.request_password_reset("one@example.test")

    def snapshot(self, path, selected=None):
        ledger = StagingLedger(path)
        with ledger.connect() as db:
            schema = {row["name"]: tuple(row) for row in db.execute(
                "SELECT type, name, tbl_name, sql FROM sqlite_schema WHERE name NOT LIKE 'sqlite_%'"
            ) if selected is None or row["name"] in selected}
            rows = {name: [tuple(row) for row in db.execute(f'SELECT * FROM "{name}" ORDER BY rowid')]
                    for name, definition in schema.items() if definition[0] == "table"}
        return schema, rows

    def test_dry_run_apply_reapply_and_restore_preserve_history(self):
        legacy = self.root / "legacy-snapshot.sqlite"
        backup_database(self.source, legacy)
        baseline = self.snapshot(legacy)
        self.assertEqual(migrate_legacy_database(legacy, dry_run=True)["new_mappings"], 2)
        self.assertEqual(self.snapshot(legacy), baseline)
        self.assertEqual(migrate_legacy_database(legacy)["new_mappings"], 2)
        self.assertEqual(self.snapshot(legacy, baseline[0]), baseline)
        migrated = self.snapshot(legacy)
        self.assertEqual(migrate_legacy_database(legacy)["new_mappings"], 0)
        self.assertEqual(self.snapshot(legacy), migrated)
        branches = {row[0]: row[1:] for row in migrated[1]["branches"]}
        self.assertEqual(set(branches), {self.business, self.other_business})
        self.assertTrue(all(default == 1 for _, default in branches.values()))
        self.assertEqual(len(set(org for org, _ in branches.values())), 2)
        self.assertTrue(all(org not in branches for org, _ in branches.values()))
        self.assertEqual(set(migrated[1]["organization_memberships"]), {
            (branches[self.business][0], self.owner["user_id"], "OWNER"),
            (branches[self.other_business][0], self.owner["user_id"], "OWNER"),
            (branches[self.other_business][0], self.other["user_id"], "OWNER"),
        })
        self.assertEqual(migrated[1]["branch_assignments"], [])

        copy = self.root / "migrated-backup.sqlite"
        result = backup_database(legacy, copy)
        restored = self.root / "restore.sqlite"
        restore_database(copy, restored, result["sha256"])
        expected = {**migrated[1], "sessions": [], "account_links": []}
        self.assertEqual(self.snapshot(restored), (migrated[0], expected))
        self.assertEqual(migrate_legacy_database(restored)["new_mappings"], 0)
        replica = StagingLedger(restored)
        token = replica.login("one@example.test", self.password)
        other_token = replica.login("two@example.test", self.password)
        self.assertEqual(replica.get_balance(token, self.business, self.customer).as_integer_ratio(), (7499, 100))
        self.assertEqual(replica.get_balance(other_token, self.other_business,
                                             self.other_customer).as_integer_ratio(), (7999, 100))
        with TestClient(create_app(restored)) as client:
            base = f"/api/v1/businesses/{self.business}"
            headers = {"Authorization": f"Bearer {token}"}
            params = {"kind": "sale", "transaction_id": self.receipt_id}
            receipt = client.get(base + "/receipts", params=params, headers=headers)
            self.assertEqual(receipt.status_code, 200)
            self.assertEqual(receipt.json()["amount"], "100.01")
            self.assertEqual(receipt.json()["timezone"], "Africa/Lagos")
            self.assertEqual(client.get(base + "/receipts", params=params,
                                        headers={"Authorization": f"Bearer {other_token}"}).status_code, 403)
            recovery = client.post(
                f"/api/v1/businesses/{self.other_business}/recovery/{self.pending_id}/check",
                headers={"Authorization": f"Bearer {other_token}"},
            )
            self.assertEqual(recovery.status_code, 200)
            self.assertEqual(recovery.json()["status"], "committed")

    def test_injected_failure_rolls_back_version_schema_and_rows(self):
        baseline = self.snapshot(self.source)
        with patch("app.db.migrations._verify_mapping", side_effect=RuntimeError("Injected after backfill")):
            with self.assertRaisesRegex(RuntimeError, "Injected after backfill"):
                migrate_legacy_database(self.source)
        self.assertEqual(self.snapshot(self.source), baseline)
        self.assertEqual(migrate_legacy_database(self.source)["new_mappings"], 2)

    def test_ownerless_legacy_business_blocks_migration(self):
        with self.db.connect() as db:
            db.execute("INSERT INTO businesses (id, name) VALUES ('ownerless', 'Synthetic Ownerless')")
        baseline = self.snapshot(self.source)
        with self.assertRaisesRegex(ValueError, "without an owner"):
            migrate_legacy_database(self.source)
        self.assertEqual(self.snapshot(self.source), baseline)

    def test_new_legacy_business_is_added_without_changing_old_mapping(self):
        migrate_legacy_database(self.source)
        before = set(self.snapshot(self.source)[1]["branches"])
        self.db.register_owner("New Legacy Market", "three@example.test", self.password)
        self.assertEqual(migrate_legacy_database(self.source)["new_mappings"], 1)
        after = set(self.snapshot(self.source)[1]["branches"])
        self.assertTrue(before < after)
        self.assertEqual(len(after - before), 1)

    def test_scope_constraints_reject_cross_organization_assignments(self):
        migrate_legacy_database(self.source)
        with self.db.connect() as db:
            branches = dict(db.execute("SELECT id, organization_id FROM branches"))
            own_org, other_org = branches[self.business], branches[self.other_business]
            for owner, branch_id in ((self.owner, self.other_business), (self.other, self.business)):
                with self.assertRaises(sqlite3.IntegrityError):
                    db.execute("INSERT INTO branch_assignments VALUES (?, ?, ?, 'CASHIER')",
                               (own_org, branch_id, owner["user_id"]))
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("UPDATE branches SET organization_id = ? WHERE id = ?", (other_org, self.business))
            db.execute("INSERT INTO branch_assignments VALUES (?, ?, ?, 'ACCOUNTANT')",
                       (own_org, self.business, self.owner["user_id"]))
