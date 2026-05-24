"""
Programming Jobs Telegram Bot — Main entry point.

New runtime flow:
fetch → filter → persist in SQLite → send pending jobs → record per-topic status.

Important guarantees:
- Jobs are stored before sending, so a Telegram failure does not lose them.
- A job is marked sent only after all intended topics are sent successfully.
- Successful topic sends are not retried, which prevents duplicate messages after partial failures.
"""

from __future__ import annotations

import os
import logging
import time
from dataclasses import dataclass
from typing import Callable, Iterable

from config import MAX_JOBS_PER_RUN, SEED_MODE_ENV
try:
    from sources import ALL_FETCHERS
except ModuleNotFoundError:  # local flat-file test layout
    from __init__ import ALL_FETCHERS
from models import Job, is_programming_job, passes_geo_filter
from telegram_sender import send_job, route_job
from cleanup import cleanup_join_messages
from db import (
    DB_FILE,
    connect,
    count_jobs,
    get_jobs_for_sending,
    get_sent_topic_keys,
    record_topic_send,
    set_job_send_status,
    update_source_run,
    upsert_jobs,
)

# ─── Logging ─────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("main")

Fetcher = tuple[str, Callable[[], list[Job]]]
Sender = Callable[[Job, list[str] | None], dict[str, bool]]
Router = Callable[[Job], list[str]]
Cleanup = Callable[[], None]


@dataclass
class RunSummary:
    raw_jobs: int = 0
    filtered_jobs: int = 0
    inserted_jobs: int = 0
    refreshed_jobs: int = 0
    pending_processed: int = 0
    topic_send_successes: int = 0
    topic_send_failures: int = 0
    skipped_jobs: int = 0
    total_jobs_in_db: int = 0
    seed_mode: bool = False


def _is_seed_mode(seed_mode: bool | None = None) -> bool:
    """Return whether this run should persist jobs without sending them."""
    if seed_mode is not None:
        return seed_mode
    return os.getenv(SEED_MODE_ENV, "").lower() in ("1", "true", "yes")


def fetch_all_jobs(conn, fetchers: Iterable[Fetcher]) -> list[Job]:
    """Fetch jobs from configured sources and record source health."""
    all_jobs: list[Job] = []

    for display_name, fetcher in fetchers:
        source_key = display_name.strip().lower()
        try:
            log.info(f"📡 Fetching from {display_name}...")
            jobs = fetcher() or []
            all_jobs.extend(jobs)
            update_source_run(conn, source_key, "ok")
            log.info(f"  ✓ {display_name}: {len(jobs)} raw jobs")
        except Exception as exc:  # keep one failed source from killing the run
            update_source_run(conn, source_key, "failed", str(exc))
            log.error(f"  ✗ {display_name} failed: {exc}")

    return all_jobs


def should_keep_job(job: Job) -> bool:
    """Runtime quality filter.

    WUZZUF and normal category jobs still use the existing keyword + geo rules.
    Fresh LinkedIn jobs are allowed through even when they do not match category
    keywords, so they can reach the dedicated LinkedIn Fresh Jobs topic.
    """
    if not job.title or not job.url:
        return False

    source = (job.source or "").strip().lower()
    if source == "linkedin":
        return passes_geo_filter(job)

    return is_programming_job(job) and passes_geo_filter(job)


def filter_jobs_for_runtime(jobs: list[Job]) -> list[Job]:
    """Apply the bot's runtime filter rules."""
    return [job for job in jobs if should_keep_job(job)]


def persist_filtered_jobs(conn, jobs: list[Job]) -> tuple[int, int, list[Job]]:
    """Apply runtime filters, persist matching jobs, and return counts."""
    filtered = filter_jobs_for_runtime(jobs)
    inserted, refreshed = upsert_jobs(conn, filtered)
    conn.commit()
    return inserted, refreshed, filtered


def _aggregate_send_status(target_topics: list[str], sent_topics: set[str]) -> str:
    """Map per-topic state to one job-level send_status."""
    if not target_topics:
        return "skipped"
    if all(topic in sent_topics for topic in target_topics):
        return "sent"
    if sent_topics:
        return "partial"
    return "retry"


def send_pending_jobs(
    conn,
    limit: int = MAX_JOBS_PER_RUN,
    sender: Sender = send_job,
    router: Router = route_job,
) -> tuple[int, int, int, int]:
    """
    Send pending/retry/partial jobs and persist per-topic results.

    Returns:
        (jobs_processed, topic_successes, topic_failures, skipped_jobs)
    """
    pending_jobs = get_jobs_for_sending(conn, limit=limit)
    processed = 0
    successes = 0
    failures = 0
    skipped = 0

    for stored in pending_jobs:
        job = stored.to_job()
        target_topics = router(job)

        if not target_topics:
            set_job_send_status(conn, stored.id, "skipped")
            conn.commit()
            skipped += 1
            processed += 1
            log.info(f"⏭️ Skipped job with no matching topics: {job.title}")
            continue

        already_sent = get_sent_topic_keys(conn, stored.id)
        topics_to_send = [topic for topic in target_topics if topic not in already_sent]

        if not topics_to_send:
            set_job_send_status(conn, stored.id, "sent")
            conn.commit()
            processed += 1
            log.info(f"✅ Already sent to all topics: {job.title}")
            continue

        results = sender(job, topics_to_send)

        # Defensive: every intended topic must be recorded, even when the sender
        # returns no key because a Telegram topic is missing from env vars.
        for topic_key in topics_to_send:
            success = bool(results.get(topic_key, False))
            error = "" if success else "send failed or topic not configured"
            record_topic_send(conn, stored.id, topic_key, success, error=error)
            if success:
                successes += 1
            else:
                failures += 1

        sent_topics = get_sent_topic_keys(conn, stored.id)
        status = _aggregate_send_status(target_topics, sent_topics)
        set_job_send_status(conn, stored.id, status)
        conn.commit()

        processed += 1
        log.info(
            f"📨 {job.title}: attempted {len(topics_to_send)} topics, "
            f"status={status}"
        )

    return processed, successes, failures, skipped


def mark_pending_as_skipped(conn, limit: int = MAX_JOBS_PER_RUN) -> int:
    """Seed-mode helper: keep current jobs but do not send them."""
    skipped = 0
    for stored in get_jobs_for_sending(conn, limit=limit):
        set_job_send_status(conn, stored.id, "skipped")
        skipped += 1
    conn.commit()
    return skipped


def run_bot(
    db_path: str = DB_FILE,
    fetchers: Iterable[Fetcher] = ALL_FETCHERS,
    sender: Sender = send_job,
    router: Router = route_job,
    cleanup_func: Cleanup = cleanup_join_messages,
    max_jobs_per_run: int = MAX_JOBS_PER_RUN,
    seed_mode: bool | None = None,
) -> RunSummary:
    """Run one bot cycle. Parameters are injectable for tests."""
    start = time.time()
    summary = RunSummary(seed_mode=_is_seed_mode(seed_mode))

    log.info("=" * 60)
    log.info("Programming Jobs Bot — Starting run")
    log.info("=" * 60)

    try:
        cleanup_func()
    except Exception as exc:
        log.warning(f"Cleanup failed (non-critical): {exc}")

    with connect(db_path) as conn:
        all_jobs = fetch_all_jobs(conn, fetchers)
        summary.raw_jobs = len(all_jobs)
        log.info(f"Total raw jobs fetched: {summary.raw_jobs}")

        inserted, refreshed, filtered = persist_filtered_jobs(conn, all_jobs)
        summary.filtered_jobs = len(filtered)
        summary.inserted_jobs = inserted
        summary.refreshed_jobs = refreshed
        log.info(
            f"After filtering: {summary.filtered_jobs} jobs | "
            f"inserted={inserted}, refreshed={refreshed}"
        )

        if summary.seed_mode:
            skipped = mark_pending_as_skipped(conn, limit=10**9)
            summary.skipped_jobs = skipped
            log.info(f"🌱 SEED MODE: stored and skipped {skipped} pending jobs.")
        else:
            processed, successes, failures, skipped = send_pending_jobs(
                conn,
                limit=max_jobs_per_run,
                sender=sender,
                router=router,
            )
            summary.pending_processed = processed
            summary.topic_send_successes = successes
            summary.topic_send_failures = failures
            summary.skipped_jobs = skipped
            log.info(
                f"✅ Processed {processed} pending jobs | "
                f"topic successes={successes}, failures={failures}, skipped={skipped}"
            )

        summary.total_jobs_in_db = count_jobs(conn)

    elapsed = time.time() - start
    log.info(f"Run complete in {elapsed:.1f}s. Total DB jobs: {summary.total_jobs_in_db}")
    log.info("=" * 60)
    return summary


def main() -> None:
    run_bot()


if __name__ == "__main__":
    main()
