"""Bounded-retention maintenance for the GitHub-persisted SQLite database.

The bot keeps the durable job rows long-term for deduplication, but operational
rows (delivery attempts, per-source observations, old posting mirrors, etc.) do
not need to grow forever.  This module prunes only data that is no longer used
by the live delivery path, then VACUUMs occasionally so jobs.db stays below
GitHub's large-file warning/hard-limit range.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import os
import sqlite3
from pathlib import Path

RETENTION_DAYS = 30
COMPACT_INTERVAL_HOURS = 24 * 7
COMPACT_SIZE_THRESHOLD_MB = 70
LAST_COMPACT_METADATA_KEY = "db_last_compact_at"
TERMINAL_DELIVERY_STATUSES = (
    "sent",
    "failed_permanent",
    "config_error",
    "unknown",
    "expired",
)


@dataclass(frozen=True)
class MaintenanceResult:
    ran: bool
    before_bytes: int
    after_bytes: int
    deleted_job_sends: int = 0
    deleted_delivery_attempts: int = 0
    deleted_source_history: int = 0
    deleted_source_observations: int = 0
    deleted_job_postings: int = 0

    @property
    def reclaimed_bytes(self) -> int:
        return max(0, self.before_bytes - self.after_bytes)


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_iso(value: str | None) -> datetime | None:
    text = (value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return None


def _metadata(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM metadata WHERE key = ?", (key,)).fetchone()
    return str(row[0]) if row else None


def _set_metadata(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        """
        INSERT INTO metadata(key, value) VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """,
        (key, value),
    )


def _should_run(
    conn: sqlite3.Connection,
    *,
    db_size_bytes: int,
    reference_time: datetime,
    interval_hours: int,
    size_threshold_mb: int,
) -> bool:
    if db_size_bytes >= max(1, int(size_threshold_mb)) * 1024 * 1024:
        return True
    last = _parse_iso(_metadata(conn, LAST_COMPACT_METADATA_KEY))
    if last is None:
        return True
    return reference_time - last >= timedelta(hours=max(1, int(interval_hours)))


def compact_database(
    db_path: str | Path,
    *,
    reference_time: datetime | None = None,
    retention_days: int = RETENTION_DAYS,
    interval_hours: int = COMPACT_INTERVAL_HOURS,
    size_threshold_mb: int = COMPACT_SIZE_THRESHOLD_MB,
    force: bool = False,
) -> MaintenanceResult:
    """Prune old operational rows and occasionally VACUUM the SQLite file.

    Durable rows in ``jobs`` remain untouched so historical dedup memory is
    preserved.  Old ``job_postings`` are intentionally bounded because after
    30 days the canonical URL and preferred source are already persisted on the
    job cluster, while reposts are allowed to be rediscovered as fresh work.
    """
    path = Path(db_path)
    if not path.exists():
        return MaintenanceResult(False, 0, 0)

    now = (reference_time or datetime.now(UTC)).astimezone(UTC).replace(microsecond=0)
    cutoff = _iso(now - timedelta(days=max(1, int(retention_days))))
    before = os.path.getsize(path)

    conn = sqlite3.connect(str(path))
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        if not force and not _should_run(
            conn,
            db_size_bytes=before,
            reference_time=now,
            interval_hours=interval_hours,
            size_threshold_mb=size_threshold_mb,
        ):
            return MaintenanceResult(False, before, before)

        placeholders = ",".join("?" for _ in TERMINAL_DELIVERY_STATUSES)
        cur = conn.execute(
            f"DELETE FROM job_sends WHERE updated_at < ? AND status IN ({placeholders})",
            (cutoff, *TERMINAL_DELIVERY_STATUSES),
        )
        deleted_job_sends = max(0, int(cur.rowcount or 0))

        cur = conn.execute("DELETE FROM delivery_attempts WHERE attempted_at < ?", (cutoff,))
        deleted_attempts = max(0, int(cur.rowcount or 0))

        cur = conn.execute("DELETE FROM source_run_history WHERE run_at < ?", (cutoff,))
        deleted_history = max(0, int(cur.rowcount or 0))

        cur = conn.execute("DELETE FROM source_observations WHERE last_seen_at < ?", (cutoff,))
        deleted_observations = max(0, int(cur.rowcount or 0))

        cur = conn.execute("DELETE FROM job_postings WHERE last_seen_at < ?", (cutoff,))
        deleted_postings = max(0, int(cur.rowcount or 0))

        # Long descriptions/evidence are only useful for recent enrichment and
        # admin/debug review. Keep the compact classification on the job row.
        conn.execute(
            """
            UPDATE jobs
            SET description = '', eligibility_evidence = ''
            WHERE first_seen_at < ? AND (description != '' OR eligibility_evidence != '')
            """,
            (cutoff,),
        )
        conn.commit()

        # VACUUM is deliberately infrequent (weekly unless the file is large).
        conn.execute("VACUUM")
        _set_metadata(conn, LAST_COMPACT_METADATA_KEY, _iso(now))
        conn.commit()
    finally:
        conn.close()

    after = os.path.getsize(path)
    return MaintenanceResult(
        True,
        before,
        after,
        deleted_job_sends=deleted_job_sends,
        deleted_delivery_attempts=deleted_attempts,
        deleted_source_history=deleted_history,
        deleted_source_observations=deleted_observations,
        deleted_job_postings=deleted_postings,
    )
