"""Monitoring Log AI assist — Ollama qwen2.5-coder:14b path (0.99.0)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app import __version__
from tests.frontend_paths import FRONTEND_INDEX

MONITOR_LOGS_JS = Path("frontend/static/js/monitor/logs.js")
ENV_EXAMPLE = Path(".env.example")


def test_version_and_ui_markers() -> None:
    assert __version__ == "0.99.0"
    html = FRONTEND_INDEX.read_text(encoding="utf-8")
    assert 'content="0.99.0"' in html
    assert "monitor/logs.js?v=0.99.0" in html
    assert 'id="mlAiParse"' in html
    assert 'id="mlAiSuggest"' in html
    assert 'id="mlAiNarrative"' in html
    assert 'id="mlAiAssistPanel"' in html
    assert "assist only" in html.lower() or "Assist only" in html
    assert "qwen2.5-coder:14b" in html
    js = MONITOR_LOGS_JS.read_text(encoding="utf-8")
    assert "/api/monitor/logs/ai/parse" in js
    assert "/api/monitor/logs/ai/suggest-filters" in js
    assert "/api/monitor/logs/ai/predict-narrative" in js
    assert "/api/monitor/logs/ai/status" in js
    assert "OLLAMA_LOG_MODEL" in js
    assert "Apply suggested filters" in html or "mlAiApplyFilters" in html
    env = ENV_EXAMPLE.read_text(encoding="utf-8")
    assert "OLLAMA_LOG_MODEL=qwen2.5-coder:14b" in env


def test_log_ai_status_fail_closed(
    client: TestClient,
    auth_headers: dict[str, str],
    monkeypatch,
) -> None:
    monkeypatch.setenv("OLLAMA_ENABLED", "false")
    from app.config import get_settings

    get_settings.cache_clear()
    try:
        resp = client.get("/api/monitor/logs/ai/status", headers=auth_headers)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["assist_only"] is True
        assert body["ollama_enabled"] is False
        assert body["log_model"] == "qwen2.5-coder:14b"
        assert body["will_use_ollama"] is False
        assert body["rule_fallback_always_available"] is True
        assert body["filters_authoritative"] is True
        assert body["auto_write_rules"] is False
        assert body["auto_create_incidents"] is False
        assert body["safety"]["assist_only"] is True
        assert body["safety"]["auto_apply"] is False
        assert "parse" in body["tasks"]
    finally:
        get_settings.cache_clear()


def test_log_ai_empty_body_400(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    resp = client.post(
        "/api/monitor/logs/ai/parse",
        headers=auth_headers,
        json={"event_ids": [], "messages": []},
    )
    assert resp.status_code == 400


def test_parse_suggest_narrative_rule_fallback(
    client: TestClient,
    auth_headers: dict[str, str],
    monkeypatch,
    clean_db,
) -> None:
    monkeypatch.setenv("OLLAMA_ENABLED", "false")
    from app.config import get_settings

    get_settings.cache_clear()
    try:
        tick = client.post(
            "/api/monitor/logs/simulate-tick?events_per_stream=3",
            headers=auth_headers,
        )
        assert tick.status_code == 200, tick.text

        events = client.get(
            "/api/monitor/logs/events?page_size=10", headers=auth_headers
        )
        assert events.status_code == 200, events.text
        items = events.json()["items"]
        assert items
        event_ids = [row["event_id"] for row in items[:5]]

        parse = client.post(
            "/api/monitor/logs/ai/parse",
            headers=auth_headers,
            json={"event_ids": event_ids, "force_fallback": True},
        )
        assert parse.status_code == 200, parse.text
        pbody = parse.json()
        assert pbody["source"] == "rule_based_fallback"
        assert pbody["safety"]["auto_write_rules"] is False
        assert isinstance(pbody["fields"], list)
        assert "summary" in pbody

        # Also accept raw messages
        parse_msg = client.post(
            "/api/monitor/logs/ai/parse",
            headers=auth_headers,
            json={
                "messages": [
                    "Upstream timeout connecting to dependency retry=3 status=500"
                ]
            },
        )
        assert parse_msg.status_code == 200, parse_msg.text
        assert parse_msg.json()["attrs_suggestions"].get("status") == "500" or any(
            f.get("name") == "status" for f in parse_msg.json()["fields"]
        )

        suggest = client.post(
            "/api/monitor/logs/ai/suggest-filters",
            headers=auth_headers,
            json={
                "event_ids": event_ids,
                "current_filters": {"q": "timeout", "severity": "error"},
                "force_fallback": True,
            },
        )
        assert suggest.status_code == 200, suggest.text
        sbody = suggest.json()
        assert sbody["source"] == "rule_based_fallback"
        assert "suggested_filters" in sbody
        assert sbody["safety"]["auto_create_incidents"] is False

        from app.db import require_monitor_database
        from app.tenancy import MIGRATION_TENANT_ID, tenant_filter

        rules_before = require_monitor_database()["alert_rules"].count_documents(
            tenant_filter(MIGRATION_TENANT_ID)
        )

        narrative = client.post(
            "/api/monitor/logs/ai/predict-narrative",
            headers=auth_headers,
            json={"event_ids": event_ids, "force_fallback": True},
        )
        assert narrative.status_code == 200, narrative.text
        nbody = narrative.json()
        assert nbody["source"] == "rule_based_fallback"
        assert nbody["narrative"]
        assert nbody["disclaimer"]
        assert nbody["safety"]["human_must_confirm"] is True

        rules_after = require_monitor_database()["alert_rules"].count_documents(
            tenant_filter(MIGRATION_TENANT_ID)
        )
        assert rules_after == rules_before
    finally:
        get_settings.cache_clear()


def test_parse_uses_ollama_log_model_when_enabled(
    client: TestClient,
    auth_headers: dict[str, str],
    monkeypatch,
) -> None:
    monkeypatch.setenv("OLLAMA_ENABLED", "true")
    monkeypatch.setenv("AI_CLOUD_SUGGESTIONS_ENABLED", "false")
    monkeypatch.setenv("OLLAMA_LOG_MODEL", "qwen2.5-coder:14b")
    from app.config import get_settings

    get_settings.cache_clear()
    try:
        fake_payload = {
            "fields": [
                {
                    "name": "retry",
                    "value": "3",
                    "confidence": "high",
                    "evidence": "retry=3",
                }
            ],
            "attrs_suggestions": {"retry": "3"},
            "summary": "Parsed via mock Ollama",
        }

        with patch(
            "app.services.ai_providers.OllamaSuggestionProvider.chat_json",
            return_value=fake_payload,
        ):
            with patch(
                "app.monitor.services.ai_log_assist._log_ollama_client"
            ) as mocked_client_factory:
                mock_client = MagicMock()
                mock_client.model = "qwen2.5-coder:14b"
                mocked_client_factory.return_value = mock_client
                # OllamaSuggestionProvider uses client.chat_json via wrapper —
                # patch at facade provider level already; also ensure entitlement.
                with patch(
                    "app.services.ai_facade.OllamaSuggestionProvider"
                ) as provider_cls:
                    instance = MagicMock()
                    instance.model = "qwen2.5-coder:14b"
                    instance.chat_json.return_value = fake_payload
                    provider_cls.return_value = instance

                    resp = client.post(
                        "/api/monitor/logs/ai/parse",
                        headers=auth_headers,
                        json={
                            "messages": ["Upstream timeout retry=3"],
                        },
                    )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["source"] == "ollama"
        assert body["model"] == "qwen2.5-coder:14b"
        assert any(f.get("name") == "retry" for f in body["fields"])
        assert body["safety"]["assist_only"] is True
    finally:
        get_settings.cache_clear()


def test_force_fallback_skips_ollama(
    client: TestClient,
    auth_headers: dict[str, str],
    monkeypatch,
) -> None:
    monkeypatch.setenv("OLLAMA_ENABLED", "true")
    from app.config import get_settings

    get_settings.cache_clear()
    try:
        with patch(
            "app.services.ai_facade.OllamaSuggestionProvider.chat_json"
        ) as chat:
            resp = client.post(
                "/api/monitor/logs/ai/suggest-filters",
                headers=auth_headers,
                json={
                    "messages": ["Authentication failure for principal=svc-9"],
                    "force_fallback": True,
                },
            )
            assert resp.status_code == 200, resp.text
            assert resp.json()["source"] == "rule_based_fallback"
            chat.assert_not_called()
    finally:
        get_settings.cache_clear()


def test_config_default_log_model(monkeypatch) -> None:
    monkeypatch.delenv("OLLAMA_LOG_MODEL", raising=False)
    from app.config import get_settings

    get_settings.cache_clear()
    try:
        settings = get_settings()
        assert settings.ollama_log_model == "qwen2.5-coder:14b"
    finally:
        get_settings.cache_clear()
