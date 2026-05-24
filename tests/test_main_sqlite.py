import os
import tempfile
import unittest
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import main
from db import connect, count_jobs, get_jobs_for_sending, get_sent_topic_keys
from models import Job


class MainSqliteFlowTests(unittest.TestCase):
    def make_db_path(self, tmp):
        return os.path.join(tmp, "jobs.db")

    def test_run_bot_persists_then_sends_pending_jobs(self):
        job = Job(
            title="Backend Developer",
            company="Acme",
            location="Cairo, Egypt",
            url="https://wuzzuf.net/jobs/p/backend",
            source="wuzzuf",
            tags=["Python"],
        )
        sent = []

        def fake_sender(job_obj, topics):
            sent.append((job_obj.title, list(topics or [])))
            return {topic: True for topic in topics}

        def fake_router(job_obj):
            return ["general", "backend"]

        with tempfile.TemporaryDirectory() as tmp:
            summary = main.run_bot(
                db_path=self.make_db_path(tmp),
                fetchers=[("WUZZUF", lambda: [job])],
                sender=fake_sender,
                router=fake_router,
                cleanup_func=lambda: None,
                seed_mode=False,
            )
            self.assertEqual(summary.raw_jobs, 1)
            self.assertEqual(summary.filtered_jobs, 1)
            self.assertEqual(summary.inserted_jobs, 1)
            self.assertEqual(summary.topic_send_successes, 2)
            self.assertEqual(summary.topic_send_failures, 0)
            self.assertEqual(sent, [("Backend Developer", ["general", "backend"])])

            with connect(self.make_db_path(tmp)) as conn:
                self.assertEqual(count_jobs(conn), 1)
                self.assertEqual(get_jobs_for_sending(conn), [])

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
            summary1 = main.run_bot(
                db_path=db_path,
                fetchers=[("WUZZUF", lambda: [job])],
                sender=first_sender,
                router=fake_router,
                cleanup_func=lambda: None,
                seed_mode=False,
            )
            self.assertEqual(summary1.topic_send_successes, 1)
            self.assertEqual(summary1.topic_send_failures, 1)
            self.assertEqual(calls[-1], ["general", "backend"])

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
            )
            self.assertEqual(summary2.refreshed_jobs, 1)
            self.assertEqual(summary2.topic_send_successes, 1)
            self.assertEqual(summary2.topic_send_failures, 0)
            self.assertEqual(calls[-1], ["backend"])

            with connect(db_path) as conn:
                self.assertEqual(get_jobs_for_sending(conn), [])

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
            summary = main.run_bot(
                db_path=self.make_db_path(tmp),
                fetchers=[("LinkedIn", lambda: [job])],
                sender=lambda job_obj, topics: sent.append(topics) or {topic: True for topic in topics},
                router=lambda job_obj: ["linkedin_all"],
                cleanup_func=lambda: None,
                seed_mode=True,
            )
            self.assertEqual(summary.inserted_jobs, 1)
            self.assertEqual(summary.skipped_jobs, 1)
            self.assertEqual(sent, [])
            with connect(self.make_db_path(tmp)) as conn:
                self.assertEqual(get_jobs_for_sending(conn), [])

    def test_failed_source_does_not_stop_other_sources(self):
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
            summary = main.run_bot(
                db_path=self.make_db_path(tmp),
                fetchers=[("Broken", bad_fetcher), ("WUZZUF", lambda: [good_job])],
                sender=lambda job_obj, topics: {topic: True for topic in topics},
                router=lambda job_obj: ["general"],
                cleanup_func=lambda: None,
                seed_mode=False,
            )
            self.assertEqual(summary.raw_jobs, 1)
            self.assertEqual(summary.inserted_jobs, 1)
            self.assertEqual(summary.topic_send_successes, 1)

    def test_jobs_with_no_topics_are_skipped_not_retried_forever(self):
        job = Job(
            title="Backend Developer",
            company="Acme",
            location="Cairo, Egypt",
            url="https://wuzzuf.net/jobs/p/backend",
            source="wuzzuf",
        )

        with tempfile.TemporaryDirectory() as tmp:
            summary = main.run_bot(
                db_path=self.make_db_path(tmp),
                fetchers=[("WUZZUF", lambda: [job])],
                sender=lambda job_obj, topics: {topic: True for topic in topics},
                router=lambda job_obj: [],
                cleanup_func=lambda: None,
                seed_mode=False,
            )
            self.assertEqual(summary.skipped_jobs, 1)
            with connect(self.make_db_path(tmp)) as conn:
                self.assertEqual(get_jobs_for_sending(conn), [])

    def test_unclassified_linkedin_job_is_kept_for_linkedin_all_topic(self):
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
            summary = main.run_bot(
                db_path=self.make_db_path(tmp),
                fetchers=[("LinkedIn", lambda: [job])],
                sender=lambda job_obj, topics: sent.append((job_obj.title, list(topics))) or {topic: True for topic in topics},
                router=lambda job_obj: ["linkedin_all"],
                cleanup_func=lambda: None,
                seed_mode=False,
            )
            self.assertEqual(summary.filtered_jobs, 1)
            self.assertEqual(summary.inserted_jobs, 1)
            self.assertEqual(summary.topic_send_successes, 1)
            self.assertEqual(sent, [("People Operations Coordinator", ["linkedin_all"])])

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
            summary = main.run_bot(
                db_path=self.make_db_path(tmp),
                fetchers=[("WUZZUF", lambda: [job])],
                sender=lambda job_obj, topics: {topic: True for topic in topics},
                router=lambda job_obj: ["general"],
                cleanup_func=lambda: None,
                seed_mode=False,
            )
            self.assertEqual(summary.filtered_jobs, 0)
            self.assertEqual(summary.inserted_jobs, 0)
            self.assertEqual(summary.topic_send_successes, 0)
            with connect(self.make_db_path(tmp)) as conn:
                self.assertEqual(count_jobs(conn), 0)


if __name__ == "__main__":
    unittest.main()
