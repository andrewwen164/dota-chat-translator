"""No-network contract tests for the proposed hosted backend."""
import unittest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from server.app import create_app, Request


class StubService:
    def __init__(self):
        self.calls = []
    async def translate(self, token, request):
        self.calls.append((token, request.text, request.target))
        if token != "valid":
            raise HTTPException(401, "Sign in again")
        return {"translation": "Hello"}


class HostedApiContractTests(unittest.TestCase):
    def setUp(self):
        self.service = StubService()
        self.client = TestClient(create_app(self.service))
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)

    def test_health(self):
        self.assertEqual(self.client.get("/health").json(), {"status": "ok"})

    def test_missing_token(self):
        r = self.client.post("/v1/translate", json={"text": "привет", "target": "English"})
        self.assertEqual(r.status_code, 401)
        self.assertFalse(self.service.calls)

    def test_valid_request(self):
        r = self.client.post("/v1/translate", headers={"Authorization": "Bearer valid"},
                             json={"text": "привет", "target": "English"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {"translation": "Hello"})

    def test_invalid_input_does_not_reach_provider(self):
        for body in [{"text": "x" * 501, "target": "English"},
                     {"text": "hello", "target": "French"},
                     {"text": "hello", "target": "English", "extra": "not allowed"}]:
            r = self.client.post("/v1/translate", headers={"Authorization": "Bearer valid"}, json=body)
            self.assertEqual(r.status_code, 422)
        self.assertFalse(self.service.calls)


if __name__ == "__main__":
    unittest.main()
