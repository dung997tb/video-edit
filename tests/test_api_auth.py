from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

try:
    from fastapi.testclient import TestClient
except Exception:  # pragma: no cover - optional dependency in minimal env
    TestClient = None

try:
    from api.main import create_app
except Exception:  # pragma: no cover - optional dependency in minimal env
    create_app = None


def _fake_services(auth_enabled: bool, secret_key: str = "test-secret"):
    settings = SimpleNamespace(
        api_auth_enabled=auth_enabled,
        api_secret_key=secret_key,
        api_embedded_worker=False,
        cancel_grace_seconds=0.1,
    )
    return SimpleNamespace(settings=settings)


@unittest.skipIf(TestClient is None or create_app is None, "fastapi stack is not installed")
class ApiAuthTests(unittest.TestCase):
    def test_health_is_public(self):
        services = _fake_services(auth_enabled=True)
        with patch("api.main.get_services", return_value=services):
            with TestClient(create_app()) as client:
                response = client.get("/health")
        self.assertEqual(response.status_code, 200)

    def test_protected_route_requires_api_key_when_enabled(self):
        services = _fake_services(auth_enabled=True)
        with patch("api.main.get_services", return_value=services):
            with TestClient(create_app()) as client:
                response = client.get("/openapi.json")
        self.assertEqual(response.status_code, 401)

    def test_protected_route_accepts_x_api_key(self):
        services = _fake_services(auth_enabled=True)
        with patch("api.main.get_services", return_value=services):
            with TestClient(create_app()) as client:
                response = client.get("/openapi.json", headers={"x-api-key": "test-secret"})
        self.assertEqual(response.status_code, 200)

    def test_protected_route_accepts_bearer_token(self):
        services = _fake_services(auth_enabled=True)
        with patch("api.main.get_services", return_value=services):
            with TestClient(create_app()) as client:
                response = client.get("/openapi.json", headers={"Authorization": "Bearer test-secret"})
        self.assertEqual(response.status_code, 200)

    def test_auth_can_be_disabled(self):
        services = _fake_services(auth_enabled=False)
        with patch("api.main.get_services", return_value=services):
            with TestClient(create_app()) as client:
                response = client.get("/openapi.json")
        self.assertEqual(response.status_code, 200)
