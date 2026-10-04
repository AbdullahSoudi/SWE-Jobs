"""Programming Jobs Telegram Bot - main entry point.

Runtime flow:
fetch -> filter -> freshness gate -> persist -> send pending jobs -> record results.

Important guarantees:
- A new source's first successful fetch is a no-send baseline.
- Newly discovered jobs are sent only while they are fresh enough for that source.
- A coverage gap disables observation-based freshness fallbacks.
- Jobs are stored before sending, so Telegram failures do not lose discovery state.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Callable, Iterable

from config import (
    DEFAULT_SOURCE_FRESHNESS_POLICY,
    LEGACY_BACKLOG_MAX_AGE_MINUTES,
    MAX_JOBS_PER_RUN,
    PENDING_SEND_MAX_AGE_MINUTES,
    SEED_MODE_ENV,
    SOURCE_FRESHNESS_POLICIES,
)
try:
    from sources import ALL_FETCHERS
except ModuleNotFoundError:  # local flat-file test layout
    from __init__ import ALL_FETCHERS
from models import Job, is_programming_job, passes_geo_filter
from telegram_sender import (
    CONFIG_ERROR,
    RATE_LIMITED,
    RETRYABLE,
    SENT,
    TelegramSendResult,
    send_job,
    route_job,
)
from cleanup import cleanup_join_messages
from freshness import (
    BASELINE,
    UNCERTAIN,
    PublicationEvidence,
    ensure_utc,
    evaluate_new_posting,
    iso_utc,
    utc_now,
)
from db import (
    DB_FILE,
    connect,
    count_jobs,
    expire_legacy_backlog_once,
    expire_stale_unsent_jobs,
    get_jobs_for_sending,
    get_metadata,
    ensure_topic_deliveries,
    get_source_last_success,
    get_topic_delivery_states,
    is_source_baselined,
    mark_source_baselined,
    mark_topic_sending,
    record_delivery_result,
    recover_stale_sending_deliveries,
    set_job_freshness_state,
    set_job_send_status,
    set_metadata,
    update_source_run,
    upsert_job,
    upsert_jobs,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("main")

Fetcher = tuple[str, Callable[[], list[Job]]]
Sender = Callable[[Job, list[str] | None], dict[str, object]]
Router = Callable[[Job], list[str]]
Cleanup = Callable[[], None]
TELEGRAM_BLOCKED_UNTIL_KEY = "telegram_group_blocked_until"


@dataclass(frozen=True)
class SourceContext:
    was_baselined: bool
    previous_success_at: str | None


@dataclass
class RunSummary:
    raw_jobs: int = 0
    filtered_jobs: int = 0
    inserted_jobs: int = 0
    refreshed_jobs: int = 0
    fresh_new_jobs: int = 0
    expired_new_jobs: int = 0
    uncertain_new_jobs: int = 0
    baseline_skipped_jobs: int = 0
    sources_baselined: int = 0
    pending_processed: int = 0
    topic_send_successes: int = 0
    topic_send_failures: int = 0
    skipped_jobs: int = 0
    expired_backlog_jobs: int = 0
    expired_queue_jobs: int = 0
    ambiguous_deliveries_recovered: int = 0
    total_jobs_in_db: int = 0
    seed_mode: bool = False


def _source_key(value: str) -> str:
    return (value or "").strip().lower()


def _is_seed_mode(seed_mode: bool | None = None) -> bool:
    """Return whether this run should persist jobs without sending them."""
    if seed_mode is not None:
        return seed_mode
    return os.getenv(SEED_MODE_ENV, "").lower() in ("1", "true", "yes")


def _capture_source_context(conn, fetchers: Iterable[Fetcher]) -> dict[str, SourceContext]:
    """Snapshot source state before this run changes last_success_at."""
    context: dict[str, SourceContext] = {}
    for display_name, _ in fetchers:
        key = _source_key(display_name)
        context[key] = SourceContext(
            was_baselined=is_source_baselined(conn, key),
            previous_success_at=get_source_last_success(conn, key),
        )
    return context


def fetch_all_jobs(
    conn,
    fetchers: Iterable[Fetcher],
    *,
    run_at: str | None = None,
) -> tuple[list[Job], set[str]]:
    """Fetch jobs and return both rows and successfully fetched source keys.

    Successful source state is committed only after fetched jobs are persisted.
    Failed source state is recorded immediately so failures survive the run.
    """
    all_jobs: list[Job] = []
    successful_sources: set[str] = set()

    for display_name, fetcher in fetchers:
        source_key = _source_key(display_name)
        try:
            log.info("Fetching from %s...", display_name)
            jobs = fetcher() or []
            for job in jobs:
                if not _source_key(job.source):
                    job.source = source_key
                elif _source_key(job.source) != source_key:
                    log.warning(
                        "Source %s returned a job labelled %s; freshness state will use the job label.",
                        source_key,
                        job.source,
                    )
            all_jobs.extend(jobs)
            successful_sources.add(source_key)
            log.info("  %s: %s raw jobs", display_name, len(jobs))
        except Exception as exc:  # keep one failed source from killing the run
            update_source_run(conn, source_key, "failed", str(exc), last_run_at=run_at)
            log.error("  %s failed: %s", display_name, exc)

    return all_jobs, successful_sources


def should_keep_job(job: Job) -> bool:
    """Runtime quality filter."""
    if not job.title or not job.url:
        return False

    source = _source_key(job.source)
    if source == "linkedin":
        return passes_geo_filter(job)

    return is_programming_job(job) and passes_geo_filter(job)


def filter_jobs_for_runtime(jobs: list[Job]) -> list[Job]:
    """Apply the bot's runtime filter rules."""
    return [job for job in jobs if should_keep_job(job)]


def _publication_evidence(job: Job) -> PublicationEvidence:
    return PublicationEvidence(
        raw=job.published_at_raw or "",
        earliest=job.published_at_earliest or "",
        latest=job.published_at_latest or "",
        estimate=job.published_at_est or "",
        precision=job.published_precision or "NONE",
        semantics=job.time_semantics or "UNKNOWN",
    )


def _policy_for_source(source_key: str) -> dict[str, object]:
    policy = SOURCE_FRESHNESS_POLICIES.get(source_key, DEFAULT_SOURCE_FRESHNESS_POLICY)
    return dict(policy)


def persist_filtered_jobs(
    conn,
    jobs: list[Job],
    source_context: dict[str, SourceContext],
    *,
    reference_time: datetime | None = None,
) -> tuple[int, int, list[Job], int, int, int, int]:
    """Filter, persist, and freshness-gate newly discovered jobs.

    Returns:
        inserted, refreshed, filtered, fresh_new, expired_new,
        uncertain_new, baseline_skipped
    """
    filtered = filter_jobs_for_runtime(jobs)
    inserted = 0
    refreshed = 0
    fresh_new = 0
    expired_new = 0
    uncertain_new = 0
    baseline_skipped = 0
    now = ensure_utc(reference_time or utc_now())

    for job in filtered:
        job_id, is_new = upsert_job(conn, job)
        if not is_new:
            refreshed += 1
            continue

        inserted += 1
        source_key = _source_key(job.source)
        context = source_context.get(source_key, SourceContext(False, None))
        policy = _policy_for_source(source_key)
        decision = evaluate_new_posting(
            _publication_evidence(job),
            source_was_baselined=context.was_baselined,
            previous_success_at=context.previous_success_at,
            max_age_seconds=int(policy["max_age_seconds"]),
            uncertain_fallback=str(policy.get("uncertain_fallback", "NONE")),
            reference_time=now,
        )
        set_job_freshness_state(conn, job_id, decision.status, decision.reason)

        if decision.send_eligible:
            fresh_new += 1
            continue

        if decision.status == BASELINE:
            set_job_send_status(conn, job_id, "skipped")
            baseline_skipped += 1
        else:
            set_job_send_status(conn, job_id, "expired")
            expired_new += 1
            if decision.status == UNCERTAIN:
                uncertain_new += 1

    conn.commit()
    return (
        inserted,
        refreshed,
        filtered,
        fresh_new,
        expired_new,
        uncertain_new,
        baseline_skipped,
    )


def _parse_iso(value: str) -> datetime:
    text = (value or "").strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    return ensure_utc(datetime.fromisoformat(text))


def _delivery_deadline(first_seen_at: str) -> str:
    deadline = _parse_iso(first_seen_at) + timedelta(minutes=PENDING_SEND_MAX_AGE_MINUTES)
    return iso_utc(deadline)


def _coerce_send_result(value: object) -> TelegramSendResult:
    """Keep test/custom senders backward compatible with bool results."""
    if isinstance(value, TelegramSendResult):
        return value
    if bool(value):
        return TelegramSendResult(True, SENT)
    return TelegramSendResult(False, RETRYABLE, "sender returned false")


def _topic_ready(state: dict | None, reference_time: datetime) -> bool:
    if not state:
        return True
    status = str(state.get("status") or "queued")
    if status == "queued":
        return True
    if status != "retry_wait":
        return False
    next_attempt = state.get("next_attempt_at")
    if not next_attempt:
        return True
    return _parse_iso(str(next_attempt)) <= reference_time


def _aggregate_delivery_status(target_topics: list[str], states: dict[str, dict]) -> str:
    """Derive the job-level status from durable per-topic delivery rows."""
    if not target_topics:
        return "skipped"
    statuses = [str((states.get(topic) or {}).get("status") or "queued") for topic in target_topics]
    if all(status == "sent" for status in statuses):
        return "sent"

    has_sent = any(status == "sent" for status in statuses)
    has_retryable = any(status in {"queued", "retry_wait", "sending"} for status in statuses)
    if has_retryable:
        return "partial" if has_sent else "retry"

    if any(status == "unknown" for status in statuses):
        return "partial_failed" if has_sent else "unknown"

    return "partial_failed" if has_sent else "failed"


def send_pending_jobs(
    conn,
    limit: int = MAX_JOBS_PER_RUN,
    sender: Sender = send_job,
    router: Router = route_job,
    *,
    reference_time: datetime | None = None,
) -> tuple[int, int, int, int]:
    """Deliver queued jobs with durable per-topic state and Telegram backpressure."""
    pending_jobs = get_jobs_for_sending(conn, limit=limit)
    processed = 0
    successes = 0
    failures = 0
    skipped = 0
    now = ensure_utc(reference_time or utc_now())
    blocked_until = get_metadata(conn, TELEGRAM_BLOCKED_UNTIL_KEY)
    if blocked_until:
        try:
            blocked_dt = _parse_iso(blocked_until)
        except ValueError:
            blocked_dt = now
        if blocked_dt > now:
            log.warning("Telegram group queue is paused until %s after a prior 429.", blocked_until)
            return 0, 0, 0, 0
        set_metadata(conn, TELEGRAM_BLOCKED_UNTIL_KEY, "")
        conn.commit()

    queue_rate_limited = False
    disabled_topics: set[str] = set()

    for stored in pending_jobs:
        job = stored.to_job()
        target_topics = router(job)

        if not target_topics:
            set_job_send_status(conn, stored.id, "skipped")
            conn.commit()
            skipped += 1
            processed += 1
            log.info("Skipped job with no matching topics: %s", job.title)
            continue

        # Transition guard for Update 5: older versions could fan one job out
        # to several topics.  If any legacy delivery already succeeded, the
        # user has already seen this job; do not create a new primary-topic
        # copy during the routing migration.
        existing_states = get_topic_delivery_states(conn, stored.id)
        legacy_sent_topics = {
            topic
            for topic, state in existing_states.items()
            if topic not in target_topics and str(state.get("status") or "") == "sent"
        }
        if legacy_sent_topics:
            set_job_send_status(conn, stored.id, "sent")
            conn.commit()
            processed += 1
            log.info(
                "%s: already delivered by retired routing topics %s; suppressing duplicate",
                job.title,
                sorted(legacy_sent_topics),
            )
            continue

        deadline_at = _delivery_deadline(stored.first_seen_at)
        ensure_topic_deliveries(conn, stored.id, target_topics, deadline_at)
        conn.commit()  # durable outbox before any network call

        states = get_topic_delivery_states(conn, stored.id)
        topics_to_send = [
            topic
            for topic in target_topics
            if topic not in disabled_topics and _topic_ready(states.get(topic), now)
        ]

        if not topics_to_send:
            status = _aggregate_delivery_status(target_topics, states)
            set_job_send_status(conn, stored.id, status)
            conn.commit()
            if status not in {"retry", "partial"}:
                processed += 1
            continue

        for topic_key in topics_to_send:
            # Claim + commit before send. If the process dies after Telegram accepted
            # the message, the next run recovers this as UNKNOWN rather than blindly
            # retrying and potentially duplicating it.
            mark_topic_sending(conn, stored.id, topic_key, reference_time=now)
            conn.commit()

            raw_results = sender(job, [topic_key]) or {}
            result = _coerce_send_result(raw_results.get(topic_key, False))
            record_delivery_result(
                conn,
                stored.id,
                topic_key,
                outcome=result.outcome,
                error=result.error,
                http_status=result.http_status,
                tg_error_code=result.tg_error_code,
                retry_after_s=result.retry_after_s,
                telegram_message_id=result.message_id,
                fallback_used=result.fallback_used,
                reference_time=now,
            )
            conn.commit()

            if result.success:
                successes += 1
            else:
                failures += 1

            if result.outcome == CONFIG_ERROR:
                disabled_topics.add(topic_key)
                log.error("Disabled topic for the rest of this run after CONFIG_ERROR: %s", topic_key)

            if result.outcome == RATE_LIMITED:
                queue_rate_limited = True
                retry_after = max(1, int(result.retry_after_s or 60))
                blocked_until = iso_utc(now + timedelta(seconds=retry_after))
                set_metadata(conn, TELEGRAM_BLOCKED_UNTIL_KEY, blocked_until)
                conn.commit()
                log.warning(
                    "Telegram rate-limited the group; stopping this run's send queue until %s.",
                    blocked_until,
                )
                break

        states = get_topic_delivery_states(conn, stored.id)
        status = _aggregate_delivery_status(target_topics, states)
        set_job_send_status(conn, stored.id, status)
        conn.commit()
        processed += 1
        log.info("%s: delivery status=%s", job.title, status)

        if queue_rate_limited:
            break

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
    reference_time: datetime | None = None,
) -> RunSummary:
    """Run one bot cycle. Parameters are injectable for tests."""
    start = time.time()
    run_reference = ensure_utc(reference_time or datetime.now(UTC)).replace(microsecond=0)
    run_at = iso_utc(run_reference)
    summary = RunSummary(seed_mode=_is_seed_mode(seed_mode))
    fetcher_list = list(fetchers)

    log.info("=" * 60)
    log.info("Programming Jobs Bot - Starting run")
    log.info("=" * 60)

    try:
        cleanup_func()
    except Exception as exc:
        log.warning("Cleanup failed (non-critical): %s", exc)

    with connect(db_path) as conn:
        summary.expired_backlog_jobs = expire_legacy_backlog_once(
            conn,
            max_age_minutes=LEGACY_BACKLOG_MAX_AGE_MINUTES,
            reference_time=run_reference,
        )
        summary.expired_queue_jobs = expire_stale_unsent_jobs(
            conn,
            max_age_minutes=PENDING_SEND_MAX_AGE_MINUTES,
            reference_time=run_reference,
        )
        summary.ambiguous_deliveries_recovered = recover_stale_sending_deliveries(
            conn,
            stale_after_minutes=10,
            reference_time=run_reference,
        )
        if summary.expired_backlog_jobs or summary.expired_queue_jobs:
            log.info(
                "Expired stale queue rows: legacy=%s, live_deadline=%s",
                summary.expired_backlog_jobs,
                summary.expired_queue_jobs,
            )

        source_context = _capture_source_context(conn, fetcher_list)
        all_jobs, successful_sources = fetch_all_jobs(
            conn,
            fetcher_list,
            run_at=run_at,
        )
        summary.raw_jobs = len(all_jobs)
        log.info("Total raw jobs fetched: %s", summary.raw_jobs)

        (
            inserted,
            refreshed,
            filtered,
            fresh_new,
            expired_new,
            uncertain_new,
            baseline_skipped,
        ) = persist_filtered_jobs(
            conn,
            all_jobs,
            source_context,
            reference_time=run_reference,
        )
        summary.filtered_jobs = len(filtered)
        summary.inserted_jobs = inserted
        summary.refreshed_jobs = refreshed
        summary.fresh_new_jobs = fresh_new
        summary.expired_new_jobs = expired_new
        summary.uncertain_new_jobs = uncertain_new
        summary.baseline_skipped_jobs = baseline_skipped

        # Advance successful source state only after fetched rows are persisted.
        for source_key in sorted(successful_sources):
            update_source_run(conn, source_key, "ok", last_run_at=run_at)
            context = source_context.get(source_key, SourceContext(False, None))
            if not context.was_baselined:
                mark_source_baselined(conn, source_key, baselined_at=run_at)
                summary.sources_baselined += 1
        conn.commit()

        log.info(
            "After filtering: %s jobs | inserted=%s, refreshed=%s, fresh=%s, "
            "expired=%s, uncertain=%s, baseline_skipped=%s",
            summary.filtered_jobs,
            inserted,
            refreshed,
            fresh_new,
            expired_new,
            uncertain_new,
            baseline_skipped,
        )

        if summary.seed_mode:
            skipped = mark_pending_as_skipped(conn, limit=10**9)
            summary.skipped_jobs = skipped
            log.info("SEED MODE: stored and skipped %s pending jobs.", skipped)
        else:
            processed, successes, failures, skipped = send_pending_jobs(
                conn,
                limit=max_jobs_per_run,
                sender=sender,
                router=router,
                reference_time=run_reference,
            )
            summary.pending_processed = processed
            summary.topic_send_successes = successes
            summary.topic_send_failures = failures
            summary.skipped_jobs = skipped
            log.info(
                "Processed %s pending jobs | topic successes=%s, failures=%s, skipped=%s",
                processed,
                successes,
                failures,
                skipped,
            )

        summary.total_jobs_in_db = count_jobs(conn)

    elapsed = time.time() - start
    log.info("Run complete in %.1fs. Total DB jobs: %s", elapsed, summary.total_jobs_in_db)
    log.info("=" * 60)
    return summary


def main() -> None:
    run_bot()


if __name__ == "__main__":
    main()
