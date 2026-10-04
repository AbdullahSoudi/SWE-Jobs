import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from db import connect, configured_journal_mode
from runtime_lock import try_process_lock
import vps_runner


class VpsRuntimeTests(unittest.TestCase):
    def test_default_journal_mode_remains_delete_for_github(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SQLITE_JOURNAL_MODE", None)
            self.assertEqual(configured_journal_mode(), "DELETE")

    def test_wal_mode_can_be_enabled_for_persistent_host(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ, {"SQLITE_JOURNAL_MODE": "WAL"}
        ):
            db_path = Path(tmp) / "state" / "jobs.db"
            with connect(db_path) as conn:
                mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
                synchronous = conn.execute("PRAGMA synchronous").fetchone()[0]
            self.assertEqual(str(mode).lower(), "wal")
            self.assertEqual(int(synchronous), 1)  # NORMAL
            self.assertTrue(db_path.exists())

    def test_invalid_journal_mode_is_rejected(self):
        with patch.dict(os.environ, {"SQLITE_JOURNAL_MODE": "MEMORY"}):
            with self.assertRaises(ValueError):
                configured_journal_mode()


    def test_vps_runner_calls_normal_bot_path_under_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            lock_path = Path(tmp) / "runner.lock"
            with patch.dict(os.environ, {"BOT_LOCK_FILE": str(lock_path)}), \
                 patch.object(vps_runner, "DB_FILE", str(Path(tmp) / "jobs.db")), \
                 patch.object(vps_runner, "run_bot") as run_bot:
                self.assertEqual(vps_runner.main(), 0)
                run_bot.assert_called_once_with(db_path=str(Path(tmp) / "jobs.db"))

    def test_vps_runner_skips_when_another_run_holds_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            lock_path = Path(tmp) / "runner.lock"
            with try_process_lock(lock_path) as acquired:
                self.assertTrue(acquired)
                with patch.dict(os.environ, {"BOT_LOCK_FILE": str(lock_path)}), \
                     patch.object(vps_runner, "run_bot") as run_bot:
                    self.assertEqual(vps_runner.main(), 0)
                    run_bot.assert_not_called()

    def test_process_lock_prevents_overlap(self):
        with tempfile.TemporaryDirectory() as tmp:
            lock_path = Path(tmp) / "bot.lock"
            with try_process_lock(lock_path) as first:
                self.assertTrue(first)
                with try_process_lock(lock_path) as second:
                    self.assertFalse(second)
            with try_process_lock(lock_path) as third:
                self.assertTrue(third)


if __name__ == "__main__":
    unittest.main()
