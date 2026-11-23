import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def find_chromium():
    installed = (
        os.environ.get("KUDILEDGER_BROWSER"),
        shutil.which("chromium"),
        shutil.which("google-chrome"),
        shutil.which("msedge"),
        "C:/Program Files/Google/Chrome/Application/chrome.exe",
        "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
    )
    return next((path for path in installed if path and Path(path).is_file()), None)


class TestDashboardRecovery(unittest.TestCase):
    widths = (320, 360, 390, 430, 768)

    @unittest.skipUnless(find_chromium(), "Chromium browser is unavailable")
    def test_trader_flows_and_recovery_in_mobile_browser(self):
        page = (ROOT / "app/web/index.html").read_text(encoding="utf-8-sig")
        test_script = Path(__file__).with_suffix(".js").read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            clock = """
                <script>
                const RealDate = Date;
                Date = class extends RealDate {
                  constructor(...args) {
                    super(...(args.length ? args : ["2024-02-28T23:00:00Z"]));
                  }
                };
                </script>
            """
            (root / "dashboard.html").write_text(
                page.replace("<script>", clock + "<script>", 1)
                    .replace("</body>", f"<script>{test_script}</script></body>"),
                encoding="utf-8",
            )
            driver = root / "driver.html"
            driver.write_text(
                '''<!doctype html><meta charset="utf-8">
                <script>
                window.addEventListener("message", event => {
                  const result = document.getElementById("result-" + event.data.width);
                  if (result) result.textContent = event.data.result;
                });
                </script>''' + "".join(
                    f'<output id="result-{width}">waiting</output>'
                    f'<iframe width="{width}" height="800" src="dashboard.html"></iframe>'
                    for width in self.widths
                ),
                encoding="utf-8",
            )
            result = subprocess.run(
                [
                    find_chromium(), "--headless", "--disable-gpu",
                    "--no-first-run", "--disable-background-networking",
                    "--disable-background-timer-throttling", "--disable-renderer-backgrounding",
                    f"--user-data-dir={root / 'profile'}",
                    "--virtual-time-budget=20000", "--dump-dom", driver.as_uri(),
                ],
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                timeout=40,
                check=False,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        for width in self.widths:
            with self.subTest(width=width):
                self.assertIn(f'<output id="result-{width}">PASS</output>', result.stdout)
