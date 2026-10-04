import os
import tempfile
import unittest

from db import connect, count_jobs, count_postings, get_job_postings, get_jobs_for_sending, upsert_job
from dedup import normalize_company_key, title_similarity
from models import Job


class CrossSourceDedupTests(unittest.TestCase):
    def _job(self, *, title, company="Acme", location="Riyadh, Saudi Arabia", url, source, source_job_id=""):
        return Job(
            title=title,
            company=company,
            location=location,
            url=url,
            source=source,
            source_job_id=source_job_id,
        )

    def test_same_opening_different_urls_merges_into_one_cluster(self):
        with tempfile.TemporaryDirectory() as tmp:
            with connect(os.path.join(tmp, "jobs.db")) as conn:
                linkedin = self._job(
                    title="Junior Backend .NET Developer",
                    url="https://linkedin.com/jobs/view/111",
                    source="linkedin",
                    source_job_id="111",
                )
                ats = self._job(
                    title=".NET Backend Developer - Junior",
                    url="https://jobs.example.com/backend-111",
                    source="ats_acme",
                    source_job_id="gh-111",
                )
                first_id, first_new = upsert_job(conn, linkedin)
                second_id, second_new = upsert_job(conn, ats)
                self.assertTrue(first_new)
                self.assertFalse(second_new)
                self.assertEqual(first_id, second_id)
                self.assertEqual(count_jobs(conn), 1)
                self.assertEqual(count_postings(conn), 2)
                postings = get_job_postings(conn, first_id)
                self.assertEqual({row["source"] for row in postings}, {"linkedin", "ats_acme"})
                self.assertEqual(postings[-1]["match_method"], "company_location_title")

    def test_official_ats_link_becomes_preferred_without_changing_primary_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            with connect(os.path.join(tmp, "jobs.db")) as conn:
                job_id, _ = upsert_job(conn, self._job(
                    title="Senior Software Backend Engineer",
                    company="HALA",
                    url="https://linkedin.com/jobs/view/222",
                    source="linkedin",
                    source_job_id="222",
                ))
                upsert_job(conn, self._job(
                    title="Backend Senior Software Engineer",
                    company="HALA",
                    url="https://job-boards.greenhouse.io/hala/jobs/222",
                    source="ats_greenhouse_hala",
                    source_job_id="222-gh",
                ))
                row = conn.execute(
                    "SELECT source, preferred_source, preferred_url FROM jobs WHERE id = ?",
                    (job_id,),
                ).fetchone()
                self.assertEqual(row["source"], "linkedin")
                self.assertEqual(row["preferred_source"], "ats_greenhouse_hala")
                self.assertIn("greenhouse.io", row["preferred_url"])
                delivery_job = get_jobs_for_sending(conn)[0].to_job()
                self.assertIn("greenhouse.io", delivery_job.url)
                self.assertEqual(delivery_job.original_source, "ats_greenhouse_hala")

    def test_seniority_conflict_is_not_merged(self):
        with tempfile.TemporaryDirectory() as tmp:
            with connect(os.path.join(tmp, "jobs.db")) as conn:
                upsert_job(conn, self._job(
                    title="Junior Backend .NET Developer",
                    url="https://linkedin.com/jobs/view/300",
                    source="linkedin",
                ))
                _, is_new = upsert_job(conn, self._job(
                    title="Senior Backend .NET Developer",
                    url="https://jobs.example.com/301",
                    source="ats_acme",
                ))
                self.assertTrue(is_new)
                self.assertEqual(count_jobs(conn), 2)

    def test_stack_conflict_is_not_merged(self):
        with tempfile.TemporaryDirectory() as tmp:
            with connect(os.path.join(tmp, "jobs.db")) as conn:
                upsert_job(conn, self._job(
                    title="Senior Backend Java Developer",
                    url="https://linkedin.com/jobs/view/400",
                    source="linkedin",
                ))
                _, is_new = upsert_job(conn, self._job(
                    title="Senior Backend .NET Developer",
                    url="https://jobs.example.com/401",
                    source="ats_acme",
                ))
                self.assertTrue(is_new)
                self.assertEqual(count_jobs(conn), 2)

    def test_city_conflict_is_not_merged(self):
        with tempfile.TemporaryDirectory() as tmp:
            with connect(os.path.join(tmp, "jobs.db")) as conn:
                upsert_job(conn, self._job(
                    title="Senior Backend Software Engineer",
                    location="Riyadh, Saudi Arabia",
                    url="https://linkedin.com/jobs/view/500",
                    source="linkedin",
                ))
                _, is_new = upsert_job(conn, self._job(
                    title="Senior Backend Software Engineer",
                    location="Jeddah, Saudi Arabia",
                    url="https://jobs.example.com/501",
                    source="ats_acme",
                ))
                self.assertTrue(is_new)
                self.assertEqual(count_jobs(conn), 2)

    def test_short_generic_title_is_intentionally_not_fuzzy_merged(self):
        with tempfile.TemporaryDirectory() as tmp:
            with connect(os.path.join(tmp, "jobs.db")) as conn:
                upsert_job(conn, self._job(
                    title="QA Engineer",
                    url="https://linkedin.com/jobs/view/600",
                    source="linkedin",
                ))
                _, is_new = upsert_job(conn, self._job(
                    title="QA Engineer",
                    url="https://jobs.example.com/601",
                    source="ats_acme",
                ))
                self.assertTrue(is_new)
                self.assertEqual(count_jobs(conn), 2)

    def test_same_source_repost_is_not_fuzzy_merged(self):
        with tempfile.TemporaryDirectory() as tmp:
            with connect(os.path.join(tmp, "jobs.db")) as conn:
                upsert_job(conn, self._job(
                    title="Senior Backend Software Engineer",
                    url="https://linkedin.com/jobs/view/700",
                    source="linkedin",
                    source_job_id="700",
                ))
                _, is_new = upsert_job(conn, self._job(
                    title="Backend Senior Software Engineer",
                    url="https://linkedin.com/jobs/view/701",
                    source="linkedin",
                    source_job_id="701",
                ))
                self.assertTrue(is_new)
                self.assertEqual(count_jobs(conn), 2)

    def test_safe_company_aliases_are_supported(self):
        self.assertEqual(normalize_company_key("HPE"), normalize_company_key("Hewlett Packard Enterprise"))
        self.assertEqual(normalize_company_key("STC"), normalize_company_key("Saudi Telecom Company"))

    def test_token_order_similarity_is_one(self):
        self.assertEqual(
            title_similarity("Junior Backend .NET Developer", ".NET Backend Developer - Junior"),
            1.0,
        )


if __name__ == "__main__":
    unittest.main()
