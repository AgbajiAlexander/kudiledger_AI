import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.services.operators import PilotLedger
from app.services.recovery import RecoveryConflict, RecoveryLedger


CRASH_WORKER = """
import json
import os
import sys
from contextlib import contextmanager
from app.services.recovery import RecoveryLedger

db_path, token, business, attempt, phase = json.load(sys.stdin)

class InterruptedLedger(RecoveryLedger):
    @contextmanager
    def _using_connection(self, connection=None, *, immediate=False):
        with super()._using_connection(connection, immediate=immediate) as db:
            yield db
            if getattr(self, "crashing", False) and immediate and connection is None:
                if phase == "before_commit":
                    os._exit(43)

    def _write_recovery(self, db, token, row):
        if phase == "before_write":
            os._exit(41)
        result = super()._write_recovery(db, token, row)
        if phase == "after_insert":
            os._exit(42)
        return result

ledger = InterruptedLedger(db_path)
ledger.crashing = True
result = ledger.submit_recovery(token, business, attempt)
if result["status"] != "saved":
    raise RuntimeError("Expected a committed financial write")
os._exit(44)
"""


class TestAtomicRecovery(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.database = Path(folder.name) / "atomic.db"
        self.ledger = PilotLedger(self.database)
        email, password = "atomic@example.test", "SyntheticAtomicPassword123!"
        self.business = self.ledger.register_owner("Atomic Shop", email, password)["business_id"]
        self.token = self.ledger.login(email, password)
        self.customer = self.ledger.add_customer(self.token, self.business, "Musa")
        self.reference = "ATOMIC-1"
        attempt = self.ledger.prepare_recovery(self.token, self.business, "sale", {
            "customer_id": self.customer, "reference": self.reference,
            "total": "100.01", "paid": "20.01", "confirmed": True,
        })
        self.attempt = attempt["id"]

    def crash(self, phase, code):
        result = subprocess.run(
            [sys.executable, "-c", CRASH_WORKER],
            input=json.dumps([str(self.database), self.token, self.business, self.attempt, phase]),
            capture_output=True, text=True, timeout=20, check=False,
        )
        self.assertEqual(result.returncode, code, result.stderr)
        return PilotLedger(self.database)

    def assert_unsent(self, ledger):
        self.assertEqual(ledger.check_recovery(self.token, self.business, self.attempt)["status"], "prepared")
        self.assertFalse(ledger.lookup_transaction(self.token, self.business, "sale", self.reference)["found"])
        self.assertEqual(str(ledger.get_balance(self.token, self.business, self.customer)), "0")

    def test_process_death_before_financial_insert(self):
        self.assert_unsent(self.crash("before_write", 41))

    def test_process_death_after_financial_insert(self):
        self.assert_unsent(self.crash("after_insert", 42))

    def test_process_death_after_journal_update_before_commit(self):
        self.assert_unsent(self.crash("before_commit", 43))

    def test_process_death_after_commit_before_response(self):
        ledger = self.crash("after_commit", 44)
        self.assertEqual(ledger.list_recovery(self.token, self.business)[0]["status"], "unresolved")
        checked = ledger.check_recovery(self.token, self.business, self.attempt)
        self.assertEqual(checked["status"], "committed")
        self.assertEqual(str(ledger.get_balance(self.token, self.business, self.customer)), "80")
        with self.assertRaises(RecoveryConflict):
            ledger.submit_recovery(self.token, self.business, self.attempt)
        with ledger.connect() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM sales").fetchone()[0], 1)

    def test_validation_error_after_insert_rolls_back_savepoint(self):
        write = RecoveryLedger._write_recovery

        def fail_after_insert(ledger, connection, token, row):
            write(ledger, connection, token, row)
            raise ValueError("Synthetic validation failure")

        with patch.object(RecoveryLedger, "_write_recovery", fail_after_insert):
            rejection = self.ledger.submit_recovery(self.token, self.business, self.attempt)
        self.assertEqual(rejection["status"], "rejected")
        self.assertFalse(self.ledger.lookup_transaction(
            self.token, self.business, "sale", self.reference,
        )["found"])
