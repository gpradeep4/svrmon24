"""HTTP Basic authentication tests."""

from __future__ import annotations

import base64

from fastapi.testclient import TestClient


def test_protected_route_requires_auth(client: TestClient) -> None:
    response = client.get("/api/me")
    assert response.status_code == 401
    assert response.headers.get("WWW-Authenticate", "").startswith("Basic")


def test_protected_route_rejects_bad_credentials(client: TestClient) -> None:
    bad = base64.b64encode(b"testuser:wrongpass").decode("ascii")
    response = client.get("/api/me", headers={"Authorization": f"Basic {bad}"})
    assert response.status_code == 401


def test_protected_route_accepts_valid_credentials(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    response = client.get("/api/me", headers=auth_headers)
    assert response.status_code == 200
    assert response.json() == {"username": "testuser"}


def test_api_status_requires_auth(client: TestClient) -> None:
    response = client.get("/api/status")
    assert response.status_code == 401
