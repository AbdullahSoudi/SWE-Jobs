import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
README = ROOT / "README.md"


class ReadmeDocumentationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = README.read_text(encoding="utf-8")

    def test_readme_documents_current_source_design(self):
        self.assertIn("WUZZUF", self.text)
        self.assertIn("LinkedIn", self.text)
        self.assertIn("ALL_FETCHERS", self.text)
        self.assertIn("jobs.db", self.text)
        self.assertIn("SQLite", self.text)
        self.assertIn("Greenhouse", self.text)
        self.assertIn("Lever", self.text)
        self.assertIn("Ashby", self.text)
        self.assertIn("Workday", self.text)
        self.assertIn("discover_ats_candidates", self.text)
        self.assertIn("companies/saudi_ats.json", self.text)

    def test_readme_documents_single_primary_topic_design(self):
        self.assertIn("one primary topic", self.text.lower())
        self.assertIn("TOPIC_BACKEND", self.text)
        self.assertIn("TOPIC_AI_ML", self.text)
        self.assertIn("no longer read by the workflow", self.text)
        self.assertIn("one primary topic per job", self.text.lower())

    def test_readme_documents_seed_mode_and_workflow(self):
        self.assertIn("seed_mode", self.text)
        self.assertIn("concurrency", self.text)
        self.assertIn("data branch", self.text)

    def test_readme_no_longer_claims_old_runtime(self):
        forbidden_claims = [
            "15 free sources",
            "every 5 minutes",
            "seen_jobs.json → find new jobs only",
            "RAPIDAPI_KEY`, `ADZUNA_APP_ID",
            "253 keywords",
        ]
        for phrase in forbidden_claims:
            with self.subTest(phrase=phrase):
                self.assertNotIn(phrase, self.text)

    def test_readme_lists_current_tests(self):
        for test_file in [
            "test_ats.py",
            "test_ats_detector.py",
            "test_company_registry.py",
            "test_db.py",
            "test_freshness.py",
            "test_linkedin.py",
            "test_main_sqlite.py",
            "test_routing.py",
            "test_source_analytics.py",
            "test_source_runtime.py",
            "test_sources_registry.py",
            "test_telegram_sender.py",
            "test_workflow.py",
            "test_wuzzuf.py",
        ]:
            with self.subTest(test_file=test_file):
                self.assertIn(test_file, self.text)


if __name__ == "__main__":
    unittest.main()
