import os
import tempfile
import unittest
from datetime import UTC, datetime, timedelta

from db import (
    connect,
    record_source_observation,
    record_source_run_history,
    set_metadata,
    upsert_job,
)
from freshness import iso_utc
from models import Job
from source_analytics import build_source_analytics, format_source_analytics


class SourceAnalyticsTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)

    def _job(self, suffix: str, location: str = "Riyadh, Saudi Arabia") -> Job:
        return Job(
            title="Backend Developer",
            company="Acme",
            location=location,
            url=f"https://www.linkedin.com/jobs/view/{suffix}",
            source="linkedin_saudi_v2",
            source_job_id=suffix,
        )

    def test_observation_upsert_preserves_first_seen_and_counts_repeats(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "jobs.db")
            with connect(db_path) as conn:
                job_id, _ = upsert_job(conn, self._job("100"))
                t1 = iso_utc(self.now - timedelta(minutes=20))
                t2 = iso_utc(self.now - timedelta(minutes=5))
                record_source_observation(
                    conn, job_id, "linkedin_saudi_v2",
                    source_job_id="100", observed_at=t1,
                    fresh_eligible=True, shadow_mode=True, was_new_job=True,
                )
                record_source_observation(
                    conn, job_id, "linkedin_saudi_v2",
                    source_job_id="100", observed_at=t2,
                    fresh_eligible=False, shadow_mode=True, was_new_job=False,
                )
                row = conn.execute(
                    "SELECT * FROM source_observations WHERE job_id = ? AND source = ?",
                    (job_id, "linkedin_saudi_v2"),
                ).fetchone()
                self.assertEqual(row["first_seen_at"], t1)
                self.assertEqual(row["last_seen_at"], t2)
                self.assertEqual(row["times_seen"], 2)
                self.assertEqual(row["first_fresh_eligible"], 1)
                self.assertEqual(row["last_fresh_eligible"], 0)
                self.assertEqual(row["first_was_new_job"], 1)

    def test_first_discovery_lead_and_exclusive_metrics_are_processing_order_independent(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "jobs.db")
            with connect(db_path) as conn:
                start = self.now - timedelta(days=3)
                set_metadata(conn, "source_analytics_started_at", iso_utc(start))

                # Job 1: V2 sees it first, production sees it 30 minutes later.
                job1, _ = upsert_job(conn, self._job("101"))
                v2_t1 = self.now - timedelta(hours=30)
                prod_t1 = v2_t1 + timedelta(minutes=30)
                record_source_observation(
                    conn, job1, "linkedin_saudi_v2",
                    observed_at=iso_utc(v2_t1), fresh_eligible=True,
                    shadow_mode=True, was_new_job=True,
                )
                record_source_observation(
                    conn, job1, "linkedin",
                    observed_at=iso_utc(prod_t1), fresh_eligible=True,
                    shadow_mode=False, was_new_job=False,
                )

                # Job 2: V2 sees it first and nobody else sees it within 24h.
                job2, _ = upsert_job(conn, self._job("102"))
                v2_t2 = self.now - timedelta(hours=26)
                record_source_observation(
                    conn, job2, "linkedin_saudi_v2",
                    observed_at=iso_utc(v2_t2), fresh_eligible=True,
                    shadow_mode=True, was_new_job=True,
                )

                # Job 3 is Egypt-only and must be excluded by saudi_only.
                job3, _ = upsert_job(conn, self._job("103", "Cairo, Egypt"))
                record_source_observation(
                    conn, job3, "linkedin_saudi_v2",
                    observed_at=iso_utc(self.now - timedelta(hours=25)),
                    fresh_eligible=True, shadow_mode=True, was_new_job=True,
                )

                rows = build_source_analytics(
                    conn,
                    sources=("linkedin_saudi_v2", "linkedin"),
                    hours=72,
                    saudi_only=True,
                    reference_time=self.now,
                )
                by_source = {row.source: row for row in rows}
                v2 = by_source["linkedin_saudi_v2"]
                prod = by_source["linkedin"]

                self.assertEqual(v2.discoveries, 2)
                self.assertEqual(v2.first_discoveries, 2)
                self.assertEqual(v2.mature_first_discoveries, 2)
                self.assertEqual(v2.exclusive_24h, 1)
                self.assertEqual(v2.median_lead_minutes, 30.0)
                self.assertEqual(prod.discoveries, 1)
                self.assertEqual(prod.first_discoveries, 0)

    def test_run_quality_metrics_and_formatting(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "jobs.db")
            with connect(db_path) as conn:
                set_metadata(
                    conn, "source_analytics_started_at",
                    iso_utc(self.now - timedelta(days=1)),
                )
                record_source_run_history(
                    conn,
                    "linkedin_saudi_v2",
                    run_at=iso_utc(self.now - timedelta(minutes=15)),
                    status="ok",
                    raw_count=100,
                    filtered_count=40,
                    fresh_count=12,
                    shadow_eligible_count=12,
                    shadow_mode=True,
                )
                record_source_run_history(
                    conn,
                    "linkedin_saudi_v2",
                    run_at=iso_utc(self.now),
                    status="failed",
                    error="timeout",
                    shadow_mode=True,
                    coverage_gap=True,
                )
                rows = build_source_analytics(
                    conn,
                    sources=("linkedin_saudi_v2",),
                    hours=24,
                    saudi_only=True,
                    reference_time=self.now,
                )
                row = rows[0]
                self.assertEqual(row.runs, 2)
                self.assertEqual(row.successful_runs, 1)
                self.assertEqual(row.raw_count, 100)
                self.assertEqual(row.relevant_count, 40)
                self.assertAlmostEqual(row.relevant_rate, 0.4)
                self.assertEqual(row.coverage_gaps, 1)
                line = format_source_analytics(rows, label="Saudi 24h")[0]
                self.assertIn("linkedin_saudi_v2", line)
                self.assertIn("relevant=40 (40%)", line)
                self.assertIn("gaps=1", line)

    def test_pre_tracking_jobs_are_not_counted_as_discoveries(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "jobs.db")
            with connect(db_path) as conn:
                tracking_start = self.now - timedelta(hours=2)
                set_metadata(conn, "source_analytics_started_at", iso_utc(tracking_start))
                job_id, _ = upsert_job(conn, self._job("104"))
                # First observation after tracking started, but this job was not
                # newly created by observation tracking (legacy/pre-v6 row).
                record_source_observation(
                    conn, job_id, "linkedin_saudi_v2",
                    observed_at=iso_utc(self.now - timedelta(hours=1)),
                    fresh_eligible=True, shadow_mode=True, was_new_job=False,
                )
                row = build_source_analytics(
                    conn,
                    sources=("linkedin_saudi_v2",),
                    hours=24,
                    saudi_only=True,
                    reference_time=self.now,
                )[0]
                self.assertEqual(row.discoveries, 0)


if __name__ == "__main__":
    unittest.main()
