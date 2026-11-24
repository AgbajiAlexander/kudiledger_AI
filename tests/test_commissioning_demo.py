import os
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.api.main import create_app
from app.services.telemetry import StagingLedger
from scripts.commissioning_demo import simulate_interruption


class TestCommissioningDemo(unittest.TestCase):
    def test_one_shot_interruption_occurs_after_a_committed_write(self):
        with tempfile.TemporaryDirectory() as folder:
            database = Path(folder) / "test.sqlite"
            ledger = StagingLedger(database)
            email, password = "rehearsal@example.test", "SyntheticDemoPassword123!"
            business = ledger.register_owner("Demo Market", email, password)["business_id"]
            token = ledger.login(email, password)
            customer = ledger.add_customer(token, business, "Synthetic Customer")
            application = create_app(database)
            armed = threading.Event()
            simulate_interruption(application, armed)
            headers = {"Authorization": "Bearer " + token}
            base = f"/api/v1/businesses/{business}/recovery"
            with TestClient(application) as client:
                def submit(reference, total):
                    draft = client.post(base, headers=headers, json={
                        "kind": "sale", "total": total, "paid": "0", "customer_id": customer,
                        "reference": reference, "confirmed": True,
                    })
                    self.assertEqual(draft.status_code, 201)
                    attempt = base + "/" + draft.json()["id"]
                    return attempt, client.post(attempt + "/submit", headers=headers)

                armed.set()
                _, invalid = submit("BAD-SALE", "0")
                self.assertEqual(invalid.json()["status"], "rejected")
                self.assertTrue(armed.is_set())
                attempt, interrupted = submit("DEMO-LOST", "20.01")
                self.assertEqual(interrupted.status_code, 503)
                self.assertFalse(armed.is_set())
                checked = client.post(attempt + "/check", headers=headers).json()
                self.assertEqual(checked["status"], "committed")
                self.assertEqual(client.post(attempt + "/submit", headers=headers).status_code, 409)
                _, next_save = submit("DEMO-NEXT", "1.01")
                self.assertEqual(next_save.json()["status"], "saved")
            with ledger.connect() as db:
                refs = db.execute("SELECT sale_reference FROM sales ORDER BY rowid").fetchall()
                self.assertEqual([row[0] for row in refs], ["DEMO-LOST", "DEMO-NEXT"])

    def test_entry_point_starts_a_loopback_sandbox_and_cleans_it(self):
        with tempfile.TemporaryDirectory() as folder:
            result = subprocess.run(
                [sys.executable, "-m", "scripts.commissioning_demo"], input="E\nQ\n",
                env={**os.environ, "TMPDIR": folder, "TEMP": folder, "TMP": folder},
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=30, check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("Synthetic dashboard http://127.0.0.1:", result.stdout)
            self.assertIn("commissioning-other@example.test", result.stdout)
            self.assertIn("Synthetic sessions expired.", result.stdout)
            self.assertNotIn("#invite=", result.stdout + result.stderr)
            self.assertEqual(list(Path(folder).iterdir()), [])
