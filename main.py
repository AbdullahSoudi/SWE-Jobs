"""
Programming Jobs Bot v2 — Main entry point.
Orchestrates: fetch (with circuit breaker) -> enrich -> filter -> dedup -> insert -> send -> notify -> track.
"""

import os
import sys
import asyncio
import logging
import time

from core.logging_config import setup_logging
from core.config import MAX_JOBS_PER_RUN, SEED_MODE_ENV, TELEGRAM_BOT_TOKEN
from core import db
from core.enrichment import enrich_job
from core.filtering import filter_jobs
from core.dedup import deduplicate_batch
from core.circuit_breaker import fetch_with_retry
from sources import ALL_FETCHERS

setup_logging()
log = logging.getLogger("main")


async def main():
    start = time.time()
    log.info("Programming Jobs Bot v2 — Starting run")

    # ── 1. Start run tracking ──────────────────────────────
    run_id = db.start_run()
    source_stats = {}
    errors = []

    is_seed = os.getenv(SEED_MODE_ENV, "").lower() in ("1", "true", "yes")
    if is_seed:
        log.info("SEED MODE: will register all jobs without sending")

    # ── 2. Fetch from all sources in parallel ────────────────
    async def _fetch_one(name, source_key, fetcher):
        jobs = await asyncio.to_thread(fetch_with_retry, source_key, fetcher)
        return name, source_key, jobs

    log.info(f"Fetching from {len(ALL_FETCHERS)} sources in parallel...")
    fetch_tasks = [
        _fetch_one(name, key, fetcher)
        for name, key, fetcher in ALL_FETCHERS
    ]
    results = await asyncio.gather(*fetch_tasks)

    all_jobs = []
    fetch_summary = []
    for name, source_key, jobs in results:
        all_jobs.extend(jobs)
        source_stats[source_key] = len(jobs)
        if not jobs:
            errors.append({"source": source_key, "error": "no jobs returned"})
        fetch_summary.append(f"{name}={len(jobs)}")

    log.info(f"Fetched {len(all_jobs)} jobs: {', '.join(fetch_summary)}")

    # ── 3. Enrich all jobs ──────────────────────────────────
    for job in all_jobs:
        enrich_job(job)

    # ── 4. Filter (weighted scoring + geo) ──────────────────
    filtered = filter_jobs(all_jobs)
    log.info(f"After filtering: {len(filtered)} jobs")

    # ── 5. Deduplicate ──────────────────────────────────────
    # Get existing unique_ids from DB
    existing = db._fetchall("SELECT unique_id FROM jobs")
    seen_ids = {row["unique_id"] for row in existing}

    new_jobs = deduplicate_batch(filtered, seen_ids)
    log.info(f"New jobs: {len(new_jobs)}")

    # ── 6. Fuzzy dedup + batch insert ─────────────────────
    non_dupes = db.fuzzy_dedup_batch(new_jobs)
    fuzzy_dupes = len(new_jobs) - len(non_dupes)
    log.info(f"Fuzzy dedup: {fuzzy_dupes} duplicates removed, {len(non_dupes)} remaining")

    inserted_rows = db.insert_jobs_batch(non_dupes)
    # Build (Job, db_id) list for sending
    uid_to_job = {job.unique_id: job for job in non_dupes}
    inserted_jobs = [(uid_to_job[row["unique_id"]], row["id"]) for row in inserted_rows]
    log.info(f"Inserted: {len(inserted_jobs)} jobs")

    # ── 7. Send or seed ─────────────────────────────────────
    jobs_sent = 0
    if is_seed:
        log.info(f"Seed mode: {len(inserted_jobs)} jobs registered (no sending)")
    else:
        to_send = inserted_jobs[:MAX_JOBS_PER_RUN]
        if len(inserted_jobs) > MAX_JOBS_PER_RUN:
            log.warning(f"Capped to {MAX_JOBS_PER_RUN} (had {len(inserted_jobs)})")

        if to_send and TELEGRAM_BOT_TOKEN:
            from telegram import Bot
            from bot.sender import send_jobs
            from bot.notifications import notify_subscribers

            bot = Bot(token=TELEGRAM_BOT_TOKEN)
            async with bot:
                log.info(f"Sending {len(to_send)} jobs to Telegram...")
                jobs_sent = await send_jobs(bot, to_send)
                log.info(f"Sent {jobs_sent} messages")

                # Notify subscribers
                dm_count = await notify_subscribers(bot, to_send)
                log.info(f"Sent {dm_count} DM alerts")
        elif not TELEGRAM_BOT_TOKEN:
            log.warning("No TELEGRAM_BOT_TOKEN — skipping send")
        else:
            log.info("No new jobs to send")

    # ── 8. Finish run tracking ──────────────────────────────
    db.finish_run(
        run_id,
        jobs_fetched=len(all_jobs),
        jobs_filtered=len(filtered),
        jobs_new=len(new_jobs),
        jobs_sent=jobs_sent,
        source_stats=source_stats,
        errors=errors,
    )

    # ── 9. Check alerts ─────────────────────────────────────
    if TELEGRAM_BOT_TOKEN:
        try:
            from telegram import Bot
            from core.monitoring import check_alerts
            bot = Bot(token=TELEGRAM_BOT_TOKEN)
            async with bot:
                await check_alerts(bot, run_id)
        except Exception as e:
            log.warning(f"Alert check failed: {e}")

    elapsed = time.time() - start
    log.info(f"Run complete in {elapsed:.1f}s. Fetched={len(all_jobs)} Filtered={len(filtered)} New={len(new_jobs)} Sent={jobs_sent}")


if __name__ == "__main__":
    asyncio.run(main())
