import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sources.ats import fetch_ashby_company, fetch_greenhouse_company, fetch_lever_company


class ATSAdapterTests(unittest.TestCase):
    def test_greenhouse_keeps_only_explicit_saudi_rows_and_does_not_treat_updated_as_published(self):
        payload = {
            "jobs": [
                {
                    "id": 101,
                    "title": "Backend Engineer",
                    "location": {"name": "Riyadh, Saudi Arabia"},
                    "absolute_url": "https://job-boards.greenhouse.io/acme/jobs/101",
                    "updated_at": "2026-10-04T18:00:00Z",
                },
                {
                    "id": 102,
                    "title": "Backend Engineer",
                    "location": {"name": "London, United Kingdom"},
                    "absolute_url": "https://job-boards.greenhouse.io/acme/jobs/102",
                    "updated_at": "2026-10-04T18:00:00Z",
                },
            ]
        }
        calls = []

        def getter(url, params=None):
            calls.append((url, params))
            return payload

        jobs = fetch_greenhouse_company(
            tenant="acme",
            company="Acme",
            source_key="ats_greenhouse_acme",
            http_getter=getter,
        )
        self.assertEqual(len(jobs), 1)
        job = jobs[0]
        self.assertEqual(job.source_job_id, "101")
        self.assertEqual(job.original_source, "Acme Careers")
        self.assertEqual(job.time_semantics, "UPDATED")
        self.assertEqual(job.published_precision, "NONE")
        self.assertEqual(job.published_at_earliest, "")
        self.assertIn("Riyadh", job.location)
        self.assertEqual(calls[0][1], None)

    def test_lever_uses_country_code_and_normalizes_workplace_metadata(self):
        payload = [
            {
                "id": "lever-1",
                "text": "Information Security Officer",
                "categories": {
                    "location": "Riyadh",
                    "commitment": "Full-Time",
                    "team": "Technology",
                    "department": "Engineering",
                },
                "country": "SA",
                "hostedUrl": "https://jobs.lever.co/acme/lever-1",
                "workplaceType": "on-site",
            },
            {
                "id": "lever-2",
                "text": "Software Engineer",
                "categories": {"location": "Cairo"},
                "country": "EG",
                "hostedUrl": "https://jobs.lever.co/acme/lever-2",
                "workplaceType": "remote",
            },
        ]

        def getter(url, params=None):
            self.assertEqual(params, {"mode": "json"})
            return payload

        jobs = fetch_lever_company(
            tenant="acme",
            company="Acme",
            source_key="ats_lever_acme",
            http_getter=getter,
        )
        self.assertEqual(len(jobs), 1)
        job = jobs[0]
        self.assertEqual(job.source_job_id, "lever-1")
        self.assertEqual(job.location, "Riyadh")
        self.assertIn("Technology", job.tags)
        self.assertIn("Full-Time", job.job_type)
        self.assertFalse(job.is_remote)

    def test_ashby_preserves_exact_published_at_and_filters_non_saudi(self):
        payload = {
            "apiVersion": "1",
            "jobs": [
                {
                    "title": "Full Stack Software Engineer",
                    "location": "Riyadh, Saudi Arabia",
                    "department": "Engineering",
                    "team": "Platform",
                    "isListed": True,
                    "isRemote": True,
                    "workplaceType": "Remote",
                    "publishedAt": "2026-10-04T18:21:55+00:00",
                    "employmentType": "FullTime",
                    "address": {"postalAddress": {"addressCountry": "Saudi Arabia"}},
                    "jobUrl": "https://jobs.ashbyhq.com/acme/abc-123",
                    "applyUrl": "https://jobs.ashbyhq.com/acme/abc-123/application",
                },
                {
                    "title": "Software Engineer",
                    "location": "New York, NY",
                    "isListed": True,
                    "workplaceType": "OnSite",
                    "publishedAt": "2026-10-04T18:21:55+00:00",
                    "employmentType": "FullTime",
                    "address": {"postalAddress": {"addressCountry": "USA"}},
                    "jobUrl": "https://jobs.ashbyhq.com/acme/us-123",
                },
            ],
        }

        def getter(url, params=None):
            self.assertEqual(params, {"includeCompensation": "false"})
            return payload

        jobs = fetch_ashby_company(
            tenant="acme",
            company="Acme",
            source_key="ats_ashby_acme",
            http_getter=getter,
        )
        self.assertEqual(len(jobs), 1)
        job = jobs[0]
        self.assertEqual(job.source_job_id, "abc-123")
        self.assertEqual(job.published_precision, "EXACT")
        self.assertEqual(job.time_semantics, "POSTED")
        self.assertEqual(job.published_at_est, "2026-10-04T18:21:55Z")
        self.assertTrue(job.is_remote)
        self.assertIn("Engineering", job.tags)

    def test_adapter_failure_is_not_silently_reported_as_empty_success(self):
        with self.assertRaises(RuntimeError):
            fetch_greenhouse_company(
                tenant="acme",
                company="Acme",
                source_key="ats_greenhouse_acme",
                http_getter=lambda *args, **kwargs: None,
            )
        with self.assertRaises(ValueError):
            fetch_lever_company(
                tenant="acme",
                company="Acme",
                source_key="ats_lever_acme",
                http_getter=lambda *args, **kwargs: {"unexpected": True},
            )


if __name__ == "__main__":
    unittest.main()
