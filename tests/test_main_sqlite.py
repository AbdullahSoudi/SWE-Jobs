import os
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import main
from db import (
    connect,
    count_jobs,
    get_jobs_for_sending,
    get_sent_topic_keys,
    get_source_state,
    is_source_baselined,
    mark_source_baselined,
    update_source_run,
)
from freshness import parse_relative_publication
from models import Job


class MainSqliteFlowTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime.now(UTC).replace(microsecond=0)

    def make_db_path(self, tmp):
        return os.path.join(tmp, "jobs.db")

    def prime_source(self, db_path, source, minutes_ago=15):
        previous = self.now - timedelta(minutes=minutes_ago)
        stamp = previous.isoformat().replace("+00:00", "Z")
        with connect(db_path) as conn:
            update_source_run(conn, source, "ok", last_run_at=stamp)
            mark_source_baselined(conn, source, baselined_at=stamp)

    def fresh_job(self, *, title, url, source, at):
        evidence = parse_relative_publication("5 minutes ago", fetched_at=at)
        return Job(
            title=title,
            company="Acme",
            location="Riyadh, Saudi Arabia",
            url=url,
            source=source,
            tags=["Python"],
            published_at_raw=evidence.raw,
            published_at_earliest=evidence.earliest,
            published_at_latest=evidence.latest,
            published_at_est=evidence.estimate,
            published_precision=evidence.precision,
            time_semantics=evidence.semantics,
        )

    def test_new_source_first_fetch_is_baseline_then_next_new_job_sends(self):
        first_job = Job(
            title="Backend Developer",
            company="Acme",
            location="Cairo, Egypt",
            url="https://wuzzuf.net/jobs/p/backend-1",
            source="wuzzuf",
            tags=["Python"],
        )
        second_job = Job(
            title="Backend Developer II",
            company="Acme",
            location="Cairo, Egypt",
            url="https://wuzzuf.net/jobs/p/backend-2",
            source="wuzzuf",
            tags=["Python"],
        )
        sent = []

        def fake_sender(job_obj, topics):
            sent.append((job_obj.title, list(topics or [])))
            return {topic: True for topic in topics}

        with tempfile.TemporaryDirectory() as tmp:
            db_path = self.make_db_path(tmp)
            first = main.run_bot(
                db_path=db_path,
                fetchers=[("WUZZUF", lambda: [first_job])],
                sender=fake_sender,
                router=lambda job_obj: ["backend"],
                cleanup_func=lambda: None,
                seed_mode=False,
                reference_time=self.now,
            )
            self.assertEqual(first.inserted_jobs, 1)
            self.assertEqual(first.baseline_skipped_jobs, 1)
            self.assertEqual(first.sources_baselined, 1)
            self.assertEqual(first.topic_send_successes, 0)
            self.assertEqual(sent, [])

            second = main.run_bot(
                db_path=db_path,
                fetchers=[("WUZZUF", lambda: [first_job, second_job])],
                sender=fake_sender,
                router=lambda job_obj: ["backend"],
                cleanup_func=lambda: None,
                seed_mode=False,
                reference_time=self.now + timedelta(minutes=15),
            )
            self.assertEqual(second.inserted_jobs, 1)
            self.assertEqual(second.fresh_new_jobs, 1)
            self.assertEqual(second.topic_send_successes, 1)
            self.assertEqual(sent, [("Backend Developer II", ["backend"])])

            with connect(db_path) as conn:
                rows = conn.execute(
                    "SELECT title, send_status, freshness_status FROM jobs ORDER BY id"
                ).fetchall()
                self.assertEqual(rows[0]["send_status"], "skipped")
                self.assertEqual(rows[0]["freshness_status"], "BASELINE")
                self.assertEqual(rows[1]["send_status"], "sent")
                self.assertEqual(rows[1]["freshness_status"], "FRESH")

    def test_partial_send_retries_only_unsent_topics_without_duplicates(self):
        job = Job(
            title="Backend Developer",
            company="Acme",
            location="Cairo, Egypt",
            url="https://wuzzuf.net/jobs/p/backend",
            source="wuzzuf",
            tags=["Python"],
        )
        calls = []

        def fake_router(job_obj):
            return ["general", "backend"]

        def first_sender(job_obj, topics):
            calls.append(list(topics or []))
            return {"general": True, "backend": False}

        def second_sender(job_obj, topics):
            calls.append(list(topics or []))
            return {topic: True for topic in topics}

        with tempfile.TemporaryDirectory() as tmp:
            db_path = self.make_db_path(tmp)
            self.prime_source(db_path, "wuzzuf")
            summary1 = main.run_bot(
                db_path=db_path,
                fetchers=[("WUZZUF", lambda: [job])],
                sender=first_sender,
                router=fake_router,
                cleanup_func=lambda: None,
                seed_mode=False,
                reference_time=self.now,
            )
            self.assertEqual(summary1.topic_send_successes, 1)
            self.assertEqual(summary1.topic_send_failures, 1)
            self.assertEqual(calls[-2:], [["general"], ["backend"]])

            with connect(db_path) as conn:
                pending = get_jobs_for_sending(conn)
                self.assertEqual(len(pending), 1)
                self.assertEqual(pending[0].send_status, "partial")
                self.assertEqual(get_sent_topic_keys(conn, pending[0].id), {"general"})

            summary2 = main.run_bot(
                db_path=db_path,
                fetchers=[("WUZZUF", lambda: [job])],
                sender=second_sender,
                router=fake_router,
                cleanup_func=lambda: None,
                seed_mode=False,
                reference_time=self.now + timedelta(minutes=15),
            )
            self.assertEqual(summary2.refreshed_jobs, 1)
            self.assertEqual(summary2.topic_send_successes, 1)
            self.assertEqual(summary2.topic_send_failures, 0)
            self.assertEqual(calls[-1], ["backend"])

            with connect(db_path) as conn:
                self.assertEqual(get_jobs_for_sending(conn), [])

    def test_legacy_multi_topic_success_suppresses_new_primary_topic_duplicate(self):
        job = Job(
            title="Backend Developer",
            company="Acme",
            location="Cairo, Egypt",
            url="https://wuzzuf.net/jobs/p/routing-migration",
            source="wuzzuf",
            tags=["Python"],
        )
        calls = []

        def old_router(job_obj):
            return ["general", "backend"]

        def first_sender(job_obj, topics):
            topic = topics[0]
            calls.append(topic)
            return {topic: topic == "general"}

        with tempfile.TemporaryDirectory() as tmp:
            db_path = self.make_db_path(tmp)
            self.prime_source(db_path, "wuzzuf")
            first = main.run_bot(
                db_path=db_path,
                fetchers=[("WUZZUF", lambda: [job])],
                sender=first_sender,
                router=old_router,
                cleanup_func=lambda: None,
                seed_mode=False,
                reference_time=self.now,
            )
            self.assertEqual(first.topic_send_successes, 1)
            self.assertEqual(first.topic_send_failures, 1)
            self.assertEqual(calls, ["general", "backend"])

            second_calls = []
            second = main.run_bot(
                db_path=db_path,
                fetchers=[("WUZZUF", lambda: [job])],
                sender=lambda job_obj, topics: second_calls.append(topics[0]) or {topics[0]: True},
                cleanup_func=lambda: None,
                seed_mode=False,
                reference_time=self.now + timedelta(minutes=15),
            )
            self.assertEqual(second.topic_send_successes, 0)
            self.assertEqual(second_calls, [])
            with connect(db_path) as conn:
                row = conn.execute(
                    "SELECT send_status FROM jobs WHERE url = ?", (job.url,)
                ).fetchone()
                self.assertEqual(row["send_status"], "sent")

    def test_unknown_source_stays_shadow_after_baseline_until_explicitly_promoted(self):
        source = "saudiboard"
        first_time = self.now
        second_time = self.now + timedelta(minutes=15)
        third_time = self.now + timedelta(minutes=30)
        job1 = self.fresh_job(
            title="Backend Developer I",
            url="https://jobs.example.com/saudi-1",
            source=source,
            at=first_time,
        )
        job2 = self.fresh_job(
            title="Backend Developer II",
            url="https://jobs.example.com/saudi-2",
            source=source,
            at=second_time,
        )
        job3 = self.fresh_job(
            title="Backend Developer III",
            url="https://jobs.example.com/saudi-3",
            source=source,
            at=third_time,
        )
        sent = []

        def fake_sender(job_obj, topics):
            sent.append(job_obj.title)
            return {topic: True for topic in topics}

        with tempfile.TemporaryDirectory() as tmp:
            db_path = self.make_db_path(tmp)

            first = main.run_bot(
                db_path=db_path,
                fetchers=[("SaudiBoard", lambda: [job1])],
                sender=fake_sender,
                router=lambda job_obj: ["backend"],
                cleanup_func=lambda: None,
                reference_time=first_time,
            )
            self.assertEqual(first.baseline_skipped_jobs, 1)
            self.assertEqual(sent, [])

            second = main.run_bot(
                db_path=db_path,
                fetchers=[("SaudiBoard", lambda: [job1, job2])],
                sender=fake_sender,
                router=lambda job_obj: ["backend"],
                cleanup_func=lambda: None,
                reference_time=second_time,
            )
            self.assertEqual(second.fresh_new_jobs, 1)
            self.assertEqual(second.shadow_eligible_jobs, 1)
            self.assertEqual(second.topic_send_successes, 0)
            self.assertEqual(sent, [])

            with connect(db_path) as conn:
                row = conn.execute(
                    "SELECT send_status FROM jobs WHERE url = ?", (job2.url,)
                ).fetchone()
                self.assertEqual(row["send_status"], "shadow")
                state = get_source_state(conn, source)
                self.assertEqual(state["shadow_mode"], 1)
                history = conn.execute(
                    "SELECT * FROM source_run_history WHERE source = ? ORDER BY id",
                    (source,),
                ).fetchall()
                self.assertEqual(len(history), 2)
                self.assertEqual(history[-1]["shadow_eligible_count"], 1)

            third = main.run_bot(
                db_path=db_path,
                fetchers=[("SaudiBoard", lambda: [job1, job2, job3])],
                sender=fake_sender,
                router=lambda job_obj: ["backend"],
                cleanup_func=lambda: None,
                reference_time=third_time,
                production_source_keys={source},
            )
            self.assertEqual(third.fresh_new_jobs, 1)
            self.assertEqual(third.shadow_eligible_jobs, 0)
            self.assertEqual(third.topic_send_successes, 1)
            self.assertEqual(sent, ["Backend Developer III"])
            with connect(db_path) as conn:
                state = get_source_state(conn, source)
                self.assertEqual(state["shadow_mode"], 0)
                old_shadow = conn.execute(
                    "SELECT send_status FROM jobs WHERE url = ?", (job2.url,)
                ).fetchone()["send_status"]
                self.assertEqual(old_shadow, "shadow")

    def test_source_run_metrics_capture_failure_and_success(self):
        job = self.fresh_job(
            title="Backend Developer",
            url="https://jobs.example.com/metrics",
            source="wuzzuf",
            at=self.now,
        )

        def broken():
            raise RuntimeError("source down")

        with tempfile.TemporaryDirectory() as tmp:
            db_path = self.make_db_path(tmp)
            self.prime_source(db_path, "wuzzuf")
            summary = main.run_bot(
                db_path=db_path,
                fetchers=[("Broken", broken), ("WUZZUF", lambda: [job])],
                sender=lambda job_obj, topics: {topic: True for topic in topics},
                router=lambda job_obj: ["backend"],
                cleanup_func=lambda: None,
                reference_time=self.now,
            )
            self.assertEqual(summary.source_runs_recorded, 2)
            self.assertEqual(summary.source_failures, 1)
            with connect(db_path) as conn:
                success = conn.execute(
                    "SELECT * FROM source_run_history WHERE source = 'wuzzuf' ORDER BY id DESC LIMIT 1"
                ).fetchone()
                failed = conn.execute(
                    "SELECT * FROM source_run_history WHERE source = 'broken' ORDER BY id DESC LIMIT 1"
                ).fetchone()
                self.assertEqual(success["status"], "ok")
                self.assertEqual(success["raw_count"], 1)
                self.assertEqual(success["filtered_count"], 1)
                self.assertEqual(success["inserted_count"], 1)
                self.assertEqual(failed["status"], "failed")
                self.assertIn("source down", failed["error"])

    def test_seed_mode_stores_jobs_without_sending(self):
        job = Job(
            title="Data Analyst",
            company="Acme",
            location="Remote",
            url="https://www.linkedin.com/jobs/view/1234567890",
            source="linkedin",
            tags=["Data"],
            is_remote=True,
        )
        sent = []

        with tempfile.TemporaryDirectory() as tmp:
            db_path = self.make_db_path(tmp)
            summary = main.run_bot(
                db_path=db_path,
                fetchers=[("LinkedIn", lambda: [job])],
                sender=lambda job_obj, topics: sent.append(topics) or {topic: True for topic in topics},
                router=lambda job_obj: ["general"],
                cleanup_func=lambda: None,
                seed_mode=True,
                reference_time=self.now,
            )
            self.assertEqual(summary.inserted_jobs, 1)
            self.assertEqual(summary.baseline_skipped_jobs, 1)
            self.assertEqual(summary.sources_baselined, 1)
            self.assertEqual(sent, [])
            with connect(db_path) as conn:
                self.assertEqual(get_jobs_for_sending(conn), [])
                self.assertTrue(is_source_baselined(conn, "linkedin"))

    def test_run_expires_old_legacy_backlog_before_sending(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self.make_db_path(tmp)
            old_job = Job(
                title="Backend Developer",
                company="Legacy Co",
                location="Riyadh, Saudi Arabia",
                url="https://www.linkedin.com/jobs/view/7777777777",
                source="linkedin",
            )
            with connect(db_path) as conn:
                main.upsert_jobs(conn, [old_job])
                row = conn.execute("SELECT id FROM jobs WHERE url = ?", (old_job.url,)).fetchone()
                old_ts = (self.now - timedelta(hours=3)).isoformat().replace("+00:00", "Z")
                conn.execute("UPDATE jobs SET first_seen_at = ? WHERE id = ?", (old_ts, row["id"]))

            sent = []
            summary = main.run_bot(
                db_path=db_path,
                fetchers=[],
                sender=lambda job_obj, topics: sent.append(job_obj.title) or {topic: True for topic in topics},
                router=lambda job_obj: ["backend"],
                cleanup_func=lambda: None,
                seed_mode=False,
                reference_time=self.now,
            )

            self.assertEqual(summary.expired_backlog_jobs, 1)
            self.assertEqual(summary.pending_processed, 0)
            self.assertEqual(sent, [])
            with connect(db_path) as conn:
                status = conn.execute(
                    "SELECT send_status FROM jobs WHERE url = ?", (old_job.url,)
                ).fetchone()["send_status"]
                self.assertEqual(status, "expired")

    def test_live_queue_deadline_expires_retry_before_it_can_send_late(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self.make_db_path(tmp)
            job = Job(
                title="QA Engineer",
                company="Acme",
                location="Cairo, Egypt",
                url="https://wuzzuf.net/jobs/p/qa-old",
                source="wuzzuf",
            )
            with connect(db_path) as conn:
                job_id, _ = main.upsert_job(conn, job)
                old_ts = (self.now - timedelta(minutes=75)).isoformat().replace("+00:00", "Z")
                conn.execute(
                    "UPDATE jobs SET first_seen_at = ?, send_status = 'retry' WHERE id = ?",
                    (old_ts, job_id),
                )

            sent = []
            summary = main.run_bot(
                db_path=db_path,
                fetchers=[],
                sender=lambda job_obj, topics: sent.append(job_obj.title) or {topic: True for topic in topics},
                router=lambda job_obj: ["qa"],
                cleanup_func=lambda: None,
                seed_mode=False,
                reference_time=self.now,
            )
            self.assertEqual(summary.expired_queue_jobs, 1)
            self.assertEqual(summary.pending_processed, 0)
            self.assertEqual(sent, [])
            with connect(db_path) as conn:
                row = conn.execute(
                    "SELECT send_status, freshness_reason FROM jobs WHERE id = ?", (job_id,)
                ).fetchone()
                self.assertEqual(row["send_status"], "expired")
                self.assertEqual(row["freshness_reason"], "send_queue_deadline_exceeded")

    def test_failed_source_does_not_stop_other_sources_or_baseline_failed_source(self):
        good_job = Job(
            title="Frontend Developer",
            company="Acme",
            location="Remote",
            url="https://wuzzuf.net/jobs/p/frontend",
            source="wuzzuf",
            tags=["React"],
            is_remote=True,
        )

        def bad_fetcher():
            raise RuntimeError("source down")

        with tempfile.TemporaryDirectory() as tmp:
            db_path = self.make_db_path(tmp)
            self.prime_source(db_path, "wuzzuf")
            summary = main.run_bot(
                db_path=db_path,
                fetchers=[("Broken", bad_fetcher), ("WUZZUF", lambda: [good_job])],
                sender=lambda job_obj, topics: {topic: True for topic in topics},
                router=lambda job_obj: ["general"],
                cleanup_func=lambda: None,
                seed_mode=False,
                reference_time=self.now,
            )
            self.assertEqual(summary.raw_jobs, 1)
            self.assertEqual(summary.inserted_jobs, 1)
            self.assertEqual(summary.topic_send_successes, 1)
            with connect(db_path) as conn:
                self.assertFalse(is_source_baselined(conn, "broken"))
                self.assertEqual(get_source_state(conn, "broken")["status"], "failed")

    def test_jobs_with_no_topics_are_skipped_not_retried_forever(self):
        job = Job(
            title="Backend Developer",
            company="Acme",
            location="Cairo, Egypt",
            url="https://wuzzuf.net/jobs/p/backend-no-topic",
            source="wuzzuf",
        )

        with tempfile.TemporaryDirectory() as tmp:
            db_path = self.make_db_path(tmp)
            self.prime_source(db_path, "wuzzuf")
            summary = main.run_bot(
                db_path=db_path,
                fetchers=[("WUZZUF", lambda: [job])],
                sender=lambda job_obj, topics: {topic: True for topic in topics},
                router=lambda job_obj: [],
                cleanup_func=lambda: None,
                seed_mode=False,
                reference_time=self.now,
            )
            self.assertEqual(summary.skipped_jobs, 1)
            with connect(db_path) as conn:
                self.assertEqual(get_jobs_for_sending(conn), [])

    def test_unclassified_linkedin_job_is_filtered_before_persistence(self):
        job = Job(
            title="People Operations Coordinator",
            company="Acme",
            location="Cairo, Egypt",
            url="https://www.linkedin.com/jobs/view/5555555555",
            source="linkedin",
            tags=[],
            is_remote=False,
        )
        sent = []

        with tempfile.TemporaryDirectory() as tmp:
            db_path = self.make_db_path(tmp)
            self.prime_source(db_path, "linkedin")
            summary = main.run_bot(
                db_path=db_path,
                fetchers=[("LinkedIn", lambda: [job])],
                sender=lambda job_obj, topics: sent.append((job_obj.title, list(topics))) or {topic: True for topic in topics},
                cleanup_func=lambda: None,
                seed_mode=False,
                reference_time=self.now,
            )
            self.assertEqual(summary.filtered_jobs, 0)
            self.assertEqual(summary.inserted_jobs, 0)
            self.assertEqual(summary.fresh_new_jobs, 0)
            self.assertEqual(summary.topic_send_successes, 0)
            self.assertEqual(summary.skipped_jobs, 0)
            self.assertEqual(sent, [])
            with connect(db_path) as conn:
                self.assertEqual(count_jobs(conn), 0)

    def test_old_linkedin_job_is_stored_but_never_sent(self):
        evidence = parse_relative_publication("2 hours ago", fetched_at=self.now)
        job = Job(
            title="Backend Developer",
            company="Acme",
            location="Riyadh, Saudi Arabia",
            url="https://www.linkedin.com/jobs/view/9999999999",
            source="linkedin",
            published_at_raw=evidence.raw,
            published_at_earliest=evidence.earliest,
            published_at_latest=evidence.latest,
            published_at_est=evidence.estimate,
            published_precision=evidence.precision,
            time_semantics=evidence.semantics,
        )
        sent = []

        with tempfile.TemporaryDirectory() as tmp:
            db_path = self.make_db_path(tmp)
            self.prime_source(db_path, "linkedin")
            summary = main.run_bot(
                db_path=db_path,
                fetchers=[("LinkedIn", lambda: [job])],
                sender=lambda job_obj, topics: sent.append(job_obj.title) or {topic: True for topic in topics},
                router=lambda job_obj: ["backend"],
                cleanup_func=lambda: None,
                seed_mode=False,
                reference_time=self.now,
            )
            self.assertEqual(summary.inserted_jobs, 1)
            self.assertEqual(summary.fresh_new_jobs, 0)
            self.assertEqual(summary.expired_new_jobs, 1)
            self.assertEqual(sent, [])
            with connect(db_path) as conn:
                row = conn.execute(
                    "SELECT send_status, freshness_status FROM jobs WHERE url = ?", (job.url,)
                ).fetchone()
                self.assertEqual(row["send_status"], "expired")
                self.assertEqual(row["freshness_status"], "TOO_OLD")

    def test_observation_fallback_is_disabled_after_long_source_gap(self):
        job = Job(
            title="Backend Developer",
            company="Acme",
            location="Cairo, Egypt",
            url="https://wuzzuf.net/jobs/p/after-gap",
            source="wuzzuf",
        )

        with tempfile.TemporaryDirectory() as tmp:
            db_path = self.make_db_path(tmp)
            self.prime_source(db_path, "wuzzuf", minutes_ago=90)
            summary = main.run_bot(
                db_path=db_path,
                fetchers=[("WUZZUF", lambda: [job])],
                sender=lambda job_obj, topics: {topic: True for topic in topics},
                router=lambda job_obj: ["backend"],
                cleanup_func=lambda: None,
                seed_mode=False,
                reference_time=self.now,
            )
            self.assertEqual(summary.inserted_jobs, 1)
            self.assertEqual(summary.uncertain_new_jobs, 1)
            self.assertEqual(summary.topic_send_successes, 0)
            with connect(db_path) as conn:
                row = conn.execute(
                    "SELECT send_status, freshness_reason FROM jobs WHERE url = ?", (job.url,)
                ).fetchone()
                self.assertEqual(row["send_status"], "expired")
                self.assertEqual(row["freshness_reason"], "coverage_gap_too_large")

    def test_unclassified_non_linkedin_job_is_still_filtered_out(self):
        job = Job(
            title="People Operations Coordinator",
            company="Acme",
            location="Cairo, Egypt",
            url="https://wuzzuf.net/jobs/p/people-ops",
            source="wuzzuf",
            tags=[],
            is_remote=False,
        )

        with tempfile.TemporaryDirectory() as tmp:
            db_path = self.make_db_path(tmp)
            summary = main.run_bot(
                db_path=db_path,
                fetchers=[("WUZZUF", lambda: [job])],
                sender=lambda job_obj, topics: {topic: True for topic in topics},
                router=lambda job_obj: ["general"],
                cleanup_func=lambda: None,
                seed_mode=False,
                reference_time=self.now,
            )
            self.assertEqual(summary.filtered_jobs, 0)
            self.assertEqual(summary.inserted_jobs, 0)
            self.assertEqual(summary.topic_send_successes, 0)
            with connect(db_path) as conn:
                self.assertEqual(count_jobs(conn), 0)

    def test_rate_limit_stops_wider_queue_and_persists_retry_after(self):
        from telegram_sender import RATE_LIMITED, TelegramSendResult

        jobs = [
            Job(
                title=f"Backend Developer {i}",
                company="Acme",
                location="Cairo, Egypt",
                url=f"https://wuzzuf.net/jobs/p/rate-{i}",
                source="wuzzuf",
                tags=["Python"],
            )
            for i in (1, 2)
        ]
        calls = []

        def limited_sender(job_obj, topics):
            calls.append(job_obj.title)
            topic = topics[0]
            return {
                topic: TelegramSendResult(
                    False, RATE_LIMITED, "Too Many Requests",
                    http_status=429, tg_error_code=429, retry_after_s=20,
                )
            }

        with tempfile.TemporaryDirectory() as tmp:
            db_path = self.make_db_path(tmp)
            self.prime_source(db_path, "wuzzuf")
            summary = main.run_bot(
                db_path=db_path,
                fetchers=[("WUZZUF", lambda: jobs)],
                sender=limited_sender,
                router=lambda job_obj: ["backend"],
                cleanup_func=lambda: None,
                seed_mode=False,
                reference_time=self.now,
            )
            self.assertEqual(len(calls), 1)
            self.assertEqual(summary.topic_send_failures, 1)
            with connect(db_path) as conn:
                delivery = conn.execute(
                    "SELECT status, retry_after_s FROM job_sends ORDER BY id LIMIT 1"
                ).fetchone()
                self.assertEqual(delivery["status"], "retry_wait")
                self.assertEqual(delivery["retry_after_s"], 20)
                self.assertEqual(len(get_jobs_for_sending(conn)), 2)

            # retry_after pauses the whole supergroup queue, not just this row.
            second = main.run_bot(
                db_path=db_path,
                fetchers=[("WUZZUF", lambda: jobs)],
                sender=lambda job_obj, topics: calls.append("should-not-send") or {topics[0]: True},
                router=lambda job_obj: ["backend"],
                cleanup_func=lambda: None,
                seed_mode=False,
                reference_time=self.now + timedelta(seconds=10),
            )
            self.assertEqual(second.topic_send_successes, 0)
            self.assertNotIn("should-not-send", calls)

    def test_unknown_delivery_becomes_terminal_not_blindly_retried(self):
        from telegram_sender import UNKNOWN, TelegramSendResult

        job = Job(
            title="Backend Developer",
            company="Acme",
            location="Cairo, Egypt",
            url="https://wuzzuf.net/jobs/p/ambiguous",
            source="wuzzuf",
            tags=["Python"],
        )
        calls = []

        def ambiguous_sender(job_obj, topics):
            calls.append(job_obj.title)
            return {topics[0]: TelegramSendResult(False, UNKNOWN, "ReadTimeout")}

        with tempfile.TemporaryDirectory() as tmp:
            db_path = self.make_db_path(tmp)
            self.prime_source(db_path, "wuzzuf")
            main.run_bot(
                db_path=db_path,
                fetchers=[("WUZZUF", lambda: [job])],
                sender=ambiguous_sender,
                router=lambda job_obj: ["backend"],
                cleanup_func=lambda: None,
                seed_mode=False,
                reference_time=self.now,
            )
            with connect(db_path) as conn:
                row = conn.execute("SELECT send_status FROM jobs").fetchone()
                self.assertEqual(row["send_status"], "unknown")
                self.assertEqual(get_jobs_for_sending(conn), [])
            self.assertEqual(calls, ["Backend Developer"])

    def test_discovery_only_source_never_queues_telegram_even_with_fresh_timestamp(self):
        evidence = parse_relative_publication("5 minutes ago", fetched_at=self.now)
        job = Job(
            title="Backend Software Developer",
            company="Saudi Tech Co",
            location="Riyadh, Saudi Arabia",
            url="https://www.jobzaty.com/job/backend-developer-1",
            source="jobzaty",
            source_job_id="backend-developer-1",
            tags=["تقنية المعلومات", "backend"],
            published_at_raw=evidence.raw,
            published_at_earliest=evidence.earliest,
            published_at_latest=evidence.latest,
            published_at_est=evidence.estimate,
            published_precision=evidence.precision,
            time_semantics=evidence.semantics,
        )
        calls = []

        with tempfile.TemporaryDirectory() as tmp:
            db_path = self.make_db_path(tmp)
            self.prime_source(db_path, "jobzaty", minutes_ago=60)
            summary = main.run_bot(
                db_path=db_path,
                fetchers=[("Jobzaty", lambda: [job])],
                sender=lambda job_obj, topics: calls.append((job_obj, topics)) or {topics[0]: True},
                router=lambda job_obj: ["backend"],
                cleanup_func=lambda: None,
                seed_mode=False,
                reference_time=self.now,
                source_poll_intervals={"jobzaty": 60},
            )
            self.assertEqual(summary.inserted_jobs, 1)
            self.assertEqual(summary.fresh_new_jobs, 0)
            self.assertEqual(summary.topic_send_successes, 0)
            self.assertEqual(calls, [])

            with connect(db_path) as conn:
                row = conn.execute(
                    "SELECT send_status, freshness_status, freshness_reason FROM jobs LIMIT 1"
                ).fetchone()
                self.assertEqual(row["send_status"], "expired")
                self.assertEqual(row["freshness_status"], "UNCERTAIN")
                self.assertEqual(row["freshness_reason"], "discovery_only_source")

            # A discovery-only observation must not suppress a later fresh
            # production observation of the same real-world opening.
            linkedin_evidence = parse_relative_publication(
                "3 minutes ago", fetched_at=self.now + timedelta(minutes=5)
            )
            production_job = Job(
                title="Backend Software Developer",
                company="Saudi Tech Co",
                location="Riyadh, Saudi Arabia",
                url="https://www.linkedin.com/jobs/view/1234509876",
                source="linkedin",
                source_job_id="1234509876",
                tags=["backend"],
                published_at_raw=linkedin_evidence.raw,
                published_at_earliest=linkedin_evidence.earliest,
                published_at_latest=linkedin_evidence.latest,
                published_at_est=linkedin_evidence.estimate,
                published_precision=linkedin_evidence.precision,
                time_semantics=linkedin_evidence.semantics,
            )
            self.prime_source(db_path, "linkedin", minutes_ago=15)
            promoted_calls = []
            promoted = main.run_bot(
                db_path=db_path,
                fetchers=[("LinkedIn", lambda: [production_job])],
                sender=lambda job_obj, topics: promoted_calls.append(job_obj.source) or {topics[0]: True},
                router=lambda job_obj: ["backend"],
                cleanup_func=lambda: None,
                seed_mode=False,
                reference_time=self.now + timedelta(minutes=5),
            )
            self.assertEqual(promoted.fresh_new_jobs, 1)
            self.assertEqual(promoted.topic_send_successes, 1)
            self.assertEqual(promoted_calls, ["linkedin"])
            with connect(db_path) as conn:
                rows = conn.execute("SELECT source, send_status FROM jobs").fetchall()
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]["source"], "linkedin")
                self.assertEqual(rows[0]["send_status"], "sent")


if __name__ == "__main__":
    unittest.main()

class ShadowPromotionTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime.now(UTC).replace(microsecond=0)

    def _fresh(self, source):
        evidence = parse_relative_publication("5 minutes ago", fetched_at=self.now)
        return Job(
            title="Backend Developer",
            company="Acme",
            location="Riyadh, Saudi Arabia",
            url="https://www.linkedin.com/jobs/view/9999999999",
            source=source,
            tags=[".NET"],
            source_job_id="9999999999",
            published_at_raw=evidence.raw,
            published_at_earliest=evidence.earliest,
            published_at_latest=evidence.latest,
            published_at_est=evidence.estimate,
            published_precision=evidence.precision,
            time_semantics=evidence.semantics,
        )

    def test_shadow_discovery_does_not_block_later_production_delivery(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "jobs.db")
            stamp = (self.now - timedelta(minutes=15)).isoformat().replace("+00:00", "Z")
            with connect(db_path) as conn:
                for source in ("linkedin_saudi_v2", "linkedin"):
                    update_source_run(conn, source, "ok", last_run_at=stamp)
                    mark_source_baselined(conn, source, baselined_at=stamp)

            shadow_job = self._fresh("linkedin_saudi_v2")
            first = main.run_bot(
                db_path=db_path,
                fetchers=[("LinkedIn Saudi V2", lambda: [shadow_job])],
                sender=lambda job_obj, topics: {topic: True for topic in topics},
                router=lambda job_obj: ["backend"],
                cleanup_func=lambda: None,
                reference_time=self.now,
            )
            self.assertEqual(first.shadow_eligible_jobs, 1)
            with connect(db_path) as conn:
                row = conn.execute("SELECT source, send_status FROM jobs").fetchone()
                self.assertEqual(row["source"], "linkedin_saudi_v2")
                self.assertEqual(row["send_status"], "shadow")

            sent = []
            production_job = self._fresh("linkedin")
            second = main.run_bot(
                db_path=db_path,
                fetchers=[("LinkedIn", lambda: [production_job])],
                sender=lambda job_obj, topics: sent.append(job_obj.title) or {topic: True for topic in topics},
                router=lambda job_obj: ["backend"],
                cleanup_func=lambda: None,
                reference_time=self.now + timedelta(minutes=10),
            )
            self.assertEqual(second.inserted_jobs, 0)
            self.assertEqual(second.refreshed_jobs, 1)
            self.assertEqual(second.fresh_new_jobs, 1)
            self.assertEqual(second.topic_send_successes, 1)
            self.assertEqual(sent, ["Backend Developer"])
            with connect(db_path) as conn:
                row = conn.execute("SELECT source, send_status FROM jobs").fetchone()
                self.assertEqual(row["source"], "linkedin")
                self.assertEqual(row["send_status"], "sent")


class ATSSnapshotShadowFlowTests(unittest.TestCase):
    def test_ats_snapshot_source_baselines_then_marks_new_tech_job_shadow_without_sending(self):
        now = datetime.now(UTC).replace(microsecond=0)
        baseline_job = Job(
            title="Backend Engineer",
            company="HALA",
            location="Riyadh, Saudi Arabia",
            url="https://job-boards.greenhouse.io/hala/jobs/1",
            source="ats_greenhouse_hala",
            source_job_id="1",
            original_source="HALA Careers",
        )
        fresh_job = Job(
            title="Site Reliability Engineer",
            company="HALA",
            location="Riyadh, Saudi Arabia",
            url="https://job-boards.greenhouse.io/hala/jobs/2",
            source="ats_greenhouse_hala",
            source_job_id="2",
            original_source="HALA Careers",
        )
        sent = []

        def sender(job_obj, topics):
            sent.append(job_obj.title)
            return {topic: True for topic in topics}

        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "jobs.db")
            first = main.run_bot(
                db_path=db_path,
                fetchers=[("ATS Greenhouse hala", lambda: [baseline_job])],
                sender=sender,
                router=lambda job_obj: ["backend"],
                cleanup_func=lambda: None,
                seed_mode=False,
                reference_time=now,
            )
            self.assertEqual(first.baseline_skipped_jobs, 1)
            self.assertEqual(sent, [])

            second = main.run_bot(
                db_path=db_path,
                fetchers=[("ATS Greenhouse hala", lambda: [baseline_job, fresh_job])],
                sender=sender,
                router=lambda job_obj: ["backend"],
                cleanup_func=lambda: None,
                seed_mode=False,
                reference_time=now + timedelta(minutes=30),
            )
            self.assertEqual(second.fresh_new_jobs, 1)
            self.assertEqual(second.shadow_eligible_jobs, 1)
            self.assertEqual(second.topic_send_successes, 0)
            self.assertEqual(sent, [])

            with connect(db_path) as conn:
                row = conn.execute(
                    "SELECT send_status, freshness_reason FROM jobs WHERE url = ?",
                    (fresh_job.url,),
                ).fetchone()
                self.assertEqual(row["send_status"], "shadow")
                self.assertEqual(row["freshness_reason"], "recent_observation_after_success")



if __name__ == "__main__":
    unittest.main()
