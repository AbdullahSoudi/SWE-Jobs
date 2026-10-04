import gzip
import os
import sqlite3
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from ops.backup_sqlite import create_backup


class BackupSqliteTests(unittest.TestCase):
    def test_backup_is_verified_compressed_and_readable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "jobs.db"
            backup_dir = root / "backups"
            conn = sqlite3.connect(db_path)
            conn.execute("CREATE TABLE sample(id INTEGER PRIMARY KEY, value TEXT)")
            conn.execute("INSERT INTO sample(value) VALUES ('hello')")
            conn.commit()
            conn.close()

            backup = create_backup(
                db_path,
                backup_dir,
                reference_time=datetime(2026, 10, 4, 21, 0, tzinfo=UTC),
            )
            self.assertTrue(backup.exists())
            self.assertEqual(backup.name, "jobs-20261004T210000Z.db.gz")

            restored = root / "restored.db"
            with gzip.open(backup, "rb") as src, restored.open("wb") as dst:
                dst.write(src.read())
            conn = sqlite3.connect(restored)
            try:
                self.assertEqual(conn.execute("PRAGMA integrity_check").fetchone()[0], "ok")
                self.assertEqual(conn.execute("SELECT value FROM sample").fetchone()[0], "hello")
            finally:
                conn.close()

    def test_backup_rotation_removes_files_older_than_retention(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "jobs.db"
            backup_dir = root / "backups"
            backup_dir.mkdir()
            conn = sqlite3.connect(db_path)
            conn.execute("CREATE TABLE sample(id INTEGER)")
            conn.commit()
            conn.close()

            old = backup_dir / "jobs-20260801T000000Z.db.gz"
            old.write_bytes(b"old")
            old_time = datetime(2026, 8, 1, tzinfo=UTC).timestamp()
            os.utime(old, (old_time, old_time))

            create_backup(
                db_path,
                backup_dir,
                retention_days=14,
                reference_time=datetime(2026, 10, 4, 21, 0, tzinfo=UTC),
            )
            self.assertFalse(old.exists())


if __name__ == "__main__":
    unittest.main()
