"""SLA business-hours / holiday clock math.

When ``calendar.business_hours_only`` is false (default), clocks are wall-clock
24×7. When true, only configured weekdays between start/end (local timezone)
count toward target minutes; ``holidays`` (YYYY-MM-DD) are fully excluded.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

_DAY_NAMES = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
_DEFAULT_DAYS = ("mon", "tue", "wed", "thu", "fri")


def _parse_hhmm(value: str | None, *, default: str) -> tuple[int, int]:
    raw = (value or default).strip()
    parts = raw.split(":")
    if len(parts) != 2:
        raise ValueError(f"Invalid HH:MM '{raw}'")
    hour, minute = int(parts[0]), int(parts[1])
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"Invalid HH:MM '{raw}'")
    return hour, minute


def _tz(calendar: dict[str, Any] | None) -> ZoneInfo:
    name = str((calendar or {}).get("timezone") or "UTC").strip() or "UTC"
    try:
        return ZoneInfo(name)
    except Exception:  # noqa: BLE001 — fall back for unknown tz labels
        return ZoneInfo("UTC")


def _business_days(calendar: dict[str, Any] | None) -> set[str]:
    raw = (calendar or {}).get("business_days")
    if not raw:
        return set(_DEFAULT_DAYS)
    out: set[str] = set()
    for item in raw:
        key = str(item or "").strip().lower()[:3]
        if key in _DAY_NAMES:
            out.add(key)
    return out or set(_DEFAULT_DAYS)


def _holiday_set(calendar: dict[str, Any] | None) -> set[date]:
    out: set[date] = set()
    for raw in (calendar or {}).get("holidays") or []:
        item = str(raw or "").strip()
        if not item:
            continue
        try:
            out.add(date.fromisoformat(item[:10]))
        except ValueError:
            continue
    return out


def is_business_hours_calendar(calendar: dict[str, Any] | None) -> bool:
    return bool((calendar or {}).get("business_hours_only"))


def ensure_aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def add_business_minutes(
    start: datetime,
    minutes: int,
    calendar: dict[str, Any] | None = None,
) -> datetime:
    """Advance ``start`` by ``minutes`` of business time (or wall-clock)."""
    start = ensure_aware(start) or datetime.now(timezone.utc)
    mins = max(0, int(minutes))
    if mins == 0:
        return start
    if not is_business_hours_calendar(calendar):
        return start + timedelta(minutes=mins)

    tz = _tz(calendar)
    days = _business_days(calendar)
    holidays = _holiday_set(calendar)
    start_h, start_m = _parse_hhmm(
        (calendar or {}).get("business_hours_start"), default="09:00"
    )
    end_h, end_m = _parse_hhmm(
        (calendar or {}).get("business_hours_end"), default="17:00"
    )
    window_start = start_h * 60 + start_m
    window_end = end_h * 60 + end_m
    if window_end <= window_start:
        # Degenerate window — treat as 24×7 to avoid infinite loops.
        return start + timedelta(minutes=mins)

    remaining = mins
    cursor = start.astimezone(tz)
    # Cap iterations: minutes * worst-case day skips (holidays).
    guard = 0
    max_guard = max(10_000, mins * 20)
    while remaining > 0 and guard < max_guard:
        guard += 1
        day_key = _DAY_NAMES[cursor.weekday()]
        local_date = cursor.date()
        if day_key not in days or local_date in holidays:
            cursor = datetime(
                local_date.year,
                local_date.month,
                local_date.day,
                0,
                0,
                tzinfo=tz,
            ) + timedelta(days=1)
            continue

        minute_of_day = cursor.hour * 60 + cursor.minute
        if minute_of_day >= window_end:
            cursor = datetime(
                local_date.year,
                local_date.month,
                local_date.day,
                0,
                0,
                tzinfo=tz,
            ) + timedelta(days=1)
            continue
        if minute_of_day < window_start:
            cursor = cursor.replace(
                hour=start_h, minute=start_m, second=0, microsecond=0
            )
            minute_of_day = window_start

        available = window_end - minute_of_day
        take = min(remaining, available)
        cursor = cursor + timedelta(minutes=take)
        remaining -= take

    return cursor.astimezone(timezone.utc)


def business_seconds_between(
    start: datetime,
    end: datetime,
    calendar: dict[str, Any] | None = None,
) -> int:
    """Count business seconds between two instants (wall seconds if 24×7)."""
    start = ensure_aware(start)
    end = ensure_aware(end)
    if start is None or end is None:
        return 0
    if end <= start:
        return 0
    if not is_business_hours_calendar(calendar):
        return int((end - start).total_seconds())

    tz = _tz(calendar)
    days = _business_days(calendar)
    holidays = _holiday_set(calendar)
    start_h, start_m = _parse_hhmm(
        (calendar or {}).get("business_hours_start"), default="09:00"
    )
    end_h, end_m = _parse_hhmm(
        (calendar or {}).get("business_hours_end"), default="17:00"
    )
    window_start = start_h * 60 + start_m
    window_end = end_h * 60 + end_m
    if window_end <= window_start:
        return int((end - start).total_seconds())

    total = 0
    cursor = start.astimezone(tz)
    end_local = end.astimezone(tz)
    guard = 0
    while cursor < end_local and guard < 50_000:
        guard += 1
        day_key = _DAY_NAMES[cursor.weekday()]
        local_date = cursor.date()
        day_end = datetime(
            local_date.year,
            local_date.month,
            local_date.day,
            end_h,
            end_m,
            tzinfo=tz,
        )
        next_midnight = datetime(
            local_date.year,
            local_date.month,
            local_date.day,
            0,
            0,
            tzinfo=tz,
        ) + timedelta(days=1)

        if day_key not in days or local_date in holidays:
            cursor = next_midnight
            continue

        day_start = datetime(
            local_date.year,
            local_date.month,
            local_date.day,
            start_h,
            start_m,
            tzinfo=tz,
        )
        segment_start = max(cursor, day_start)
        segment_end = min(end_local, day_end)
        if segment_end > segment_start:
            total += int((segment_end - segment_start).total_seconds())
        cursor = next_midnight

    return max(0, total)


def compute_due_at(
    *,
    started_at: datetime,
    target_minutes: int,
    calendar: dict[str, Any] | None = None,
) -> datetime:
    return add_business_minutes(started_at, target_minutes, calendar)


def compute_due_after_resume(
    *,
    now: datetime,
    target_minutes: int,
    elapsed_business_seconds: int,
    calendar: dict[str, Any] | None = None,
    due_at: datetime | None = None,
    paused_wall_seconds: int = 0,
) -> datetime:
    """Recompute due_at after a pause ends."""
    if not is_business_hours_calendar(calendar):
        base = ensure_aware(due_at) or now
        return base + timedelta(seconds=max(0, int(paused_wall_seconds)))

    remaining_secs = max(0, int(target_minutes) * 60 - max(0, int(elapsed_business_seconds)))
    remaining_mins = (remaining_secs + 59) // 60  # ceil to whole minutes
    if remaining_mins <= 0:
        return now
    return add_business_minutes(now, remaining_mins, calendar)
