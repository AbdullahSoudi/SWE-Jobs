"""Scheduling and health helpers for persisted job sources.

The GitHub workflow still wakes every 15 minutes, but individual sources may
run less often. Source state is persisted in SQLite so expanding the Saudi ATS
registry does not multiply request volume linearly with every workflow run.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Mapping

DEFAULT_POLL_INTERVAL_MINUTES = 15
FAILURE_RETRY_INTERVAL_MINUTES = 15


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def parse_utc(value: str | None) -> datetime | None:
    text = (value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return _ensure_utc(parsed)


def iso_utc(value: datetime) -> str:
    return _ensure_utc(value).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def normalize_poll_interval(value: int | str | None) -> int:
    """Return a safe polling interval; GitHub itself only wakes every 15 min."""
    try:
        minutes = int(value or DEFAULT_POLL_INTERVAL_MINUTES)
    except (TypeError, ValueError):
        minutes = DEFAULT_POLL_INTERVAL_MINUTES
    return max(DEFAULT_POLL_INTERVAL_MINUTES, minutes)


def is_source_due(state, *, now: datetime, poll_interval_minutes: int) -> bool:
    """Return True when a source should be fetched on this workflow run."""
    if state is None:
        return True

    next_poll = None
    if "next_poll_at" in state.keys():
        next_poll = parse_utc(state["next_poll_at"])
    if next_poll is not None:
        return _ensure_utc(now) >= next_poll

    last_run = parse_utc(state["last_run_at"] if "last_run_at" in state.keys() else None)
    if last_run is None:
        return True
    interval = normalize_poll_interval(poll_interval_minutes)
    return _ensure_utc(now) >= last_run + timedelta(minutes=interval)


def compute_next_poll_at(
    *,
    run_at: datetime,
    status: str,
    poll_interval_minutes: int,
) -> str:
    """Schedule a normal poll after success and a quick retry after failure."""
    interval = normalize_poll_interval(poll_interval_minutes)
    if (status or "").lower() != "ok":
        interval = min(interval, FAILURE_RETRY_INTERVAL_MINUTES)
    return iso_utc(_ensure_utc(run_at) + timedelta(minutes=interval))


def classify_source_health(
    source_key: str,
    *,
    status: str,
    raw_count: int,
    previous_state=None,
    empty_warning_threshold: int = 4,
) -> str:
    """Classify health without treating an idle ATS tenant as broken.

    ATS feeds often legitimately have zero Saudi jobs for long periods, so an
    empty successful ATS fetch is IDLE. Search/board sources are marked
    DEGRADED only after repeated successful empty runs. Transport/schema
    failures become DEGRADED immediately and UNHEALTHY after three in a row.
    """
    prev_failures = 0
    prev_empty = 0
    if previous_state is not None:
        if "consecutive_failures" in previous_state.keys():
            prev_failures = int(previous_state["consecutive_failures"] or 0)
        if "consecutive_empty_runs" in previous_state.keys():
            prev_empty = int(previous_state["consecutive_empty_runs"] or 0)

    if (status or "").lower() != "ok":
        failures = prev_failures + 1
        return "UNHEALTHY" if failures >= 3 else "DEGRADED"

    if int(raw_count or 0) > 0:
        return "HEALTHY"

    if (source_key or "").startswith("ats_"):
        return "IDLE"

    empty_runs = prev_empty + 1
    if empty_runs >= max(1, int(empty_warning_threshold)):
        return "DEGRADED"
    return "QUIET"


def detect_ats_adapter_outages(source_statuses: Mapping[str, str]) -> list[str]:
    """Return ATS platform names whose multiple tenants all failed this run.

    A single tenant failure is a tenant problem. Two or more tenants on the
    same adapter failing together is a stronger signal that the shared adapter
    or upstream platform changed.
    """
    grouped: dict[str, list[str]] = {}
    for source, status in source_statuses.items():
        parts = (source or "").split("_")
        if len(parts) < 3 or parts[0] != "ats":
            continue
        grouped.setdefault(parts[1], []).append((status or "").lower())

    outages: list[str] = []
    for platform, statuses in sorted(grouped.items()):
        if len(statuses) >= 2 and all(status != "ok" for status in statuses):
            outages.append(platform)
    return outages
