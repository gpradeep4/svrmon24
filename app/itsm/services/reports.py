"""Custom ITSM report definitions + run/export (ITSM DB only)."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from pymongo import DESCENDING
from pymongo.collection import Collection

from ...db import require_itsm_database
from ...serialization import serialize_document
from ...tenancy import merge_tenant_filter, require_tenant_id, stamp_tenant_id
from ..models.reports import (
    DEFAULT_TICKET_COLUMNS,
    REPORT_METRICS,
    ReportDefinitionCreate,
    ReportDefinitionUpdate,
    ReportFilters,
)
from . import dashboard as dashboard_service
from .indexes import (
    CHANGES,
    INCIDENTS,
    PROBLEMS,
    REPORT_DEFINITIONS,
    ensure_itsm_indexes,
)
from .report_io import dict_rows_to_table, render_csv_tables, render_xlsx_tables

MAX_TICKET_ROWS = 5000
ID_FIELDS = {
    "incident": "incident_id",
    "change": "change_id",
    "problem": "problem_id",
}
COLL_BY_TYPE = {
    "incident": INCIDENTS,
    "change": CHANGES,
    "problem": PROBLEMS,
}


class ReportError(Exception):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _coll() -> Collection:
    ensure_itsm_indexes()
    return require_itsm_database()[REPORT_DEFINITIONS]


def _new_report_id() -> str:
    return f"RPT-{uuid.uuid4().hex[:10].upper()}"


def _actor_fields(actor: dict[str, Any] | None) -> dict[str, str | None]:
    actor = actor or {}
    return {
        "user_id": actor.get("user_id") or actor.get("username"),
        "username": actor.get("username") or actor.get("user_id"),
    }


def _parse_date_bound(raw: str | None, *, end_of_day: bool = False) -> datetime | None:
    if not raw:
        return None
    text = str(raw).strip()
    if not text:
        return None
    try:
        if len(text) == 10 and text[4] == "-" and text[7] == "-":
            dt = datetime.fromisoformat(text).replace(tzinfo=timezone.utc)
            if end_of_day:
                dt = dt + timedelta(days=1) - timedelta(microseconds=1)
            return dt
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError as exc:
        raise ReportError(f"Invalid date '{raw}'") from exc


def _resolve_window(filters: ReportFilters | dict[str, Any]) -> tuple[datetime | None, datetime | None, int | None]:
    if isinstance(filters, dict):
        filters = ReportFilters.model_validate(filters)
    date_from = _parse_date_bound(filters.date_from, end_of_day=False)
    date_to = _parse_date_bound(filters.date_to, end_of_day=True)
    window_days = filters.window_days
    if date_from is not None or date_to is not None:
        return date_from, date_to, None
    if window_days is None:
        return None, None, None
    start = _now() - timedelta(days=int(window_days))
    return start, None, int(window_days)


def get_definition(report_id: str, *, tenant_id: str) -> dict[str, Any] | None:
    tid = require_tenant_id(tenant_id)
    doc = _coll().find_one({"tenant_id": tid, "report_id": report_id})
    return serialize_document(doc)


def list_definitions(
    *,
    tenant_id: str,
    q: str | None = None,
    page: int = 1,
    page_size: int = 50,
) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    page = max(1, int(page))
    page_size = min(max(1, int(page_size)), 200)
    clauses: list[dict[str, Any]] = []
    if q and q.strip():
        rx = {"$regex": q.strip(), "$options": "i"}
        clauses.append({"$or": [{"name": rx}, {"description": rx}, {"report_id": rx}]})
    query = {"$and": clauses} if clauses else None
    scoped = merge_tenant_filter(query, tid)
    coll = _coll()
    total = coll.count_documents(scoped)
    cursor = (
        coll.find(scoped)
        .sort([("updated_at", DESCENDING)])
        .skip((page - 1) * page_size)
        .limit(page_size)
    )
    items = [serialize_document(doc) for doc in cursor]
    return {
        "items": items,
        "count": len(items),
        "total": total,
        "page": page,
        "page_size": page_size,
        "tenant_id": tid,
    }


def create_definition(
    payload: ReportDefinitionCreate,
    *,
    tenant_id: str,
    actor: dict[str, Any] | None = None,
) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    now = _now()
    actor_info = _actor_fields(actor)
    doc = stamp_tenant_id(
        {
            "report_id": _new_report_id(),
            "name": payload.name,
            "description": payload.description,
            "metrics": list(payload.metrics),
            "filters": payload.filters.model_dump(),
            "columns": list(payload.columns),
            "created_at": now,
            "updated_at": now,
            "created_by": actor_info,
            "updated_by": actor_info,
        },
        tenant_id=tid,
    )
    _coll().insert_one(doc)
    return serialize_document(doc)  # type: ignore[return-value]


def update_definition(
    report_id: str,
    payload: ReportDefinitionUpdate,
    *,
    tenant_id: str,
    actor: dict[str, Any] | None = None,
) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    existing = _coll().find_one({"tenant_id": tid, "report_id": report_id})
    if existing is None:
        raise ReportError(f"Report '{report_id}' not found", status_code=404)
    updates = payload.model_dump(exclude_unset=True)
    if not updates:
        return serialize_document(existing)  # type: ignore[return-value]
    if "filters" in updates and updates["filters"] is not None:
        updates["filters"] = ReportFilters.model_validate(updates["filters"]).model_dump()
    updates["updated_at"] = _now()
    updates["updated_by"] = _actor_fields(actor)
    _coll().update_one(
        {"tenant_id": tid, "report_id": report_id},
        {"$set": updates},
    )
    refreshed = _coll().find_one({"tenant_id": tid, "report_id": report_id})
    return serialize_document(refreshed)  # type: ignore[return-value]


def delete_definition(report_id: str, *, tenant_id: str) -> None:
    tid = require_tenant_id(tenant_id)
    result = _coll().delete_one({"tenant_id": tid, "report_id": report_id})
    if result.deleted_count == 0:
        raise ReportError(f"Report '{report_id}' not found", status_code=404)


def _ticket_query(
    *,
    ticket_type: str,
    filters: ReportFilters,
    start: datetime | None,
    end: datetime | None,
) -> dict[str, Any]:
    clauses: list[dict[str, Any]] = []
    if filters.statuses:
        clauses.append({"status": {"$in": list(filters.statuses)}})
    if filters.priorities:
        clauses.append({"priority": {"$in": list(filters.priorities)}})
    if filters.category:
        clauses.append({"category": filters.category})
    if filters.service_tier:
        clauses.append({"service_tier": filters.service_tier})
    if start is not None or end is not None:
        created: dict[str, Any] = {}
        if start is not None:
            created["$gte"] = start
        if end is not None:
            created["$lte"] = end
        clauses.append({"created_at": created})
    return {"$and": clauses} if clauses else {}


def _project_ticket_row(
    doc: dict[str, Any],
    *,
    ticket_type: str,
    columns: list[str],
) -> dict[str, Any]:
    id_field = ID_FIELDS[ticket_type]
    base = {
        "ticket_type": ticket_type,
        "ticket_id": doc.get(id_field),
        "number": doc.get("number_display") or doc.get("number"),
        "title": doc.get("title"),
        "status": doc.get("status"),
        "priority": doc.get("priority"),
        "category": doc.get("category"),
        "service_tier": doc.get("service_tier"),
        "assignee_user_id": doc.get("assignee_user_id"),
        "created_at": doc.get("created_at"),
        "updated_at": doc.get("updated_at"),
    }
    return {col: base.get(col) for col in columns}


def _fetch_ticket_rows(
    *,
    tenant_id: str,
    filters: ReportFilters,
    columns: list[str],
    start: datetime | None,
    end: datetime | None,
) -> list[dict[str, Any]]:
    tid = require_tenant_id(tenant_id)
    itsm = require_itsm_database()
    rows: list[dict[str, Any]] = []
    remaining = MAX_TICKET_ROWS
    for ticket_type in filters.ticket_types:
        if remaining <= 0:
            break
        coll = itsm[COLL_BY_TYPE[ticket_type]]
        query = merge_tenant_filter(
            _ticket_query(
                ticket_type=ticket_type,
                filters=filters,
                start=start,
                end=end,
            )
            or None,
            tid,
        )
        cursor = (
            coll.find(query)
            .sort([("created_at", DESCENDING)])
            .limit(remaining)
        )
        for doc in cursor:
            rows.append(
                _project_ticket_row(doc, ticket_type=ticket_type, columns=columns)
            )
            remaining -= 1
            if remaining <= 0:
                break
    return rows


def _metric_value(summary: dict[str, Any], metric: str) -> Any:
    created = summary.get("created_in_window") or {}
    resolved = summary.get("resolved_in_window") or {}
    mapping = {
        "open_incidents": summary.get("open_incidents", 0),
        "open_changes": summary.get("open_changes", 0),
        "open_problems": summary.get("open_problems", 0),
        "pending_approvals": summary.get("pending_approvals", 0),
        "sla_breaches": summary.get("sla_breaches", 0),
        "sla_at_risk": summary.get("sla_at_risk", 0),
        "workflows_in_progress": summary.get("workflows_in_progress", 0),
        "knowledge_published": summary.get("knowledge_published", 0),
        "notifications_unread": summary.get("notifications_unread", 0),
        "created_incidents": created.get("incidents", 0),
        "created_changes": created.get("changes", 0),
        "created_problems": created.get("problems", 0),
        "resolved_incidents": resolved.get("incidents", 0),
        "resolved_changes": resolved.get("changes", 0),
        "resolved_problems": resolved.get("problems", 0),
    }
    return mapping.get(metric, 0)


def run_definition(
    report_id: str,
    *,
    tenant_id: str,
    override_filters: ReportFilters | None = None,
) -> dict[str, Any]:
    """Execute a saved report: KPI metrics + optional ticket detail rows."""
    tid = require_tenant_id(tenant_id)
    doc = get_definition(report_id, tenant_id=tid)
    if doc is None:
        raise ReportError(f"Report '{report_id}' not found", status_code=404)

    filters = override_filters or ReportFilters.model_validate(doc.get("filters") or {})
    metrics = [m for m in (doc.get("metrics") or []) if m in REPORT_METRICS]
    if not metrics:
        raise ReportError("Report has no valid metrics")
    columns = [
        c
        for c in (doc.get("columns") or list(DEFAULT_TICKET_COLUMNS))
        if c in DEFAULT_TICKET_COLUMNS
    ] or list(DEFAULT_TICKET_COLUMNS)

    start, end, window_days = _resolve_window(filters)
    # Dashboard summary uses window_days=7|30 only; for explicit dates use None
    # and still compute created/resolved via ticket query for ticket_rows.
    summary_window = window_days if (filters.date_from is None and filters.date_to is None) else None
    if summary_window is None and start is not None and end is None and filters.window_days:
        summary_window = filters.window_days
    # When only absolute dates are set, pass None for snapshot KPIs + omit window counts.
    try:
        summary = dashboard_service.summary(
            tenant_id=tid,
            window_days=summary_window if summary_window in (7, 30) else None,
        )
    except ValueError as exc:
        raise ReportError(str(exc)) from exc

    metric_rows = []
    include_tickets = "ticket_rows" in metrics
    for metric in metrics:
        if metric == "ticket_rows":
            continue
        metric_rows.append(
            {
                "metric": metric,
                "value": _metric_value(summary, metric),
            }
        )

    ticket_rows: list[dict[str, Any]] = []
    if include_tickets:
        ticket_rows = _fetch_ticket_rows(
            tenant_id=tid,
            filters=filters,
            columns=columns,
            start=start,
            end=end,
        )

    return {
        "report_id": report_id,
        "name": doc.get("name"),
        "tenant_id": tid,
        "filters": filters.model_dump(),
        "metrics": metrics,
        "columns": columns,
        "generated_at": _now().isoformat(),
        "window_start": start.isoformat() if start else None,
        "window_end": end.isoformat() if end else None,
        "summary_metrics": metric_rows,
        "ticket_rows": ticket_rows,
        "ticket_row_count": len(ticket_rows),
        "notes": (
            "Custom ITSM report run. Snapshot KPIs use dashboard aggregates; "
            "ticket_rows honor filters (type/status/priority/category/tier/date)."
        ),
    }


def render_run_export(result: dict[str, Any], *, fmt: str) -> tuple[bytes, str, int]:
    fmt = fmt.lower()
    if fmt not in ("csv", "xlsx"):
        raise ReportError("format must be csv or xlsx")
    tables: list[tuple[str, list[str], list[list[Any]]]] = []
    metrics = result.get("summary_metrics") or []
    if metrics:
        tables.append(
            dict_rows_to_table(
                title="Summary metrics",
                headers=["metric", "value"],
                items=metrics,
            )
        )
    ticket_rows = result.get("ticket_rows") or []
    columns = result.get("columns") or list(DEFAULT_TICKET_COLUMNS)
    if ticket_rows or "ticket_rows" in (result.get("metrics") or []):
        tables.append(
            dict_rows_to_table(
                title="Ticket rows",
                headers=columns,
                items=ticket_rows,
            )
        )
    if not tables:
        tables.append(("Empty", ["message"], [["No metrics selected"]]))

    if fmt == "xlsx":
        body = render_xlsx_tables(tables)
        filename = f"itsm-report-{result.get('report_id', 'custom')}.xlsx"
    else:
        body = render_csv_tables(tables)
        filename = f"itsm-report-{result.get('report_id', 'custom')}.csv"
    count = len(metrics) + len(ticket_rows)
    return body, filename, count


def build_dashboard_export(
    *,
    tenant_id: str,
    window_days: int = 30,
    include_tickets: bool = True,
) -> dict[str, Any]:
    """Build summary + detail datasets for the Reports / Dashboard download."""
    tid = require_tenant_id(tenant_id)
    if window_days not in (7, 30):
        raise ReportError("window_days must be 7 or 30")
    data = dashboard_service.reports(tenant_id=tid, window_days=window_days)
    filters = ReportFilters(
        ticket_types=list(COLL_BY_TYPE.keys()),
        window_days=window_days,
    )
    start, end, _ = _resolve_window(filters)
    ticket_rows: list[dict[str, Any]] = []
    if include_tickets:
        ticket_rows = _fetch_ticket_rows(
            tenant_id=tid,
            filters=filters,
            columns=list(DEFAULT_TICKET_COLUMNS),
            start=start,
            end=end,
        )
    return {
        "tenant_id": tid,
        "window_days": window_days,
        "generated_at": data.get("generated_at"),
        "summary": data,
        "ticket_rows": ticket_rows,
        "columns": list(DEFAULT_TICKET_COLUMNS),
    }


def render_dashboard_export(payload: dict[str, Any], *, fmt: str) -> tuple[bytes, str, int]:
    fmt = fmt.lower()
    if fmt not in ("csv", "xlsx"):
        raise ReportError("format must be csv or xlsx")
    summary = payload.get("summary") or {}
    created = summary.get("created_in_window") or {}
    resolved = summary.get("resolved_in_window") or {}
    kpi_items = [
        {"metric": "open_incidents", "value": summary.get("open_incidents", 0)},
        {"metric": "open_changes", "value": summary.get("open_changes", 0)},
        {"metric": "open_problems", "value": summary.get("open_problems", 0)},
        {"metric": "pending_approvals", "value": summary.get("pending_approvals", 0)},
        {"metric": "sla_breaches", "value": summary.get("sla_breaches", 0)},
        {"metric": "sla_at_risk", "value": summary.get("sla_at_risk", 0)},
        {"metric": "workflows_in_progress", "value": summary.get("workflows_in_progress", 0)},
        {"metric": "knowledge_published", "value": summary.get("knowledge_published", 0)},
        {"metric": "notifications_unread", "value": summary.get("notifications_unread", 0)},
        {"metric": "created_incidents", "value": created.get("incidents", 0)},
        {"metric": "created_changes", "value": created.get("changes", 0)},
        {"metric": "created_problems", "value": created.get("problems", 0)},
        {"metric": "resolved_incidents", "value": resolved.get("incidents", 0)},
        {"metric": "resolved_changes", "value": resolved.get("changes", 0)},
        {"metric": "resolved_problems", "value": resolved.get("problems", 0)},
    ]
    tables: list[tuple[str, list[str], list[list[Any]]]] = [
        dict_rows_to_table(
            title="Summary KPIs",
            headers=["metric", "value"],
            items=kpi_items,
        ),
        dict_rows_to_table(
            title="Daily created",
            headers=["date", "incidents", "changes", "problems", "total"],
            items=summary.get("series_daily_created") or [],
        ),
        dict_rows_to_table(
            title="Incidents by status",
            headers=["status", "count"],
            items=[
                {"status": k, "count": v}
                for k, v in sorted((summary.get("incidents_by_status") or {}).items())
            ],
        ),
        dict_rows_to_table(
            title="Open incidents by priority",
            headers=["priority", "count"],
            items=[
                {"priority": k, "count": v}
                for k, v in sorted((summary.get("open_by_priority") or {}).items())
            ],
        ),
        dict_rows_to_table(
            title="Changes by status",
            headers=["status", "count"],
            items=[
                {"status": k, "count": v}
                for k, v in sorted((summary.get("changes_by_status") or {}).items())
            ],
        ),
        dict_rows_to_table(
            title="Problems by status",
            headers=["status", "count"],
            items=[
                {"status": k, "count": v}
                for k, v in sorted((summary.get("problems_by_status") or {}).items())
            ],
        ),
    ]
    ticket_rows = payload.get("ticket_rows") or []
    columns = payload.get("columns") or list(DEFAULT_TICKET_COLUMNS)
    if ticket_rows:
        tables.append(
            dict_rows_to_table(
                title="Ticket detail",
                headers=columns,
                items=ticket_rows,
            )
        )

    window = payload.get("window_days") or 30
    if fmt == "xlsx":
        body = render_xlsx_tables(tables)
        filename = f"itsm-reports-{window}d.xlsx"
    else:
        body = render_csv_tables(tables)
        filename = f"itsm-reports-{window}d.csv"
    count = len(kpi_items) + len(summary.get("series_daily_created") or []) + len(
        ticket_rows
    )
    return body, filename, count
