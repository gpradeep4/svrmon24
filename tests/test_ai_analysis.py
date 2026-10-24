"""AI diagnostic analysis tests — mocked Ollama only (no external API)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
from fastapi.testclient import TestClient

from app.services.ai_analysis import build_rule_based_fallback
from app.services.ollama_client import OllamaClient, OllamaError, extract_json_from_text


def _seed_and_run_diag(client: TestClient, headers: dict) -> str:
    assert (
        client.post(
            "/api/components",
            headers=headers,
            json={
                "component_id": "srv-ai",
                "component_type": "Server",
                "name": "ai-host",
                "environment": "prod",
                "status": "active",
                "hostname": "ai-host",
                "os_family": "RHEL",
                "os_version": "9",
            },
        ).status_code
        == 201
    )
    created = client.post(
        "/api/diagnostics",
        headers=headers,
        json={"component_id": "srv-ai", "profile_name": "basic-health"},
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


def test_extract_json_from_text_tolerates_fences() -> None:
    raw = 'Here you go:\n```json\n{"executive_summary": "x", "observed_evidence": []}\n```'
    parsed = extract_json_from_text(raw)
    assert parsed["executive_summary"] == "x"


def test_rule_based_fallback_separates_observations_and_hypotheses(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    diag_id = _seed_and_run_diag(client, auth_headers)
    diagnostic = client.get(f"/api/diagnostics/{diag_id}", headers=auth_headers).json()
    analysis = build_rule_based_fallback(diagnostic, reason="unit_test")
    assert analysis["source"] == "rule_based_fallback"
    assert analysis["derived_from_simulated_data"] is True
    assert analysis["evidence_label"] == "SIMULATED"
    assert analysis["safety"]["auto_remediation"] is False
    assert analysis["observed_evidence"]
    assert analysis["potential_causes"]
    assert all(
        item.upper().startswith("[HYPOTHESIS]") or "HYPOTHESIS" in item.upper()
        for item in analysis["observations_vs_hypotheses"]["hypotheses"]
    )
    # Must only reference provided checks — every observation mentions known fields
    joined = " ".join(analysis["observed_evidence"])
    assert "execution_mode=SIMULATED" in joined or "SIMULATED" in joined


def test_analyze_endpoint_uses_fallback_when_ollama_unavailable(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    diag_id = _seed_and_run_diag(client, auth_headers)
    with patch("app.services.ai_analysis.analyze_with_ollama") as mocked:
        mocked.side_effect = OllamaError("down", kind="unavailable")
        response = client.post(
            f"/api/diagnostics/{diag_id}/analyze",
            headers=auth_headers,
            json={},
        )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ai_analysis"]["source"] == "rule_based_fallback"
    assert body["ai_analysis"]["derived_from_simulated_data"] is True
    assert "SIMULATED" in body["ai_analysis"]["labels"]["banner"]
    assert len(body["ai_analysis_history"]) >= 1


def test_analyze_with_mocked_ollama_success(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    diag_id = _seed_and_run_diag(client, auth_headers)
    model_payload = {
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

    mock_response = _mock_ollama_json_response(model_payload)
    mock_client_instance = MagicMock()
    mock_client_instance.__enter__.return_value = mock_client_instance
    mock_client_instance.__exit__.return_value = False
    mock_client_instance.post.return_value = mock_response

    with patch("app.services.ollama_client.httpx.Client", return_value=mock_client_instance):
        response = client.post(
            f"/api/diagnostics/{diag_id}/analyze",
            headers=auth_headers,
            json={},
        )
    assert response.status_code == 200, response.text
    analysis = response.json()["ai_analysis"]
    assert analysis["source"] == "ollama"
    assert analysis["executive_summary"] == "Simulated checks look nominal."
    assert analysis["derived_from_simulated_data"] is True
    assert analysis["model"]


def test_malformed_ollama_output_falls_back(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    diag_id = _seed_and_run_diag(client, auth_headers)
    bad = MagicMock()
    bad.raise_for_status = MagicMock()
    bad.json.return_value = {"message": {"content": "not-json-at-all"}}
    bad.status_code = 200
    bad.text = "ok"
    mock_client_instance = MagicMock()
    mock_client_instance.__enter__.return_value = mock_client_instance
    mock_client_instance.__exit__.return_value = False
    mock_client_instance.post.return_value = bad

    with patch("app.services.ollama_client.httpx.Client", return_value=mock_client_instance):
        response = client.post(
            f"/api/diagnostics/{diag_id}/analyze",
            headers=auth_headers,
            json={},
        )
    assert response.status_code == 200
    assert response.json()["ai_analysis"]["source"] == "rule_based_fallback"
    assert "malformed" in response.json()["ai_analysis"]["fallback_reason"]


def test_timeout_falls_back(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    diag_id = _seed_and_run_diag(client, auth_headers)
    mock_client_instance = MagicMock()
    mock_client_instance.__enter__.return_value = mock_client_instance
    mock_client_instance.__exit__.return_value = False
    mock_client_instance.post.side_effect = httpx.TimeoutException("slow")

    with patch("app.services.ollama_client.httpx.Client", return_value=mock_client_instance):
        response = client.post(
            f"/api/diagnostics/{diag_id}/analyze",
            headers=auth_headers,
            json={},
        )
    assert response.status_code == 200
    assert "timeout" in response.json()["ai_analysis"]["fallback_reason"]


def test_force_fallback_skips_ollama(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    diag_id = _seed_and_run_diag(client, auth_headers)
    with patch("app.services.ai_analysis.analyze_with_ollama") as mocked:
        response = client.post(
            f"/api/diagnostics/{diag_id}/analyze",
            headers=auth_headers,
            json={"force_fallback": True},
        )
        mocked.assert_not_called()
    assert response.status_code == 200
    assert response.json()["ai_analysis"]["source"] == "rule_based_fallback"


def test_unknown_diagnostic_analyze(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    response = client.post(
        "/api/diagnostics/diag-missing/analyze",
        headers=auth_headers,
        json={},
    )
    assert response.status_code == 404


def test_analysis_history_appended(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    diag_id = _seed_and_run_diag(client, auth_headers)
    first = client.post(
        f"/api/diagnostics/{diag_id}/analyze",
        headers=auth_headers,
        json={"force_fallback": True},
    )
    second = client.post(
        f"/api/diagnostics/{diag_id}/analyze",
        headers=auth_headers,
        json={"force_fallback": True},
    )
    assert first.status_code == 200 and second.status_code == 200
    history = second.json()["ai_analysis_history"]
    assert len(history) >= 2
    assert second.json()["ai_analysis"]["analysis_id"] == history[-1]["analysis_id"]


def test_ollama_client_chat_json_direct_unit() -> None:
    client = OllamaClient(
        base_url="http://ollama.test",
        model="llama3.2:3b",
        timeout_seconds=5,
    )
    payload = {
        "executive_summary": "ok",
        "observed_evidence": ["a"],
        "potential_causes": ["b"],
        "recommended_verification_steps": ["c"],
        "suggested_remediation": ["d"],
        "confidence": "low",
        "uncertainty": "u",
        "potential_dependency_impact": "i",
    }
    mock_response = _mock_ollama_json_response(payload)
    mock_http = MagicMock()
    mock_http.__enter__.return_value = mock_http
    mock_http.__exit__.return_value = False
    mock_http.post.return_value = mock_response
    with patch("app.services.ollama_client.httpx.Client", return_value=mock_http):
        out = client.chat_json([{"role": "user", "content": "hi"}])
    assert out["executive_summary"] == "ok"
