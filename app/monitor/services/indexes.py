"""Idempotent indexes for Monitoring collections (monitor DB only)."""

from __future__ import annotations

from typing import Any

from pymongo import ASCENDING, DESCENDING, TEXT
from pymongo.database import Database

from ...db import require_monitor_database
from .. import MONITOR_COLLECTIONS

FILE_TARGETS_COLLECTION = "file_watch_targets"
FILE_EVENTS_COLLECTION = "file_version_events"
MONITOR_TARGETS_COLLECTION = "monitor_targets"
METRIC_SAMPLES_COLLECTION = "metric_samples"
LOG_STREAMS_COLLECTION = "log_streams"
LOG_EVENTS_COLLECTION = "log_events"
SIMULATE_TICKS_COLLECTION = "monitor_simulate_ticks"
ALERT_RULES_COLLECTION = "alert_rules"
ALERT_INSTANCES_COLLECTION = "alert_instances"
DIAGNOSTIC_HISTORY_COLLECTION = "diagnostic_history"
MONITOR_CHECKS_COLLECTION = "monitor_checks"
MONITOR_CHECK_RESULTS_COLLECTION = "monitor_check_results"
LOG_INGEST_KEYS_COLLECTION = "log_ingest_keys"
SYSLOG_SOURCES_COLLECTION = "syslog_sources"
LOG_INGEST_DAILY_COLLECTION = "monitor_log_ingest_daily"
MONITOR_AGENTS_COLLECTION = "monitor_agents"
MONITOR_AGENT_ENROLLMENTS_COLLECTION = "monitor_agent_enrollments"
MONITOR_INGEST_CURSORS_COLLECTION = "monitor_ingest_cursors"


def ensure_monitor_indexes(db: Database | None = None) -> dict[str, Any]:
    """Create Monitoring collection indexes. Safe to call repeatedly."""
    handle = db if db is not None else require_monitor_database()
    created: dict[str, list[str]] = {}

    file_targets = handle[FILE_TARGETS_COLLECTION]
    created[FILE_TARGETS_COLLECTION] = [
        str(
            file_targets.create_index(
                [("tenant_id", ASCENDING), ("watch_id", ASCENDING)],
                unique=True,
                name="tenant_watch_id_unique",
            )
        ),
        str(
            file_targets.create_index(
                [("tenant_id", ASCENDING), ("path", ASCENDING)],
                name="tenant_path_idx",
            )
        ),
        str(
            file_targets.create_index(
                [("tenant_id", ASCENDING)], name="tenant_id_idx"
            )
        ),
        str(
            file_targets.create_index(
                [
                    ("tenant_id", ASCENDING),
                    ("watch_mode", ASCENDING),
                    ("status", ASCENDING),
                ],
                name="tenant_watch_mode_status_idx",
            )
        ),
        str(
            file_targets.create_index(
                [("tenant_id", ASCENDING), ("agent_id", ASCENDING)],
                name="tenant_agent_id_idx",
            )
        ),
    ]

    file_events = handle[FILE_EVENTS_COLLECTION]
    created[FILE_EVENTS_COLLECTION] = [
        str(
            file_events.create_index(
                [("tenant_id", ASCENDING), ("event_id", ASCENDING)],
                unique=True,
                name="tenant_event_id_unique",
            )
        ),
        str(
            file_events.create_index(
                [
                    ("tenant_id", ASCENDING),
                    ("watch_id", ASCENDING),
                    ("version", ASCENDING),
                ],
                name="tenant_watch_version_idx",
            )
        ),
        str(
            file_events.create_index(
                [("tenant_id", ASCENDING), ("changed_at", ASCENDING)],
                name="tenant_changed_at_idx",
            )
        ),
        str(
            file_events.create_index(
                [("tenant_id", ASCENDING)], name="tenant_id_idx"
            )
        ),
    ]

    monitor_targets = handle[MONITOR_TARGETS_COLLECTION]
    created[MONITOR_TARGETS_COLLECTION] = [
        str(
            monitor_targets.create_index(
                [("tenant_id", ASCENDING), ("target_id", ASCENDING)],
                unique=True,
                name="tenant_target_id_unique",
            )
        ),
        str(
            monitor_targets.create_index(
                [("tenant_id", ASCENDING), ("component_id", ASCENDING)],
                unique=True,
                name="tenant_component_id_unique",
            )
        ),
        str(
            monitor_targets.create_index(
                [
                    ("tenant_id", ASCENDING),
                    ("domain", ASCENDING),
                    ("status", ASCENDING),
                ],
                name="tenant_domain_status_idx",
            )
        ),
        str(
            monitor_targets.create_index(
                [
                    ("tenant_id", ASCENDING),
                    ("collect_mode", ASCENDING),
                    ("target_kind", ASCENDING),
                ],
                name="tenant_collect_kind_idx",
            )
        ),
        str(
            monitor_targets.create_index(
                [("tenant_id", ASCENDING), ("os_family", ASCENDING)],
                name="tenant_os_family_idx",
            )
        ),
    ]

    samples = handle[METRIC_SAMPLES_COLLECTION]
    created[METRIC_SAMPLES_COLLECTION] = [
        str(
            samples.create_index(
                [("tenant_id", ASCENDING), ("sample_id", ASCENDING)],
                unique=True,
                name="tenant_sample_id_unique",
            )
        ),
        str(
            samples.create_index(
                [
                    ("tenant_id", ASCENDING),
                    ("target_id", ASCENDING),
                    ("observed_at", ASCENDING),
                ],
                name="tenant_target_observed_idx",
            )
        ),
        str(
            samples.create_index(
                [
                    ("tenant_id", ASCENDING),
                    ("component_id", ASCENDING),
                    ("metric_name", ASCENDING),
                ],
                name="tenant_component_metric_idx",
            )
        ),
    ]

    streams = handle[LOG_STREAMS_COLLECTION]
    created[LOG_STREAMS_COLLECTION] = [
        str(
            streams.create_index(
                [("tenant_id", ASCENDING), ("stream_id", ASCENDING)],
                unique=True,
                name="tenant_stream_id_unique",
            )
        ),
        str(
            streams.create_index(
                [("tenant_id", ASCENDING), ("component_id", ASCENDING)],
                name="tenant_stream_component_idx",
            )
        ),
        str(
            streams.create_index(
                [
                    ("tenant_id", ASCENDING),
                    ("source_kind", ASCENDING),
                    ("status", ASCENDING),
                ],
                name="tenant_stream_kind_status_idx",
            )
        ),
    ]

    events = handle[LOG_EVENTS_COLLECTION]
    created[LOG_EVENTS_COLLECTION] = [
        str(
            events.create_index(
                [("tenant_id", ASCENDING), ("event_id", ASCENDING)],
                unique=True,
                name="tenant_log_event_id_unique",
            )
        ),
        str(
            events.create_index(
                [
                    ("tenant_id", ASCENDING),
                    ("stream_id", ASCENDING),
                    ("observed_at", DESCENDING),
                ],
                name="tenant_stream_observed_idx",
            )
        ),
        str(
            events.create_index(
                [
                    ("tenant_id", ASCENDING),
                    ("component_id", ASCENDING),
                    ("severity", ASCENDING),
                    ("observed_at", DESCENDING),
                ],
                name="tenant_component_severity_idx",
            )
        ),
        str(
            events.create_index(
                [("tenant_id", ASCENDING), ("observed_at", ASCENDING)],
                name="tenant_log_observed_asc_idx",
            )
        ),
        str(
            events.create_index(
                [("message", TEXT)],
                name="log_message_text_idx",
                default_language="english",
            )
        ),
    ]

    ticks = handle[SIMULATE_TICKS_COLLECTION]
    created[SIMULATE_TICKS_COLLECTION] = [
        str(
            ticks.create_index(
                [("tenant_id", ASCENDING), ("day", ASCENDING)],
                unique=True,
                name="tenant_simulate_day_unique",
            )
        ),
    ]

    rules = handle[ALERT_RULES_COLLECTION]
    created[ALERT_RULES_COLLECTION] = [
        str(
            rules.create_index(
                [("tenant_id", ASCENDING), ("rule_id", ASCENDING)],
                unique=True,
                name="tenant_rule_id_unique",
            )
        ),
        str(
            rules.create_index(
                [("tenant_id", ASCENDING), ("enabled", ASCENDING)],
                name="tenant_rule_enabled_idx",
            )
        ),
        str(
            rules.create_index(
                [("tenant_id", ASCENDING), ("name", ASCENDING)],
                name="tenant_rule_name_idx",
            )
        ),
    ]

    instances = handle[ALERT_INSTANCES_COLLECTION]
    created[ALERT_INSTANCES_COLLECTION] = [
        str(
            instances.create_index(
                [("tenant_id", ASCENDING), ("alert_id", ASCENDING)],
                unique=True,
                name="tenant_alert_id_unique",
            )
        ),
        str(
            instances.create_index(
                [
                    ("tenant_id", ASCENDING),
                    ("fingerprint", ASCENDING),
                    ("status", ASCENDING),
                ],
                name="tenant_alert_fingerprint_status_idx",
            )
        ),
        str(
            instances.create_index(
                [
                    ("tenant_id", ASCENDING),
                    ("status", ASCENDING),
                    ("fired_at", DESCENDING),
                ],
                name="tenant_alert_status_fired_idx",
            )
        ),
        str(
            instances.create_index(
                [("tenant_id", ASCENDING), ("rule_id", ASCENDING)],
                name="tenant_alert_rule_idx",
            )
        ),
        str(
            instances.create_index(
                [("tenant_id", ASCENDING), ("component_id", ASCENDING)],
                name="tenant_alert_component_idx",
            )
        ),
    ]

    diagnostics = handle[DIAGNOSTIC_HISTORY_COLLECTION]
    created[DIAGNOSTIC_HISTORY_COLLECTION] = [
        str(
            diagnostics.create_index(
                [("tenant_id", ASCENDING), ("diagnostic_id", ASCENDING)],
                unique=True,
                name="tenant_diagnostic_id_unique",
            )
        ),
        str(
            diagnostics.create_index(
                [("tenant_id", ASCENDING), ("timestamp", DESCENDING)],
                name="tenant_diag_timestamp_idx",
            )
        ),
        str(
            diagnostics.create_index(
                [("tenant_id", ASCENDING), ("component_id", ASCENDING)],
                name="tenant_diag_component_idx",
            )
        ),
        str(
            diagnostics.create_index(
                [("tenant_id", ASCENDING), ("profile_name", ASCENDING)],
                name="tenant_diag_profile_idx",
            )
        ),
    ]

    checks = handle[MONITOR_CHECKS_COLLECTION]
    created[MONITOR_CHECKS_COLLECTION] = [
        str(
            checks.create_index(
                [("tenant_id", ASCENDING), ("check_id", ASCENDING)],
                unique=True,
                name="tenant_check_id_unique",
            )
        ),
        str(
            checks.create_index(
                [("tenant_id", ASCENDING), ("target_id", ASCENDING)],
                name="tenant_check_target_idx",
            )
        ),
        str(
            checks.create_index(
                [
                    ("tenant_id", ASCENDING),
                    ("enabled", ASCENDING),
                    ("protocol", ASCENDING),
                ],
                name="tenant_check_enabled_protocol_idx",
            )
        ),
        str(
            checks.create_index(
                [("tenant_id", ASCENDING), ("last_run_at", ASCENDING)],
                name="tenant_check_last_run_idx",
            )
        ),
    ]

    check_results = handle[MONITOR_CHECK_RESULTS_COLLECTION]
    created[MONITOR_CHECK_RESULTS_COLLECTION] = [
        str(
            check_results.create_index(
                [("tenant_id", ASCENDING), ("result_id", ASCENDING)],
                unique=True,
                name="tenant_check_result_id_unique",
            )
        ),
        str(
            check_results.create_index(
                [
                    ("tenant_id", ASCENDING),
                    ("check_id", ASCENDING),
                    ("observed_at", DESCENDING),
                ],
                name="tenant_check_observed_idx",
            )
        ),
    ]

    ingest_keys = handle[LOG_INGEST_KEYS_COLLECTION]
    created[LOG_INGEST_KEYS_COLLECTION] = [
        str(
            ingest_keys.create_index(
                [("tenant_id", ASCENDING), ("key_id", ASCENDING)],
                unique=True,
                name="tenant_ingest_key_id_unique",
            )
        ),
        str(
            ingest_keys.create_index(
                [("key_hash", ASCENDING)],
                unique=True,
                name="ingest_key_hash_unique",
            )
        ),
        str(
            ingest_keys.create_index(
                [("tenant_id", ASCENDING), ("status", ASCENDING)],
                name="tenant_ingest_key_status_idx",
            )
        ),
    ]

    syslog_sources = handle[SYSLOG_SOURCES_COLLECTION]
    created[SYSLOG_SOURCES_COLLECTION] = [
        str(
            syslog_sources.create_index(
                [("tenant_id", ASCENDING), ("source_id", ASCENDING)],
                unique=True,
                name="tenant_syslog_source_id_unique",
            )
        ),
        str(
            syslog_sources.create_index(
                [("tenant_id", ASCENDING), ("source_ip", ASCENDING)],
                unique=True,
                name="tenant_syslog_source_ip_unique",
            )
        ),
        str(
            syslog_sources.create_index(
                [("status", ASCENDING), ("source_ip", ASCENDING)],
                name="syslog_status_ip_idx",
            )
        ),
    ]

    ingest_daily = handle[LOG_INGEST_DAILY_COLLECTION]
    created[LOG_INGEST_DAILY_COLLECTION] = [
        str(
            ingest_daily.create_index(
                [("tenant_id", ASCENDING), ("day", ASCENDING)],
                unique=True,
                name="tenant_log_ingest_day_unique",
            )
        ),
    ]

    agents = handle[MONITOR_AGENTS_COLLECTION]
    created[MONITOR_AGENTS_COLLECTION] = [
        str(
            agents.create_index(
                [("tenant_id", ASCENDING), ("agent_id", ASCENDING)],
                unique=True,
                name="tenant_agent_id_unique",
            )
        ),
        str(
            agents.create_index(
                [("token_hash", ASCENDING)],
                unique=True,
                name="agent_token_hash_unique",
            )
        ),
        str(
            agents.create_index(
                [("tenant_id", ASCENDING), ("status", ASCENDING)],
                name="tenant_agent_status_idx",
            )
        ),
        str(
            agents.create_index(
                [("tenant_id", ASCENDING), ("last_seen_at", DESCENDING)],
                name="tenant_agent_last_seen_idx",
            )
        ),
    ]

    enrollments = handle[MONITOR_AGENT_ENROLLMENTS_COLLECTION]
    created[MONITOR_AGENT_ENROLLMENTS_COLLECTION] = [
        str(
            enrollments.create_index(
                [("tenant_id", ASCENDING), ("enrollment_id", ASCENDING)],
                unique=True,
                name="tenant_enrollment_id_unique",
            )
        ),
        str(
            enrollments.create_index(
                [("code_hash", ASCENDING)],
                unique=True,
                name="enrollment_code_hash_unique",
            )
        ),
        str(
            enrollments.create_index(
                [("tenant_id", ASCENDING), ("status", ASCENDING), ("expires_at", ASCENDING)],
                name="tenant_enrollment_status_expiry_idx",
            )
        ),
    ]

    cursors = handle[MONITOR_INGEST_CURSORS_COLLECTION]
    created[MONITOR_INGEST_CURSORS_COLLECTION] = [
        str(
            cursors.create_index(
                [
                    ("tenant_id", ASCENDING),
                    ("agent_id", ASCENDING),
                    ("channel", ASCENDING),
                    ("key", ASCENDING),
                ],
                unique=True,
                name="tenant_agent_channel_key_unique",
            )
        ),
        str(
            cursors.create_index(
                [("tenant_id", ASCENDING), ("agent_id", ASCENDING)],
                name="tenant_agent_cursor_idx",
            )
        ),
    ]

    return {"ok": True, "indexes": created, "collections": list(MONITOR_COLLECTIONS)}
