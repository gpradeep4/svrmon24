"""MongoDB connection behavior and ObjectId serialization tests."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from bson import ObjectId
from fastapi.testclient import TestClient
from pymongo.errors import ServerSelectionTimeoutError

from app.db import DatabaseUnavailableError, ping_database, require_database
from app.serialization import parse_object_id, serialize_document, serialize_value


def test_serialize_object_id() -> None:
    oid = ObjectId()
    assert serialize_value(oid) == str(oid)


def test_serialize_document_nested() -> None:
    oid = ObjectId()
    when = datetime(2026, 10, 24, 12, 0, 0, tzinfo=timezone.utc)
    doc = {"_id": oid, "name": "host-a", "nested": {"ref": oid}, "tags": [oid], "ts": when}
    out = serialize_document(doc)
    assert out is not None
    assert out["_id"] == str(oid)
    assert out["nested"]["ref"] == str(oid)
    assert out["tags"] == [str(oid)]
    assert out["ts"] == when.isoformat()


def test_parse_object_id_valid() -> None:
    oid = ObjectId()
    assert parse_object_id(str(oid)) == oid


def test_parse_object_id_invalid() -> None:
    try:
        parse_object_id("not-an-objectid")
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "Invalid ObjectId" in str(exc)


def test_ping_database_connection_failure() -> None:
    mock_client = MagicMock()
    mock_client.admin.command.side_effect = ServerSelectionTimeoutError("timed out")
    with patch("app.db.get_client", return_value=mock_client):
        status = ping_database()
    assert status["ok"] is False
    assert status["error"] == "connection_failed"


def test_ping_database_success() -> None:
    mock_client = MagicMock()
    mock_client.admin.command.return_value = {"ok": 1.0}
    with patch("app.db.get_client", return_value=mock_client):
        status = ping_database()
    assert status["ok"] is True
    assert status["ping"]["ok"] == 1.0


def test_require_database_raises_when_unavailable() -> None:
    with patch("app.db.ping_database", return_value={"ok": False, "detail": "down"}):
        try:
            require_database()
            assert False, "expected DatabaseUnavailableError"
        except DatabaseUnavailableError as exc:
            assert "down" in exc.message


def test_api_status_reports_degraded_when_db_down(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    with patch(
        "app.main.ping_database",
        return_value={"ok": False, "error": "connection_failed", "detail": "down"},
    ):
        response = client.get("/api/status", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "degraded"
    assert body["mongodb"]["ok"] is False
