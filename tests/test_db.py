import os
import sqlite3
import tempfile
from datetime import UTC, datetime, timedelta
import unittest

from models import Job
from db import (
    canonicalize_url,
    connect,
    expire_legacy_backlog_once,
    count_jobs,
    get_jobs_for_sending,
    get_metadata,
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

    def test_legacy_backlog_expiry_is_one_time_and_preserves_fresh_jobs(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "jobs.db")
            reference = datetime(2026, 10, 4, 12, 0, tzinfo=UTC)
            old_ts = (reference - timedelta(hours=3)).isoformat().replace("+00:00", "Z")
            fresh_ts = (reference - timedelta(minutes=15)).isoformat().replace("+00:00", "Z")

            with connect(db_path) as conn:
                old_id, _ = upsert_job(
                    conn,
                    Job("Backend Developer", "Old Co", "Riyadh", "https://jobs.example.com/old", "linkedin"),
                )
                fresh_id, _ = upsert_job(
                    conn,
                    Job("Frontend Developer", "Fresh Co", "Riyadh", "https://jobs.example.com/fresh", "linkedin"),
                )
                conn.execute("UPDATE jobs SET first_seen_at = ? WHERE id = ?", (old_ts, old_id))
                conn.execute("UPDATE jobs SET first_seen_at = ? WHERE id = ?", (fresh_ts, fresh_id))

                expired = expire_legacy_backlog_once(conn, 120, reference_time=reference)
                self.assertEqual(expired, 1)
                old_status = conn.execute("SELECT send_status FROM jobs WHERE id = ?", (old_id,)).fetchone()["send_status"]
                fresh_status = conn.execute("SELECT send_status FROM jobs WHERE id = ?", (fresh_id,)).fetchone()["send_status"]
                self.assertEqual(old_status, "expired")
                self.assertEqual(fresh_status, "pending")
                self.assertIsNotNone(get_metadata(conn, "legacy_backlog_expiry_v1_applied_at"))

                # The migration marker prevents later runs from reclassifying rows.
                self.assertEqual(expire_legacy_backlog_once(conn, 1, reference_time=reference), 0)

    def test_expired_is_a_valid_terminal_send_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "jobs.db")
            with connect(db_path) as conn:
                job_id, _ = upsert_job(
                    conn,
                    Job("QA Engineer", "Acme", "Riyadh", "https://jobs.example.com/expired", "linkedin"),
                )
                set_job_send_status(conn, job_id, "expired")
                self.assertEqual(get_jobs_for_sending(conn), [])

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


class FreshnessSchemaV3Tests(unittest.TestCase):
    def test_publication_evidence_round_trips_through_sqlite(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "jobs.db")
            job = Job(
                "Backend Developer",
                "Acme",
                "Riyadh",
                "https://jobs.example.com/freshness",
                "linkedin",
                source_job_id="123",
                published_at_raw="5 minutes ago",
                published_at_earliest="2026-10-04T14:54:00Z",
                published_at_latest="2026-10-04T14:55:00Z",
                published_at_est="2026-10-04T14:55:00Z",
                published_precision="MINUTE",
                time_semantics="POSTED",
            )
            with connect(db_path) as conn:
                upsert_job(conn, job)
                stored = get_jobs_for_sending(conn)[0]
                self.assertEqual(stored.source_job_id, "123")
                self.assertEqual(stored.published_at_raw, "5 minutes ago")
                self.assertEqual(stored.published_at_earliest, "2026-10-04T14:54:00Z")
                self.assertEqual(stored.published_at_latest, "2026-10-04T14:55:00Z")
                self.assertEqual(stored.published_precision, "MINUTE")
                restored = stored.to_job()
                self.assertEqual(restored.published_at_est, "2026-10-04T14:55:00Z")
                self.assertEqual(restored.time_semantics, "POSTED")

    def test_schema_v1_source_is_migrated_as_already_baselined(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "jobs.db")
            raw = sqlite3.connect(db_path)
            raw.execute("CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            raw.execute("INSERT INTO metadata(key, value) VALUES ('schema_version', '1')")
            raw.execute(
                """
                CREATE TABLE source_runs (
                    source TEXT PRIMARY KEY,
                    last_run_at TEXT,
                    status TEXT NOT NULL DEFAULT 'never',
                    error TEXT DEFAULT '',
                    updated_at TEXT NOT NULL
                )
                """
            )
            raw.execute(
                "INSERT INTO source_runs(source, last_run_at, status, error, updated_at) VALUES (?, ?, 'ok', '', ?)",
                ("linkedin", "2026-10-04T12:00:00Z", "2026-10-04T12:00:00Z"),
            )
            raw.commit()
            raw.close()

            with connect(db_path) as conn:
                row = conn.execute("SELECT * FROM source_runs WHERE source = 'linkedin'").fetchone()
                self.assertEqual(row["last_success_at"], "2026-10-04T12:00:00Z")
                self.assertEqual(row["baselined_at"], "2026-10-04T12:00:00Z")
                self.assertEqual(get_metadata(conn, "schema_version"), "3")

    def test_new_source_does_not_auto_baseline_across_reconnects(self):
        from db import is_source_baselined, mark_source_baselined

        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "jobs.db")
            with connect(db_path) as conn:
                update_source_run(conn, "new-saudi-source", "ok", last_run_at="2026-10-04T15:00:00Z")
                self.assertFalse(is_source_baselined(conn, "new-saudi-source"))

            with connect(db_path) as conn:
                self.assertFalse(is_source_baselined(conn, "new-saudi-source"))
                mark_source_baselined(conn, "new-saudi-source", "2026-10-04T15:01:00Z")
                self.assertTrue(is_source_baselined(conn, "new-saudi-source"))

    def test_failed_run_preserves_last_success_and_counts_failures(self):
        from db import get_source_last_success, get_source_state

        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "jobs.db")
            with connect(db_path) as conn:
                update_source_run(conn, "linkedin", "ok", last_run_at="2026-10-04T15:00:00Z")
                update_source_run(conn, "linkedin", "failed", "timeout", last_run_at="2026-10-04T15:15:00Z")
                state = get_source_state(conn, "linkedin")
                self.assertEqual(get_source_last_success(conn, "linkedin"), "2026-10-04T15:00:00Z")
                self.assertEqual(state["last_run_at"], "2026-10-04T15:15:00Z")
                self.assertEqual(state["consecutive_failures"], 1)
                self.assertEqual(state["status"], "failed")
