import os
import sqlite3
import tempfile
import unittest

from models import Job
from db import (
    canonicalize_url,
    connect,
    count_jobs,
    get_jobs_for_sending,
    get_source_last_run,
    get_sent_topic_keys,
    job_content_hash,
    normalize_company,
    record_topic_send,
    set_job_send_status,
    update_source_run,
    upsert_job,
    upsert_jobs,
)


class DbLayerTests(unittest.TestCase):
    def test_canonicalize_url_removes_tracking_params_and_fragment(self):
        url = "https://Example.com/jobs/123/?utm_source=x&keep=1&fbclid=abc#section"
        self.assertEqual(canonicalize_url(url), "https://example.com/jobs/123?keep=1")

    def test_company_normalization_does_not_corrupt_words(self):
        self.assertEqual(normalize_company("Agency Labs LLC"), "agency labs")
        self.assertEqual(normalize_company("Saga Tech"), "saga tech")

    def test_init_upsert_and_duplicate_refresh(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "jobs.db")
            with connect(db_path) as conn:
                job = Job(
                    title="Backend Developer",
                    company="Acme LLC",
                    location="Cairo, Egypt",
                    url="https://jobs.example.com/123?utm_source=linkedin",
                    source="linkedin",
                    tags=["Python", "Django"],
                    is_remote=False,
                )
                job_id, is_new = upsert_job(conn, job)
                self.assertTrue(is_new)
                self.assertEqual(count_jobs(conn), 1)

                same_job = Job(
                    title="Backend Developer",
                    company="Acme LLC",
                    location="Cairo, Egypt",
                    url="https://jobs.example.com/123?utm_medium=social",
                    source="linkedin",
                    tags=["Python", "FastAPI"],
                    is_remote=False,
                )
                job_id_2, is_new_2 = upsert_job(conn, same_job)
                self.assertFalse(is_new_2)
                self.assertEqual(job_id_2, job_id)
                self.assertEqual(count_jobs(conn), 1)

    def test_upsert_jobs_counts_inserted_and_refreshed(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "jobs.db")
            with connect(db_path) as conn:
                jobs = [
                    Job("Data Analyst", "A", "Egypt", "https://x.test/a", "wuzzuf"),
                    Job("Data Analyst", "A", "Egypt", "https://x.test/a?utm_source=x", "wuzzuf"),
                    Job("UX Designer", "B", "Remote", "https://x.test/b", "linkedin", is_remote=True),
                ]
                inserted, refreshed = upsert_jobs(conn, jobs)
                self.assertEqual(inserted, 2)
                self.assertEqual(refreshed, 1)
                self.assertEqual(count_jobs(conn), 2)

    def test_pending_jobs_and_job_conversion(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "jobs.db")
            with connect(db_path) as conn:
                job = Job(
                    title="Frontend Developer",
                    company="Web Co",
                    location="Remote",
                    url="https://jobs.example.com/front",
                    source="wuzzuf",
                    salary="",
                    job_type="Full Time",
                    tags=["React"],
                    is_remote=True,
                )
                job_id, _ = upsert_job(conn, job)
                pending = get_jobs_for_sending(conn)
                self.assertEqual(len(pending), 1)
                self.assertEqual(pending[0].id, job_id)
                self.assertEqual(pending[0].to_job().title, "Frontend Developer")

                set_job_send_status(conn, job_id, "sent")
                self.assertEqual(get_jobs_for_sending(conn), [])

    def test_record_topic_send_and_source_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "jobs.db")
            with connect(db_path) as conn:
                job_id, _ = upsert_job(
                    conn,
                    Job("QA Engineer", "Quality Co", "Cairo", "https://jobs.example.com/qa", "wuzzuf"),
                )
                record_topic_send(conn, job_id, "qa", True)
                row = conn.execute(
                    "SELECT status, sent_at FROM job_sends WHERE job_id = ? AND topic_key = 'qa'",
                    (job_id,),
                ).fetchone()
                self.assertEqual(row["status"], "sent")
                self.assertIsNotNone(row["sent_at"])
                self.assertEqual(get_sent_topic_keys(conn, job_id), {"qa"})

                record_topic_send(conn, job_id, "qa", False, "Telegram timeout")
                row = conn.execute(
                    "SELECT status, error FROM job_sends WHERE job_id = ? AND topic_key = 'qa'",
                    (job_id,),
                ).fetchone()
                self.assertEqual(row["status"], "failed")
                self.assertEqual(row["error"], "Telegram timeout")

                update_source_run(conn, "wuzzuf", "ok", last_run_at="2026-05-24T00:00:00Z")
                self.assertEqual(get_source_last_run(conn, "wuzzuf"), "2026-05-24T00:00:00Z")

    def test_invalid_status_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "jobs.db")
            with connect(db_path) as conn:
                job_id, _ = upsert_job(
                    conn,
                    Job("Product Manager", "Product Co", "Remote", "https://jobs.example.com/pm", "linkedin"),
                )
                with self.assertRaises(ValueError):
                    set_job_send_status(conn, job_id, "unknown")

    def test_hash_is_stable_for_tracking_url_variants(self):
        base = Job("Backend Developer", "Acme LLC", "Cairo", "https://x.test/j/1", "wuzzuf")
        tracked = Job("Backend Developer", "Acme LLC", "Cairo", "https://x.test/j/1?utm_campaign=a", "linkedin")
        self.assertEqual(job_content_hash(base), job_content_hash(tracked))


if __name__ == "__main__":
    unittest.main()
