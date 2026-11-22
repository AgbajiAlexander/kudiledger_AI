import unittest

from fastapi.testclient import TestClient

from app.api.main import create_app


class TestAPIHealth(unittest.TestCase):

    def setUp(self):
        self.client = TestClient(create_app())

    def test_health_returns_200(self):
        response = self.client.get("/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")

    def test_application_name(self):
        response = self.client.get("/health")

        self.assertEqual(
            response.json()["application"],
            "KudiLedger AI",
        )

    def test_unknown_route_returns_404(self):
        response = self.client.get(
            "/this-route-does-not-exist"
        )

        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
