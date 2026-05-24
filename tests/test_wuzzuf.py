import unittest

from sources.wuzzuf import (
    fetch_wuzzuf,
    parse_wuzzuf_html,
    _with_start,
)

SAMPLE_HTML = """
<html><body>
  <div class="job-card">
    <h2><a href="/jobs/p/abc123-Backend-Developer-Linket-Cairo-Egypt">Backend Developer</a></h2>
    <a class="company" href="/jobs/careers/Linket-Egypt-123">Linket -</a>
    <span class="location">Cairo, Egypt</span>
    <span>2 days ago</span>
    <span>Full Time</span><span>Remote</span>
    <a>Experienced</a> · <a>IT/Software Development</a> · <a>AWS</a> · <a>Node.js</a> · <a>Software Engineering</a>
  </div>
  <div class="job-card">
    <h2><a href="https://wuzzuf.net/jobs/p/def456-Front-End-Developer-Internship-3D-Diagnostix-Cairo-Egypt?utm_source=x">Front End Developer Internship</a></h2>
    <a href="/jobs/careers/3D-Diagnostix-Egypt-456">3D Diagnostix -</a>
    <span>Cairo, Egypt</span>
    <span>Internship</span><span>Remote</span>
    <a>Student</a> · <a>IT/Software Development</a> · <a>HTML</a> · <a>CSS</a> · <a>JavaScript</a> · <a>React</a>
  </div>
  <div class="job-card duplicate">
    <h2><a href="/jobs/p/abc123-Backend-Developer-Linket-Cairo-Egypt">Backend Developer</a></h2>
    <a href="/jobs/careers/Linket-Egypt-123">Linket -</a>
    <span>Cairo, Egypt</span>
  </div>
</body></html>
"""

PLAIN_FALLBACK_HTML = """
<div>
  <h2><a href="/jobs/p/xyz789-Graphic-Designer-Cairo-Egypt">Graphic Designer</a></h2>
  Design Co - Giza, Egypt
  <span>Full Time</span><span>On-site</span>
  <a>Creative/Design/Art</a><a>Graphic Design</a><a>Figma</a>
</div>
"""


class WuzzufSourceTests(unittest.TestCase):
    def test_parse_wuzzuf_html_extracts_jobs(self):
        jobs = parse_wuzzuf_html(SAMPLE_HTML)
        self.assertEqual(len(jobs), 2)

        first = jobs[0]
        self.assertEqual(first.title, "Backend Developer")
        self.assertEqual(first.company, "Linket")
        self.assertEqual(first.location, "Cairo, Egypt")
        self.assertEqual(first.url, "https://wuzzuf.net/jobs/p/abc123-Backend-Developer-Linket-Cairo-Egypt")
        self.assertEqual(first.source, "wuzzuf")
        self.assertTrue(first.is_remote)
        self.assertIn("Full Time", first.job_type)
        self.assertIn("Remote", first.job_type)
        self.assertIn("IT/Software Development", first.tags)
        self.assertIn("Node.js", first.tags)
        self.assertEqual(getattr(first, "source_job_id"), "abc123-Backend-Developer-Linket-Cairo-Egypt")

    def test_parse_wuzzuf_html_cleans_absolute_url_tracking_and_detects_internship(self):
        jobs = parse_wuzzuf_html(SAMPLE_HTML)
        second = jobs[1]
        self.assertEqual(second.title, "Front End Developer Internship")
        self.assertEqual(second.company, "3D Diagnostix")
        self.assertTrue(second.url.startswith("https://wuzzuf.net/jobs/p/def456"))
        self.assertNotIn("utm_source", second.url)
        self.assertIn("Internship", second.job_type)
        self.assertTrue(second.is_remote)
        self.assertIn("React", second.tags)

    def test_parse_wuzzuf_html_fallback_company_location(self):
        jobs = parse_wuzzuf_html(PLAIN_FALLBACK_HTML)
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].company, "Design Co")
        self.assertEqual(jobs[0].location, "Giza, Egypt")
        self.assertFalse(jobs[0].is_remote)
        self.assertIn("On-site", jobs[0].job_type)

    def test_with_start_adds_or_replaces_pagination(self):
        self.assertEqual(
            _with_start("https://wuzzuf.net/a/Software-Development-Jobs-in-Egypt", 20),
            "https://wuzzuf.net/a/Software-Development-Jobs-in-Egypt?start=20",
        )
        self.assertEqual(
            _with_start("https://wuzzuf.net/a/Jobs?foo=1&start=20", 40),
            "https://wuzzuf.net/a/Jobs?foo=1&start=40",
        )
        self.assertEqual(
            _with_start("https://wuzzuf.net/a/Jobs?foo=1", 0),
            "https://wuzzuf.net/a/Jobs?foo=1",
        )

    def test_fetch_wuzzuf_uses_injected_getter_and_deduplicates_across_pages(self):
        requested_urls = []

        def fake_getter(url):
            requested_urls.append(url)
            return SAMPLE_HTML

        jobs = fetch_wuzzuf(
            search_urls=["https://wuzzuf.net/a/Software-Development-Jobs-in-Egypt"],
            max_pages_per_search=2,
            http_getter=fake_getter,
        )

        self.assertEqual(len(jobs), 2)
        self.assertEqual(requested_urls, [
            "https://wuzzuf.net/a/Software-Development-Jobs-in-Egypt",
            "https://wuzzuf.net/a/Software-Development-Jobs-in-Egypt?start=20",
        ])

    def test_fetch_wuzzuf_rejects_invalid_page_count(self):
        with self.assertRaises(ValueError):
            fetch_wuzzuf(max_pages_per_search=0, http_getter=lambda _: "")


if __name__ == "__main__":
    unittest.main()
