"""AI A0 — shared facade, Ollama path, optional cloud suggestions, entitlements."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.services.ai_facade import (
    run_structured_task,
    safe_run_structured_task,
)
from app.services.ai_providers import SOURCE_CLOUD, SOURCE_OLLAMA, SOURCE_RULE


@pytest.fixture()
def providers_off(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("OLLAMA_ENABLED", "false")
    monkeypatch.setenv("AI_CLOUD_SUGGESTIONS_ENABLED", "false")
    from app.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture()
def ollama_on(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("OLLAMA_ENABLED", "true")
    monkeypatch.setenv("AI_CLOUD_SUGGESTIONS_ENABLED", "false")
    from app.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture()
def cloud_on(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("OLLAMA_ENABLED", "false")
    monkeypatch.setenv("AI_CLOUD_SUGGESTIONS_ENABLED", "true")
    monkeypatch.setenv("AI_CLOUD_API_KEY_ENV_REF", "AI_CLOUD_API_KEY")
    monkeypatch.setenv("AI_CLOUD_API_KEY", "sk-test-not-real")
    monkeypatch.setenv("AI_CLOUD_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("AI_CLOUD_MODEL", "gpt-test")
    from app.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _fallback(reason: str) -> dict:
    return {
        "source": SOURCE_RULE,
        "fallback_reason": reason,
        "executive_summary": f"fallback:{reason}",
        "value": 1,
    }


def test_ai_status_defaults(
    providers_off,
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    with patch("app.services.ollama_client.httpx.Client") as mocked_http:
        status = client.get("/api/ai/status", headers=auth_headers)
    assert status.status_code == 200, status.text
    body = status.json()
    assert body["rule_fallback_always_available"] is True
    assert body["providers"]["ollama"] is False
    assert body["providers"]["cloud_suggestions"] is False
    assert body["cloud_suggestions"]["platform_enabled"] is False
    assert body["cloud_suggestions"]["will_use"] is False
    assert body["will_use_ollama"] is False
    assert body["will_use_cloud"] is False
    assert body["external_providers"] is False
    assert body["safety"]["auto_transitions"] is False
    assert body["safety"]["auto_approvals"] is False
    assert body["safety"]["secrets_stored_in_mongo"] is False
    assert "shared" in (body.get("shared_local_contention") or "").lower()
    assert "entitlement" in body
    mocked_http.assert_not_called()


def test_diagnostics_ollama_status_delegates(
    providers_off,
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    platform = client.get("/api/ai/status", headers=auth_headers).json()
    diag = client.get("/api/diagnostics/ollama/status", headers=auth_headers).json()
    assert diag["enabled"] == platform["enabled"]
    assert diag["rule_fallback_always_available"] is True
    assert diag["external_providers"] is False


def test_run_structured_task_rule_when_providers_off(providers_off) -> None:
    result = run_structured_task(
        task_key="unit.ping",
        tenant_id="tenant-svrmon24-legacy",
        messages=[{"role": "user", "content": "hi"}],
        fallback_builder=_fallback,
        record_usage=False,
    )
    assert result.source == SOURCE_RULE
    assert "ollama_disabled" in (result.fallback_reason or "")


def test_run_structured_task_uses_ollama(
    ollama_on, client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {
        "message": {"content": json.dumps({"ok": True, "n": 2})}
    }
    mock_http = MagicMock()
    mock_http.__enter__.return_value = mock_http
    mock_http.__exit__.return_value = False
    mock_http.post.return_value = mock_response

    with patch("app.services.ollama_client.httpx.Client", return_value=mock_http):
        result = run_structured_task(
            task_key="unit.ollama",
            tenant_id="tenant-svrmon24-legacy",
            messages=[{"role": "user", "content": "hi"}],
            fallback_builder=_fallback,
            record_usage=True,
        )
    assert result.source == SOURCE_OLLAMA
    assert result.payload["ok"] is True
    from app.services import entitlements as entitlements_service

    # Assist usage should debit the shared generative quota.
    used = entitlements_service.count_ollama_analyses("tenant-svrmon24-legacy")
    assert used >= 1


def test_cloud_requires_tenant_opt_in(
    cloud_on, client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    status = client.get("/api/ai/status", headers=auth_headers).json()
    assert status["cloud_suggestions"]["platform_enabled"] is True
    assert status["cloud_suggestions"]["api_key_configured"] is True
    assert status["cloud_suggestions"]["tenant_opt_in"] is False
    assert status["cloud_suggestions"]["will_use"] is False
    assert status["external_providers"] is True

    result = run_structured_task(
        task_key="unit.cloud",
        tenant_id="tenant-svrmon24-legacy",
        messages=[{"role": "user", "content": "hi"}],
        fallback_builder=_fallback,
        record_usage=False,
    )
    assert result.source == SOURCE_RULE


def test_cloud_opt_in_and_provider(
    cloud_on, client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    opt = client.put(
        "/api/ai/cloud-opt-in",
        headers=auth_headers,
        json={"enabled": True},
    )
    assert opt.status_code == 200, opt.text
    assert opt.json()["ai_cloud_suggestions_opt_in"] is True
    assert opt.json()["status"]["cloud_suggestions"]["will_use"] is True

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {
        "choices": [
            {"message": {"content": json.dumps({"ok": True, "via": "cloud"})}}
        ]
    }
    mock_http = MagicMock()
    mock_http.__enter__.return_value = mock_http
    mock_http.__exit__.return_value = False
    mock_http.post.return_value = mock_response

    with patch("app.services.ai_providers.httpx.Client", return_value=mock_http):
        result = run_structured_task(
            task_key="unit.cloud",
            tenant_id="tenant-svrmon24-legacy",
            messages=[{"role": "user", "content": "hi"}],
            fallback_builder=_fallback,
            record_usage=True,
        )
    assert result.source == SOURCE_CLOUD
    assert result.payload["via"] == "cloud"
    mock_http.post.assert_called_once()
    # Authorization header present; secret value must not appear in status.
    status = client.get("/api/ai/status", headers=auth_headers).json()
    dumped = json.dumps(status)
    assert "sk-test-not-real" not in dumped
    assert status["cloud_suggestions"]["api_key_configured"] is True


def test_cloud_failure_falls_back_to_rule(
    cloud_on, client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    assert (
        client.put(
            "/api/ai/cloud-opt-in",
            headers=auth_headers,
            json={"enabled": True},
        ).status_code
        == 200
    )
    mock_http = MagicMock()
    mock_http.__enter__.return_value = mock_http
    mock_http.__exit__.return_value = False
    mock_http.post.side_effect = Exception("boom")

    with patch("app.services.ai_providers.httpx.Client", return_value=mock_http):
        result = run_structured_task(
            task_key="unit.cloud_fail",
            tenant_id="tenant-svrmon24-legacy",
            messages=[{"role": "user", "content": "hi"}],
            fallback_builder=_fallback,
            record_usage=False,
        )
    assert result.source == SOURCE_RULE
    assert result.fallback_reason


def test_safe_run_never_raises_on_fallback_builder_error(providers_off) -> None:
    def bad_fallback(_reason: str) -> dict:
        raise RuntimeError("fallback exploded")

    result = safe_run_structured_task(
        task_key="unit.safe",
        tenant_id="tenant-svrmon24-legacy",
        messages=[{"role": "user", "content": "hi"}],
        fallback_builder=bad_fallback,
        record_usage=False,
    )
    assert result.source == SOURCE_RULE
    assert "ai_internal_error" in (result.fallback_reason or "")


def test_force_fallback_skips_providers(ollama_on) -> None:
    with patch("app.services.ai_facade.OllamaSuggestionProvider") as mocked:
        result = run_structured_task(
            task_key="unit.force",
            tenant_id="tenant-svrmon24-legacy",
            messages=[{"role": "user", "content": "hi"}],
            fallback_builder=_fallback,
            force_fallback=True,
            record_usage=False,
        )
    assert result.source == SOURCE_RULE
    assert "forced_fallback" in (result.fallback_reason or "")
    mocked.assert_not_called()


def test_analyze_still_falls_back_when_disabled(
    providers_off,
    client: TestClient,
    auth_headers: dict[str, str],
    clean_db,
) -> None:
    assert (
        client.post(
            "/api/components",
            headers=auth_headers,
            json={
                "component_id": "srv-a0",
                "component_type": "Server",
                "name": "a0-host",
                "environment": "prod",
                "status": "active",
                "hostname": "a0-host",
                "os_family": "RHEL",
                "os_version": "9",
            },
        ).status_code
        == 201
    )
    created = client.post(
        "/api/diagnostics",
        headers=auth_headers,
        json={"component_id": "srv-a0", "profile_name": "basic-health"},
    )
    assert created.status_code == 201, created.text
    diag_id = created.json()["diagnostic_id"]
    response = client.post(
        f"/api/diagnostics/{diag_id}/analyze",
        headers=auth_headers,
        json={},
    )
    assert response.status_code == 200, response.text
    analysis = response.json()["ai_analysis"]
    assert analysis["source"] == "rule_based_fallback"
    assert "ollama_disabled" in (analysis.get("fallback_reason") or "")


def test_version_marker(client: TestClient, auth_headers: dict[str, str]) -> None:
    from app import __version__

    assert __version__ == "0.99.8"
    html = client.get("/", headers=auth_headers).text
    assert __version__ in html
