import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.api.main import create_app
from app.services.reports import ReportLedger


class TestLostResponseRecovery(unittest.TestCase):

    def test_saved_sale_can_be_verified_without_duplicate(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "recovery.db"
            ledger = ReportLedger(path)
            client = TestClient(create_app(path))

            owner = ledger.register_owner(
                "Recovery Test Shop",
                "recovery@example.test",
                "SecureTestPassword123!",
            )

            business_id = owner["business_id"]
            token = ledger.login(
                "recovery@example.test",
                "SecureTestPassword123!",
            )
            headers = {"Authorization": f"Bearer {token}"}
            base = f"/api/v1/businesses/{business_id}"

            customer_response = client.post(
                base + "/customers",
                json={"name": "Musa Ibrahim"},
                headers=headers,
            )
            self.assertEqual(customer_response.status_code, 201)
            customer_id = customer_response.json()["id"]

            payload = {
                "customer_id": customer_id,
                "reference": "RECOVERY-TEST-001",
                "total": "15000",
                "paid": "5000",
                "confirmed": True,
            }

            # The server saves the sale.
            response = client.post(
                base + "/sales",
                json=payload,
                headers=headers,
            )
            self.assertEqual(response.status_code, 201)

            # Simulate the browser not receiving that response.
            # Recovery must not depend on its contents.

            lookup = client.get(
                base + "/transactions/lookup",
                params={
                    "kind": "sale",
                    "reference": payload["reference"],
                },
                headers=headers,
            )

            self.assertEqual(lookup.status_code, 200)
            saved = lookup.json()

            self.assertTrue(saved["found"])
            self.assertEqual(saved["customer_id"], customer_id)
            self.assertEqual(saved["total"], "15000")
            self.assertEqual(saved["paid"], "5000")

            # An accidental repeat cannot save another sale.
            duplicate = client.post(
                base + "/sales",
                json=payload,
                headers=headers,
            )
            self.assertEqual(duplicate.status_code, 400)

            balance = client.get(
                base + f"/customers/{customer_id}/balance",
                headers=headers,
            )
            self.assertEqual(balance.status_code, 200)
            self.assertEqual(
                balance.json()["balance_naira"],
                "10000.00",
            )

            print(
                "Recovery verified: original sale found, "
                "duplicate rejected, balance unchanged."
            )


if __name__ == "__main__":
    unittest.main()
