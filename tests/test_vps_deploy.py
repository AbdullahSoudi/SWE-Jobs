import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "deploy"


class VpsDeploymentTests(unittest.TestCase):
    def test_service_uses_persistent_paths_and_vps_runner(self):
        text = (DEPLOY / "systemd" / "swe-jobs.service").read_text(encoding="utf-8")
        self.assertIn("User=swejobs", text)
        self.assertIn("EnvironmentFile=/etc/swe-jobs/swe-jobs.env", text)
        self.assertIn("StateDirectory=swe-jobs", text)
        self.assertIn("/opt/swe-jobs/current/vps_runner.py", text)
        self.assertIn("/var/lib/swe-jobs", text)
        self.assertIn("/run/swe-jobs", text)

    def test_timer_is_every_fifteen_minutes_and_persistent(self):
        text = (DEPLOY / "systemd" / "swe-jobs.timer").read_text(encoding="utf-8")
        self.assertIn("OnCalendar=*:0/15", text)
        self.assertIn("Persistent=true", text)
        self.assertIn("AccuracySec=5s", text)

    def test_backup_timer_and_service_are_installed(self):
        service = (DEPLOY / "systemd" / "swe-jobs-backup.service").read_text(encoding="utf-8")
        timer = (DEPLOY / "systemd" / "swe-jobs-backup.timer").read_text(encoding="utf-8")
        self.assertIn("ops/backup_sqlite.py", service)
        self.assertIn("/var/backups/swe-jobs", service)
        self.assertIn("OnCalendar=*-*-* 03:30:00", timer)
        self.assertIn("Persistent=true", timer)

    def test_environment_template_uses_wal_without_real_secrets(self):
        text = (DEPLOY / "swe-jobs.env.example").read_text(encoding="utf-8")
        self.assertIn("JOBS_DB_PATH=/var/lib/swe-jobs/jobs.db", text)
        self.assertIn("SQLITE_JOURNAL_MODE=WAL", text)
        self.assertIn("BOT_LOCK_FILE=/run/swe-jobs/run.lock", text)
        self.assertIn("BACKUP_RETENTION_DAYS=14", text)
        self.assertIn("TELEGRAM_BOT_TOKEN=\n", text)
        self.assertIn("TELEGRAM_GROUP_ID=\n", text)

    def test_installer_imports_existing_data_branch_state_once(self):
        text = (DEPLOY / "install_systemd.sh").read_text(encoding="utf-8")
        self.assertIn("git -C \"${APP_DIR}\" fetch --depth=1 origin data", text)
        self.assertIn("git -C \"${APP_DIR}\" show origin/data:jobs.db", text)
        self.assertIn("systemctl daemon-reload", text)
        commands = [line.strip() for line in text.splitlines() if not line.lstrip().startswith("echo ")]
        self.assertNotIn("systemctl enable --now swe-jobs.timer swe-jobs-backup.timer", commands)


if __name__ == "__main__":
    unittest.main()
