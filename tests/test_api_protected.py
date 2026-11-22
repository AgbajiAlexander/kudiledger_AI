import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.api.main import create_app
from app.services.accounts import AccountLedger


class TestProtectedAPI(unittest.TestCase):

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)

        path = Path(temp.name) / "api_test.db"
        self.ledger = AccountLedger(path)
        self.client = TestClient(create_app(path))

        self.owner_a = self.ledger.register_owner(
            "Abuja Shop A",
            "shopa@example.test",
            "TestingPassword123!"
        )
        self.owner_b = self.ledger.register_owner(
            "Abuja Shop B",
            "shopb@example.test",
            "AnotherPassword456!"
        )

        self.token_a = self.login(
            "shopa@example.test", "TestingPassword123!"
        )
        self.token_b = self.login(
            "shopb@example.test", "AnotherPassword456!"
        )

    def login(self, email, password):
        response = self.client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": password},
        )
        self.assertEqual(response.status_code, 200)
        return response.json()["access_token"]

    def headers(self, token):
        return {"Authorization": f"Bearer {token}"}

    def add_customer(self):
        business = self.owner_a["business_id"]
        response = self.client.post(
            f"/api/v1/businesses/{business}/customers",
            json={"name": "Musa"},
            headers=self.headers(self.token_a),
        )
        self.assertEqual(response.status_code, 201)
        return response.json()["id"]

    def test_login_rejects_wrong_password(self):
        response = self.client.post(
            "/api/v1/auth/login",
            json={
                "email": "shopa@example.test",
                "password": "IncorrectPassword",
            },
        )
        self.assertEqual(response.status_code, 401)

    def test_customer_requires_authentication(self):
        business = self.owner_a["business_id"]
        response = self.client.post(
            f"/api/v1/businesses/{business}/customers",
            json={"name": "Musa"},
        )
        self.assertEqual(response.status_code, 401)

    def test_customer_sale_and_repayment(self):
        business = self.owner_a["business_id"]
        customer = self.add_customer()
        headers = self.headers(self.token_a)

        sale = self.client.post(
            f"/api/v1/businesses/{business}/sales",
            json={
                "customer_id": customer,
                "reference": "SALE-001",
                "total": "15000",
                "paid": "10000",
                "confirmed": True,
            },
            headers=headers,
        )
        self.assertEqual(sale.status_code, 201)

        repayment = self.client.post(
            f"/api/v1/businesses/{business}/repayments",
            json={
                "customer_id": customer,
                "reference": "PAY-001",
                "amount": "3000",
                "confirmed": True,
            },
            headers=headers,
        )
        self.assertEqual(repayment.status_code, 201)

        balance = self.client.get(
            f"/api/v1/businesses/{business}/customers/"
            f"{customer}/balance",
            headers=headers,
        )
        self.assertEqual(balance.status_code, 200)
        self.assertEqual(
            balance.json()["balance_naira"], "2000.00"
        )

        history = self.client.get(
            f"/api/v1/businesses/{business}/customers/"
            f"{customer}/repayments",
            headers=headers,
        )
        self.assertEqual(history.status_code, 200)
        self.assertEqual(len(history.json()), 1)
        self.assertEqual(
            history.json()[0]["amount"], "3000.00"
        )

    def test_cross_business_access_denied(self):
        business = self.owner_a["business_id"]
        customer = self.add_customer()

        response = self.client.get(
            f"/api/v1/businesses/{business}/customers/"
            f"{customer}/balance",
            headers=self.headers(self.token_b),
        )
        self.assertEqual(response.status_code, 403)

        response = self.client.post(
            f"/api/v1/businesses/{business}/sales",
            json={
                "customer_id": customer,
                "reference": "SALE-002",
                "total": "5000",
                "paid": "0",
                "confirmed": True,
            },
            headers=self.headers(self.token_b),
        )
        self.assertEqual(response.status_code, 403)

    def test_unconfirmed_sale_is_rejected(self):
        business = self.owner_a["business_id"]
        customer = self.add_customer()

        response = self.client.post(
            f"/api/v1/businesses/{business}/sales",
            json={
                "customer_id": customer,
                "reference": "SALE-003",
                "total": "5000",
                "paid": "2000",
                "confirmed": False,
            },
            headers=self.headers(self.token_a),
        )
        self.assertEqual(response.status_code, 400)

    def test_logout_revokes_token(self):
        response = self.client.post(
            "/api/v1/auth/logout",
            headers=self.headers(self.token_a),
        )
        self.assertEqual(response.status_code, 200)

        business = self.owner_a["business_id"]
        response = self.client.post(
            f"/api/v1/businesses/{business}/customers",
            json={"name": "Another Customer"},
            headers=self.headers(self.token_a),
        )
        self.assertEqual(response.status_code, 403)


if __name__ == "__main__":
    unittest.main()
