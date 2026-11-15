"""CMDB inventory CSV/Excel import and export helpers."""

from __future__ import annotations

import csv
import io
import json
from typing import Any, Iterable

from openpyxl import Workbook, load_workbook
from openpyxl.worksheet.worksheet import Worksheet
from pydantic import ValidationError

from ..models.component_io import (
    FIELD_ALIASES,
    IMPORTABLE_FIELDS,
    REQUIRED_IMPORT_FIELDS,
    ImportReport,
    ImportRowResult,
    normalize_header,
    resolve_field_key,
)
from ..models.components import COMPONENT_TYPES, ComponentCreate, ComponentStatus, to_inventory_row
from . import components as components_service
from .components import ComponentError

# Stable export headers for round-trip friendliness.
EXPORT_HEADERS: tuple[str, ...] = (
    "component_id",
    "component_type",
    "name",
    "environment",
    "status",
    "hostname",
    "ip_address",
    "os_family",
    "os_version",
    "product_type",
    "product_version",
    "instance_name",
    "domain_name",
    "host_server_id",
    "listen_address",
    "listen_port",
    "installation_path",
    "domain_home",
    "log_folder_path",
    "endpoint",
    "cluster_or_replication_details",
    "device_name",
    "device_type",
    "management_ip",
    "virtual_ip",
    "listener_port",
    "application_name",
    "application_type",
    "service_url",
    "business_criticality",
    "owner",
)

MAX_IMPORT_ROWS = 2000
MAX_EXPORT_ROWS = 5000


def importable_field_catalog() -> dict[str, Any]:
    return {
        "fields": list(IMPORTABLE_FIELDS),
        "required": sorted(REQUIRED_IMPORT_FIELDS),
        "aliases": dict(FIELD_ALIASES),
        "component_types": list(COMPONENT_TYPES),
        "statuses": [s.value for s in ComponentStatus],
        "max_rows": MAX_IMPORT_ROWS,
    }


def _cell_str(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _detect_format(filename: str, content_type: str | None) -> str:
    name = (filename or "").lower()
    ctype = (content_type or "").lower()
    if name.endswith(".xlsx") or "spreadsheetml" in ctype or "excel" in ctype:
        return "xlsx"
    if name.endswith(".csv") or "csv" in ctype or "text/plain" in ctype:
        return "csv"
    if name.endswith(".xlsx"):
        return "xlsx"
    raise ComponentError(
        "Unsupported file type — upload a .csv or .xlsx file",
        status_code=422,
    )


def _read_csv_rows(raw: bytes) -> tuple[list[str], list[dict[str, str]]]:
    text = raw.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise ComponentError("CSV has no header row", status_code=422)
    headers = [h for h in reader.fieldnames if h is not None]
    rows: list[dict[str, str]] = []
    for row in reader:
        rows.append({k: _cell_str(v) for k, v in row.items() if k is not None})
    return headers, rows


def _read_xlsx_rows(raw: bytes) -> tuple[list[str], list[dict[str, str]]]:
    try:
        wb = load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
    except Exception as exc:  # noqa: BLE001 — surface as validation error
        raise ComponentError(f"Invalid Excel file: {exc}", status_code=422) from exc
    ws: Worksheet = wb.active
    iterator = ws.iter_rows(values_only=True)
    try:
        header_row = next(iterator)
    except StopIteration as exc:
        raise ComponentError("Excel sheet is empty", status_code=422) from exc
    headers = [_cell_str(h) for h in header_row]
    if not any(headers):
        raise ComponentError("Excel sheet has no header row", status_code=422)
    # Deduplicate blank trailing headers
    while headers and not headers[-1]:
        headers.pop()
    rows: list[dict[str, str]] = []
    for values in iterator:
        if values is None:
            continue
        cells = list(values) + [None] * max(0, len(headers) - len(values))
        mapped = {
            headers[i]: _cell_str(cells[i]) for i in range(len(headers)) if headers[i]
        }
        if not any(mapped.values()):
            continue
        rows.append(mapped)
    wb.close()
    return headers, rows


def build_auto_mapping(headers: Iterable[str]) -> dict[str, str]:
    """Map source header → canonical field (first match wins per field)."""
    mapping: dict[str, str] = {}
    used_fields: set[str] = set()
    for header in headers:
        field = resolve_field_key(header)
        if field is None or field in used_fields:
            continue
        mapping[header] = field
        used_fields.add(field)
    return mapping


def _normalize_mapping(
    headers: list[str], mapping: dict[str, str] | None
) -> tuple[dict[str, str], list[str], list[str]]:
    if mapping:
        cleaned: dict[str, str] = {}
        for src, dest in mapping.items():
            src_key = str(src).strip()
            dest_key = str(dest).strip()
            if not src_key or not dest_key:
                continue
            if dest_key not in IMPORTABLE_FIELDS:
                raise ComponentError(
                    f"Unknown target field in mapping: {dest_key}",
                    status_code=422,
                )
            cleaned[src_key] = dest_key
        resolved = cleaned
    else:
        resolved = build_auto_mapping(headers)

    mapped_fields = set(resolved.values())
    missing = sorted(REQUIRED_IMPORT_FIELDS - mapped_fields)
    unmapped = [h for h in headers if h and h not in resolved]
    return resolved, unmapped, missing


def _coerce_row_payload(raw: dict[str, Any]) -> dict[str, Any]:
    payload = dict(raw)
    # Normalize status / type casing for friendlier spreadsheets.
    if "status" in payload and payload["status"]:
        payload["status"] = str(payload["status"]).strip().lower()
    if "component_type" in payload and payload["component_type"]:
        ctype = str(payload["component_type"]).strip()
        for known in COMPONENT_TYPES:
            if known.lower() == ctype.lower():
                payload["component_type"] = known
                break
    for int_key in ("listen_port", "listener_port"):
        if int_key in payload and payload[int_key] not in (None, ""):
            try:
                payload[int_key] = int(str(payload[int_key]).strip())
            except ValueError:
                pass  # leave as-is; ComponentCreate will fail validation
    # Drop empty optional strings so type-foreign blanks don't trip validators.
    for key, value in list(payload.items()):
        if value == "":
            if key in REQUIRED_IMPORT_FIELDS or key == "component_type":
                continue
            if key == "component_id":
                payload.pop(key)
            else:
                payload.pop(key)
    return payload


def _row_to_payload(
    row: dict[str, str], mapping: dict[str, str]
) -> tuple[dict[str, Any] | None, list[str]]:
    payload: dict[str, Any] = {}
    errors: list[str] = []
    for src, field in mapping.items():
        if src not in row:
            continue
        payload[field] = row.get(src, "")
    payload = _coerce_row_payload(payload)
    for req in REQUIRED_IMPORT_FIELDS:
        if not payload.get(req):
            errors.append(f"Missing required field: {req}")
    if errors:
        return payload, errors
    try:
        ComponentCreate.model_validate(payload)
    except ValidationError as exc:
        for err in exc.errors():
            loc = ".".join(str(p) for p in err.get("loc", ()))
            msg = err.get("msg", "invalid")
            errors.append(f"{loc}: {msg}" if loc else msg)
    return payload, errors


def parse_import_file(
    *,
    filename: str,
    content: bytes,
    content_type: str | None = None,
    mapping: dict[str, str] | None = None,
) -> tuple[str, list[str], dict[str, str], list[str], list[str], list[dict[str, str]]]:
    if not content:
        raise ComponentError("Uploaded file is empty", status_code=422)
    fmt = _detect_format(filename, content_type)
    if fmt == "xlsx":
        headers, rows = _read_xlsx_rows(content)
    else:
        headers, rows = _read_csv_rows(content)
    if len(rows) > MAX_IMPORT_ROWS:
        raise ComponentError(
            f"Import limited to {MAX_IMPORT_ROWS} data rows (got {len(rows)})",
            status_code=422,
        )
    resolved, unmapped, missing = _normalize_mapping(headers, mapping)
    return fmt, headers, resolved, unmapped, missing, rows


def run_import(
    *,
    tenant_id: str,
    filename: str,
    content: bytes,
    content_type: str | None = None,
    mapping: dict[str, str] | None = None,
    dry_run: bool = True,
) -> ImportReport:
    fmt, headers, resolved, unmapped, missing, rows = parse_import_file(
        filename=filename,
        content=content,
        content_type=content_type,
        mapping=mapping,
    )
    results: list[ImportRowResult] = []
    created = 0
    skipped = 0
    valid = 0
    for idx, row in enumerate(rows, start=2):  # header is row 1
        if missing:
            results.append(
                ImportRowResult(
                    row_number=idx,
                    ok=False,
                    errors=[
                        f"Mapping missing required fields: {', '.join(missing)}"
                    ],
                )
            )
            continue
        payload, errors = _row_to_payload(row, resolved)
        if errors:
            results.append(
                ImportRowResult(
                    row_number=idx,
                    ok=False,
                    errors=errors,
                    payload=payload,
                )
            )
            continue
        assert payload is not None
        valid += 1
        if dry_run:
            results.append(
                ImportRowResult(
                    row_number=idx,
                    ok=True,
                    errors=[],
                    component_id=payload.get("component_id"),
                    payload=payload,
                )
            )
            continue
        try:
            model = ComponentCreate.model_validate(payload)
            doc = components_service.create_component(model, tenant_id=tenant_id)
            created += 1
            results.append(
                ImportRowResult(
                    row_number=idx,
                    ok=True,
                    errors=[],
                    component_id=doc.get("component_id"),
                    payload=payload,
                )
            )
        except ComponentError as exc:
            skipped += 1
            results.append(
                ImportRowResult(
                    row_number=idx,
                    ok=False,
                    errors=[exc.message],
                    payload=payload,
                )
            )
        except Exception as exc:  # noqa: BLE001
            skipped += 1
            results.append(
                ImportRowResult(
                    row_number=idx,
                    ok=False,
                    errors=[str(exc)],
                    payload=payload,
                )
            )

    invalid = sum(1 for r in results if not r.ok)
    return ImportReport(
        dry_run=dry_run,
        filename=filename or "upload",
        format=fmt,
        headers=headers,
        mapping=resolved,
        total_rows=len(rows),
        valid_rows=valid,
        invalid_rows=invalid,
        created=created,
        skipped=skipped,
        rows=results[:200],  # cap response size; totals remain accurate
        unmapped_headers=unmapped,
        missing_required=missing,
    )


def _export_row(doc: dict[str, Any]) -> list[Any]:
    return [doc.get(h) if doc.get(h) is not None else "" for h in EXPORT_HEADERS]


def build_export_rows(
    *,
    tenant_id: str,
    q: str | None = None,
    component_type: str | None = None,
    environment: str | None = None,
    status: str | None = None,
    os_family: str | None = None,
    product_type: str | None = None,
) -> list[dict[str, Any]]:
    data = components_service.list_components(
        tenant_id=tenant_id,
        q=q,
        component_type=component_type,
        environment=environment,
        status=status,
        os_family=os_family,
        product_type=product_type,
        page=1,
        page_size=MAX_EXPORT_ROWS,
        sort_by="component_id",
        sort_dir="asc",
    )
    return list(data.get("items") or [])


def render_csv(items: list[dict[str, Any]]) -> bytes:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(list(EXPORT_HEADERS))
    for doc in items:
        writer.writerow(_export_row(doc))
    return buf.getvalue().encode("utf-8-sig")


def render_xlsx(items: list[dict[str, Any]]) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Inventory"
    ws.append(list(EXPORT_HEADERS))
    for doc in items:
        ws.append(_export_row(doc))
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def render_template(fmt: str) -> bytes:
    sample = [
        {
            "component_id": "srv-example01",
            "component_type": "Server",
            "name": "example-web",
            "environment": "nonprod",
            "status": "active",
            "hostname": "example-web.local",
            "ip_address": "10.0.0.10",
            "os_family": "RHEL",
            "os_version": "9.4",
        }
    ]
    if fmt == "xlsx":
        return render_xlsx(sample)
    return render_csv(sample)


def parse_mapping_json(raw: str | None) -> dict[str, str] | None:
    if raw is None or not str(raw).strip():
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ComponentError(f"Invalid mapping JSON: {exc}", status_code=422) from exc
    if not isinstance(data, dict):
        raise ComponentError("mapping must be a JSON object", status_code=422)
    return {str(k): str(v) for k, v in data.items()}


def inventory_preview_rows(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [to_inventory_row(doc).model_dump() for doc in items]
