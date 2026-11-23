import os
import shutil
import socket
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path

import uvicorn

from app.api.main import create_app
from app.services.recovery import RecoveryLedger
from tests.test_dashboard_recovery import find_chromium


class TestBrowserPersistentRecovery(unittest.TestCase):
    @unittest.skipUnless(find_chromium() and shutil.which("node"), "Chromium and Node are required")
    def test_committed_sale_with_lost_response_survives_refresh(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            database = root / "live-recovery.db"
            ledger = RecoveryLedger(database)
            email, password = "live@example.test", "SyntheticLiveRecovery123!"
            business = ledger.register_owner("Recovery Demo Market", email, password)["business_id"]
            token = ledger.login(email, password)
            customer = ledger.add_customer(token, business, "Amina Yusuf")

            with socket.socket() as listener:
                listener.bind(("127.0.0.1", 0))
                port = listener.getsockname()[1]
                server = uvicorn.Server(uvicorn.Config(create_app(database), log_level="warning"))
                worker = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
                worker.start()
                chrome = None
                try:
                    for _ in range(100):
                        if server.started:
                            break
                        time.sleep(0.05)
                    self.assertTrue(server.started, "Local Uvicorn test server did not start")
                    profile = root / "chrome"
                    chrome = subprocess.Popen(
                        [
                            find_chromium(), "--headless", "--disable-gpu",
                            "--no-first-run", "--disable-background-networking",
                            "--remote-debugging-port=0", f"--user-data-dir={profile}", "about:blank",
                        ],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                    debugger = profile / "DevToolsActivePort"
                    for _ in range(100):
                        if debugger.is_file() and debugger.stat().st_size:
                            break
                        time.sleep(0.05)
                    self.assertTrue(debugger.is_file(), "Chrome debugging port unavailable")
                    result = subprocess.run(
                        [
                            "node", str(Path(__file__).with_suffix(".js")),
                            debugger.read_text().splitlines()[0], f"http://127.0.0.1:{port}", customer,
                            os.environ.get("KUDILEDGER_RECOVERY_SCREENSHOTS", ""),
                        ],
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        timeout=45,
                        check=False,
                    )
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                finally:
                    if chrome is not None:
                        chrome.terminate()
                        chrome.wait(timeout=10)
                    server.should_exit = True
                    worker.join(timeout=10)

            with ledger.connect() as db:
                saved = db.execute(
                    "SELECT sale_reference, total_kobo, paid_kobo FROM sales"
                ).fetchall()
                self.assertEqual([tuple(row) for row in saved], [("LIVE-LOSS-1", 10001, 2001)])
                stages = db.execute("SELECT stage FROM recovery_attempts").fetchall()
                self.assertEqual([row["stage"] for row in stages], ["verified"])
