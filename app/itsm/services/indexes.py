"""Idempotent indexes for ITSM collections (ITSM DB only)."""

from __future__ import annotations

from typing import Any

from pymongo import ASCENDING, DESCENDING
from pymongo.database import Database

from ...db import require_itsm_database
from .. import ITSM_COLLECTIONS

INCIDENTS = "itsm_incidents"
CHANGES = "itsm_changes"
PROBLEMS = "itsm_problems"
ACTIVITIES = "itsm_ticket_activities"
COUNTERS = "itsm_counters"
APPROVALS = "itsm_approvals"
WORKFLOWS = "itsm_workflows"
WORKFLOW_EXECUTIONS = "itsm_workflow_executions"
SLA_POLICIES = "itsm_sla_policies"
SLA_TRACKING = "itsm_sla_tracking"
KNOWLEDGE_ARTICLES = "itsm_knowledge_articles"
NOTIFICATIONS = "itsm_notifications"
NOTIFICATION_CHANNEL_SETTINGS = "itsm_notification_channel_settings"
NOTIFICATION_DELIVERIES = "itsm_notification_deliveries"
JOB_LEASES = "itsm_job_leases"
JOB_RUNS = "itsm_job_runs"
REPORT_DEFINITIONS = "itsm_report_definitions"
REPORT_SCHEDULES = "itsm_report_schedules"
REPORT_SCHEDULE_RUNS = "itsm_report_schedule_runs"
ASSIGNMENT_GROUPS = "itsm_assignment_groups"
ATTACHMENTS = "itsm_ticket_attachments"


def _ticket_indexes(coll, *, id_field: str, prefix: str) -> list[str]:
    names = [
        coll.create_index(
            [("tenant_id", ASCENDING), (id_field, ASCENDING)],
            unique=True,
            name=f"tenant_{prefix}_id_unique",
        ),
        coll.create_index(
            [("tenant_id", ASCENDING), ("number", ASCENDING)],
            unique=True,
            name=f"tenant_{prefix}_number_unique",
        ),
        coll.create_index(
            [("tenant_id", ASCENDING), ("status", ASCENDING), ("updated_at", DESCENDING)],
            name=f"tenant_{prefix}_status_updated_idx",
        ),
        coll.create_index(
            [
                ("tenant_id", ASCENDING),
                ("assignee_user_id", ASCENDING),
                ("status", ASCENDING),
            ],
            name=f"tenant_{prefix}_assignee_status_idx",
        ),
        coll.create_index(
            [("tenant_id", ASCENDING), ("ci_links.component_id", ASCENDING)],
            name=f"tenant_{prefix}_ci_component_idx",
        ),
        coll.create_index([("tenant_id", ASCENDING)], name=f"tenant_{prefix}_tenant_id_idx"),
    ]
    return [str(n) for n in names]


def ensure_itsm_indexes(db: Database | None = None) -> dict[str, Any]:
    """Create ITSM collection indexes. Safe to call repeatedly."""
    handle = db if db is not None else require_itsm_database()
    created: dict[str, list[str]] = {}

    created[INCIDENTS] = _ticket_indexes(
        handle[INCIDENTS], id_field="incident_id", prefix="incident"
    )
    created[CHANGES] = _ticket_indexes(
        handle[CHANGES], id_field="change_id", prefix="change"
    )
    created[PROBLEMS] = _ticket_indexes(
        handle[PROBLEMS], id_field="problem_id", prefix="problem"
    )

    act = handle[ACTIVITIES]
    names = [
        act.create_index(
            [("tenant_id", ASCENDING), ("activity_id", ASCENDING)],
            unique=True,
            name="tenant_activity_id_unique",
        ),
        act.create_index(
            [
                ("tenant_id", ASCENDING),
                ("ticket_type", ASCENDING),
                ("ticket_id", ASCENDING),
                ("created_at", DESCENDING),
            ],
            name="tenant_ticket_created_idx",
        ),
        act.create_index([("tenant_id", ASCENDING)], name="tenant_id_idx"),
    ]
    created[ACTIVITIES] = [str(n) for n in names]

    ctr = handle[COUNTERS]
    names = [
        ctr.create_index(
            [("tenant_id", ASCENDING), ("counter_key", ASCENDING)],
            unique=True,
            name="tenant_counter_key_unique",
        ),
    ]
    created[COUNTERS] = [str(n) for n in names]

    apr = handle[APPROVALS]
    names = [
        apr.create_index(
            [("tenant_id", ASCENDING), ("approval_id", ASCENDING)],
            unique=True,
            name="tenant_approval_id_unique",
        ),
        apr.create_index(
            [
                ("tenant_id", ASCENDING),
                ("status", ASCENDING),
                ("updated_at", DESCENDING),
            ],
            name="tenant_approval_status_updated_idx",
        ),
        apr.create_index(
            [
                ("tenant_id", ASCENDING),
                ("ticket_type", ASCENDING),
                ("ticket_id", ASCENDING),
            ],
            name="tenant_approval_ticket_idx",
        ),
        apr.create_index(
            [("tenant_id", ASCENDING), ("workflow_execution_id", ASCENDING)],
            name="tenant_approval_execution_idx",
        ),
        apr.create_index([("tenant_id", ASCENDING)], name="tenant_approval_tenant_id_idx"),
    ]
    created[APPROVALS] = [str(n) for n in names]

    wf = handle[WORKFLOWS]
    names = [
        wf.create_index(
            [("tenant_id", ASCENDING), ("workflow_id", ASCENDING)],
            unique=True,
            name="tenant_workflow_id_unique",
        ),
        wf.create_index(
            [
                ("tenant_id", ASCENDING),
                ("active", ASCENDING),
                ("applies_to", ASCENDING),
            ],
            name="tenant_workflow_active_applies_idx",
        ),
        wf.create_index(
            [("tenant_id", ASCENDING), ("updated_at", DESCENDING)],
            name="tenant_workflow_updated_idx",
        ),
        wf.create_index([("tenant_id", ASCENDING)], name="tenant_workflow_tenant_id_idx"),
    ]
    created[WORKFLOWS] = [str(n) for n in names]

    wx = handle[WORKFLOW_EXECUTIONS]
    names = [
        wx.create_index(
            [("tenant_id", ASCENDING), ("execution_id", ASCENDING)],
            unique=True,
            name="tenant_execution_id_unique",
        ),
        wx.create_index(
            [
                ("tenant_id", ASCENDING),
                ("workflow_id", ASCENDING),
                ("updated_at", DESCENDING),
            ],
            name="tenant_execution_workflow_updated_idx",
        ),
        wx.create_index(
            [
                ("tenant_id", ASCENDING),
                ("ticket_type", ASCENDING),
                ("ticket_id", ASCENDING),
            ],
            name="tenant_execution_ticket_idx",
        ),
        wx.create_index(
            [
                ("tenant_id", ASCENDING),
                ("status", ASCENDING),
                ("updated_at", DESCENDING),
            ],
            name="tenant_execution_status_updated_idx",
        ),
        wx.create_index(
            [("tenant_id", ASCENDING)], name="tenant_execution_tenant_id_idx"
        ),
    ]
    created[WORKFLOW_EXECUTIONS] = [str(n) for n in names]

    sla_p = handle[SLA_POLICIES]
    names = [
        sla_p.create_index(
            [("tenant_id", ASCENDING), ("policy_id", ASCENDING)],
            unique=True,
            name="tenant_sla_policy_id_unique",
        ),
        sla_p.create_index(
            [
                ("tenant_id", ASCENDING),
                ("active", ASCENDING),
                ("applies_to", ASCENDING),
            ],
            name="tenant_sla_policy_active_applies_idx",
        ),
        sla_p.create_index(
            [("tenant_id", ASCENDING), ("updated_at", DESCENDING)],
            name="tenant_sla_policy_updated_idx",
        ),
        sla_p.create_index(
            [("tenant_id", ASCENDING)], name="tenant_sla_policy_tenant_id_idx"
        ),
    ]
    created[SLA_POLICIES] = [str(n) for n in names]

    sla_t = handle[SLA_TRACKING]
    names = [
        sla_t.create_index(
            [("tenant_id", ASCENDING), ("tracking_id", ASCENDING)],
            unique=True,
            name="tenant_sla_tracking_id_unique",
        ),
        sla_t.create_index(
            [
                ("tenant_id", ASCENDING),
                ("ticket_type", ASCENDING),
                ("ticket_id", ASCENDING),
                ("status", ASCENDING),
            ],
            name="tenant_sla_tracking_ticket_status_idx",
        ),
        sla_t.create_index(
            [
                ("tenant_id", ASCENDING),
                ("status", ASCENDING),
                ("due_at", ASCENDING),
            ],
            name="tenant_sla_tracking_status_due_idx",
        ),
        sla_t.create_index(
            [("tenant_id", ASCENDING), ("policy_id", ASCENDING)],
            name="tenant_sla_tracking_policy_idx",
        ),
        sla_t.create_index(
            [("tenant_id", ASCENDING)], name="tenant_sla_tracking_tenant_id_idx"
        ),
    ]
    created[SLA_TRACKING] = [str(n) for n in names]

    kb = handle[KNOWLEDGE_ARTICLES]
    names = [
        kb.create_index(
            [("tenant_id", ASCENDING), ("article_id", ASCENDING)],
            unique=True,
            name="tenant_knowledge_article_id_unique",
        ),
        kb.create_index(
            [("tenant_id", ASCENDING), ("number", ASCENDING)],
            unique=True,
            name="tenant_knowledge_number_unique",
        ),
        kb.create_index(
            [
                ("tenant_id", ASCENDING),
                ("status", ASCENDING),
                ("updated_at", DESCENDING),
            ],
            name="tenant_knowledge_status_updated_idx",
        ),
        kb.create_index(
            [("tenant_id", ASCENDING), ("category", ASCENDING)],
            name="tenant_knowledge_category_idx",
        ),
        kb.create_index(
            [("tenant_id", ASCENDING), ("tags", ASCENDING)],
            name="tenant_knowledge_tags_idx",
        ),
        kb.create_index(
            [("tenant_id", ASCENDING), ("related_incident_ids", ASCENDING)],
            name="tenant_knowledge_related_incident_idx",
        ),
        kb.create_index(
            [("tenant_id", ASCENDING), ("related_problem_ids", ASCENDING)],
            name="tenant_knowledge_related_problem_idx",
        ),
        kb.create_index(
            [("tenant_id", ASCENDING), ("related_component_ids", ASCENDING)],
            name="tenant_knowledge_related_component_idx",
        ),
        kb.create_index(
            [("tenant_id", ASCENDING)], name="tenant_knowledge_tenant_id_idx"
        ),
    ]
    created[KNOWLEDGE_ARTICLES] = [str(n) for n in names]

    ntf = handle[NOTIFICATIONS]
    names = [
        ntf.create_index(
            [("tenant_id", ASCENDING), ("notification_id", ASCENDING)],
            unique=True,
            name="tenant_notification_id_unique",
        ),
        ntf.create_index(
            [
                ("tenant_id", ASCENDING),
                ("recipient_user_id", ASCENDING),
                ("status", ASCENDING),
                ("created_at", DESCENDING),
            ],
            name="tenant_notification_inbox_idx",
        ),
        ntf.create_index(
            [
                ("tenant_id", ASCENDING),
                ("recipient_user_id", ASCENDING),
                ("status", ASCENDING),
            ],
            name="tenant_notification_unread_idx",
        ),
        ntf.create_index(
            [
                ("tenant_id", ASCENDING),
                ("ticket_type", ASCENDING),
                ("ticket_id", ASCENDING),
            ],
            name="tenant_notification_ticket_idx",
        ),
        ntf.create_index(
            [("tenant_id", ASCENDING), ("event_type", ASCENDING)],
            name="tenant_notification_event_idx",
        ),
        ntf.create_index(
            [("tenant_id", ASCENDING)], name="tenant_notification_tenant_id_idx"
        ),
    ]
    created[NOTIFICATIONS] = [str(n) for n in names]

    ch = handle[NOTIFICATION_CHANNEL_SETTINGS]
    names = [
        ch.create_index(
            [("tenant_id", ASCENDING), ("channel", ASCENDING)],
            unique=True,
            name="tenant_channel_unique",
        ),
        ch.create_index(
            [("tenant_id", ASCENDING)], name="tenant_channel_settings_tenant_id_idx"
        ),
    ]
    created[NOTIFICATION_CHANNEL_SETTINGS] = [str(n) for n in names]

    dlv = handle[NOTIFICATION_DELIVERIES]
    names = [
        dlv.create_index(
            [("tenant_id", ASCENDING), ("delivery_id", ASCENDING)],
            unique=True,
            name="tenant_delivery_id_unique",
        ),
        dlv.create_index(
            [
                ("tenant_id", ASCENDING),
                ("channel", ASCENDING),
                ("status", ASCENDING),
                ("created_at", DESCENDING),
            ],
            name="tenant_delivery_channel_status_idx",
        ),
        dlv.create_index(
            [
                ("tenant_id", ASCENDING),
                ("notification_id", ASCENDING),
                ("created_at", DESCENDING),
            ],
            name="tenant_delivery_notification_idx",
        ),
        dlv.create_index(
            [
                ("tenant_id", ASCENDING),
                ("status", ASCENDING),
                ("next_retry_at", ASCENDING),
            ],
            name="tenant_delivery_retry_idx",
        ),
        dlv.create_index(
            [("tenant_id", ASCENDING)], name="tenant_delivery_tenant_id_idx"
        ),
    ]
    created[NOTIFICATION_DELIVERIES] = [str(n) for n in names]

    leases = handle[JOB_LEASES]
    names = [
        leases.create_index(
            [("job_name", ASCENDING)],
            unique=True,
            name="job_name_unique",
        ),
        leases.create_index(
            [("expires_at", ASCENDING)], name="job_lease_expires_idx"
        ),
    ]
    created[JOB_LEASES] = [str(n) for n in names]

    runs = handle[JOB_RUNS]
    names = [
        runs.create_index(
            [("run_id", ASCENDING)],
            unique=True,
            name="job_run_id_unique",
        ),
        runs.create_index(
            [("job_name", ASCENDING), ("created_at", DESCENDING)],
            name="job_run_name_created_idx",
        ),
    ]
    created[JOB_RUNS] = [str(n) for n in names]

    sch = handle[REPORT_SCHEDULES]
    names = [
        sch.create_index(
            [("tenant_id", ASCENDING), ("schedule_id", ASCENDING)],
            unique=True,
            name="tenant_report_schedule_id_unique",
        ),
        sch.create_index(
            [
                ("tenant_id", ASCENDING),
                ("active", ASCENDING),
                ("next_run_at", ASCENDING),
            ],
            name="tenant_report_schedule_due_idx",
        ),
        sch.create_index(
            [("tenant_id", ASCENDING), ("report_id", ASCENDING)],
            name="tenant_report_schedule_report_idx",
        ),
    ]
    created[REPORT_SCHEDULES] = [str(n) for n in names]

    sch_runs = handle[REPORT_SCHEDULE_RUNS]
    names = [
        sch_runs.create_index(
            [("tenant_id", ASCENDING), ("run_id", ASCENDING)],
            unique=True,
            name="tenant_report_schedule_run_id_unique",
        ),
        sch_runs.create_index(
            [
                ("tenant_id", ASCENDING),
                ("schedule_id", ASCENDING),
                ("created_at", DESCENDING),
            ],
            name="tenant_report_schedule_run_idx",
        ),
    ]
    created[REPORT_SCHEDULE_RUNS] = [str(n) for n in names]

    rpt = handle[REPORT_DEFINITIONS]
    names = [
        rpt.create_index(
            [("tenant_id", ASCENDING), ("report_id", ASCENDING)],
            unique=True,
            name="tenant_report_id_unique",
        ),
        rpt.create_index(
            [("tenant_id", ASCENDING), ("updated_at", DESCENDING)],
            name="tenant_report_updated_idx",
        ),
        rpt.create_index(
            [("tenant_id", ASCENDING), ("name", ASCENDING)],
            name="tenant_report_name_idx",
        ),
        rpt.create_index(
            [("tenant_id", ASCENDING)], name="tenant_report_tenant_id_idx"
        ),
    ]
    created[REPORT_DEFINITIONS] = [str(n) for n in names]

    groups = handle[ASSIGNMENT_GROUPS]
    names = [
        groups.create_index(
            [("tenant_id", ASCENDING), ("group_id", ASCENDING)],
            unique=True,
            name="tenant_assignment_group_id_unique",
        ),
        groups.create_index(
            [("tenant_id", ASCENDING), ("name_lower", ASCENDING)],
            unique=True,
            name="tenant_assignment_group_name_unique",
        ),
        groups.create_index(
            [("tenant_id", ASCENDING), ("active", ASCENDING), ("name_lower", ASCENDING)],
            name="tenant_assignment_group_active_name_idx",
        ),
        groups.create_index(
            [("tenant_id", ASCENDING)], name="tenant_assignment_group_tenant_id_idx"
        ),
    ]
    created[ASSIGNMENT_GROUPS] = [str(n) for n in names]

    atts = handle[ATTACHMENTS]
    names = [
        atts.create_index(
            [("tenant_id", ASCENDING), ("attachment_id", ASCENDING)],
            unique=True,
            name="tenant_attachment_id_unique",
        ),
        atts.create_index(
            [
                ("tenant_id", ASCENDING),
                ("ticket_type", ASCENDING),
                ("ticket_id", ASCENDING),
                ("created_at", DESCENDING),
            ],
            name="tenant_attachment_ticket_idx",
        ),
        atts.create_index(
            [("tenant_id", ASCENDING)], name="tenant_attachment_tenant_id_idx"
        ),
    ]
    created[ATTACHMENTS] = [str(n) for n in names]

    return {
        "ok": True,
        "database": handle.name,
        "collections": list(ITSM_COLLECTIONS),
        "indexes": created,
    }
