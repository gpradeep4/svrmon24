"""CSV / Excel rendering for ITSM report exports (mirrors CMDB inventory IO)."""

from __future__ import annotations

import csv
import io
from typing import Any, Iterable, Sequence

from openpyxl import Workbook


def _cell(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, tuple)):
        return ",".join(str(v) for v in value)
    return value


def render_csv_tables(
    tables: Sequence[tuple[str, Sequence[str], Sequence[Sequence[Any]]]],
) -> bytes:
    """Render one or more named tables into a single CSV (section headers)."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    first = True
    for title, headers, rows in tables:
        if not first:
            writer.writerow([])
        first = False
        writer.writerow([f"# {title}"])
        writer.writerow(list(headers))
        for row in rows:
            writer.writerow([_cell(v) for v in row])
    return buf.getvalue().encode("utf-8-sig")


def render_xlsx_tables(
    tables: Sequence[tuple[str, Sequence[str], Sequence[Sequence[Any]]]],
) -> bytes:
    """Render named tables as Excel worksheets (sheet title truncated to 31)."""
    wb = Workbook()
    # Remove the default sheet once we have real sheets.
    default = wb.active
    first_sheet = True
    for title, headers, rows in tables:
        safe = "".join(ch if ch.isalnum() or ch in " _-" else "_" for ch in title)[
            :31
        ] or "Sheet"
        if first_sheet:
            ws = default
            ws.title = safe
            first_sheet = False
        else:
            ws = wb.create_sheet(title=safe)
        ws.append(list(headers))
        for row in rows:
            ws.append([_cell(v) for v in row])
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def dict_rows_to_table(
    *,
    title: str,
    headers: Sequence[str],
    items: Iterable[dict[str, Any]],
) -> tuple[str, list[str], list[list[Any]]]:
    header_list = list(headers)
    rows = [[item.get(h) for h in header_list] for item in items]
    return title, header_list, rows
