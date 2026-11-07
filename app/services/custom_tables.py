"""Custom entity table definitions + records (tenant-scoped).

Collections:
  - ``cmdb_custom_table_definitions``
  - ``cmdb_custom_records`` (single collection; rows partitioned by ``table_key``)
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from pymongo import ASCENDING, DESCENDING
from pymongo.collection import Collection
from pymongo.errors import DuplicateKeyError

from ..db import require_database
from ..models.components import COMPONENT_TYPES
from ..models.custom_tables import (
    BUILTIN_REF_TABLES,
    RESERVED_TABLE_KEYS,
    CustomColumnCreate,
    CustomColumnType,
    CustomColumnUpdate,
    CustomRecordCreate,
    CustomRecordUpdate,
    CustomTableCreate,
    CustomTableUpdate,
    is_builtin_ref_table,
    normalize_ref_value,
)
from ..serialization import serialize_document
from ..tenancy import merge_tenant_filter, require_tenant_id, stamp_tenant_id, tenant_filter

DEFINITIONS_COLLECTION = "cmdb_custom_table_definitions"
RECORDS_COLLECTION = "cmdb_custom_records"


class CustomTableError(Exception):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _definitions() -> Collection:
    coll = require_database()[DEFINITIONS_COLLECTION]
    coll.create_index(
        [("tenant_id", ASCENDING), ("table_key", ASCENDING)],
        unique=True,
        name="tenant_table_key_unique",
    )
    coll.create_index([("tenant_id", ASCENDING)], name="tenant_id_idx")
    return coll


def _records() -> Collection:
    coll = require_database()[RECORDS_COLLECTION]
    coll.create_index(
        [("tenant_id", ASCENDING), ("table_key", ASCENDING), ("record_id", ASCENDING)],
        unique=True,
        name="tenant_table_record_unique",
    )
    coll.create_index(
        [("tenant_id", ASCENDING), ("record_id", ASCENDING)],
        name="tenant_record_id_idx",
    )
    coll.create_index([("tenant_id", ASCENDING)], name="tenant_id_idx")
    return coll


def generate_record_id(table_key: str) -> str:
    return f"ct-{table_key[:12]}-{uuid.uuid4().hex[:10]}"


def _serialize_table(doc: dict[str, Any] | None) -> dict[str, Any] | None:
    if doc is None:
        return None
    out = serialize_document(doc)
    assert out is not None
    columns = list(out.get("columns") or [])
    columns.sort(key=lambda c: (c.get("order", 0), c.get("column_key", "")))
    out["columns"] = columns
    return out


def _serialize_record(doc: dict[str, Any] | None) -> dict[str, Any] | None:
    if doc is None:
        return None
    return serialize_document(doc)


def list_tables(*, tenant_id: str, active_only: bool = False) -> list[dict[str, Any]]:
    tid = require_tenant_id(tenant_id)
    query: dict[str, Any] = {}
    if active_only:
        query["active"] = True
    cursor = (
        _definitions()
        .find(merge_tenant_filter(query, tid))
        .sort([("label", ASCENDING), ("table_key", ASCENDING)])
    )
    return [t for t in (_serialize_table(d) for d in cursor) if t is not None]


def get_table(table_key: str, *, tenant_id: str) -> dict[str, Any] | None:
    tid = require_tenant_id(tenant_id)
    key = (table_key or "").strip()
    if not key:
        return None
    doc = _definitions().find_one({"table_key": key, **tenant_filter(tid)})
    return _serialize_table(doc)


def require_table(table_key: str, *, tenant_id: str) -> dict[str, Any]:
    table = get_table(table_key, tenant_id=tenant_id)
    if table is None:
        raise CustomTableError(
            f"Custom table '{table_key}' not found",
            status_code=404,
        )
    return table


def _validate_reference_target(reference_table: str, *, tenant_id: str) -> None:
    if is_builtin_ref_table(reference_table):
        return
    if reference_table in RESERVED_TABLE_KEYS:
        raise CustomTableError(
            f"reference_table '{reference_table}' is reserved",
            status_code=422,
        )
    # Must point at an existing custom table for this tenant.
    if get_table(reference_table, tenant_id=tenant_id) is None:
        raise CustomTableError(
            f"reference_table '{reference_table}' does not exist for this tenant",
            status_code=422,
        )


def _prepare_columns(
    columns: list[Any],
    *,
    tenant_id: str,
) -> list[dict[str, Any]]:
    prepared: list[dict[str, Any]] = []
    seen: set[str] = set()
    for idx, col in enumerate(columns):
        data = col.model_dump() if hasattr(col, "model_dump") else dict(col)
        key = data["column_key"]
        if key in seen:
            raise CustomTableError(f"Duplicate column_key '{key}'")
        if key in {"record_id", "display_name", "table_key", "tenant_id", "fields"}:
            raise CustomTableError(f"column_key '{key}' is reserved")
        seen.add(key)
        if data.get("field_type") == CustomColumnType.REFERENCE.value or data.get(
            "field_type"
        ) == CustomColumnType.REFERENCE:
            ref = data.get("reference_table")
            if not ref:
                raise CustomTableError(
                    f"Column '{key}' of type reference requires reference_table"
                )
            _validate_reference_target(ref, tenant_id=tenant_id)
        ft = data.get("field_type")
        if hasattr(ft, "value"):
            data["field_type"] = ft.value
        data.setdefault("order", idx)
        data.setdefault("required", False)
        data.setdefault("enum_values", [])
        data.setdefault("active", True)
        prepared.append(data)
    return prepared


def create_table(payload: CustomTableCreate, *, tenant_id: str) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    if payload.table_key in RESERVED_TABLE_KEYS:
        raise CustomTableError(
            f"table_key '{payload.table_key}' is reserved",
            status_code=422,
        )
    columns = _prepare_columns(payload.columns, tenant_id=tid)
    now = _now()
    doc: dict[str, Any] = {
        "table_key": payload.table_key,
        "label": payload.label,
        "description": payload.description,
        "columns": columns,
        "active": payload.active,
        "created_at": now,
        "updated_at": now,
    }
    stamp_tenant_id(doc, tenant_id=tid)
    try:
        _definitions().insert_one(doc)
    except DuplicateKeyError as exc:
        raise CustomTableError(
            f"Custom table '{payload.table_key}' already exists",
            status_code=409,
        ) from exc
    result = _serialize_table(doc)
    assert result is not None
    return result


def update_table(
    table_key: str, payload: CustomTableUpdate, *, tenant_id: str
) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    require_table(table_key, tenant_id=tid)
    data = payload.model_dump(exclude_unset=True)
    if not data:
        result = get_table(table_key, tenant_id=tid)
        assert result is not None
        return result
    data["updated_at"] = _now()
    stamp_tenant_id(data, tenant_id=tid)
    _definitions().update_one(
        {"table_key": table_key, **tenant_filter(tid)},
        {"$set": data},
    )
    result = get_table(table_key, tenant_id=tid)
    assert result is not None
    return result


def delete_table(table_key: str, *, tenant_id: str) -> dict[str, Any]:
    """Delete table definition and all of its records (same tenant)."""
    tid = require_tenant_id(tenant_id)
    require_table(table_key, tenant_id=tid)
    # Block delete if another table's reference column points here.
    others = list_tables(tenant_id=tid)
    dependents = []
    for other in others:
        if other["table_key"] == table_key:
            continue
        for col in other.get("columns") or []:
            if (
                col.get("field_type") == CustomColumnType.REFERENCE.value
                and col.get("reference_table") == table_key
            ):
                dependents.append(f"{other['table_key']}.{col['column_key']}")
    if dependents:
        raise CustomTableError(
            "Cannot delete table referenced by columns: " + ", ".join(dependents),
            status_code=409,
        )
    records_deleted = _records().delete_many(
        {"table_key": table_key, **tenant_filter(tid)}
    )
    result = _definitions().delete_one(
        {"table_key": table_key, **tenant_filter(tid)}
    )
    if result.deleted_count == 0:
        raise CustomTableError(
            f"Custom table '{table_key}' not found",
            status_code=404,
        )
    return {
        "deleted": True,
        "table_key": table_key,
        "records_deleted": int(records_deleted.deleted_count),
    }


def add_column(
    table_key: str, payload: CustomColumnCreate, *, tenant_id: str
) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    table = require_table(table_key, tenant_id=tid)
    existing_keys = {c["column_key"] for c in table.get("columns") or []}
    if payload.column_key in existing_keys:
        raise CustomTableError(
            f"Column '{payload.column_key}' already exists on table '{table_key}'",
            status_code=409,
        )
    prepared = _prepare_columns([payload], tenant_id=tid)[0]
    if prepared["order"] == 0 and table.get("columns"):
        prepared["order"] = max(c.get("order", 0) for c in table["columns"]) + 1
    _definitions().update_one(
        {"table_key": table_key, **tenant_filter(tid)},
        {
            "$push": {"columns": prepared},
            "$set": {"updated_at": _now(), "tenant_id": tid},
        },
    )
    result = get_table(table_key, tenant_id=tid)
    assert result is not None
    return result


def update_column(
    table_key: str,
    column_key: str,
    payload: CustomColumnUpdate,
    *,
    tenant_id: str,
) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    table = require_table(table_key, tenant_id=tid)
    columns = list(table.get("columns") or [])
    idx = next(
        (i for i, c in enumerate(columns) if c.get("column_key") == column_key),
        None,
    )
    if idx is None:
        raise CustomTableError(
            f"Column '{column_key}' not found on table '{table_key}'",
            status_code=404,
        )
    merged = {**columns[idx], **payload.model_dump(exclude_unset=True)}
    ft = merged.get("field_type")
    if hasattr(ft, "value"):
        merged["field_type"] = ft.value
        ft = merged["field_type"]
    # Re-validate via CustomColumnCreate shape.
    validated = CustomColumnCreate.model_validate(merged)
    prepared = _prepare_columns([validated], tenant_id=tid)[0]
    columns[idx] = prepared
    _definitions().update_one(
        {"table_key": table_key, **tenant_filter(tid)},
        {
            "$set": {
                "columns": columns,
                "updated_at": _now(),
                "tenant_id": tid,
            }
        },
    )
    result = get_table(table_key, tenant_id=tid)
    assert result is not None
    return result


def delete_column(
    table_key: str, column_key: str, *, tenant_id: str
) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    table = require_table(table_key, tenant_id=tid)
    columns = [c for c in (table.get("columns") or []) if c.get("column_key") != column_key]
    if len(columns) == len(table.get("columns") or []):
        raise CustomTableError(
            f"Column '{column_key}' not found on table '{table_key}'",
            status_code=404,
        )
    _definitions().update_one(
        {"table_key": table_key, **tenant_filter(tid)},
        {
            "$set": {
                "columns": columns,
                "updated_at": _now(),
                "tenant_id": tid,
            }
        },
    )
    # Strip the field from existing records (best-effort cleanup).
    _records().update_many(
        {"table_key": table_key, **tenant_filter(tid)},
        {"$unset": {f"fields.{column_key}": ""}},
    )
    result = get_table(table_key, tenant_id=tid)
    assert result is not None
    return result


def _coerce_field_value(col: dict[str, Any], value: Any) -> Any:
    ft = col.get("field_type")
    key = col["column_key"]
    if value is None or value == "":
        if col.get("required"):
            raise CustomTableError(f"Field '{key}' is required", status_code=422)
        return None
    if ft == CustomColumnType.STRING.value:
        return str(value).strip()
    if ft == CustomColumnType.NUMBER.value:
        if isinstance(value, bool):
            raise CustomTableError(f"Field '{key}' must be a number", status_code=422)
        try:
            if isinstance(value, str) and "." in value:
                return float(value)
            if isinstance(value, float):
                return value
            return int(value) if float(value) == int(float(value)) else float(value)
        except (TypeError, ValueError) as exc:
            raise CustomTableError(
                f"Field '{key}' must be a number", status_code=422
            ) from exc
    if ft == CustomColumnType.BOOLEAN.value:
        if isinstance(value, bool):
            return value
        if isinstance(value, str) and value.strip().lower() in {"true", "1", "yes"}:
            return True
        if isinstance(value, str) and value.strip().lower() in {"false", "0", "no"}:
            return False
        raise CustomTableError(f"Field '{key}' must be a boolean", status_code=422)
    if ft == CustomColumnType.ENUM.value:
        text = str(value).strip()
        allowed = col.get("enum_values") or []
        if text not in allowed:
            raise CustomTableError(
                f"Field '{key}' must be one of: {', '.join(allowed)}",
                status_code=422,
            )
        return text
    if ft == CustomColumnType.REFERENCE.value:
        try:
            ref = normalize_ref_value(value)
        except ValueError as exc:
            raise CustomTableError(str(exc), status_code=422) from exc
        if ref is None:
            if col.get("required"):
                raise CustomTableError(f"Field '{key}' is required", status_code=422)
            return None
        expected = col.get("reference_table")
        if expected and ref["ref_table"] != expected:
            raise CustomTableError(
                f"Field '{key}' must reference table '{expected}' "
                f"(got '{ref['ref_table']}')",
                status_code=422,
            )
        return ref
    return value


def _validate_record_fields(
    table: dict[str, Any],
    fields: dict[str, Any],
    *,
    tenant_id: str,
    resolve_refs: bool = True,
) -> dict[str, Any]:
    columns = {c["column_key"]: c for c in table.get("columns") or [] if c.get("active", True)}
    unknown = set(fields) - set(columns)
    if unknown:
        raise CustomTableError(
            f"Unknown field(s) for table '{table['table_key']}': "
            + ", ".join(sorted(unknown)),
            status_code=422,
        )
    out: dict[str, Any] = {}
    for key, col in columns.items():
        raw = fields.get(key)
        if key not in fields:
            if col.get("required"):
                raise CustomTableError(f"Field '{key}' is required", status_code=422)
            continue
        coerced = _coerce_field_value(col, raw)
        if coerced is None:
            out[key] = None
            continue
        if (
            resolve_refs
            and col.get("field_type") == CustomColumnType.REFERENCE.value
            and isinstance(coerced, dict)
        ):
            resolve_entity_ref(
                coerced["ref_id"],
                coerced["ref_table"],
                tenant_id=tenant_id,
                role=f"field '{key}'",
            )
        out[key] = coerced
    return out


def resolve_entity_ref(
    entity_id: str,
    ref_table: str | None,
    *,
    tenant_id: str,
    role: str = "entity",
) -> dict[str, Any]:
    """Resolve a CMDB component or custom record for relationships / references.

    Returns a normalized stub:
    ``{entity_id, ref_table, kind, display_name, environment?}``.
    """
    tid = require_tenant_id(tenant_id)
    eid = (entity_id or "").strip()
    table = (ref_table or "").strip() or None

    if not eid:
        raise CustomTableError(f"Invalid {role}: missing id", status_code=422)

    # Explicit custom table.
    if table and table not in BUILTIN_REF_TABLES:
        if table in RESERVED_TABLE_KEYS:
            raise CustomTableError(
                f"Invalid {role}: ref_table '{table}' is reserved",
                status_code=422,
            )
        require_table(table, tenant_id=tid)
        doc = get_record(table, eid, tenant_id=tid)
        if doc is None:
            raise CustomTableError(
                f"Invalid {role} '{eid}' — record not found in custom table '{table}'",
                status_code=422,
            )
        return {
            "entity_id": eid,
            "ref_table": table,
            "kind": "custom",
            "display_name": doc.get("display_name"),
            "environment": (doc.get("fields") or {}).get("environment"),
        }

    # Built-in CMDB component (optionally typed).
    from . import components as components_service

    doc = components_service.get_component(eid, tenant_id=tid)
    if doc is None:
        # Fall back: maybe it's a custom record and table was omitted — do not
        # silently accept; require explicit table for custom entities.
        raise CustomTableError(
            f"Invalid {role} component_id '{eid}' — component does not exist",
            status_code=422,
        )
    ctype = doc.get("component_type")
    if table and table in BUILTIN_REF_TABLES and ctype != table:
        raise CustomTableError(
            f"Invalid {role}: component '{eid}' is type {ctype}, expected {table}",
            status_code=422,
        )
    return {
        "entity_id": eid,
        "ref_table": ctype if ctype in COMPONENT_TYPES else (table or "components"),
        "kind": "component",
        "display_name": doc.get("name") or doc.get("hostname"),
        "environment": doc.get("environment"),
        "component": doc,
    }


def get_record(
    table_key: str, record_id: str, *, tenant_id: str
) -> dict[str, Any] | None:
    tid = require_tenant_id(tenant_id)
    doc = _records().find_one(
        {
            "table_key": table_key,
            "record_id": record_id,
            **tenant_filter(tid),
        }
    )
    return _serialize_record(doc)


def find_record_by_id(record_id: str, *, tenant_id: str) -> dict[str, Any] | None:
    """Lookup a custom record by tenant-scoped ``record_id`` (any table).

    ``record_id`` is unique per tenant (and cannot collide with ``component_id``),
    so dependency graphs can resolve custom endpoints without an explicit table.
    """
    tid = require_tenant_id(tenant_id)
    eid = (record_id or "").strip()
    if not eid:
        return None
    doc = _records().find_one({"record_id": eid, **tenant_filter(tid)})
    return _serialize_record(doc)


def create_record(
    table_key: str, payload: CustomRecordCreate, *, tenant_id: str
) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    table = require_table(table_key, tenant_id=tid)
    if not table.get("active", True):
        raise CustomTableError(
            f"Custom table '{table_key}' is inactive",
            status_code=422,
        )
    fields = _validate_record_fields(table, payload.fields or {}, tenant_id=tid)
    record_id = payload.record_id or generate_record_id(table_key)

    # Avoid colliding with a CMDB component_id (global uniqueness preference).
    from .cmdb_collections import component_id_taken

    if component_id_taken(require_database(), record_id):
        raise CustomTableError(
            f"record_id '{record_id}' collides with an existing component_id",
            status_code=409,
        )
    # Also unique across custom records within tenant (any table).
    existing_any = _records().find_one(
        {"record_id": record_id, **tenant_filter(tid)}, {"_id": 1}
    )
    if existing_any is not None:
        raise CustomTableError(
            f"record_id '{record_id}' already exists for this tenant",
            status_code=409,
        )

    now = _now()
    doc: dict[str, Any] = {
        "record_id": record_id,
        "table_key": table_key,
        "display_name": payload.display_name,
        "fields": fields,
        "created_at": now,
        "updated_at": now,
    }
    stamp_tenant_id(doc, tenant_id=tid)
    try:
        _records().insert_one(doc)
    except DuplicateKeyError as exc:
        raise CustomTableError(
            f"record_id '{record_id}' already exists on table '{table_key}'",
            status_code=409,
        ) from exc
    result = _serialize_record(doc)
    assert result is not None
    return result


def update_record(
    table_key: str,
    record_id: str,
    payload: CustomRecordUpdate,
    *,
    tenant_id: str,
) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    table = require_table(table_key, tenant_id=tid)
    existing = get_record(table_key, record_id, tenant_id=tid)
    if existing is None:
        raise CustomTableError(
            f"Record '{record_id}' not found on table '{table_key}'",
            status_code=404,
        )
    data: dict[str, Any] = {}
    if payload.display_name is not None:
        data["display_name"] = payload.display_name
    if payload.fields is not None:
        # Merge with existing fields so partial updates work; required checked
        # against the merged map.
        merged_fields = {**(existing.get("fields") or {}), **payload.fields}
        data["fields"] = _validate_record_fields(
            table, merged_fields, tenant_id=tid
        )
    if not data:
        return existing
    data["updated_at"] = _now()
    stamp_tenant_id(data, tenant_id=tid)
    _records().update_one(
        {
            "table_key": table_key,
            "record_id": record_id,
            **tenant_filter(tid),
        },
        {"$set": data},
    )
    result = get_record(table_key, record_id, tenant_id=tid)
    assert result is not None
    return result


def delete_record(
    table_key: str, record_id: str, *, tenant_id: str
) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    require_table(table_key, tenant_id=tid)
    result = _records().delete_one(
        {
            "table_key": table_key,
            "record_id": record_id,
            **tenant_filter(tid),
        }
    )
    if result.deleted_count == 0:
        raise CustomTableError(
            f"Record '{record_id}' not found on table '{table_key}'",
            status_code=404,
        )
    return {"deleted": True, "table_key": table_key, "record_id": record_id}


def list_records(
    table_key: str,
    *,
    tenant_id: str,
    q: str | None = None,
    page: int = 1,
    page_size: int = 25,
) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    require_table(table_key, tenant_id=tid)
    page = max(1, page)
    page_size = min(max(1, page_size), 200)
    query: dict[str, Any] = {"table_key": table_key}
    if q:
        import re

        pattern = re.compile(re.escape(q.strip()), re.IGNORECASE)
        query["$or"] = [
            {"record_id": pattern},
            {"display_name": pattern},
        ]
    scoped = merge_tenant_filter(query, tid)
    coll = _records()
    total = coll.count_documents(scoped)
    cursor = (
        coll.find(scoped)
        .sort("updated_at", DESCENDING)
        .skip((page - 1) * page_size)
        .limit(page_size)
    )
    items = [r for r in (_serialize_record(d) for d in cursor) if r is not None]
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size if page_size else 0,
        "items": items,
        "table_key": table_key,
        "tenant_id": tid,
    }


def list_entity_refs(
    *,
    tenant_id: str,
    q: str | None = None,
    table: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    """Unified picker list: CMDB components + custom records."""
    tid = require_tenant_id(tenant_id)
    limit = min(max(1, limit), 500)
    items: list[dict[str, Any]] = []

    include_components = table is None or table in BUILTIN_REF_TABLES or table == "components"
    include_custom = table is None or (
        table not in BUILTIN_REF_TABLES and table != "components"
    )

    if include_components:
        from . import components as components_service

        ctype = table if table in BUILTIN_REF_TABLES else None
        listed = components_service.list_components(
            tenant_id=tid,
            q=q,
            component_type=ctype,
            page=1,
            page_size=limit,
        )
        for c in listed.get("items") or []:
            items.append(
                {
                    "entity_id": c.get("component_id"),
                    "ref_table": c.get("component_type"),
                    "kind": "component",
                    "display_name": c.get("name") or c.get("hostname") or c.get("component_id"),
                    "environment": c.get("environment"),
                }
            )

    if include_custom:
        query: dict[str, Any] = {}
        if table and table not in BUILTIN_REF_TABLES and table != "components":
            require_table(table, tenant_id=tid)
            query["table_key"] = table
        if q:
            import re

            pattern = re.compile(re.escape(q.strip()), re.IGNORECASE)
            query["$or"] = [
                {"record_id": pattern},
                {"display_name": pattern},
            ]
        cursor = (
            _records()
            .find(merge_tenant_filter(query, tid))
            .sort("updated_at", DESCENDING)
            .limit(limit)
        )
        for raw in cursor:
            doc = _serialize_record(raw)
            if not doc:
                continue
            items.append(
                {
                    "entity_id": doc.get("record_id"),
                    "ref_table": doc.get("table_key"),
                    "kind": "custom",
                    "display_name": doc.get("display_name"),
                    "environment": (doc.get("fields") or {}).get("environment"),
                }
            )

    # Prefer stable ordering: components first then custom, capped.
    items = items[:limit]
    return {
        "items": items,
        "tenant_id": tid,
        "builtin_ref_tables": sorted(BUILTIN_REF_TABLES),
    }
