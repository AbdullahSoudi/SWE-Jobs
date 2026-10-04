import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from db import connect, ensure_topic_deliveries, upsert_job
from db_maintenance import LAST_COMPACT_METADATA_KEY, compact_database
from models import Job


def iso(dt):
    return dt.astimezone(UTC).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


class DatabaseMaintenanceTests(unittest.TestCase):
    def test_compaction_prunes_old_operational_rows_but_keeps_jobs(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / 'jobs.db'
            now = datetime(2026, 10, 4, 20, 0, tzinfo=UTC)
            old = iso(now - timedelta(days=45))
            recent = iso(now - timedelta(days=2))

            with connect(db_path) as conn:
                old_id, _ = upsert_job(conn, Job('Backend Developer', 'Old Co', 'Riyadh', 'https://old.test/1', 'linkedin'))
                new_id, _ = upsert_job(conn, Job('Backend Developer', 'New Co', 'Riyadh', 'https://new.test/1', 'linkedin'))
                conn.execute('UPDATE jobs SET first_seen_at=?, last_seen_at=? WHERE id=?', (old, old, old_id))
                conn.execute('UPDATE jobs SET first_seen_at=?, last_seen_at=? WHERE id=?', (recent, recent, new_id))
                conn.execute('UPDATE job_postings SET first_seen_at=?, last_seen_at=? WHERE job_id=?', (old, old, old_id))
                conn.execute('UPDATE job_postings SET first_seen_at=?, last_seen_at=? WHERE job_id=?', (recent, recent, new_id))

                ensure_topic_deliveries(conn, old_id, ['backend'], deadline_at=old)
                ensure_topic_deliveries(conn, new_id, ['backend'], deadline_at=recent)
                conn.execute("UPDATE job_sends SET status='sent', updated_at=? WHERE job_id=?", (old, old_id))
                conn.execute("UPDATE job_sends SET status='sent', updated_at=? WHERE job_id=?", (recent, new_id))

                conn.execute(
                    "INSERT INTO source_observations(job_id,source,first_seen_at,last_seen_at) VALUES (?,?,?,?)",
                    (old_id, 'linkedin', old, old),
                )
                conn.execute(
                    "INSERT INTO source_observations(job_id,source,first_seen_at,last_seen_at) VALUES (?,?,?,?)",
                    (new_id, 'linkedin', recent, recent),
                )
                conn.execute(
                    """INSERT INTO source_run_history(
                        source,run_at,status,created_at
                    ) VALUES (?,?,?,?)""",
                    ('linkedin', old, 'ok', old),
                )
                conn.execute(
                    """INSERT INTO source_run_history(
                        source,run_at,status,created_at
                    ) VALUES (?,?,?,?)""",
                    ('linkedin', recent, 'ok', recent),
                )

            result = compact_database(db_path, reference_time=now, force=True, retention_days=30)
            self.assertTrue(result.ran)
            self.assertEqual(result.deleted_job_sends, 1)
            self.assertEqual(result.deleted_job_postings, 1)
            self.assertEqual(result.deleted_source_observations, 1)
            self.assertEqual(result.deleted_source_history, 1)

            with connect(db_path) as conn:
                self.assertEqual(conn.execute('SELECT COUNT(*) FROM jobs').fetchone()[0], 2)
                self.assertEqual(conn.execute('SELECT COUNT(*) FROM job_sends').fetchone()[0], 1)
                self.assertEqual(conn.execute('SELECT COUNT(*) FROM job_postings').fetchone()[0], 1)
                self.assertEqual(conn.execute('SELECT COUNT(*) FROM source_observations').fetchone()[0], 1)
                self.assertEqual(conn.execute('SELECT COUNT(*) FROM source_run_history').fetchone()[0], 1)
                marker = conn.execute('SELECT value FROM metadata WHERE key=?', (LAST_COMPACT_METADATA_KEY,)).fetchone()
                self.assertIsNotNone(marker)

    def test_small_recent_database_does_not_vacuum_again_immediately(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / 'jobs.db'
            now = datetime(2026, 10, 4, 20, 0, tzinfo=UTC)
            with connect(db_path) as conn:
                upsert_job(conn, Job('QA Engineer', 'Co', 'Riyadh', 'https://x.test/1', 'linkedin'))

            first = compact_database(db_path, reference_time=now, force=True)
            second = compact_database(
                db_path,
                reference_time=now + timedelta(hours=1),
                size_threshold_mb=999,
            )
            self.assertTrue(first.ran)
            self.assertFalse(second.ran)


if __name__ == '__main__':
    unittest.main()
