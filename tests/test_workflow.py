import pathlib
import unittest
import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "job_bot.yml"


class WorkflowConfigTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = WORKFLOW.read_text(encoding="utf-8")
        cls.data = yaml.safe_load(cls.text)

    def test_workflow_yaml_is_valid(self):
        self.assertIsInstance(self.data, dict)
        self.assertIn("jobs", self.data)
        self.assertIn("run-bot", self.data["jobs"])

    def test_concurrency_is_enabled_without_canceling_running_job(self):
        concurrency = self.data.get("concurrency")
        self.assertIsInstance(concurrency, dict)
        self.assertEqual(concurrency.get("group"), "programming-jobs-bot")
        self.assertIs(concurrency.get("cancel-in-progress"), False)

    def test_schedule_is_every_15_minutes_not_every_5(self):
        self.assertIn("cron: '*/15 * * * *'", self.text)
        self.assertNotIn("cron: '*/5 * * * *'", self.text)

    def test_restore_uses_sqlite_database_only(self):
        self.assertIn("Restore SQLite database from data branch", self.text)
        self.assertRegex(self.text, r"git checkout origin/data -- jobs\.db")
        self.assertIn("db.py will create it during the first run", self.text)
        self.assertNotRegex(self.text, r"git checkout origin/data -- seen_jobs\.json")

    def test_save_persists_sqlite_database_only(self):
        self.assertIn("Save SQLite database to data branch", self.text)
        self.assertIn("cp jobs.db /tmp/job-bot-data/jobs.db", self.text)
        self.assertRegex(self.text, r"git add jobs\.db")
        self.assertIn("git rm -f seen_jobs.json", self.text)
        self.assertNotIn("git add seen_jobs.json", self.text)
        self.assertNotIn("cp seen_jobs.json", self.text)


    def test_manual_seed_mode_input_is_available(self):
        self.assertIn("seed_mode:", self.text)
        self.assertIn("Store fetched jobs without sending them", self.text)
        self.assertIn("SEED_MODE: ${{ github.event.inputs.seed_mode || 'false' }}", self.text)

    def test_runtime_env_has_current_required_secrets(self):
        required_envs = [
            "TELEGRAM_BOT_TOKEN",
            "TELEGRAM_GROUP_ID",
            "TOPIC_GENERAL",
            "TOPIC_LINKEDIN_ALL",
            "TOPIC_BACKEND",
            "TOPIC_FRONTEND",
            "TOPIC_MOBILE",
            "TOPIC_DEVOPS",
            "TOPIC_QA",
            "TOPIC_AI_ML",
            "TOPIC_CYBERSECURITY",
            "TOPIC_GAMEDEV",
            "TOPIC_BLOCKCHAIN",
            "TOPIC_EGYPT",
            "TOPIC_SAUDI",
            "TOPIC_INTERNSHIPS",
            "TOPIC_ERP",
            "TOPIC_MARKETING",
            "TOPIC_DATA_ENG",
            "TOPIC_APP_SUPPORT",
            "TOPIC_DESIGN",
            "TOPIC_BUSINESS",
        ]
        for env_name in required_envs:
            with self.subTest(env_name=env_name):
                self.assertIn(env_name + ":", self.text)

    def test_disabled_source_api_secrets_are_not_in_workflow(self):
        disabled_envs = [
            "RAPIDAPI_KEY",
            "ADZUNA_APP_ID",
            "ADZUNA_APP_KEY",
            "FINDWORK_API_KEY",
            "JOOBLE_API_KEY",
            "REED_API_KEY",
            "MUSE_API_KEY",
            "USAJOBS_API_KEY",
            "USAJOBS_EMAIL",
        ]
        for env_name in disabled_envs:
            with self.subTest(env_name=env_name):
                self.assertNotIn(env_name + ":", self.text)

    def test_permissions_allow_data_branch_push(self):
        permissions = self.data.get("permissions")
        self.assertEqual(permissions, {"contents": "write"})

    def test_workflow_still_runs_main_py(self):
        self.assertIn("run: python main.py", self.text)


if __name__ == "__main__":
    unittest.main()
