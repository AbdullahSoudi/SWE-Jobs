import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sources.jobzaty import fetch_jobzaty, parse_jobzaty_listing


PAGE = r'''
<html><body>
  <article class="job-card">
    <h2><a href="/job/backend-api-developer-12345">مطور باك اند API</a></h2>
    <div>شركة مثال التقنية</div>
    <span>الرياض</span>
    <span>سعودي أو مقيم</span>
    <span>دوام كامل</span>
  </article>
  <article class="job-card">
    <h2><a href="https://www.jobzaty.com/job/security-engineer-999">مهندس أمن سيبراني</a></h2>
    <div>شركة أمن</div>
    <span>الخبر</span>
    <span>سعودي فقط</span>
    <span>دوام كامل</span>
  </article>
</body></html>
'''


class JobzatyTests(unittest.TestCase):
    def test_parse_public_category_cards(self):
        jobs = parse_jobzaty_listing(
            PAGE,
            page_url="https://www.jobzaty.com/jobs/category/information-technology",
            category_tag="تقنية المعلومات",
        )
        self.assertEqual(len(jobs), 2)
        first = jobs[0]
        self.assertEqual(first.source, "jobzaty")
        self.assertEqual(first.source_job_id, "backend-api-developer-12345")
        self.assertEqual(first.company, "شركة مثال التقنية")
        self.assertEqual(first.location, "الرياض, Saudi Arabia")
        self.assertEqual(first.job_type, "دوام كامل")
        self.assertIn("تقنية المعلومات", first.tags)
        self.assertIn("سعودي أو مقيم", first.tags)
        self.assertEqual(first.published_precision, "NONE")

    def test_unknown_city_stays_country_level_saudi(self):
        html = r'''
        <a href="/job/data-role-1">محلل بيانات</a>
        <div>شركة البيانات</div><span>غير محدد</span><span>دوام كامل</span>
        '''
        jobs = parse_jobzaty_listing(html, category_tag="تقنية المعلومات")
        self.assertEqual(jobs[0].location, "Saudi Arabia")

    def test_fetch_deduplicates_same_job_across_categories(self):
        seen = []

        def getter(url):
            seen.append(url)
            return PAGE

        jobs = fetch_jobzaty(
            category_feeds=[
                ("https://www.jobzaty.com/jobs/category/information-technology", "تقنية المعلومات"),
                ("https://www.jobzaty.com/jobs/category/programming-web-development", "البرمجة وتطوير الويب"),
            ],
            http_getter=getter,
        )
        self.assertEqual(len(jobs), 2)
        self.assertEqual(len(seen), 2)

    def test_page_two_uses_page_query_parameter(self):
        requested = []

        def getter(url):
            requested.append(url)
            return ""

        fetch_jobzaty(
            category_feeds=[("https://www.jobzaty.com/jobs/category/information-technology", "تقنية المعلومات")],
            max_pages_per_category=2,
            http_getter=getter,
        )
        self.assertEqual(requested[0], "https://www.jobzaty.com/jobs/category/information-technology")
        self.assertEqual(requested[1], "https://www.jobzaty.com/jobs/category/information-technology?page=2")


if __name__ == "__main__":
    unittest.main()
