"""Health endpoint tests — must remain publicly accessible."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_health_is_public(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "SVRMON24"
    assert "version" in body


def test_health_does_not_require_auth(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code != 401
    assert "WWW-Authenticate" not in response.headers
