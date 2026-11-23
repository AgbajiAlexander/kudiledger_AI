import hashlib
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from app.operations.pilot import backup_database, restore_database, verify_database
from app.services.operators import PilotLedger


class TestPilotDatabase(unittest.TestCase):
    email = "backup@example.test"
    password = "SyntheticBackupPassword123!"

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.directory = Path(folder.name)
        self.source = self.directory / "source.db"
        self.backup = self.directory / "snapshot.sqlite"
        self.restored = self.directory / "restore.sqlite"
        self.ledger = PilotLedger(self.source)
        self.business = self.ledger.register_owner(
            "Backup Drill Shop", self.email, self.password,
        )["business_id"]
        self.token = self.ledger.login(self.email, self.password)
        self.customer = self.ledger.add_customer(self.token, self.business, "Amina")

    def run_cli(self, *args):
        result = subprocess.run(
            [sys.executable, "-m", "app.operations.pilot", *map(str, args)],
            capture_output=True, text=True, timeout=30, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_backup_and_restore_drill_preserves_balances_references_and_recovery(self):
        self.run_cli("grant-operator", "--database", self.source,
                     "--business-id", self.business, "--email", self.email)
        self.ledger.add_sale(
            self.token, self.business, self.customer, "BACKUP-SALE", "100.01", "20.01", True,
        )
        self.ledger.add_repayment(
            self.token, self.business, self.customer, "BACKUP-PAY", "5.01", True,
        )
        self.ledger.record_expense(
            self.token, self.business, "BACKUP-EXP", "Transport", "Stock delivery", "1.01", True,
        )
        committed = self.ledger.prepare_recovery(self.token, self.business, "sale", {
            "customer_id": self.customer, "reference": "REC-COMMITTED",
            "total": "50.01", "paid": "10.01", "confirmed": True,
        })["id"]
        original = self.ledger.submit_recovery(self.token, self.business, committed)["transaction_id"]

        unresolved = self.ledger.prepare_recovery(self.token, self.business, "expense", {
            "reference": "REC-UNCERTAIN", "category": "Transport",
            "description": "Synthetic legacy attempt", "amount": "4.50", "confirmed": True,
        })["id"]
        with self.ledger.connect() as db:
            db.execute("UPDATE recovery_attempts SET stage = 'sending' WHERE id = ?", (unresolved,))
        decision = self.ledger.decide_recovery(
            self.token, self.business, unresolved, decision="retain_uncertain",
            evidence_type="inconclusive", evidence_reference="BACKUP-INCIDENT-1",
            evidence_notes="The synthetic incident is unavailable for further review.",
            confirmed=True,
        )

        snapshot = self.run_cli("backup", self.source, self.backup)
        self.assertEqual(snapshot, self.run_cli("verify", self.backup))
        self.assertEqual(snapshot["counts"]["sales"], 2)
        self.assertEqual(snapshot["counts"]["recovery_attempts"], 2)
        self.assertEqual(snapshot["counts"]["recovery_operator_audit"], 1)
        restored = self.run_cli("restore", self.backup, self.restored, "--sha256", snapshot["sha256"])
        self.assertEqual(restored["counts"], snapshot["counts"])

        restored_ledger = PilotLedger(self.restored)
        self.assertFalse(restored_ledger.is_active_session(self.token))
        self.assertTrue(self.ledger.is_active_session(self.token))
        token = restored_ledger.login(self.email, self.password)
        self.assertEqual(str(restored_ledger.get_balance(token, self.business, self.customer)), "114.99")
        for kind, reference in (
            ("sale", "BACKUP-SALE"), ("repayment", "BACKUP-PAY"), ("expense", "BACKUP-EXP"),
            ("sale", "REC-COMMITTED"),
        ):
            self.assertTrue(restored_ledger.lookup_transaction(token, self.business, kind, reference)["found"])
        self.assertEqual(restored_ledger.check_recovery(token, self.business, unresolved)["status"], "unresolved")
        verified = restored_ledger.check_recovery(token, self.business, committed)
        self.assertEqual((verified["status"], verified["transaction_id"]), ("committed", original))
        audit = restored_ledger.operator_recovery_audit(token, self.business, unresolved)
        self.assertEqual(audit[0]["id"], decision["audit_id"])
        print("Restore drill verified NGN 114.99 debt, four references, two recovery outcomes and one audit event.")

    def test_online_backup_excludes_uncommitted_financial_row(self):
        with self.ledger.connect() as db:
            db.execute("PRAGMA journal_mode = WAL")
        with self.ledger._using_connection(immediate=True) as db:
            self.ledger.add_sale(
                self.token, self.business, self.customer, "IN-FLIGHT", "30", "0",
                True, _db=db,
            )
            snapshot = backup_database(self.source, self.backup)
        self.assertEqual(snapshot["counts"]["sales"], 0)
        self.assertTrue(self.ledger.lookup_transaction(
            self.token, self.business, "sale", "IN-FLIGHT",
        )["found"])
        self.assertEqual(verify_database(self.backup)["counts"]["sales"], 0)

    def test_checksum_mismatch_and_existing_destination_fail_without_changes(self):
        snapshot = backup_database(self.source, self.backup)
        with self.assertRaises(FileExistsError):
            backup_database(self.source, self.backup)
        with self.assertRaises(FileExistsError):
            restore_database(self.backup, self.source, snapshot["sha256"])
        with self.backup.open("ab") as file:
            file.write(b"tampered")
        with self.assertRaisesRegex(ValueError, "checksum"):
            restore_database(self.backup, self.restored, snapshot["sha256"])
        self.assertFalse(self.restored.exists())

    def test_corrupt_file_with_matching_checksum_fails_integrity_validation(self):
        self.backup.write_bytes(b"not a SQLite database")
        digest = hashlib.sha256(self.backup.read_bytes()).hexdigest()
        with self.assertRaises(sqlite3.DatabaseError):
            restore_database(self.backup, self.restored, digest)
        self.assertFalse(self.restored.exists())
