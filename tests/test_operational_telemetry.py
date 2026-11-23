import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.api.main import create_app
from app.operations.staging import monitor
from app.services.telemetry import StagingLedger, operational_counts


class TestOperationalTelemetry(unittest.TestCase):
    def test_failed_write_is_counted_without_sensitive_values(self):
        with tempfile.TemporaryDirectory() as folder:
            database = Path(folder) / "monitor.sqlite"
            ledger = StagingLedger(database)
            email = "synthetic@example.test"
            password = "SyntheticSecretPassword123!"
            business = ledger.register_owner("Synthetic Shop", email, password)["business_id"]
            token = ledger.login(email, password)
            description = "Private synthetic transaction description"
            path = f"/api/v1/businesses/{business}/expenses"
            with TestClient(create_app(database)) as client, self.assertLogs("kudiledger.operations") as output:
                with patch.object(StagingLedger, "record_expense",
                                  side_effect=RuntimeError(description + token + password)):
                    for _ in range(3):
                        result = client.post(path, headers={"Authorization": "Bearer " + token}, json={
                            "reference": "TELEMETRY", "category": "Transport", "description": description,
                            "amount": "1.01", "confirmed": True,
                        })
                        self.assertEqual(result.status_code, 500)
                        self.assertEqual(result.json(), {"detail": "Request could not be completed"})
                client.get("/unmatched-path-containing-a-secret", params={"token": token})
            log = "\n".join(output.output)
            for secret in (description, token, password, business, "unmatched-path-containing-a-secret"):
                self.assertNotIn(secret, log)
            events = [json.loads(item.getMessage()) for item in output.records]
            self.assertEqual(events[0]["route"], "/api/v1/businesses/{business_id}/expenses")
            self.assertEqual(events[0]["financial_outcome"], "operational_failure")
            attempt = ledger.prepare_recovery(token, business, "expense", {
                "reference": "OLD-CLAIM", "description": description,
                "category": "Transport", "amount": "1", "confirmed": True,
            })
            with ledger.connect() as db:
                db.execute("""UPDATE recovery_attempts SET stage = 'sending',
                              created_at = datetime('now', '-40 minutes') WHERE id = ?""", (attempt["id"],))
                self.assertEqual(operational_counts(db), {
                    "failed_financial_writes_15m": 3, "unresolved_over_30m": 1,
                    "account_mail_failures_15m": 0,
                })
            with patch("app.operations.staging.check_health", return_value=True):
                status = monitor(database, "https://pilot.example.test")
            self.assertCountEqual(status["alerts"], ["failed_financial_writes", "old_unresolved_recovery"])

    def test_business_rejections_do_not_raise_operational_alert(self):
        with tempfile.TemporaryDirectory() as folder:
            database = Path(folder) / "rejected.sqlite"
            ledger = StagingLedger(database)
            email, password = "test@example.test", "SyntheticMonitorPassword123!"
            business = ledger.register_owner("Test Shop", email, password)["business_id"]
            token = ledger.login(email, password)
            headers = {"Authorization": "Bearer " + token}
            payload = {"kind": "expense", "reference": "RULE-1", "confirmed": True,
                       "category": "Transport", "description": "Synthetic fee", "amount": "0"}
            base = f"/api/v1/businesses/{business}"
            with TestClient(create_app(database)) as client, self.assertLogs("kudiledger.operations") as output:
                direct = client.post(base + "/expenses", headers=headers, json=payload)
                self.assertEqual(direct.status_code, 400)
                intent = client.post(base + "/recovery", headers=headers, json=payload).json()
                rejected = client.post(base + f"/recovery/{intent['id']}/submit", headers=headers)
                self.assertEqual(rejected.status_code, 200)
                self.assertEqual(rejected.json()["status"], "rejected")
            events = [json.loads(item.getMessage()) for item in output.records]
            self.assertEqual([event["financial_outcome"] for event in events if "financial_outcome" in event],
                             ["request_rejected", "request_rejected"])
            with ledger.connect() as db:
                self.assertEqual(operational_counts(db)["failed_financial_writes_15m"], 0)
