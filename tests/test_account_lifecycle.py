import json
import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlsplit
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.api.main import create_app
from app.operations.staging import invite, monitor
from app.services.account_mail import AccountMail, private_path
from app.services.identity import digest
from app.services.telemetry import StagingLedger


class TestAccountLifecycle(unittest.TestCase):
    email = "owner@example.test"
    old_password = "SyntheticVerifiedPassword123!"
    new_password = "SyntheticReplacementPassword456!"

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.outbox = Path(folder.name) / "capture"
        self.outbox.mkdir()
        self.database = Path(folder.name) / "identity.sqlite"
        self.ledger = StagingLedger(self.database)
        self.mail = AccountMail(mode="capture", origin="https://pilot.example.test", directory=self.outbox)
        self.client = TestClient(create_app(self.database, account_mail=self.mail))
        self.addCleanup(self.client.close)

    def captured(self, purpose):
        return [
            data for file in self.outbox.glob("*.json")
            if (data := json.loads(file.read_text(encoding="utf-8")))["purpose"] == purpose
        ]

    def issue(self):
        before = {mail["link"] for mail in self.captured("invite")}
        invite(self.database, self.email, "Synthetic Pilot Market", self.mail)
        mail = next(item for item in self.captured("invite") if item["link"] not in before)
        self.assertEqual(mail["to"], self.email)
        address = urlsplit(mail["link"])
        self.assertEqual((address.netloc, address.path, address.query), ("pilot.example.test", "/app", ""))
        return address.fragment.split("=", 1)[1]

    def complete(self, endpoint, token, password):
        return self.client.post("/api/v1/auth/" + endpoint, json={"token": token, "password": password})

    def login(self, password, email=None):
        return self.client.post("/api/v1/auth/login", json={"email": email or self.email, "password": password})

    def test_invitation_verifies_email_and_is_single_use(self):
        token = self.issue()
        unknown = self.login(self.old_password)
        self.assertEqual(unknown.status_code, 401)
        with self.ledger.connect() as db:
            row = db.execute("SELECT token_hash FROM account_links").fetchone()
            self.assertEqual(row[0], digest(token))
            self.assertNotEqual(row[0], token)
        wrong = self.complete("password-reset/complete", token, self.old_password)
        self.assertEqual(wrong.status_code, 400)
        verified = self.complete("invite/complete", token, self.old_password)
        self.assertEqual(verified.status_code, 200)
        self.assertEqual(self.complete("invite/complete", token, self.old_password).status_code, 400)
        self.assertEqual(self.login(self.old_password).status_code, 200)
        with self.ledger.connect() as db:
            self.assertEqual([row[0] for row in db.execute(
                "SELECT event FROM account_security_audit ORDER BY id"
            )], ["invite_issued", "email_verified"])

    def test_password_reset_is_generic_and_revokes_all_sessions_and_links(self):
        self.assertEqual(self.complete("invite/complete", self.issue(), self.old_password).status_code, 200)
        sessions = [self.login(self.old_password).json()["access_token"] for _ in range(2)]
        endpoint = "/api/v1/auth/password-reset"
        unknown = self.client.post(endpoint, json={"email": "missing@example.test"})
        known = self.client.post(endpoint, json={"email": self.email})
        self.assertEqual(unknown.status_code, 202)
        self.assertEqual(known.status_code, 202)
        self.assertEqual(unknown.json(), known.json())
        self.assertEqual(len(self.captured("reset")), 1)
        self.client.post(endpoint, json={"email": self.email})
        links = [mail["link"].split("#reset=")[1] for mail in self.captured("reset")]
        self.assertEqual(len(links), 2)
        reset = self.complete("password-reset/complete", links[0], self.new_password)
        self.assertEqual(reset.status_code, 200)
        for token in links:
            self.assertEqual(self.complete("password-reset/complete", token, self.old_password).status_code, 400)
        for token in sessions:
            auth = self.client.get("/api/v1/auth/businesses", headers={"Authorization": "Bearer " + token})
            self.assertEqual(auth.status_code, 401)
        self.assertEqual(self.login(self.old_password).status_code, 401)
        self.assertEqual(self.login(self.new_password).status_code, 200)
        with self.ledger.connect() as db:
            self.assertTrue(db.execute(
                "SELECT 1 FROM account_security_audit WHERE event = 'password_reset_sessions_revoked'"
            ).fetchone())

    def test_expiry_and_sensitive_route_rate_limits(self):
        token = self.issue()
        with self.ledger.connect() as db:
            db.execute("UPDATE account_links SET expires_at = 0")
        self.assertEqual(self.complete("invite/complete", token, self.old_password).status_code, 400)
        self.assertEqual(self.complete("invite/complete", self.issue(), self.old_password).status_code, 200)
        for index in range(8):
            email = self.email if index < 5 else "other@example.test"
            response = self.client.post("/api/v1/auth/password-reset", json={"email": email})
            self.assertEqual(response.status_code, 202)
        self.assertEqual(len(self.captured("reset")), 3)
        blocked = self.client.post("/api/v1/auth/password-reset", json={"email": "third@example.test"})
        self.assertEqual(blocked.status_code, 429)
        reset = self.captured("reset")[0]["link"].split("#reset=")[1]
        with self.ledger.connect() as db:
            db.execute("UPDATE account_links SET expires_at = 0 WHERE purpose = 'reset'")
        self.assertEqual(self.complete("password-reset/complete", reset, self.new_password).status_code, 400)

    def test_capture_refuses_real_addresses_and_untrusted_link_origins(self):
        with self.assertRaises(ValueError):
            invite(self.database, "owner@example.com", "Synthetic Shop", self.mail)
        self.assertEqual(list(self.outbox.iterdir()), [])
        for origin in ("http://public.example.test", "https://pilot.example.test/untrusted", "https://user@pilot.example.test"):
            with self.subTest(origin=origin), self.assertRaises(ValueError):
                AccountMail(mode="capture", origin=origin, directory=self.outbox)

    def test_two_reset_submissions_cannot_consume_one_link(self):
        self.assertEqual(self.complete("invite/complete", self.issue(), self.old_password).status_code, 200)
        self.client.post("/api/v1/auth/password-reset", json={"email": self.email})
        token = self.captured("reset")[0]["link"].split("#reset=")[1]
        passwords = (self.new_password, "SyntheticConcurrentPassword789!")
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda value: self.complete("password-reset/complete", token, value), passwords))
        self.assertCountEqual([result.status_code for result in results], [200, 400])
        password = next(value for value, result in zip(passwords, results) if result.status_code == 200)
        self.assertEqual(self.login(password).status_code, 200)

    def test_failed_invite_delivery_preserves_last_working_link(self):
        token = self.issue()
        with patch.object(self.mail, "send", side_effect=OSError("Synthetic secret in the mail transport")):
            with self.assertRaisesRegex(RuntimeError, "^Invitation delivery failed$"):
                invite(self.database, self.email, "Synthetic Pilot Market", self.mail)
        self.assertEqual(len(self.captured("invite")), 1)
        with self.ledger.connect() as db:
            self.assertEqual([row[0] for row in db.execute("SELECT token_hash FROM account_links")], [digest(token)])
        self.assertEqual(self.complete("invite/complete", token, self.old_password).status_code, 200)

    def test_failed_reset_delivery_preserves_previous_link_and_alerts_without_leaks(self):
        self.assertEqual(self.complete("invite/complete", self.issue(), self.old_password).status_code, 200)
        endpoint = "/api/v1/auth/password-reset"
        self.client.post(endpoint, json={"email": self.email})
        previous = self.captured("reset")[0]["link"].split("#reset=")[1]
        secret = "Synthetic SMTP credential"
        with patch.object(self.mail, "send", side_effect=OSError(secret)), self.assertLogs(
            "kudiledger.operations",
        ) as output:
            failed = self.client.post(endpoint, json={"email": self.email})
        self.assertEqual(failed.status_code, 202)
        self.assertNotIn(secret, "\n".join(output.output))
        self.assertNotIn(self.email, "\n".join(output.output))
        with self.ledger.connect() as db:
            self.assertEqual([row[0] for row in db.execute("SELECT token_hash FROM account_links")],
                             [digest(previous)])
        with patch("app.operations.staging.check_health", return_value=True):
            alerts = monitor(self.database, "https://pilot.example.test")["alerts"]
        self.assertIn("account_mail_delivery", alerts)
        self.assertEqual(self.complete("password-reset/complete", previous, self.new_password).status_code, 200)

    def test_private_staging_paths_exclude_repo_and_posix_group_access(self):
        with self.assertRaises(ValueError):
            private_path(Path(__file__))
        if os.name == "posix":
            self.outbox.chmod(0o700)
        self.assertEqual(private_path(self.outbox), self.outbox.resolve())
        if os.name == "posix":
            self.outbox.chmod(0o750)
            with self.assertRaisesRegex(ValueError, "group and other"):
                private_path(self.outbox)
            self.outbox.chmod(0o700)
