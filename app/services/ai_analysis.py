"""AI-assisted diagnostic analysis (local Ollama) with rule-based fallback.

Never invents metrics/logs/verification results. Never auto-executes remediation.
Analysis derived from SIMULATED diagnostics is clearly labeled.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from ..config import get_settings
from ..serialization import serialize_document
from . import diagnostics as diagnostics_service
from .ollama_client import OllamaClient, OllamaError

logger = logging.getLogger(__name__)

REQUIRED_ANALYSIS_KEYS = (
    "executive_summary",
    "observed_evidence",
    "potential_causes",
    "recommended_verification_steps",
    "suggested_remediation",
    "confidence",
    "uncertainty",
    "potential_dependency_impact",
)


class AnalysisError(Exception):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _evidence_label(diagnostic: dict[str, Any]) -> str:
    mode = str(diagnostic.get("execution_mode") or "").upper()
    if mode == "SIMULATED" or diagnostic.get("labels", {}).get("simulated"):
        return "SIMULATED"
    return "REAL"


def _as_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if isinstance(value, list):
        out: list[str] = []
        for item in value:
            if item is None:
                continue
            text = str(item).strip()
            if text:
                out.append(text)
        return out
    return [str(value)]


def _normalize_analysis_payload(
    raw: dict[str, Any],
    *,
    source: str,
    model: str | None,
    evidence_label: str,
    fallback_reason: str | None = None,
) -> dict[str, Any]:
    observations = _as_string_list(raw.get("observed_evidence"))
    hypotheses = _as_string_list(raw.get("potential_causes"))
    # Prefer explicit observations_vs_hypotheses when provided
    ovh = raw.get("observations_vs_hypotheses")
    if isinstance(ovh, dict):
        observations = _as_string_list(ovh.get("observations")) or observations
        hypotheses = _as_string_list(ovh.get("hypotheses")) or hypotheses

    confidence = str(raw.get("confidence") or "low").strip().lower()
    if confidence not in {"low", "medium", "high"}:
        confidence = "low"

    analysis = {
        "analysis_id": f"ana-{uuid.uuid4().hex[:12]}",
        "timestamp": _now(),
        "source": source,
        "model": model,
        "derived_from_simulated_data": evidence_label == "SIMULATED",
        "evidence_label": evidence_label,
        "executive_summary": str(raw.get("executive_summary") or "").strip()
        or "No executive summary produced.",
        "observed_evidence": observations,
        "potential_causes": hypotheses,
        "recommended_verification_steps": _as_string_list(
            raw.get("recommended_verification_steps")
        ),
        "suggested_remediation": _as_string_list(raw.get("suggested_remediation")),
        "confidence": confidence,
        "uncertainty": str(raw.get("uncertainty") or "").strip()
        or "Uncertainty not stated by analyzer.",
        "potential_dependency_impact": str(
            raw.get("potential_dependency_impact") or ""
        ).strip()
        or "No dependency impact commentary produced.",
        "observations_vs_hypotheses": {
            "observations": observations,
            "hypotheses": [
                f"[HYPOTHESIS] {item}" if not item.upper().startswith("[HYPOTHESIS]") else item
                for item in hypotheses
            ],
        },
        "safety": {
            "auto_remediation": False,
            "invented_metrics_forbidden": True,
            "never_claims_verification_completed": True,
        },
        "labels": {
            "banner": (
                "AI ANALYSIS DERIVED FROM SIMULATED DIAGNOSTIC DATA — NOT REAL TELEMETRY"
                if evidence_label == "SIMULATED"
                else "AI ANALYSIS DERIVED FROM PROVIDED DIAGNOSTIC EVIDENCE"
            )
        },
    }
    if fallback_reason:
        analysis["fallback_reason"] = fallback_reason
    return analysis


def build_rule_based_fallback(
    diagnostic: dict[str, Any],
    *,
    reason: str,
) -> dict[str, Any]:
    """Deterministic analysis using only fields present on the diagnostic record."""
    evidence_label = _evidence_label(diagnostic)
    checks = diagnostic.get("checks") or []
    component = diagnostic.get("component") or {}
    dep = diagnostic.get("dependency_context") or {}

    observed: list[str] = []
    for check in checks:
        if not isinstance(check, dict):
            continue
        observed.append(
            "Observed check "
            f"{check.get('check_id')}={check.get('value')} "
            f"(status={check.get('status')}, data_source={check.get('data_source')}, "
            f"synthetic={check.get('synthetic')})"
        )
    observed.append(
        f"Component {component.get('component_id')} "
        f"type={component.get('component_type')} "
        f"env={component.get('environment')} status={component.get('status')}"
    )
    observed.append(
        f"Diagnostic execution_mode={diagnostic.get('execution_mode')} "
        f"evidence_label={evidence_label}"
    )
    up_n = len(dep.get("upstream_direct") or [])
    down_n = len(dep.get("downstream_direct") or [])
    observed.append(
        f"Dependency context reports {up_n} direct upstream and {down_n} direct downstream links"
    )

    warning_checks = [
        c for c in checks if isinstance(c, dict) and c.get("status") not in {"ok", None}
    ]
    hypotheses: list[str] = []
    if warning_checks:
        hypotheses.append(
            "[HYPOTHESIS] One or more synthetic checks are non-ok; investigate those "
            "metrics first after confirming with real telemetry (not yet collected)."
        )
    else:
        hypotheses.append(
            "[HYPOTHESIS] No non-ok checks in the provided diagnostic; residual risk "
            "may still exist outside this simulated evidence set."
        )
    if down_n:
        hypotheses.append(
            "[HYPOTHESIS] Downstream dependants could be potentially affected if this "
            "component later becomes unavailable — impact is hypothetical only."
        )

    verification = [
        "Manually confirm the component is the intended target in CMDB inventory.",
        "Review relationship records for upstream/downstream context (no automatic probe).",
        "If live diagnostics are later approved, collect real CPU/memory/disk/service evidence "
        "before treating synthetic values as operational truth.",
    ]
    remediation = [
        "Do not execute automated remediation from this analysis.",
        "If synthetic warnings appear, plan a verified change window after real evidence is gathered.",
        "Update CMDB notes only after human review of actual findings.",
    ]

    summary = (
        f"Rule-based fallback analysis for {component.get('component_id')} "
        f"(profile={diagnostic.get('profile_name')}). "
        f"Evidence is labeled {evidence_label}. Fallback reason: {reason}."
    )

    raw = {
        "executive_summary": summary,
        "observed_evidence": observed,
        "potential_causes": hypotheses,
        "recommended_verification_steps": verification,
        "suggested_remediation": remediation,
        "confidence": "low",
        "uncertainty": (
            "This fallback does not call Ollama and cannot infer beyond the provided "
            "diagnostic fields. Synthetic metrics must not be treated as live telemetry."
        ),
        "potential_dependency_impact": (
            f"Based only on stored relationships: {down_n} direct downstream "
            f"and {up_n} direct upstream components are related. This does not mean "
            "any dependant is currently down."
        ),
    }
    return _normalize_analysis_payload(
        raw,
        source="rule_based_fallback",
        model=None,
        evidence_label=evidence_label,
        fallback_reason=reason,
    )


def _build_prompt_messages(diagnostic: dict[str, Any]) -> list[dict[str, str]]:
    evidence_label = _evidence_label(diagnostic)
    system = (
        "You are an infrastructure diagnostic analyst for SVRMON24. "
        "Respond with a single JSON object only. "
        "Use ONLY the provided diagnostic evidence. "
        "Never invent metrics, logs, packet captures, or verification results. "
        "Never instruct automated remediation execution. "
        "Clearly separate observations (from provided evidence) from hypotheses. "
        f"Evidence label for this run is {evidence_label}. "
        "If evidence is SIMULATED, say so explicitly and do not treat values as live telemetry. "
        "Required keys: executive_summary (string), observed_evidence (array of strings), "
        "potential_causes (array of strings; hypotheses), "
        "recommended_verification_steps (array of strings; future manual checks only), "
        "suggested_remediation (array of strings; suggestions only, not executed), "
        "confidence (low|medium|high), uncertainty (string), "
        "potential_dependency_impact (string), "
        "observations_vs_hypotheses (object with observations and hypotheses arrays)."
    )
    # Pass structured inputs — no fabricated extras
    user_payload = {
        "diagnostic_output": {
            "diagnostic_id": diagnostic.get("diagnostic_id"),
            "execution_mode": diagnostic.get("execution_mode"),
            "profile_name": diagnostic.get("profile_name"),
            "checks": diagnostic.get("checks"),
            "summary": diagnostic.get("summary"),
            "labels": diagnostic.get("labels"),
        },
        "component_configuration": diagnostic.get("component"),
        "relevant_dependency_paths": diagnostic.get("dependency_context"),
        "evidence_label": evidence_label,
    }
    import json

    user = (
        "Analyze the following diagnostic package and return the required JSON object.\n"
        + json.dumps(user_payload, default=str)
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def _validate_model_analysis(raw: dict[str, Any]) -> None:
    missing = [key for key in REQUIRED_ANALYSIS_KEYS if key not in raw]
    if missing:
        raise OllamaError(
            f"Ollama JSON missing required keys: {', '.join(missing)}",
            kind="malformed",
        )


def analyze_with_ollama(
    diagnostic: dict[str, Any],
    *,
    client: OllamaClient | None = None,
) -> dict[str, Any]:
    """Call Ollama; raise OllamaError on failure (caller may fallback)."""
    settings = get_settings()
    ollama = client or OllamaClient.from_settings(settings)
    evidence_label = _evidence_label(diagnostic)
    raw = ollama.chat_json(_build_prompt_messages(diagnostic))
    _validate_model_analysis(raw)
    return _normalize_analysis_payload(
        raw,
        source="ollama",
        model=ollama.model,
        evidence_label=evidence_label,
    )


def analyze_diagnostic(
    diagnostic_id: str,
    *,
    force_fallback: bool = False,
    client: OllamaClient | None = None,
) -> dict[str, Any]:
    """Produce analysis, persist onto the diagnostic record, return updated record."""
    diagnostic = diagnostics_service.get_diagnostic(diagnostic_id)
    if diagnostic is None:
        raise AnalysisError(f"Diagnostic '{diagnostic_id}' not found", status_code=404)

    analysis: dict[str, Any]
    if force_fallback:
        analysis = build_rule_based_fallback(
            diagnostic, reason="forced_fallback_for_tests_or_operator_request"
        )
    else:
        try:
            analysis = analyze_with_ollama(diagnostic, client=client)
        except OllamaError as exc:
            logger.warning(
                "ollama_analysis_fallback diagnostic_id=%s kind=%s detail=%s",
                diagnostic_id,
                exc.kind,
                exc.message,
            )
            analysis = build_rule_based_fallback(
                diagnostic,
                reason=f"ollama_{exc.kind}: {exc.message}",
            )

    updated = diagnostics_service.attach_ai_analysis(diagnostic_id, analysis)
    return updated
