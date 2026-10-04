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
    ATS_OBSERVATION_MAX_AGE_MINUTES,
    DEFAULT_SOURCE_FRESHNESS_POLICY,
    DISCOVERY_ONLY_SOURCE_KEYS,
    LEGACY_BACKLOG_MAX_AGE_MINUTES,
    MAX_JOBS_PER_RUN,
    PENDING_SEND_MAX_AGE_MINUTES,
    PRODUCTION_SOURCE_KEYS,
    SEED_MODE_ENV,
    SOURCE_EMPTY_RUN_WARNING_THRESHOLD,
    SOURCE_FRESHNESS_POLICIES,
    TELEGRAM_ADMIN_CHAT_ID,
)
try:
    from sources import ALL_FETCHERS, SOURCE_POLL_INTERVAL_MINUTES
except ModuleNotFoundError:  # local flat-file test layout
    from __init__ import ALL_FETCHERS, SOURCE_POLL_INTERVAL_MINUTES
from models import Job, is_programming_job, passes_geo_filter
from classifier import is_tech_job
from eligibility import enrich_job_eligibility
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
    FreshnessGateDecision,
    PublicationEvidence,
    ensure_utc,
    evaluate_new_posting,
    iso_utc,
    utc_now,
)
from source_analytics import build_source_analytics, format_source_analytics
from admin_monitoring import (
    build_daily_digest,
    digest_due,
    format_event_batch,
    health_transition_event,
    mark_digest_sent,
    send_admin_message,
    sync_adapter_outage_events,
    sync_coverage_gap_event,
)
from source_runtime import (
    classify_source_health,
    compute_next_poll_at,
    detect_ats_adapter_outages,
    is_source_due,
    normalize_poll_interval,
)
from db import (
    DB_FILE,
    connect,
    count_jobs,
    expire_legacy_backlog_once,
    expire_stale_unsent_jobs,
    get_jobs_for_sending,
    get_job_primary_source,
    get_job_send_status,
    get_metadata,
    ensure_topic_deliveries,
    get_source_last_success,
    get_source_state,
    get_topic_delivery_states,
    is_source_baselined,
    mark_source_baselined,
    mark_topic_sending,
    record_delivery_result,
    record_source_observation,
    record_source_run_history,
    recover_stale_sending_deliveries,
    set_job_freshness_state,
    set_job_primary_source,
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
class SourceCycleMetrics:
    status: str = "never"
    error: str = ""
    duration_ms: int = 0
    raw_jobs: int = 0
    filtered_jobs: int = 0
    inserted_jobs: int = 0
    refreshed_jobs: int = 0
    fresh_new_jobs: int = 0
    expired_new_jobs: int = 0
    uncertain_new_jobs: int = 0
    baseline_skipped_jobs: int = 0
    shadow_eligible_jobs: int = 0
    coverage_gap: bool = False
    shadow_mode: bool = True
    health_status: str = "UNKNOWN"
    poll_interval_minutes: int = 15


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
    shadow_eligible_jobs: int = 0
    sources_baselined: int = 0
    source_failures: int = 0
    source_runs_recorded: int = 0
    sources_skipped_not_due: int = 0
    ats_adapter_outages: int = 0
    pending_processed: int = 0
    topic_send_successes: int = 0
    topic_send_failures: int = 0
    skipped_jobs: int = 0
    expired_backlog_jobs: int = 0
    expired_queue_jobs: int = 0
    ambiguous_deliveries_recovered: int = 0
    total_jobs_in_db: int = 0
    seed_mode: bool = False
    admin_notifications_sent: int = 0


def _source_key(value: str) -> str:
    return (value or "").strip().lower().replace("-", "_").replace(" ", "_")


def _is_seed_mode(seed_mode: bool | None = None) -> bool:
    """Return whether this run should persist jobs without sending them."""
    if seed_mode is not None:
        return seed_mode
    return os.getenv(SEED_MODE_ENV, "").lower() in ("1", "true", "yes")


def _poll_interval_for(source_key: str, poll_intervals: dict[str, int]) -> int:
    return normalize_poll_interval(poll_intervals.get(source_key, 15))


def _select_due_fetchers(
    conn,
    fetchers: Iterable[Fetcher],
    poll_intervals: dict[str, int],
    reference_time: datetime,
) -> tuple[list[Fetcher], list[str]]:
    """Split configured fetchers into due and not-yet-due sources."""
    due: list[Fetcher] = []
    skipped: list[str] = []
    for display_name, fetcher in fetchers:
        source_key = _source_key(display_name)
        interval = _poll_interval_for(source_key, poll_intervals)
        state = get_source_state(conn, source_key)
        if is_source_due(state, now=reference_time, poll_interval_minutes=interval):
            due.append((display_name, fetcher))
        else:
            skipped.append(source_key)
    return due, skipped


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
) -> tuple[list[Job], dict[str, SourceCycleMetrics]]:
    """Fetch jobs and capture per-source timing/status metrics."""
    all_jobs: list[Job] = []
    source_metrics: dict[str, SourceCycleMetrics] = {}

    for display_name, fetcher in fetchers:
        source_key = _source_key(display_name)
        metrics = SourceCycleMetrics()
        started = time.perf_counter()
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
            metrics.status = "ok"
            metrics.raw_jobs = len(jobs)
            log.info("  %s: %s raw jobs", display_name, len(jobs))
        except Exception as exc:  # keep one failed source from killing the run
            metrics.status = "failed"
            metrics.error = str(exc)
            log.error("  %s failed: %s", display_name, exc)
        finally:
            metrics.duration_ms = max(0, int((time.perf_counter() - started) * 1000))
            source_metrics[source_key] = metrics

    return all_jobs, source_metrics


def should_keep_job(job: Job) -> bool:
    """Runtime quality filter."""
    if not job.title or not job.url:
        return False

    source = _source_key(job.source)
    if source in {"linkedin", "linkedin_saudi_v2", "jobzaty"} or source.startswith("ats_"):
        return is_tech_job(job) and passes_geo_filter(job)

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
    key = _source_key(source_key)
    if key.startswith("ats_"):
        return {
            "max_age_seconds": ATS_OBSERVATION_MAX_AGE_MINUTES * 60,
            "uncertain_fallback": "RECENT_OBSERVATION",
        }
    policy = SOURCE_FRESHNESS_POLICIES.get(key, DEFAULT_SOURCE_FRESHNESS_POLICY)
    return dict(policy)


def _is_shadow_source(source_key: str, production_source_keys: set[str]) -> bool:
    return _source_key(source_key) not in {_source_key(value) for value in production_source_keys}


def _has_coverage_gap(
    previous_success_at: str | None,
    source_key: str,
    reference_time: datetime,
) -> bool:
    if not previous_success_at:
        return False
    try:
        previous = _parse_iso(previous_success_at)
    except (TypeError, ValueError):
        return True
    policy = _policy_for_source(source_key)
    max_age_seconds = max(1, int(policy.get("max_age_seconds", 3600)))
    return (reference_time - previous).total_seconds() > max_age_seconds


def persist_filtered_jobs(
    conn,
    jobs: list[Job],
    source_context: dict[str, SourceContext],
    source_metrics: dict[str, SourceCycleMetrics],
    production_source_keys: set[str],
    *,
    reference_time: datetime | None = None,
) -> tuple[int, int, list[Job], int, int, int, int, int]:
    """Filter, persist, and freshness-gate newly discovered jobs.

    Returns:
        inserted, refreshed, filtered, fresh_new, expired_new,
        uncertain_new, baseline_skipped, shadow_eligible
    """
    filtered = filter_jobs_for_runtime(jobs)
    for job in filtered:
        source_key = _source_key(job.source)
        source_metrics.setdefault(source_key, SourceCycleMetrics(status="ok")).filtered_jobs += 1
    inserted = 0
    refreshed = 0
    fresh_new = 0
    expired_new = 0
    uncertain_new = 0
    baseline_skipped = 0
    shadow_eligible = 0
    now = ensure_utc(reference_time or utc_now())

    for job in filtered:
        source_key = _source_key(job.source)
        enrich_job_eligibility(job)
        metrics = source_metrics.setdefault(source_key, SourceCycleMetrics(status="ok"))
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
        if context.was_baselined and source_key in {_source_key(value) for value in DISCOVERY_ONLY_SOURCE_KEYS}:
            decision = FreshnessGateDecision(
                UNCERTAIN,
                "discovery_only_source",
                False,
            )
        job_id, is_new = upsert_job(conn, job)
        record_source_observation(
            conn,
            job_id,
            source_key,
            source_job_id=job.source_job_id,
            observed_at=iso_utc(now),
            fresh_eligible=decision.send_eligible,
            shadow_mode=_is_shadow_source(source_key, production_source_keys),
            was_new_job=is_new,
        )
        if not is_new:
            refreshed += 1
            metrics.refreshed_jobs += 1

            # Non-production observations must never poison production discovery.
            # A shadow/discovery-only source may see the opening first and store it
            # as shadow, skipped, or expired. If a *different* production source
            # later sees the same cluster with trustworthy fresh evidence, promote
            # that cluster into the delivery queue. Ambiguous/sent/retry states are
            # deliberately excluded to avoid duplicate Telegram delivery.
            existing_status = get_job_send_status(conn, job_id)
            primary_source = _source_key(get_job_primary_source(conn, job_id))
            if (
                not _is_shadow_source(source_key, production_source_keys)
                and primary_source != source_key
                and _is_shadow_source(primary_source, production_source_keys)
                and existing_status in {"shadow", "skipped", "expired"}
            ):
                set_job_freshness_state(conn, job_id, decision.status, decision.reason)
                if decision.send_eligible:
                    set_job_primary_source(conn, job_id, source_key, job.source_job_id)
                    set_job_send_status(conn, job_id, "pending")
                    fresh_new += 1
                    metrics.fresh_new_jobs += 1
            continue

        inserted += 1
        metrics.inserted_jobs += 1
        set_job_freshness_state(conn, job_id, decision.status, decision.reason)

        if decision.send_eligible:
            fresh_new += 1
            metrics.fresh_new_jobs += 1
            if _is_shadow_source(source_key, production_source_keys):
                set_job_send_status(conn, job_id, "shadow")
                shadow_eligible += 1
                metrics.shadow_eligible_jobs += 1
            continue

        if decision.status == BASELINE:
            set_job_send_status(conn, job_id, "skipped")
            baseline_skipped += 1
            metrics.baseline_skipped_jobs += 1
        else:
            set_job_send_status(conn, job_id, "expired")
            expired_new += 1
            metrics.expired_new_jobs += 1
            if decision.status == UNCERTAIN:
                uncertain_new += 1
                metrics.uncertain_new_jobs += 1

    conn.commit()
    return (
        inserted,
        refreshed,
        filtered,
        fresh_new,
        expired_new,
        uncertain_new,
        baseline_skipped,
        shadow_eligible,
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
    production_source_keys: set[str] | None = None,
    source_poll_intervals: dict[str, int] | None = None,
) -> RunSummary:
    """Run one bot cycle. Parameters are injectable for tests."""
    start = time.time()
    run_reference = ensure_utc(reference_time or datetime.now(UTC)).replace(microsecond=0)
    run_at = iso_utc(run_reference)
    summary = RunSummary(seed_mode=_is_seed_mode(seed_mode))
    admin_events: list[str] = []
    fetcher_list = list(fetchers)
    production_keys = set(PRODUCTION_SOURCE_KEYS if production_source_keys is None else production_source_keys)
    poll_intervals = dict(SOURCE_POLL_INTERVAL_MINUTES)
    if source_poll_intervals:
        poll_intervals.update({_source_key(k): int(v) for k, v in source_poll_intervals.items()})

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

        due_fetchers, skipped_due = _select_due_fetchers(
            conn, fetcher_list, poll_intervals, run_reference
        )
        summary.sources_skipped_not_due = len(skipped_due)
        if skipped_due:
            log.info("Skipping %s sources until next_poll_at: %s", len(skipped_due), ", ".join(skipped_due))

        source_context = _capture_source_context(conn, due_fetchers)
        all_jobs, source_metrics = fetch_all_jobs(
            conn,
            due_fetchers,
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
            shadow_eligible,
        ) = persist_filtered_jobs(
            conn,
            all_jobs,
            source_context,
            source_metrics,
            production_keys,
            reference_time=run_reference,
        )
        summary.filtered_jobs = len(filtered)
        summary.inserted_jobs = inserted
        summary.refreshed_jobs = refreshed
        summary.fresh_new_jobs = fresh_new
        summary.expired_new_jobs = expired_new
        summary.uncertain_new_jobs = uncertain_new
        summary.baseline_skipped_jobs = baseline_skipped
        summary.shadow_eligible_jobs = shadow_eligible

        # Persist immutable source metrics only after fetched rows are safely stored.
        for source_key, metrics in sorted(source_metrics.items()):
            context = source_context.get(source_key, SourceContext(False, None))
            metrics.shadow_mode = _is_shadow_source(source_key, production_keys)
            metrics.coverage_gap = _has_coverage_gap(
                context.previous_success_at, source_key, run_reference
            )
            previous_state = get_source_state(conn, source_key)
            metrics.poll_interval_minutes = _poll_interval_for(source_key, poll_intervals)
            metrics.health_status = classify_source_health(
                source_key,
                status=metrics.status,
                raw_count=metrics.raw_jobs,
                previous_state=previous_state,
                empty_warning_threshold=SOURCE_EMPTY_RUN_WARNING_THRESHOLD,
            )
            previous_health = (
                str(previous_state["health_status"] or "UNKNOWN")
                if previous_state and "health_status" in previous_state.keys()
                else "UNKNOWN"
            )
            health_event = health_transition_event(
                source_key, previous_health, metrics.health_status, error=metrics.error
            )
            if health_event:
                admin_events.append(health_event)
            coverage_event = sync_coverage_gap_event(
                conn, source_key, metrics.coverage_gap
            )
            if coverage_event:
                admin_events.append(coverage_event)
            next_poll_at = compute_next_poll_at(
                run_at=run_reference,
                status=metrics.status,
                poll_interval_minutes=metrics.poll_interval_minutes,
            )

            update_source_run(
                conn,
                source_key,
                metrics.status,
                metrics.error,
                last_run_at=run_at,
                shadow_mode=metrics.shadow_mode,
                raw_count=metrics.raw_jobs,
                filtered_count=metrics.filtered_jobs,
                inserted_count=metrics.inserted_jobs,
                fresh_count=metrics.fresh_new_jobs,
                shadow_eligible_count=metrics.shadow_eligible_jobs,
                duration_ms=metrics.duration_ms,
                poll_interval_minutes=metrics.poll_interval_minutes,
                next_poll_at=next_poll_at,
                health_status=metrics.health_status,
            )
            record_source_run_history(
                conn,
                source_key,
                run_at=run_at,
                status=metrics.status,
                error=metrics.error,
                duration_ms=metrics.duration_ms,
                raw_count=metrics.raw_jobs,
                filtered_count=metrics.filtered_jobs,
                inserted_count=metrics.inserted_jobs,
                refreshed_count=metrics.refreshed_jobs,
                fresh_count=metrics.fresh_new_jobs,
                expired_count=metrics.expired_new_jobs,
                uncertain_count=metrics.uncertain_new_jobs,
                baseline_skipped_count=metrics.baseline_skipped_jobs,
                shadow_eligible_count=metrics.shadow_eligible_jobs,
                coverage_gap=metrics.coverage_gap,
                shadow_mode=metrics.shadow_mode,
                health_status=metrics.health_status,
            )
            summary.source_runs_recorded += 1

            if metrics.status == "ok":
                if not context.was_baselined:
                    mark_source_baselined(conn, source_key, baselined_at=run_at)
                    summary.sources_baselined += 1
            else:
                summary.source_failures += 1

            state = get_source_state(conn, source_key)
            if (
                state
                and not source_key.startswith("ats_")
                and metrics.status == "ok"
                and int(state["consecutive_empty_runs"] or 0) >= SOURCE_EMPTY_RUN_WARNING_THRESHOLD
            ):
                log.warning(
                    "Source %s has returned zero jobs for %s consecutive successful runs.",
                    source_key,
                    state["consecutive_empty_runs"],
                )
            if metrics.health_status in {"DEGRADED", "UNHEALTHY"}:
                log.warning("Source %s health=%s", source_key, metrics.health_status)
            if metrics.coverage_gap:
                log.warning("Source %s has a freshness coverage gap.", source_key)

        adapter_outages = detect_ats_adapter_outages(
            {key: metrics.status for key, metrics in source_metrics.items()}
        )
        summary.ats_adapter_outages = len(adapter_outages)
        for adapter in adapter_outages:
            log.error("ATS adapter-level outage suspected: %s tenants all failed this run.", adapter)
        admin_events.extend(sync_adapter_outage_events(conn, adapter_outages))

        conn.commit()

        log.info(
            "After filtering: %s jobs | inserted=%s, refreshed=%s, fresh=%s, "
            "expired=%s, uncertain=%s, baseline_skipped=%s, shadow_eligible=%s",
            summary.filtered_jobs,
            inserted,
            refreshed,
            fresh_new,
            expired_new,
            uncertain_new,
            baseline_skipped,
            shadow_eligible,
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

        # Compact Saudi source comparison in Actions logs. Observation-based
        # discovery metrics intentionally begin with schema v6; no historical
        # discovery order is guessed or backfilled.
        analytics_rows = build_source_analytics(
            conn,
            sources=("linkedin", "linkedin_saudi_v2"),
            hours=24,
            saudi_only=True,
            reference_time=run_reference,
        )
        for line in format_source_analytics(analytics_rows, label="Saudi 24h"):
            log.info(line)

        if TELEGRAM_ADMIN_CHAT_ID:
            alert_message = format_event_batch(admin_events)
            if alert_message:
                alert_result = send_admin_message(alert_message)
                if alert_result.success:
                    summary.admin_notifications_sent += 1
                else:
                    log.warning("Admin health alert failed: %s", alert_result.error)

            if digest_due(conn, reference_time=run_reference):
                digest_message = build_daily_digest(conn, reference_time=run_reference)
                digest_result = send_admin_message(digest_message)
                if digest_result.success:
                    mark_digest_sent(conn, reference_time=run_reference)
                    conn.commit()
                    summary.admin_notifications_sent += 1
                else:
                    log.warning("Admin daily digest failed: %s", digest_result.error)

    elapsed = time.time() - start
    log.info(
        "Run complete in %.1fs. Total DB jobs: %s | source_runs=%s, source_failures=%s, "
        "skipped_not_due=%s, ats_adapter_outages=%s, shadow_eligible=%s",
        elapsed,
        summary.total_jobs_in_db,
        summary.source_runs_recorded,
        summary.source_failures,
        summary.sources_skipped_not_due,
        summary.ats_adapter_outages,
        summary.shadow_eligible_jobs,
    )
    log.info("=" * 60)
    return summary


def main() -> None:
    run_bot()


if __name__ == "__main__":
    main()
