import json
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.api.main import create_app
from app.operations.pilot import restore_database
from app.operations.staging import invite, scheduled_backup
from app.services.account_mail import AccountMail
from app.services.telemetry import StagingLedger


class TestSupervisedPilot(unittest.TestCase):
    def test_verified_traders_ledger_recovery_operator_and_restore(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            database = root / "synthetic.sqlite"
            mailbox = root / "capture"
            mailbox.mkdir()
            mail = AccountMail(mode="capture", origin="https://pilot.example.test", directory=mailbox)
            ledger = StagingLedger(database)
            password = "SyntheticPilotPassword123!"
            with TestClient(create_app(database, account_mail=mail)) as client:
                def sign_in(email):
                    login = client.post("/api/v1/auth/login", json={"email": email, "password": password})
                    self.assertEqual(login.status_code, 200)
                    headers = {"Authorization": "Bearer " + login.json()["access_token"]}
                    return headers, client.get("/api/v1/auth/businesses", headers=headers).json()[0]["id"]

                def register(email, name):
                    invite(database, email, name, mail)
                    capture = next(item for file in mailbox.glob("*.json")
                                   if (item := json.loads(file.read_text(encoding="utf-8")))["to"] == email)
                    verified = client.post("/api/v1/auth/invite/complete", json={
                        "token": capture["link"].split("#invite=")[1], "password": password,
                    })
                    self.assertEqual(verified.status_code, 200)
                    return sign_in(email)

                email = "musa@example.test"
                headers, business = register(email, "Synthetic Market")
                other, other_business = register("amina@example.test", "Separate Market")
                base = f"/api/v1/businesses/{business}"

                def request(method, suffix, status, **kwargs):
                    response = client.request(method, base + suffix, headers=headers, **kwargs)
                    self.assertEqual(response.status_code, status)
                    return response.json()

                customer = request("POST", "/customers", 201, json={"name": "Synthetic Customer"})["id"]
                sale = {"kind": "sale", "customer_id": customer, "reference": "PILOT-1",
                        "total": "100.01", "paid": "20.01", "confirmed": True}
                attempt = request("POST", "/recovery", 201, json=sale)["id"]
                # The separate real Chrome test discards this response at the network layer.
                request("POST", f"/recovery/{attempt}/submit", 200)
                client.post("/api/v1/auth/logout", headers=headers)
                headers, _ = sign_in(email)
                recovered = request("POST", f"/recovery/{attempt}/check", 200)
                self.assertEqual(recovered["status"], "committed")
                receipt = request("GET", "/receipts", 200, params={
                    "kind": "sale", "transaction_id": recovered["transaction_id"],
                })
                self.assertEqual((receipt["amount"], receipt["timezone"]), ("100.01", "Africa/Lagos"))
                request("POST", "/repayments", 201, json={
                    "customer_id": customer, "reference": "PILOT-PAY", "amount": "5.01", "confirmed": True,
                })
                request("POST", "/expenses", 201, json={
                    "reference": "PILOT-EXP", "category": "Transport",
                    "description": "Synthetic stock delivery", "amount": "1.01", "confirmed": True,
                })
                report = request("GET", "/reports/daily", 200, params={"report_date": receipt["recorded_at_local"][:10]})
                self.assertEqual(report["gross_sales"], "100.01")
                self.assertEqual(report["current_outstanding_debt"], "74.99")
                denied = client.get(base + "/receipts", headers=other,
                                    params={"kind": "sale", "reference": "PILOT-1"})
                self.assertEqual(denied.status_code, 403)
                absent = client.get(f"/api/v1/businesses/{other_business}/receipts", headers=other,
                                    params={"kind": "sale", "transaction_id": recovered["transaction_id"]})
                self.assertEqual(absent.status_code, 404)

                collision = request("POST", "/recovery", 201, json={**sale, "total": "101.01"})["id"]
                conflict = request("POST", f"/recovery/{collision}/submit", 200)
                self.assertEqual(conflict["status"], "conflict")
                ledger.set_recovery_operator(business, email, enabled=True)
                action = request("POST", f"/operator/recovery/{collision}/decisions", 201, json={
                    "decision": "release_failed", "evidence_type": "ledger_conflict",
                    "evidence_reference": "SYNTHETIC-INCIDENT-1",
                    "evidence_notes": "Compared the original committed sale and confirmed the later reference collision.",
                    "confirmed": True,
                })
                audit = request("GET", f"/operator/recovery/{collision}/audit", 200)
                self.assertEqual(audit[0]["id"], action["audit_id"])

                snapshot = scheduled_backup(database, root)
                backup = root / snapshot["file"]
                self.assertEqual(backup.with_suffix(".sha256").read_text().strip(), snapshot["sha256"])
                restored = root / "isolated-restore.sqlite"
                restore_database(backup, restored, snapshot["sha256"])
                replica = StagingLedger(restored)
                self.assertFalse(replica.is_active_session(headers["Authorization"].split()[1]))
                renewed = replica.login(email, password)
                self.assertEqual(str(replica.get_balance(renewed, business, customer)), "74.99")
                self.assertEqual(replica.operator_recovery_audit(renewed, business, collision)[0]["id"],
                                 action["audit_id"])
                with replica.connect() as db:
                    self.assertEqual(db.execute("SELECT count(*) FROM sales").fetchone()[0], 1)
                    self.assertEqual(db.execute("SELECT count(*) FROM account_links").fetchone()[0], 0)
        print("Synthetic acceptance restored NGN 74.99 debt, one sale, and the collision decision.")
