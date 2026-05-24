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
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterator, Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from models import Job

DB_FILE = "jobs.db"
SCHEMA_VERSION = 1

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
            status TEXT NOT NULL DEFAULT 'never',
            error TEXT DEFAULT '',
            updated_at TEXT NOT NULL
        );
        """
    )
    conn.execute(
        "INSERT OR REPLACE INTO metadata(key, value) VALUES (?, ?)",
        ("schema_version", str(SCHEMA_VERSION)),
    )


def now_utc() -> str:
    """Return an ISO-8601 UTC timestamp without microseconds."""
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


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
    source_job_id = str(getattr(job, "source_job_id", "") or "")
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
                is_remote = ?, original_source = ?, last_seen_at = ?
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
            content_hash, send_status, first_seen_at, last_seen_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)
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
    allowed = {"pending", "sent", "retry", "partial", "skipped"}
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
    """Record source run health/timing."""
    ts = now_utc()
    conn.execute(
        """
        INSERT INTO source_runs(source, last_run_at, status, error, updated_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(source) DO UPDATE SET
            last_run_at = excluded.last_run_at,
            status = excluded.status,
            error = excluded.error,
            updated_at = excluded.updated_at
        """,
        (source, last_run_at or ts, status, error or "", ts),
    )


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
        first_seen_at=row["first_seen_at"],
        last_seen_at=row["last_seen_at"],
    )
