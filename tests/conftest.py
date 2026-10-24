"""Shared pytest fixtures."""

from __future__ import annotations

import os
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient

# Configure test env before importing the app settings cache
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("BASIC_AUTH_USERNAME", "testuser")
os.environ.setdefault("BASIC_AUTH_PASSWORD", "testpass")
os.environ.setdefault("MONGODB_URI", "mongodb://localhost:27017")
os.environ.setdefault("MONGODB_DB", "svrmon24_test")
os.environ.setdefault("MONGODB_CONNECT_TIMEOUT_MS", "500")
os.environ.setdefault("MONGODB_SERVER_SELECTION_TIMEOUT_MS", "500")
os.environ.setdefault("LOG_LEVEL", "WARNING")


@pytest.fixture()
def auth_headers() -> dict[str, str]:
    import base64

    token = base64.b64encode(b"testuser:testpass").decode("ascii")
    return {"Authorization": f"Basic {token}"}


@pytest.fixture()
def client() -> Generator[TestClient, None, None]:
    from app.config import get_settings
    from app.db import reset_client_for_tests
    from app.main import create_app

    get_settings.cache_clear()
    reset_client_for_tests()
    app = create_app()
    with TestClient(app) as test_client:
        yield test_client
    reset_client_for_tests()
    get_settings.cache_clear()
