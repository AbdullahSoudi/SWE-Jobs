import tempfile
import unittest
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import db
from sources import linkedin

SAMPLE_HTML = """
<ul>
  <li>
    <div class="base-card job-search-card">
      <a class="base-card__full-link" href="https://www.linkedin.com/jobs/view/backend-developer-at-acme-1234567890?refId=abc&trk=public_jobs_jserp-result_search-card"></a>
      <h3 class="base-search-card__title"> Backend Developer </h3>
      <h4 class="base-search-card__subtitle"><a>Acme Technologies</a></h4>
      <span class="job-search-card__location">Cairo, Egypt</span>
      <span>Full-time</span>
      <span>On-site</span>
    </div>
  </li>
  <li>
    <div class="base-card job-search-card">
      <a class="base-card__full-link" href="/jobs/view/data-analyst-at-beta-9876543210?position=1&pageNum=0"></a>
      <h3 class="base-search-card__title">Data Analyst</h3>
      <h4 class="base-search-card__subtitle"><a>Beta LLC</a></h4>
      <span class="job-search-card__location">Remote</span>
      <span>Contract</span>
    </div>
  </li>
</ul>
"""

DUPLICATE_HTML = """
<li><a href="https://www.linkedin.com/jobs/view/test-at-x-1111111111?trk=a"></a><h3 class="base-search-card__title">Test Engineer</h3><h4 class="base-search-card__subtitle">X</h4><span class="job-search-card__location">Egypt</span></li>
<li><a href="https://www.linkedin.com/jobs/view/test-at-x-1111111111?trk=b"></a><h3 class="base-search-card__title">Test Engineer</h3><h4 class="base-search-card__subtitle">X</h4><span class="job-search-card__location">Egypt</span></li>
"""


class LinkedInParserTests(unittest.TestCase):
    def test_parse_two_cards(self):
        jobs = linkedin.parse_linkedin_html(SAMPLE_HTML, {"location": "Egypt"})
        self.assertEqual(len(jobs), 2)
        self.assertEqual(jobs[0].title, "Backend Developer")
        self.assertEqual(jobs[0].company, "Acme Technologies")
        self.assertEqual(jobs[0].location, "Cairo, Egypt")
        self.assertEqual(jobs[0].source, "linkedin")
        self.assertIn("Full-time", jobs[0].job_type)
        self.assertFalse(jobs[0].is_remote)

    def test_relative_url_and_remote_detection(self):
        jobs = linkedin.parse_linkedin_html(SAMPLE_HTML, {"f_WT": "2"})
        self.assertEqual(jobs[1].url, "https://www.linkedin.com/jobs/view/data-analyst-at-beta-9876543210")
        self.assertTrue(jobs[1].is_remote)
        self.assertIn("Remote", jobs[1].tags)

    def test_extract_source_job_id(self):
        jobs = linkedin.parse_linkedin_html(SAMPLE_HTML, {})
        self.assertEqual(getattr(jobs[0], "source_job_id"), "1234567890")
        self.assertEqual(getattr(jobs[1], "source_job_id"), "9876543210")

    def test_deduplicates_same_card_url(self):
        jobs = linkedin.parse_linkedin_html(DUPLICATE_HTML, {})
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].url, "https://www.linkedin.com/jobs/view/test-at-x-1111111111")

    def test_search_list_is_intentionally_small(self):
        self.assertLessEqual(len(linkedin.LINKEDIN_SEARCHES), 24)

    def test_fetch_uses_pagination_and_getter(self):
        requested = []

        def fake_getter(url, params=None, headers=None):
            requested.append((url, dict(params or {}), dict(headers or {})))
            return SAMPLE_HTML

        jobs = linkedin.fetch_linkedin(
            searches=[{"keywords": "backend developer", "location": "Egypt"}],
            max_pages_per_search=2,
            request_delay=0,
            http_getter=fake_getter,
        )
        self.assertEqual(len(requested), 2)
        self.assertEqual(requested[0][1]["start"], "0")
        self.assertEqual(requested[1][1]["start"], str(linkedin.PAGE_SIZE))
        self.assertEqual(len(jobs), 2)
        self.assertIn("User-Agent", requested[0][2])

    def test_fetch_rejects_invalid_options(self):
        with self.assertRaises(ValueError):
            linkedin.fetch_linkedin(max_pages_per_search=0, request_delay=0, http_getter=lambda *a, **k: "")
        with self.assertRaises(ValueError):
            linkedin.fetch_linkedin(max_pages_per_search=1, request_delay=-1, http_getter=lambda *a, **k: "")

    def test_integration_with_sqlite(self):
        jobs = linkedin.parse_linkedin_html(SAMPLE_HTML, {"location": "Egypt"})
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "jobs.db"
            with db.connect(db_path) as conn:
                job_id, is_new = db.upsert_job(conn, jobs[0])
                self.assertTrue(is_new)
                pending = db.get_jobs_for_sending(conn)
                self.assertEqual(len(pending), 1)
                self.assertEqual(pending[0].source, "linkedin")
                self.assertEqual(pending[0].id, job_id)


if __name__ == "__main__":
    unittest.main()

class LinkedInFreshnessAndActiveTests(unittest.TestCase):
    def test_all_default_searches_are_fresh_and_date_sorted(self):
        self.assertGreaterEqual(linkedin.DEFAULT_FRESHNESS_SECONDS, 900)
        self.assertLessEqual(linkedin.DEFAULT_FRESHNESS_SECONDS, 3600)
        for search in linkedin.LINKEDIN_SEARCHES:
            self.assertEqual(search.get("f_TPR"), f"r{linkedin.DEFAULT_FRESHNESS_SECONDS}")
            self.assertEqual(search.get("sortBy"), "DD")

    def test_search_coverage_is_still_bounded_for_runtime(self):
        # 23 searches * 4 seconds default delay is about 92 seconds plus network time.
        # This stays practical under a 15-minute cron while covering more categories.
        self.assertLessEqual(len(linkedin.LINKEDIN_SEARCHES), 24)

    def test_parser_skips_closed_or_inactive_cards(self):
        html = """
        <li><a href="https://www.linkedin.com/jobs/view/test-at-x-2222222222"></a>
        <h3 class="base-search-card__title">Backend Developer</h3>
        <h4 class="base-search-card__subtitle">X</h4>
        <span class="job-search-card__location">Cairo</span>
        <span>No longer accepting applications</span></li>
        <li><a href="https://www.linkedin.com/jobs/view/test-at-y-3333333333"></a>
        <h3 class="base-search-card__title">Frontend Developer</h3>
        <h4 class="base-search-card__subtitle">Y</h4>
        <span class="job-search-card__location">Cairo</span>
        <time>15 minutes ago</time></li>
        """
        jobs = linkedin.parse_linkedin_html(html, {"location": "Egypt"}, max_age_seconds=3600)
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].title, "Frontend Developer")
        self.assertEqual(getattr(jobs[0], "source_job_id"), "3333333333")

    def test_parser_skips_visible_stale_cards_when_age_is_available(self):
        html = """
        <li><a href="https://www.linkedin.com/jobs/view/fresh-at-x-4444444444"></a>
        <h3 class="base-search-card__title">Fresh Data Analyst</h3>
        <h4 class="base-search-card__subtitle">X</h4>
        <span class="job-search-card__location">Cairo</span>
        <time>45 minutes ago</time></li>
        <li><a href="https://www.linkedin.com/jobs/view/old-at-y-5555555555"></a>
        <h3 class="base-search-card__title">Old Data Analyst</h3>
        <h4 class="base-search-card__subtitle">Y</h4>
        <span class="job-search-card__location">Cairo</span>
        <time>2 hours ago</time></li>
        """
        jobs = linkedin.parse_linkedin_html(html, {"location": "Egypt"}, max_age_seconds=3600)
        self.assertEqual([job.title for job in jobs], ["Fresh Data Analyst"])

    def test_fetch_sends_freshness_and_sorting_params_to_getter(self):
        requested = []

        def fake_getter(url, params=None, headers=None):
            requested.append(dict(params or {}))
            return SAMPLE_HTML

        linkedin.fetch_linkedin(
            searches=[linkedin._fresh_params(keywords="backend developer", location="Egypt")],
            max_pages_per_search=1,
            request_delay=0,
            http_getter=fake_getter,
        )
        self.assertEqual(requested[0]["f_TPR"], f"r{linkedin.DEFAULT_FRESHNESS_SECONDS}")
        self.assertEqual(requested[0]["sortBy"], "DD")
        self.assertEqual(requested[0]["start"], "0")

    def test_fresh_jobs_are_stored_pending_for_later_sending(self):
        html = """
        <li><a href="https://www.linkedin.com/jobs/view/backend-at-acme-6666666666"></a>
        <h3 class="base-search-card__title">Backend Developer</h3>
        <h4 class="base-search-card__subtitle">Acme</h4>
        <span class="job-search-card__location">Cairo, Egypt</span>
        <time>5 minutes ago</time></li>
        """
        jobs = linkedin.parse_linkedin_html(html, {"location": "Egypt"}, max_age_seconds=3600)
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "jobs.db"
            with db.connect(db_path) as conn:
                job_id, is_new = db.upsert_job(conn, jobs[0])
                self.assertTrue(is_new)
                pending = db.get_jobs_for_sending(conn)
                self.assertEqual(len(pending), 1)
                self.assertEqual(pending[0].id, job_id)
                self.assertEqual(pending[0].title, "Backend Developer")
