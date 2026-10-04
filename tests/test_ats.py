import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from datetime import UTC, datetime

from sources.ats import fetch_ashby_company, fetch_greenhouse_company, fetch_lever_company, fetch_workday_company


class ATSAdapterTests(unittest.TestCase):
    def test_greenhouse_uses_first_published_when_available(self):
        payload = {
            "jobs": [
                {
                    "id": 101,
                    "title": "Backend Engineer",
                    "location": {"name": "Riyadh, Saudi Arabia"},
                    "absolute_url": "https://job-boards.greenhouse.io/acme/jobs/101",
                    "first_published": "2026-10-04T18:00:00Z",
                    "updated_at": "2026-10-04T19:00:00Z",
                    "content": "<p>Saudi nationals only</p><p>Build APIs</p>",
                },
                {
                    "id": 102,
                    "title": "Backend Engineer",
                    "location": {"name": "London, United Kingdom"},
                    "absolute_url": "https://job-boards.greenhouse.io/acme/jobs/102",
                    "first_published": "2026-10-04T18:00:00Z",
                },
            ]
        }

        jobs = fetch_greenhouse_company(
            tenant="acme",
            company="Acme",
            source_key="ats_greenhouse_acme",
            http_getter=lambda url, params=None: payload,
        )
        self.assertEqual(len(jobs), 1)
        job = jobs[0]
        self.assertEqual(job.source_job_id, "101")
        self.assertEqual(job.original_source, "Acme Careers")
        self.assertEqual(job.time_semantics, "POSTED")
        self.assertEqual(job.published_precision, "EXACT")
        self.assertEqual(job.published_at_est, "2026-10-04T18:00:00Z")
        self.assertEqual(job.description, "Saudi nationals only\nBuild APIs")

    def test_greenhouse_falls_back_to_snapshot_when_first_published_is_missing(self):
        payload = {
            "jobs": [{
                "id": 103,
                "title": "Platform Engineer",
                "location": {"name": "Riyadh, Saudi Arabia"},
                "absolute_url": "https://job-boards.greenhouse.io/acme/jobs/103",
                "updated_at": "2026-10-04T19:00:00Z",
            }]
        }
        job = fetch_greenhouse_company(
            tenant="acme",
            company="Acme",
            source_key="ats_greenhouse_acme",
            http_getter=lambda url, params=None: payload,
        )[0]
        self.assertEqual(job.time_semantics, "UPDATED")
        self.assertEqual(job.published_precision, "NONE")
        self.assertEqual(job.published_at_earliest, "")
        self.assertEqual(job.published_at_raw, "2026-10-04T19:00:00Z")

    def test_lever_uses_country_code_and_normalizes_workplace_metadata(self):
        payload = [
            {
                "id": "lever-1",
                "text": "Information Security Officer",
                "categories": {
                    "location": "Dubai",
                    "allLocations": ["Dubai", "Riyadh"],
                    "locationDetails": {"country": "SA"},
                    "commitment": "Full-Time",
                    "team": "Technology",
                    "department": "Engineering",
                },
                "hostedUrl": "https://jobs.lever.co/acme/lever-1",
                "workplaceType": "on-site",
                "descriptionPlain": "Open to all nationalities. Secure our platform.",
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
        self.assertIn("Open to all nationalities", job.description)

    def test_ashby_preserves_exact_published_at_and_filters_non_saudi(self):
        payload = {
            "apiVersion": "1",
            "jobs": [
                {
                    "title": "Full Stack Software Engineer",
                    "location": "Dubai, UAE",
                    "secondaryLocations": [
                        {"location": "Riyadh, Saudi Arabia", "address": {"addressCountry": "Saudi Arabia"}}
                    ],
                    "department": "Engineering",
                    "team": "Platform",
                    "isListed": True,
                    "isRemote": True,
                    "workplaceType": "Remote",
                    "publishedAt": "2026-10-04T18:21:55+00:00",
                    "employmentType": "FullTime",
                    "address": {"postalAddress": {"addressCountry": "UAE"}},
                    "jobUrl": "https://jobs.ashbyhq.com/acme/abc-123",
                    "applyUrl": "https://jobs.ashbyhq.com/acme/abc-123/application",
                    "descriptionHtml": "<p>Work visa sponsorship is provided.</p>",
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
        self.assertEqual(job.description, "Work visa sponsorship is provided.")



    def test_workday_searches_saudi_terms_deduplicates_and_preserves_freshness(self):
        calls = []

        def poster(url, payload=None, headers=None):
            calls.append((url, payload, headers))
            term = payload["searchText"]
            if term == "Riyadh":
                return {
                    "total": 2,
                    "jobPostings": [
                        {
                            "title": "Backend Software Engineer",
                            "externalPath": "/job/Riyadh-Saudi-Arabia/Backend-Software-Engineer_R123",
                            "locationsText": "Riyadh, Saudi Arabia",
                            "postedOn": "Posted 15 Minutes Ago",
                            "bulletFields": ["Full time"],
                        },
                        {
                            "title": "Software Engineer",
                            "externalPath": "/job/Dubai-UAE/Software-Engineer_R999",
                            "locationsText": "Dubai, UAE",
                            "postedOn": "Posted Today",
                        },
                    ],
                }
            if term == "Saudi Arabia":
                return {
                    "total": 2,
                    "jobPostings": [
                        {
                            "title": "Backend Software Engineer",
                            "externalPath": "/job/Riyadh-Saudi-Arabia/Backend-Software-Engineer_R123",
                            "locationsText": "Riyadh, Saudi Arabia",
                            "postedOn": "Posted 15 Minutes Ago",
                        },
                        {
                            "title": "Cloud Engineer",
                            "externalPath": "/job/Khobar-Saudi-Arabia/Cloud-Engineer_R456",
                            "locationsText": "Khobar, Saudi Arabia",
                            "postedOn": "Posted Today",
                        },
                    ],
                }
            return {"total": 0, "jobPostings": []}

        jobs = fetch_workday_company(
            host="acme.wd5.myworkdayjobs.com",
            tenant="acme",
            site="ExternalCareers",
            company="Acme",
            source_key="ats_workday_acme",
            search_terms=["Riyadh", "Saudi Arabia", "KSA"],
            max_pages_per_term=1,
            http_poster=poster,
            fetched_at=datetime(2026, 10, 4, 18, 0, tzinfo=UTC),
        )

        self.assertEqual([job.title for job in jobs], ["Backend Software Engineer", "Cloud Engineer"])
        backend = jobs[0]
        self.assertEqual(backend.source_job_id, "job/Riyadh-Saudi-Arabia/Backend-Software-Engineer_R123")
        self.assertEqual(backend.published_precision, "MINUTE")
        self.assertEqual(backend.published_at_latest, "2026-10-04T17:45:00Z")
        self.assertEqual(
            backend.url,
            "https://acme.wd5.myworkdayjobs.com/en-US/ExternalCareers/job/Riyadh-Saudi-Arabia/Backend-Software-Engineer_R123",
        )
        cloud = jobs[1]
        self.assertEqual(cloud.published_precision, "NONE")
        self.assertEqual(cloud.location, "Khobar, Saudi Arabia")
        self.assertEqual([call[1]["searchText"] for call in calls], ["Riyadh", "Saudi Arabia", "KSA"])
        self.assertTrue(all(call[1]["limit"] == 20 for call in calls))

    def test_workday_refuses_truncated_search_snapshot(self):
        rows = [{
            "title": f"Engineer {idx}",
            "externalPath": f"/job/Riyadh/Engineer-{idx}_R{idx}",
            "locationsText": "Riyadh, Saudi Arabia",
            "postedOn": "Posted Today",
        } for idx in range(20)]

        with self.assertRaisesRegex(RuntimeError, "search saturated"):
            fetch_workday_company(
                host="acme.wd5.myworkdayjobs.com",
                tenant="acme",
                site="ExternalCareers",
                company="Acme",
                source_key="ats_workday_acme",
                search_terms=["Riyadh"],
                max_pages_per_term=1,
                http_poster=lambda *args, **kwargs: {"total": 75, "jobPostings": rows},
            )

    def test_workday_failure_is_not_silently_reported_as_empty_success(self):
        with self.assertRaises(RuntimeError):
            fetch_workday_company(
                host="acme.wd5.myworkdayjobs.com",
                tenant="acme",
                site="ExternalCareers",
                company="Acme",
                source_key="ats_workday_acme",
                search_terms=["Riyadh"],
                http_poster=lambda *args, **kwargs: None,
            )

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
