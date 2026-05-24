import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
README = ROOT / "README.md"


class ReadmeDocumentationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = README.read_text(encoding="utf-8")

    def test_readme_documents_new_two_source_design(self):
        self.assertIn("WUZZUF", self.text)
        self.assertIn("LinkedIn", self.text)
        self.assertIn("ALL_FETCHERS", self.text)
        self.assertIn("jobs.db", self.text)
        self.assertIn("SQLite", self.text)

    def test_readme_documents_linkedin_all_topic(self):
        self.assertIn("TOPIC_LINKEDIN_ALL", self.text)
        self.assertIn("LinkedIn Fresh Jobs", self.text)
        self.assertIn("Receives every fresh LinkedIn job", self.text)

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
            "test_db.py",
            "test_linkedin.py",
            "test_main_sqlite.py",
            "test_routing.py",
            "test_sources_registry.py",
            "test_workflow.py",
            "test_wuzzuf.py",
        ]:
            with self.subTest(test_file=test_file):
                self.assertIn(test_file, self.text)


if __name__ == "__main__":
    unittest.main()
