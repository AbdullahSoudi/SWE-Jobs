"""Optional private admin monitoring for the job bot.

This module intentionally keeps operational notifications out of the public
Telegram forum.  When ``TELEGRAM_ADMIN_CHAT_ID`` is configured, the bot sends
rare health-transition alerts plus one compact digest roughly every 24 hours.
Without that environment variable the runtime behaviour is unchanged.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Iterable

from config import (
    ADMIN_DIGEST_INTERVAL_HOURS,
    TELEGRAM_ADMIN_CHAT_ID,
    TELEGRAM_BOT_TOKEN,
)
from db import get_metadata, set_metadata
from freshness import ensure_utc, iso_utc
from source_analytics import build_source_analytics
from telegram_sender import CONFIG_ERROR, TelegramClient, TelegramSendResult

ADMIN_LAST_DIGEST_AT_KEY = "admin_last_digest_at"
ADMIN_ACTIVE_ADAPTER_OUTAGES_KEY = "admin_active_adapter_outages"
ADMIN_COVERAGE_GAP_PREFIX = "admin_coverage_gap:"
BAD_HEALTH = {"DEGRADED", "UNHEALTHY"}


def _parse_iso(value: str | None) -> datetime | None:
    text = (value or "").strip()
    if not text:
        return None
    try:
        return ensure_utc(datetime.fromisoformat(text.replace("Z", "+00:00")))
    except ValueError:
        return None


def health_transition_event(
    source: str,
    previous_health: str | None,
    current_health: str | None,
    *,
    error: str = "",
) -> str | None:
    """Return one alert line only when source health crosses a useful boundary."""
    previous = (previous_health or "UNKNOWN").upper()
    current = (current_health or "UNKNOWN").upper()
    if current == previous:
        return None

    if current in BAD_HEALTH:
        suffix = f" — {error[:180]}" if error else ""
        return f"⚠️ {source}: {previous} → {current}{suffix}"
    if previous in BAD_HEALTH and current not in BAD_HEALTH:
        return f"✅ {source}: recovered ({previous} → {current})"
    return None


def sync_coverage_gap_event(conn, source: str, active: bool) -> str | None:
    """Persist coverage-gap alert state so delayed cron runs do not spam admins."""
    key = f"{ADMIN_COVERAGE_GAP_PREFIX}{source}"
    was_active = get_metadata(conn, key) == "1"
    if active == was_active:
        return None
    set_metadata(conn, key, "1" if active else "0")
    if active:
        return f"⏱️ {source}: freshness coverage gap detected"
    return f"✅ {source}: freshness coverage restored"


def sync_adapter_outage_events(conn, active_outages: Iterable[str]) -> list[str]:
    """Return only new/recovered ATS adapter outage events."""
    current = {str(value).strip().lower() for value in active_outages if str(value).strip()}
    previous_raw = get_metadata(conn, ADMIN_ACTIVE_ADAPTER_OUTAGES_KEY) or ""
    previous = {value for value in previous_raw.split(",") if value}

    events: list[str] = []
    for adapter in sorted(current - previous):
        events.append(f"🚨 ATS adapter outage suspected: {adapter}")
    for adapter in sorted(previous - current):
        events.append(f"✅ ATS adapter recovered: {adapter}")

    set_metadata(conn, ADMIN_ACTIVE_ADAPTER_OUTAGES_KEY, ",".join(sorted(current)))
    return events


def digest_due(
    conn,
    *,
    reference_time: datetime,
    interval_hours: int = ADMIN_DIGEST_INTERVAL_HOURS,
) -> bool:
    """Return True when the optional admin digest should be sent."""
    now = ensure_utc(reference_time)
    last = _parse_iso(get_metadata(conn, ADMIN_LAST_DIGEST_AT_KEY))
    if last is None:
        return True
    return now - last >= timedelta(hours=max(1, int(interval_hours)))


def mark_digest_sent(conn, *, reference_time: datetime) -> None:
    set_metadata(conn, ADMIN_LAST_DIGEST_AT_KEY, iso_utc(reference_time))


def _delivery_counts(conn, since_iso: str) -> dict[str, int]:
    rows = conn.execute(
        """
        SELECT outcome, COUNT(*) AS c
        FROM delivery_attempts
        WHERE attempted_at >= ?
        GROUP BY outcome
        """,
        (since_iso,),
    ).fetchall()
    return {str(row["outcome"]): int(row["c"] or 0) for row in rows}


def _health_counts(conn, since_iso: str) -> dict[str, int]:
    rows = conn.execute(
        """
        SELECT health_status, COUNT(*) AS c
        FROM source_runs
        WHERE last_run_at >= ?
        GROUP BY health_status
        """,
        (since_iso,),
    ).fetchall()
    return {str(row["health_status"] or "UNKNOWN"): int(row["c"] or 0) for row in rows}


def build_daily_digest(conn, *, reference_time: datetime) -> str:
    """Build a compact 24-hour operational digest for a private admin chat."""
    now = ensure_utc(reference_time)
    since = iso_utc(now - timedelta(hours=24))
    run = conn.execute(
        """
        SELECT
            COUNT(*) AS runs,
            SUM(CASE WHEN status = 'ok' THEN 1 ELSE 0 END) AS ok_runs,
            SUM(CASE WHEN status != 'ok' THEN 1 ELSE 0 END) AS failed_runs,
            COALESCE(SUM(raw_count), 0) AS raw_count,
            COALESCE(SUM(filtered_count), 0) AS relevant_count,
            COALESCE(SUM(fresh_count), 0) AS fresh_count,
            COALESCE(SUM(shadow_eligible_count), 0) AS shadow_count,
            COALESCE(SUM(coverage_gap), 0) AS coverage_gaps
        FROM source_run_history
        WHERE run_at >= ?
        """,
        (since,),
    ).fetchone()

    delivery = _delivery_counts(conn, since)
    health = _health_counts(conn, since)
    tracked_sources = sum(health.values())

    shadow_rows = conn.execute(
        """
        SELECT source, SUM(shadow_eligible_count) AS c
        FROM source_run_history
        WHERE run_at >= ? AND shadow_mode = 1
        GROUP BY source
        HAVING SUM(shadow_eligible_count) > 0
        ORDER BY c DESC, source
        LIMIT 5
        """,
        (since,),
    ).fetchall()

    analytics = build_source_analytics(
        conn,
        sources=("linkedin", "linkedin_saudi_v2"),
        hours=24,
        saudi_only=True,
        reference_time=now,
    )

    lines = [
        "🤖 Job Bot — 24h Admin Digest",
        "",
        (
            f"Sources: {tracked_sources} tracked · "
            f"{health.get('HEALTHY', 0)} healthy · {health.get('IDLE', 0)} idle · "
            f"{health.get('QUIET', 0)} quiet · {health.get('DEGRADED', 0)} degraded · "
            f"{health.get('UNHEALTHY', 0)} unhealthy"
        ),
        (
            f"Source runs: {int(run['ok_runs'] or 0)}/{int(run['runs'] or 0)} ok · "
            f"failures {int(run['failed_runs'] or 0)} · gaps {int(run['coverage_gaps'] or 0)}"
        ),
        (
            f"Jobs: {int(run['raw_count'] or 0)} fetched · "
            f"{int(run['relevant_count'] or 0)} relevant · {int(run['fresh_count'] or 0)} fresh · "
            f"{int(run['shadow_count'] or 0)} shadow candidates"
        ),
        (
            f"Telegram: {delivery.get('SENT', 0)} sent · "
            f"{delivery.get('RATE_LIMITED', 0)} rate-limited · "
            f"{delivery.get('UNKNOWN', 0)} unknown · "
            f"{delivery.get('CONFIG_ERROR', 0)} config errors"
        ),
    ]

    if analytics:
        lines.extend(["", "Saudi discovery:"])
        for row in analytics:
            lead = "n/a" if row.median_lead_minutes is None else f"{row.median_lead_minutes:.0f}m"
            lines.append(
                f"• {row.source}: first {row.first_discoveries} · "
                f"exclusive {row.exclusive_24h}/{row.mature_first_discoveries} · lead {lead}"
            )

    if shadow_rows:
        lines.extend(["", "Top shadow candidates:"])
        for row in shadow_rows:
            lines.append(f"• {row['source']}: {int(row['c'] or 0)}")

    return "\n".join(lines)[:3900]


def format_event_batch(events: Iterable[str]) -> str:
    clean = [str(event).strip() for event in events if str(event).strip()]
    if not clean:
        return ""
    return ("🚨 Job Bot Health\n\n" + "\n".join(f"• {event}" for event in clean))[:3900]


def send_admin_message(
    message: str,
    *,
    admin_chat_id: str = TELEGRAM_ADMIN_CHAT_ID,
    bot_token: str = TELEGRAM_BOT_TOKEN,
    client_factory=TelegramClient,
) -> TelegramSendResult:
    """Send one private admin message; no-op safely when not configured."""
    if not admin_chat_id or not bot_token or not message.strip():
        return TelegramSendResult(False, CONFIG_ERROR, "Admin chat is not configured")
    client = client_factory(bot_token=bot_token, group_id=admin_chat_id)
    return client.send_message(message, use_html=False, allow_plain_fallback=False)
