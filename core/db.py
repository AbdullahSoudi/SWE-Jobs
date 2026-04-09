"""
core/db.py — Database access layer for SWE-Jobs v2.

All Postgres I/O flows through this module. Uses psycopg2 with a simple
connection pool. Import and call functions directly; no ORM involved.
"""

import json
import logging
from contextlib import contextmanager
from typing import Optional

import psycopg2
import psycopg2.extras
from psycopg2.extras import Json, RealDictCursor
from psycopg2.pool import SimpleConnectionPool

from core.config import (
    SUPABASE_DB_HOST,
    SUPABASE_DB_PORT,
    SUPABASE_DB_NAME,
    SUPABASE_DB_USER,
    SUPABASE_DB_PASSWORD,
)

logger = logging.getLogger(__name__)

# =============================================================================
# Connection pool
# =============================================================================

_pool: Optional[SimpleConnectionPool] = None


def _get_pool() -> SimpleConnectionPool:
    """Lazy-initialise the connection pool on first use."""
    global _pool
    if _pool is None:
        _pool = SimpleConnectionPool(
            minconn=1,
            maxconn=5,
            host=SUPABASE_DB_HOST,
            port=SUPABASE_DB_PORT,
            dbname=SUPABASE_DB_NAME,
            user=SUPABASE_DB_USER,
            password=SUPABASE_DB_PASSWORD,
            sslmode="require",
            options="-c search_path=public",
        )
    return _pool


@contextmanager
def _get_conn():
    """
    Context manager: borrow a connection from the pool.
    Commits on clean exit, rolls back on exception, always returns to pool.
    """
    pool = _get_pool()
    conn = pool.getconn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        pool.putconn(conn)


def close_pool() -> None:
    """Close all connections in the pool (call at process exit)."""
    global _pool
    if _pool is not None:
        _pool.closeall()
        _pool = None


# =============================================================================
# Low-level helpers
# =============================================================================

def _execute(sql: str, params=()):
    """
    Execute a write statement.
    If the statement has a RETURNING clause, return the first row as a dict;
    otherwise return None.
    """
    with _get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, params)
            if cur.description:
                row = cur.fetchone()
                return dict(row) if row else None
            return None


def _fetchone(sql: str, params=()):
    """Execute a SELECT and return the first row as a dict, or None."""
    with _get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, params)
            row = cur.fetchone()
            return dict(row) if row else None


def _fetchall(sql: str, params=()):
    """Execute a SELECT and return all rows as a list of dicts."""
    with _get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
            return [dict(r) for r in rows]


# =============================================================================
# Jobs CRUD
# =============================================================================

# Columns that update_job() is allowed to touch (whitelist prevents SQL injection
# via dynamic column names).
_JOBS_UPDATABLE_COLUMNS = {
    "title",
    "company",
    "location",
    "url",
    "source",
    "original_source",
    "salary_raw",
    "salary_min",
    "salary_max",
    "salary_currency",
    "job_type",
    "seniority",
    "is_remote",
    "country",
    "tags",
    "topics",
    "sent_at",
    "telegram_message_ids",
}

# JSONB columns that need to be wrapped with psycopg2 Json()
_JSONB_COLUMNS = {"tags", "topics", "telegram_message_ids"}


def insert_job(job) -> Optional[dict]:
    """
    Insert a Job, ignoring duplicates by unique_id.

    Returns the inserted row dict (with id) or None if the row already existed.

    NOTE: DO NOTHING will be upgraded to DO UPDATE in Plan 2 (fuzzy dedup).
    """
    row = job.to_db_row()
    columns = ", ".join(row.keys())
    placeholders = ", ".join(f"%({k})s" for k in row.keys())
    sql = (
        f"INSERT INTO jobs ({columns}) "
        f"VALUES ({placeholders}) "
        f"ON CONFLICT (unique_id) DO NOTHING "
        f"RETURNING *"
    )
    return _execute(sql, row)


def insert_jobs_batch(jobs: list) -> list[dict]:
    """
    Batch-insert multiple Jobs in a single transaction using execute_values.
    Skips duplicates by unique_id (ON CONFLICT DO NOTHING).

    Returns list of inserted row dicts (with id and unique_id).
    """
    if not jobs:
        return []

    rows = [job.to_db_row() for job in jobs]
    columns = list(rows[0].keys())
    col_str = ", ".join(columns)
    template = "(" + ", ".join(f"%({k})s" for k in columns) + ")"
    sql = (
        f"INSERT INTO jobs ({col_str}) VALUES %s "
        f"ON CONFLICT (unique_id) DO NOTHING "
        f"RETURNING id, unique_id"
    )

    with _get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            result = psycopg2.extras.execute_values(
                cur, sql, rows,
                template=template,
                page_size=100,
                fetch=True,
            )
            inserted = [dict(r) for r in result]
    return inserted


def fuzzy_dedup_batch(jobs: list) -> list:
    """
    Filter out fuzzy duplicates against the DB.
    Fetches recent DB jobs once, then compares in Python using
    SequenceMatcher (avoids N individual DB round trips).

    Returns the list of jobs that are NOT fuzzy duplicates.
    """
    if not jobs:
        return []

    # Fetch all recent titles+companies in one query
    existing = _fetchall(
        "SELECT id, lower(title) AS title, lower(company) AS company "
        "FROM jobs WHERE created_at > now() - INTERVAL '7 days'"
    )
    if not existing:
        logger.info("Fuzzy dedup: skipped (no recent jobs in DB)")
        return jobs

    # Group by company for fast lookup
    from collections import defaultdict
    from difflib import SequenceMatcher
    by_company: dict[str, list[str]] = defaultdict(list)
    for row in existing:
        by_company[row["company"]].append(row["title"])

    kept = []
    for job in jobs:
        company_lower = job.company.lower()
        if company_lower not in by_company:
            kept.append(job)
            continue
        title_lower = job.title.lower()
        is_dupe = any(
            SequenceMatcher(None, title_lower, existing_title).ratio() > 0.7
            for existing_title in by_company[company_lower]
        )
        if not is_dupe:
            kept.append(job)

    return kept


def job_exists(unique_id: str) -> bool:
    """Return True if a job with the given unique_id already exists."""
    row = _fetchone(
        "SELECT id FROM jobs WHERE unique_id = %s",
        (unique_id,),
    )
    return row is not None


def get_job_by_unique_id(unique_id: str):
    """
    Fetch a single Job by unique_id.
    Returns a Job instance or None if not found.
    """
    from core.models import Job  # local import avoids circular dependency risk

    row = _fetchone(
        "SELECT * FROM jobs WHERE unique_id = %s",
        (unique_id,),
    )
    if row is None:
        return None
    return Job.from_db_row(row)


def get_unsent_jobs(limit: int = 50):
    """
    Return up to `limit` jobs that have not yet been sent to Telegram,
    ordered oldest-first.
    """
    from core.models import Job

    rows = _fetchall(
        "SELECT * FROM jobs WHERE sent_at IS NULL ORDER BY created_at ASC LIMIT %s",
        (limit,),
    )
    return [Job.from_db_row(r) for r in rows]


def mark_job_sent(job_id: int, telegram_message_ids: dict) -> None:
    """Record that a job was sent; store the per-channel Telegram message IDs."""
    _execute(
        "UPDATE jobs SET sent_at = now(), telegram_message_ids = %s WHERE id = %s",
        (json.dumps(telegram_message_ids), job_id),
    )


def get_recent_jobs_for_dedup(days: int = 7):
    """
    Return jobs created within the last `days` days, for dedup comparison.

    IMPORTANT: uses make_interval(days := %s) — NOT interval '%s days'
    (the latter is vulnerable to SQL injection).
    """
    from core.models import Job

    rows = _fetchall(
        "SELECT * FROM jobs WHERE created_at > now() - make_interval(days := %s)",
        (days,),
    )
    return [Job.from_db_row(r) for r in rows]


def update_job(job_id: int, updates: dict) -> None:
    """
    Partially update a job row.

    Column names are validated against _JOBS_UPDATABLE_COLUMNS to prevent
    SQL injection via dynamic column names. JSONB columns are wrapped with Json().
    """
    bad_keys = set(updates) - _JOBS_UPDATABLE_COLUMNS
    if bad_keys:
        raise ValueError(f"update_job: disallowed column(s): {bad_keys}")

    # Wrap JSONB values
    safe_updates = {
        k: (Json(v) if k in _JSONB_COLUMNS and not isinstance(v, Json) else v)
        for k, v in updates.items()
    }

    set_clause = ", ".join(f"{col} = %s" for col in safe_updates)
    values = list(safe_updates.values()) + [job_id]
    sql = f"UPDATE jobs SET {set_clause} WHERE id = %s"
    _execute(sql, values)


# =============================================================================
# Bot Runs
# =============================================================================

def start_run() -> int:
    """
    Insert a new bot_runs row with all defaults and return its id.
    """
    row = _fetchone(
        "INSERT INTO bot_runs DEFAULT VALUES RETURNING id",
    )
    return row["id"]


def finish_run(
    run_id: int,
    jobs_fetched: int = 0,
    jobs_filtered: int = 0,
    jobs_new: int = 0,
    jobs_sent: int = 0,
    source_stats: Optional[dict] = None,
    errors: Optional[list] = None,
) -> None:
    """
    Mark a bot_run as finished and record summary statistics.
    """
    _execute(
        """
        UPDATE bot_runs
        SET
            finished_at   = now(),
            jobs_fetched  = %s,
            jobs_filtered = %s,
            jobs_new      = %s,
            jobs_sent     = %s,
            source_stats  = %s,
            errors        = %s
        WHERE id = %s
        """,
        (
            jobs_fetched,
            jobs_filtered,
            jobs_new,
            jobs_sent,
            json.dumps(source_stats or {}),
            json.dumps(errors or []),
            run_id,
        ),
    )


# =============================================================================
# Source Health (circuit breaker)
# =============================================================================

def get_source_health(source: str) -> Optional[dict]:
    """Return the source_health row for a given source, or None."""
    return _fetchone(
        "SELECT * FROM source_health WHERE source = %s",
        (source,),
    )


def upsert_source_health(source: str, success: bool, error: str = "") -> None:
    """
    Record the result of a source fetch attempt.

    On success: reset consecutive_failures to 0 and clear circuit_open_until.
    On failure: increment failures; if >= 3 consecutive, open the circuit for
                1 hour.

    Error message is truncated to 200 characters.
    """
    error = (error or "")[:200]

    if success:
        _execute(
            """
            INSERT INTO source_health (source, last_success_at, consecutive_failures, last_error)
            VALUES (%s, now(), 0, '')
            ON CONFLICT (source) DO UPDATE SET
                last_success_at       = now(),
                consecutive_failures  = 0,
                circuit_open_until    = NULL,
                last_error            = ''
            """,
            (source,),
        )
    else:
        _execute(
            """
            INSERT INTO source_health (source, last_failure_at, consecutive_failures, last_error)
            VALUES (%s, now(), 1, %s)
            ON CONFLICT (source) DO UPDATE SET
                last_failure_at      = now(),
                consecutive_failures = source_health.consecutive_failures + 1,
                last_error           = %s,
                circuit_open_until   = CASE
                    WHEN source_health.consecutive_failures + 1 >= 3
                    THEN now() + INTERVAL '1 hour'
                    ELSE source_health.circuit_open_until
                END
            """,
            (source, error, error),
        )


def is_source_circuit_open(source: str) -> bool:
    """
    Return True if the circuit breaker is currently open for this source.

    Uses a single query — NOT two round trips — to evaluate the condition
    directly in the database.
    """
    row = _fetchone(
        "SELECT circuit_open_until > now() AS is_open FROM source_health WHERE source = %s",
        (source,),
    )
    if row is None:
        return False
    return bool(row.get("is_open", False))


# =============================================================================
# Users
# =============================================================================

def get_or_create_user(telegram_id: int, username: str = "") -> dict:
    """
    Return the user row for telegram_id, creating it first if absent.
    """
    row = _fetchone(
        "SELECT * FROM users WHERE telegram_id = %s",
        (telegram_id,),
    )
    if row is not None:
        return row

    new_row = _fetchone(
        """
        INSERT INTO users (telegram_id, username)
        VALUES (%s, %s)
        ON CONFLICT (telegram_id) DO UPDATE SET username = EXCLUDED.username
        RETURNING *
        """,
        (telegram_id, username),
    )
    return new_row


def update_user_subscriptions(telegram_id: int, subscriptions: dict) -> None:
    """Persist a user's subscription preferences."""
    _execute(
        "UPDATE users SET subscriptions = %s WHERE telegram_id = %s",
        (json.dumps(subscriptions), telegram_id),
    )


# =============================================================================
# User Saved Jobs
# =============================================================================

def save_job_for_user(user_id: int, job_id: int) -> bool:
    """
    Save a job for a user.
    Returns True if the row was newly inserted, False if it already existed.
    """
    row = _execute(
        """
        INSERT INTO user_saved_jobs (user_id, job_id)
        VALUES (%s, %s)
        ON CONFLICT DO NOTHING
        RETURNING id
        """,
        (user_id, job_id),
    )
    return row is not None


def get_saved_jobs(user_id: int, limit: int = 20, offset: int = 0):
    """
    Return saved jobs for a user, joined with the jobs table for full details.
    """
    from core.models import Job

    rows = _fetchall(
        """
        SELECT j.*
        FROM user_saved_jobs usj
        JOIN jobs j ON j.id = usj.job_id
        WHERE usj.user_id = %s
        ORDER BY usj.saved_at DESC
        LIMIT %s OFFSET %s
        """,
        (user_id, limit, offset),
    )
    return [Job.from_db_row(r) for r in rows]


# =============================================================================
# Job Feedback
# =============================================================================

def add_feedback(job_id: int, user_id: int, feedback_type: str) -> None:
    """Record a user's feedback (e.g. 'like', 'dislike') on a job."""
    _execute(
        """
        INSERT INTO job_feedback (job_id, user_id, feedback_type)
        VALUES (%s, %s, %s)
        """,
        (job_id, user_id, feedback_type),
    )
