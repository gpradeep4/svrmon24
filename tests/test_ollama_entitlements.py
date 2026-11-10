"""Master Phase 12 — Ollama enable flag + tenant entitlements (new functional tests only)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


def _seed_and_run_diag(
    client: TestClient, headers: dict[str, str], *, cid: str = "srv-ollama-ent"
) -> str:
    assert (
        client.post(
            "/api/components",
            headers=headers,
            json={
                "component_id": cid,
                "component_type": "Server",
                "name": "ollama-ent-host",
                "environment": "prod",
                "status": "active",
                "hostname": "ollama-ent-host",
                "os_family": "RHEL",
                "os_version": "9",
            },
        ).status_code
        == 201
    )
    created = client.post(
        "/api/diagnostics",
        headers=headers,
        json={"component_id": cid, "profile_name": "basic-health"},
    )
    assert created.status_code == 201, created.text
    return created.json()["diagnostic_id"]


def _mock_ollama_json_response(payload: dict) -> MagicMock:
    response = MagicMock()
    response.raise_for_status = MagicMock()
    response.json.return_value = {
        "message": {"content": __import__("json").dumps(payload)},
    }
    response.status_code = 200
    response.text = "ok"
    return response


def _valid_model_payload() -> dict:
    return {
        "executive_summary": "Simulated checks look nominal.",
        "observed_evidence": [
            "Observed check cpu=42 (status=ok, data_source=SYNTHETIC_DEMO, synthetic=True)"
        ],
        "potential_causes": ["[HYPOTHESIS] No live issue evidenced in simulated data"],
        "recommended_verification_steps": [
            "Collect real telemetry only if live probes are later approved"
        ],
        "suggested_remediation": ["Do not auto-execute remediation"],
        "confidence": "medium",
        "uncertainty": "Simulated evidence only",
        "potential_dependency_impact": "No claim of actual downstream outage",
        "observations_vs_hypotheses": {
            "observations": [
                "Observed check cpu=42 (status=ok, data_source=SYNTHETIC_DEMO, synthetic=True)"
            ],
            "hypotheses": ["[HYPOTHESIS] No live issue evidenced in simulated data"],
        },
    }


@pytest.fixture()
def ollama_disabled(monkeypatch: pytest.MonkeyPatch):
    """Force production-oriented default: Ollama off."""
    monkeypatch.setenv("OLLAMA_ENABLED", "false")
    from app.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture()
def ollama_enabled(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("OLLAMA_ENABLED", "true")
    from app.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_entitlements_include_max_ollama_analyses(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    ents = client.get("/api/entitlements", headers=auth_headers)
    assert ents.status_code == 200
    body = ents.json()
    assert body["billing_enabled"] is False
    assert body["payment_provider"] is None
    assert "max_ollama_analyses" in body["limits"]
    assert body["limits"]["max_ollama_analyses"] is None


def test_ollama_status_disabled_by_default(
    ollama_disabled,
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    with patch("app.services.ollama_client.httpx.Client") as mocked_http:
        status = client.get("/api/diagnostics/ollama/status", headers=auth_headers)
    assert status.status_code == 200, status.text
    body = status.json()
    assert body["enabled"] is False
    assert body["ok"] is False
    assert body["error"] == "disabled"
    assert body["will_use_ollama"] is False
    assert body["external_providers"] is False
    assert body["rule_fallback_always_available"] is True
    assert "shared" in (body.get("shared_local_contention") or "").lower()
    assert "entitlement" in body
    assert body["entitlement"]["limit"] is None
    # Disabled path must not probe the network.
    mocked_http.assert_not_called()


def test_analyze_falls_back_when_ollama_disabled(
    ollama_disabled,
    client: TestClient,
    auth_headers: dict[str, str],
    clean_db,
) -> None:
    diag_id = _seed_and_run_diag(client, auth_headers, cid="srv-ollama-off")
    with patch("app.services.ai_analysis.analyze_with_ollama") as mocked:
        response = client.post(
            f"/api/diagnostics/{diag_id}/analyze",
            headers=auth_headers,
            json={},
        )
    assert response.status_code == 200, response.text
    analysis = response.json()["ai_analysis"]
    assert analysis["source"] == "rule_based_fallback"
    assert "ollama_disabled" in (analysis.get("fallback_reason") or "")
    assert analysis["derived_from_simulated_data"] is True
    mocked.assert_not_called()


def test_analyze_falls_back_when_entitlement_limited(
    ollama_enabled,
    client: TestClient,
    auth_headers: dict[str, str],
    clean_db,
) -> None:
    diag_id = _seed_and_run_diag(client, auth_headers, cid="srv-ollama-lim")
    with (
        patch(
            "app.services.entitlements.ollama_analysis_limit", return_value=0
        ),
        patch("app.services.ai_analysis.analyze_with_ollama") as mocked,
    ):
        response = client.post(
            f"/api/diagnostics/{diag_id}/analyze",
            headers=auth_headers,
            json={},
        )
    assert response.status_code == 200, response.text
    analysis = response.json()["ai_analysis"]
    assert analysis["source"] == "rule_based_fallback"
    assert "ollama_entitlement_limit" in (analysis.get("fallback_reason") or "")
    mocked.assert_not_called()


def test_analyze_uses_ollama_when_enabled_and_unlimited(
    ollama_enabled,
    client: TestClient,
    auth_headers: dict[str, str],
    clean_db,
) -> None:
    diag_id = _seed_and_run_diag(client, auth_headers, cid="srv-ollama-on")
    mock_response = _mock_ollama_json_response(_valid_model_payload())
    mock_http = MagicMock()
    mock_http.__enter__.return_value = mock_http
    mock_http.__exit__.return_value = False
    mock_http.post.return_value = mock_response

    with patch("app.services.ollama_client.httpx.Client", return_value=mock_http):
        response = client.post(
            f"/api/diagnostics/{diag_id}/analyze",
            headers=auth_headers,
            json={},
        )
    assert response.status_code == 200, response.text
    analysis = response.json()["ai_analysis"]
    assert analysis["source"] == "ollama"
    assert analysis["derived_from_simulated_data"] is True


def test_force_fallback_skips_ollama_even_when_enabled(
    ollama_enabled,
    client: TestClient,
    auth_headers: dict[str, str],
    clean_db,
) -> None:
    diag_id = _seed_and_run_diag(client, auth_headers, cid="srv-ollama-force")
    with patch("app.services.ai_analysis.analyze_with_ollama") as mocked:
        response = client.post(
            f"/api/diagnostics/{diag_id}/analyze",
            headers=auth_headers,
            json={"force_fallback": True},
        )
    assert response.status_code == 200
    assert response.json()["ai_analysis"]["source"] == "rule_based_fallback"
    mocked.assert_not_called()


def test_ollama_status_reports_entitlement_limit(
    ollama_enabled,
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    with patch(
        "app.services.entitlements.ollama_analysis_allowed",
        return_value={
            "allowed": False,
            "limit": 1,
            "used": 1,
            "remaining": 0,
            "limited": True,
        },
    ):
        with patch(
            "app.services.ollama_client.OllamaClient.is_available",
            return_value={
                "ok": True,
                "base_url": "http://localhost:11434",
                "configured_model": "llama3.2:3b",
                "models": ["llama3.2:3b"],
                "model_present": True,
            },
        ):
            status = client.get("/api/diagnostics/ollama/status", headers=auth_headers)
    assert status.status_code == 200
    body = status.json()
    assert body["enabled"] is True
    assert body["will_use_ollama"] is False
    assert body["entitlement"]["limited"] is True
    assert "entitlement" in (body.get("detail") or "").lower() or body.get("error")


def test_count_ollama_analyses_after_success(
    ollama_enabled,
    client: TestClient,
    auth_headers: dict[str, str],
    clean_db,
) -> None:
    from app.services import entitlements as entitlements_service

    diag_id = _seed_and_run_diag(client, auth_headers, cid="srv-ollama-count")
    mock_response = _mock_ollama_json_response(_valid_model_payload())
    mock_http = MagicMock()
    mock_http.__enter__.return_value = mock_http
    mock_http.__exit__.return_value = False
    mock_http.post.return_value = mock_response

    before = entitlements_service.count_ollama_analyses("tenant-svrmon24-legacy")
    with patch("app.services.ollama_client.httpx.Client", return_value=mock_http):
        response = client.post(
            f"/api/diagnostics/{diag_id}/analyze",
            headers=auth_headers,
            json={},
        )
    assert response.status_code == 200
    assert response.json()["ai_analysis"]["source"] == "ollama"
    after = entitlements_service.count_ollama_analyses("tenant-svrmon24-legacy")
    assert after == before + 1


def test_ui_markers_and_version(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    html = client.get("/", headers=auth_headers).text
    assert 'id="ollamaStatusHint"' in html
    assert 'id="ollamaContentionHint"' in html
    assert "max_ollama_analyses" in html
    assert "OLLAMA_ENABLED" in html
    from app import __version__

    assert __version__ in html
    assert "disabled/limited/unavailable" in html
    js = client.get("/static/js/cmdb.js", headers=auth_headers).text
    assert "max_ollama_analyses" in js
    assert "OLLAMA_ENABLED=false" in js
    assert "shared_local_contention" in js
    assert "Ollama limited by entitlements" in js
