import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "app" / "web" / "index.html"


class TestDashboardJavaScript(unittest.TestCase):

    def test_dashboard_javascript_syntax(self):
        node = shutil.which("node")
        self.assertIsNotNone(
            node,
            "Node.js is required for dashboard syntax checks",
        )

        html = DASHBOARD.read_text(encoding="utf-8-sig")

        scripts = re.findall(
            r"<script\b[^>]*>(.*?)</script>",
            html,
            flags=re.DOTALL | re.IGNORECASE,
        )

        self.assertTrue(
            scripts,
            "No dashboard JavaScript found",
        )

        with tempfile.TemporaryDirectory() as directory:
            for index, script in enumerate(scripts):
                file = Path(directory) / f"dashboard-{index}.js"
                file.write_text(script, encoding="utf-8")

                result = subprocess.run(
                    [node, "--check", str(file)],
                    capture_output=True,
                    text=True,
                    timeout=20,
                    check=False,
                )

                self.assertEqual(
                    result.returncode,
                    0,
                    result.stderr,
                )

    def test_no_literal_newline_escape_in_customer_refresh(self):
        html = DASHBOARD.read_text(encoding="utf-8-sig")

        self.assertNotIn(
            r");\n    populateCustomerSelects",
            html,
        )


if __name__ == "__main__":
    unittest.main()
