"""
SQLite persistence layer for the Telegram jobs bot.

This module is intentionally isolated from the current runtime flow.
It provides the database foundation for replacing seen_jobs.json with a
single SQLite file that can be committed to the GitHub Actions data branch.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Iterator, Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from models import Job

DB_FILE = "jobs.db"
SCHEMA_VERSION = 2
LEGACY_BACKLOG_MIGRATION_KEY = "legacy_backlog_expiry_v1_applied_at"

_TRACKING_QUERY_PREFIXES = (
    "utm_",
)
_TRACKING_QUERY_KEYS = {
    "fbclid",
    "gclid",
    "msclkid",
    "mc_cid",
    "mc_eid",
    "trk",
    "tracking_id",
    "ref",
    "refid",
}


@dataclass(frozen=True)
class StoredJob:
    """A persisted job row that can later be converted back to Job."""

    id: int
    source: str
    source_job_id: str
    title: str
    company: str
    location: str
    url: str
    canonical_url: str
    salary: str
    job_type: str
    tags: list
    is_remote: bool
    original_source: str
    content_hash: str
    send_status: str
    published_at_raw: str
    published_at_earliest: str
    published_at_latest: str
    published_at_est: str
    published_precision: str
    time_semantics: str
    first_seen_at: str
    last_seen_at: str

    def to_job(self) -> Job:
        return Job(
            title=self.title,
            company=self.company,
            location=self.location,
            url=self.url,
            source=self.source,
            salary=self.salary,
            job_type=self.job_type,
            tags=self.tags,
            is_remote=self.is_remote,
            original_source=self.original_source,
            source_job_id=self.source_job_id,
            published_at_raw=self.published_at_raw,
            published_at_earliest=self.published_at_earliest,
            published_at_latest=self.published_at_latest,
            published_at_est=self.published_at_est,
            published_precision=self.published_precision,
            time_semantics=self.time_semantics,
        )


@contextmanager
def connect(db_path: str | Path = DB_FILE) -> Iterator[sqlite3.Connection]:
    """Open a SQLite connection and ensure schema exists."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        _configure_connection(conn)
        init_db(conn)
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _configure_connection(conn: sqlite3.Connection) -> None:
    """Apply safe defaults for small single-file bot storage."""
    conn.execute("PRAGMA foreign_keys = ON")
    # Keep the database as one commit-friendly file for GitHub Actions.
    # WAL mode creates sidecar -wal/-shm files that are easy to forget on the data branch.
    conn.execute("PRAGMA journal_mode = DELETE")
    conn.execute("PRAGMA busy_timeout = 5000")


def init_db(conn: sqlite3.Connection) -> None:
    """Create or migrate the database schema."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL,
            source_job_id TEXT DEFAULT '',
            title TEXT NOT NULL,
            company TEXT DEFAULT '',
            location TEXT DEFAULT '',
            url TEXT NOT NULL,
            canonical_url TEXT NOT NULL,
            salary TEXT DEFAULT '',
            job_type TEXT DEFAULT '',
            tags_json TEXT DEFAULT '[]',
            is_remote INTEGER DEFAULT 0,
            original_source TEXT DEFAULT '',
            content_hash TEXT NOT NULL UNIQUE,
            send_status TEXT NOT NULL DEFAULT 'pending',
            published_at_raw TEXT DEFAULT '',
            published_at_earliest TEXT DEFAULT '',
            published_at_latest TEXT DEFAULT '',
            published_at_est TEXT DEFAULT '',
            published_precision TEXT NOT NULL DEFAULT 'NONE',
            time_semantics TEXT NOT NULL DEFAULT 'UNKNOWN',
            first_seen_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_jobs_send_status
            ON jobs(send_status, last_seen_at);

        CREATE INDEX IF NOT EXISTS idx_jobs_source
            ON jobs(source, last_seen_at);

        CREATE TABLE IF NOT EXISTS job_sends (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id INTEGER NOT NULL,
            topic_key TEXT NOT NULL,
            status TEXT NOT NULL,
            sent_at TEXT,
            error TEXT DEFAULT '',
            updated_at TEXT NOT NULL,
            UNIQUE(job_id, topic_key),
            FOREIGN KEY(job_id) REFERENCES jobs(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_job_sends_status
            ON job_sends(status, updated_at);

        CREATE TABLE IF NOT EXISTS source_runs (
            source TEXT PRIMARY KEY,
            last_run_at TEXT,
            last_success_at TEXT,
            baselined_at TEXT,
            status TEXT NOT NULL DEFAULT 'never',
            error TEXT DEFAULT '',
            consecutive_failures INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL
        );
        """
    )
    previous_row = conn.execute(
        "SELECT value FROM metadata WHERE key = 'schema_version'"
    ).fetchone()
    previous_version = int(previous_row["value"]) if previous_row else 0
    _migrate_schema(conn, previous_version=previous_version)
    conn.execute(
        "INSERT OR REPLACE INTO metadata(key, value) VALUES (?, ?)",
        ("schema_version", str(SCHEMA_VERSION)),
    )


def _column_names(conn: sqlite3.Connection, table: str) -> set[str]:
    return {str(row["name"]) for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _ensure_column(conn: sqlite3.Connection, table: str, definition: str) -> None:
    column = definition.split()[0]
    if column not in _column_names(conn, table):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {definition}")


def _migrate_schema(conn: sqlite3.Connection, previous_version: int) -> None:
    """Apply additive migrations so existing jobs.db files remain usable."""
    for definition in (
        "published_at_raw TEXT DEFAULT ''",
        "published_at_earliest TEXT DEFAULT ''",
        "published_at_latest TEXT DEFAULT ''",
        "published_at_est TEXT DEFAULT ''",
        "published_precision TEXT NOT NULL DEFAULT 'NONE'",
        "time_semantics TEXT NOT NULL DEFAULT 'UNKNOWN'",
    ):
        _ensure_column(conn, "jobs", definition)

    for definition in (
        "last_success_at TEXT",
        "baselined_at TEXT",
        "consecutive_failures INTEGER NOT NULL DEFAULT 0",
    ):
        _ensure_column(conn, "source_runs", definition)

    # Only schema-v1 databases have legacy successful sources that predate
    # explicit baselining. Do not auto-baseline sources created after v2.
    if previous_version < 2:
        conn.execute(
            """
            UPDATE source_runs
            SET last_success_at = COALESCE(last_success_at, last_run_at, updated_at),
                baselined_at = COALESCE(baselined_at, last_run_at, updated_at)
            WHERE status = 'ok'
            """
        )


def now_utc() -> str:
    """Return an ISO-8601 UTC timestamp without microseconds."""
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def get_metadata(conn: sqlite3.Connection, key: str) -> Optional[str]:
    """Return one metadata value, or None when the key does not exist."""
    row = conn.execute(
        "SELECT value FROM metadata WHERE key = ?",
        (key,),
    ).fetchone()
    return str(row["value"]) if row else None


def set_metadata(conn: sqlite3.Connection, key: str, value: str) -> None:
    """Insert or replace one metadata value."""
    conn.execute(
        "INSERT OR REPLACE INTO metadata(key, value) VALUES (?, ?)",
        (key, str(value)),
    )


def expire_legacy_backlog_once(
    conn: sqlite3.Connection,
    max_age_minutes: int,
    reference_time: datetime | None = None,
) -> int:
    """Expire legacy unsent rows once so stale backlog is never replayed.

    This is intentionally a one-time compatibility migration for databases
    created by the old retry model. It is not the final freshness gate. Future
    delivery deadlines will handle newly-created retries separately.
    """
    if max_age_minutes <= 0:
        raise ValueError("max_age_minutes must be greater than zero")

    if get_metadata(conn, LEGACY_BACKLOG_MIGRATION_KEY):
        return 0

    now = reference_time or datetime.now(UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    else:
        now = now.astimezone(UTC)

    cutoff = (now - timedelta(minutes=max_age_minutes)).replace(microsecond=0)
    cutoff_iso = cutoff.isoformat().replace("+00:00", "Z")

    cur = conn.execute(
        """
        UPDATE jobs
        SET send_status = 'expired'
        WHERE send_status IN ('pending', 'retry', 'partial')
          AND first_seen_at < ?
        """,
        (cutoff_iso,),
    )
    set_metadata(
        conn,
        LEGACY_BACKLOG_MIGRATION_KEY,
        now.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    )
    return int(cur.rowcount)


def normalize_text(value: object) -> str:
    """Normalize text for stable hashing and comparisons."""
    if value is None:
        return ""
    text = str(value).strip().lower()
    text = re.sub(r"\s+", " ", text)
    return text


def normalize_company(value: object) -> str:
    """Normalize company names without corrupting words like 'agency'."""
    text = normalize_text(value)
    suffixes = r"\b(inc|inc\.|ltd|ltd\.|llc|corp|corporation|company|co\.|gmbh|ag|sa|pvt)\b"
    text = re.sub(suffixes, "", text)
    text = re.sub(r"\s+", " ", text).strip(" ,.-")
    return text


def canonicalize_url(url: str) -> str:
    """Return a stable URL by removing common tracking parameters."""
    if not url:
        return ""

    split = urlsplit(url.strip())
    scheme = split.scheme.lower() or "https"
    netloc = split.netloc.lower()
    path = split.path.rstrip("/") or split.path

    kept_query_pairs: list[tuple[str, str]] = []
    for key, value in parse_qsl(split.query, keep_blank_values=True):
        key_l = key.lower()
        if key_l in _TRACKING_QUERY_KEYS:
            continue
        if any(key_l.startswith(prefix) for prefix in _TRACKING_QUERY_PREFIXES):
            continue
        kept_query_pairs.append((key, value))

    query = urlencode(kept_query_pairs, doseq=True)
    return urlunsplit((scheme, netloc, path, query, ""))


def job_content_hash(job: Job) -> str:
    """Create a cross-source dedup hash for the job identity."""
    canonical_url = canonicalize_url(job.url)
    # Prefer URL when available because job boards often have stable job IDs in URLs.
    # Include title/company/location to reduce the risk of unrelated redirect URLs merging.
    raw = "|".join(
        [
            normalize_text(job.title),
            normalize_company(job.company),
            normalize_text(job.location),
            canonical_url,
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def upsert_job(conn: sqlite3.Connection, job: Job) -> tuple[int, bool]:
    """
    Insert or refresh a job.

    Returns:
        (job_id, is_new)
    """
    if not job.title or not job.url:
        raise ValueError("Job must have a title and url before persistence.")

    ts = now_utc()
    canonical_url = canonicalize_url(job.url)
    content_hash = job_content_hash(job)
    source_job_id = str(job.source_job_id or "")
    tags_json = json.dumps(job.tags or [], ensure_ascii=False, sort_keys=True)

    existing = conn.execute(
        "SELECT id FROM jobs WHERE content_hash = ?",
        (content_hash,),
    ).fetchone()

    if existing:
        job_id = int(existing["id"])
        conn.execute(
            """
            UPDATE jobs
            SET source = ?, source_job_id = ?, title = ?, company = ?, location = ?,
                url = ?, canonical_url = ?, salary = ?, job_type = ?, tags_json = ?,
                is_remote = ?, original_source = ?,
                published_at_raw = COALESCE(NULLIF(?, ''), published_at_raw),
                published_at_earliest = COALESCE(NULLIF(?, ''), published_at_earliest),
                published_at_latest = COALESCE(NULLIF(?, ''), published_at_latest),
                published_at_est = COALESCE(NULLIF(?, ''), published_at_est),
                published_precision = CASE WHEN ? != 'NONE' THEN ? ELSE published_precision END,
                time_semantics = CASE WHEN ? != 'UNKNOWN' THEN ? ELSE time_semantics END,
                last_seen_at = ?
            WHERE id = ?
            """,
            (
                job.source,
                source_job_id,
                job.title,
                job.company or "",
                job.location or "",
                job.url,
                canonical_url,
                job.salary or "",
                job.job_type or "",
                tags_json,
                1 if job.is_remote else 0,
                job.original_source or "",
                job.published_at_raw or "",
                job.published_at_earliest or "",
                job.published_at_latest or "",
                job.published_at_est or "",
                job.published_precision or "NONE",
                job.published_precision or "NONE",
                job.time_semantics or "UNKNOWN",
                job.time_semantics or "UNKNOWN",
                ts,
                job_id,
            ),
        )
        return job_id, False

    cur = conn.execute(
        """
        INSERT INTO jobs (
            source, source_job_id, title, company, location, url, canonical_url,
            salary, job_type, tags_json, is_remote, original_source,
            content_hash, send_status, published_at_raw, published_at_earliest,
            published_at_latest, published_at_est, published_precision, time_semantics,
            first_seen_at, last_seen_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            job.source,
            source_job_id,
            job.title,
            job.company or "",
            job.location or "",
            job.url,
            canonical_url,
            job.salary or "",
            job.job_type or "",
            tags_json,
            1 if job.is_remote else 0,
            job.original_source or "",
            content_hash,
            job.published_at_raw or "",
            job.published_at_earliest or "",
            job.published_at_latest or "",
            job.published_at_est or "",
            job.published_precision or "NONE",
            job.time_semantics or "UNKNOWN",
            ts,
            ts,
        ),
    )
    return int(cur.lastrowid), True


def upsert_jobs(conn: sqlite3.Connection, jobs: list[Job]) -> tuple[int, int]:
    """Persist many jobs and return (inserted_count, refreshed_count)."""
    inserted = 0
    refreshed = 0
    for job in jobs:
        _, is_new = upsert_job(conn, job)
        if is_new:
            inserted += 1
        else:
            refreshed += 1
    return inserted, refreshed


def get_jobs_for_sending(conn: sqlite3.Connection, limit: int = 100) -> list[StoredJob]:
    """Return jobs that are still pending or need retry."""
    rows = conn.execute(
        """
        SELECT * FROM jobs
        WHERE send_status IN ('pending', 'retry', 'partial')
        ORDER BY first_seen_at ASC, id ASC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [_row_to_stored_job(row) for row in rows]


def record_topic_send(
    conn: sqlite3.Connection,
    job_id: int,
    topic_key: str,
    success: bool,
    error: str = "",
) -> None:
    """Record the Telegram send result for one job/topic pair."""
    ts = now_utc()
    status = "sent" if success else "failed"
    sent_at = ts if success else None
    conn.execute(
        """
        INSERT INTO job_sends(job_id, topic_key, status, sent_at, error, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(job_id, topic_key) DO UPDATE SET
            status = excluded.status,
            sent_at = excluded.sent_at,
            error = excluded.error,
            updated_at = excluded.updated_at
        """,
        (job_id, topic_key, status, sent_at, error or "", ts),
    )




def get_sent_topic_keys(conn: sqlite3.Connection, job_id: int) -> set[str]:
    """Return topic keys already sent successfully for a job."""
    rows = conn.execute(
        "SELECT topic_key FROM job_sends WHERE job_id = ? AND status = 'sent'",
        (job_id,),
    ).fetchall()
    return {str(row["topic_key"]) for row in rows}

def set_job_send_status(conn: sqlite3.Connection, job_id: int, status: str) -> None:
    """Set the aggregate send status for a job."""
    allowed = {"pending", "sent", "retry", "partial", "skipped", "expired"}
    if status not in allowed:
        raise ValueError(f"Invalid send status: {status}")
    conn.execute("UPDATE jobs SET send_status = ? WHERE id = ?", (status, job_id))


def update_source_run(
    conn: sqlite3.Connection,
    source: str,
    status: str,
    error: str = "",
    last_run_at: Optional[str] = None,
) -> None:
    """Record source run health/timing without implicitly baselining new sources."""
    ts = now_utc()
    run_at = last_run_at or ts
    is_ok = status == "ok"
    conn.execute(
        """
        INSERT INTO source_runs(
            source, last_run_at, last_success_at, baselined_at, status, error,
            consecutive_failures, updated_at
        )
        VALUES (?, ?, ?, NULL, ?, ?, ?, ?)
        ON CONFLICT(source) DO UPDATE SET
            last_run_at = excluded.last_run_at,
            last_success_at = CASE
                WHEN excluded.status = 'ok' THEN excluded.last_run_at
                ELSE source_runs.last_success_at
            END,
            status = excluded.status,
            error = excluded.error,
            consecutive_failures = CASE
                WHEN excluded.status = 'ok' THEN 0
                ELSE source_runs.consecutive_failures + 1
            END,
            updated_at = excluded.updated_at
        """,
        (source, run_at, run_at if is_ok else None, status, error or "", 0 if is_ok else 1, ts),
    )


def get_source_state(conn: sqlite3.Connection, source: str) -> Optional[sqlite3.Row]:
    """Return the persisted state row for a source."""
    return conn.execute("SELECT * FROM source_runs WHERE source = ?", (source,)).fetchone()


def is_source_baselined(conn: sqlite3.Connection, source: str) -> bool:
    """Return whether a source has completed its initial no-send baseline."""
    row = get_source_state(conn, source)
    return bool(row and row["baselined_at"])


def mark_source_baselined(
    conn: sqlite3.Connection,
    source: str,
    baselined_at: Optional[str] = None,
) -> None:
    """Mark a source baseline explicitly after its initial results are stored."""
    ts = baselined_at or now_utc()
    conn.execute(
        "UPDATE source_runs SET baselined_at = ?, updated_at = ? WHERE source = ?",
        (ts, now_utc(), source),
    )


def get_source_last_success(conn: sqlite3.Connection, source: str) -> Optional[str]:
    """Return the last successful source fetch timestamp, if available."""
    row = get_source_state(conn, source)
    return str(row["last_success_at"]) if row and row["last_success_at"] else None


def get_source_last_run(conn: sqlite3.Connection, source: str) -> Optional[str]:
    """Return the last run timestamp for a source, if available."""
    row = conn.execute(
        "SELECT last_run_at FROM source_runs WHERE source = ?",
        (source,),
    ).fetchone()
    return str(row["last_run_at"]) if row and row["last_run_at"] else None


def count_jobs(conn: sqlite3.Connection) -> int:
    """Return total persisted jobs."""
    row = conn.execute("SELECT COUNT(*) AS c FROM jobs").fetchone()
    return int(row["c"])


def _row_to_stored_job(row: sqlite3.Row) -> StoredJob:
    tags = []
    try:
        loaded = json.loads(row["tags_json"] or "[]")
        tags = loaded if isinstance(loaded, list) else []
    except json.JSONDecodeError:
        tags = []

    return StoredJob(
        id=int(row["id"]),
        source=row["source"],
        source_job_id=row["source_job_id"] or "",
        title=row["title"],
        company=row["company"] or "",
        location=row["location"] or "",
        url=row["url"],
        canonical_url=row["canonical_url"],
        salary=row["salary"] or "",
        job_type=row["job_type"] or "",
        tags=tags,
        is_remote=bool(row["is_remote"]),
        original_source=row["original_source"] or "",
        content_hash=row["content_hash"],
        send_status=row["send_status"],
        published_at_raw=row["published_at_raw"] or "",
        published_at_earliest=row["published_at_earliest"] or "",
        published_at_latest=row["published_at_latest"] or "",
        published_at_est=row["published_at_est"] or "",
        published_precision=row["published_precision"] or "NONE",
        time_semantics=row["time_semantics"] or "UNKNOWN",
        first_seen_at=row["first_seen_at"],
        last_seen_at=row["last_seen_at"],
    )
