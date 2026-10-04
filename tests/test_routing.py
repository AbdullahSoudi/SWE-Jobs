import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from models import Job
from telegram_sender import format_job_message, route_job
from config import CHANNELS, PRIMARY_TOPIC_ORDER


class TelegramRoutingTests(unittest.TestCase):
    def test_only_compact_primary_topics_are_active(self):
        self.assertEqual(
            set(CHANNELS),
            {
                "general",
                "backend",
                "frontend",
                "mobile",
                "devops",
                "qa",
                "ai_ml",
                "cybersecurity",
                "internships",
                "erp",
            },
        )
        self.assertNotIn("linkedin_all", CHANNELS)
        self.assertNotIn("egypt", CHANNELS)
        self.assertNotIn("saudi", CHANNELS)

    def test_priority_order_contains_only_specific_topics(self):
        self.assertNotIn("general", PRIMARY_TOPIC_ORDER)
        self.assertEqual(PRIMARY_TOPIC_ORDER[0], "internships")
        self.assertTrue(set(PRIMARY_TOPIC_ORDER).issubset(CHANNELS))

    def test_backend_job_routes_once_even_when_linkedin_and_in_egypt(self):
        job = Job(
            title="Backend Developer",
            company="Acme",
            location="Cairo, Egypt",
            url="https://www.linkedin.com/jobs/view/1234567890",
            source="linkedin",
            tags=["Python"],
        )
        self.assertEqual(route_job(job), ["backend"])

    def test_internship_wins_over_role_to_avoid_cross_posting(self):
        job = Job(
            title="Backend Developer Intern",
            company="Acme",
            location="Riyadh, Saudi Arabia",
            url="https://example.com/intern",
            source="wuzzuf",
            tags=[".NET"],
        )
        self.assertEqual(route_job(job), ["internships"])

    def test_data_engineering_is_merged_into_data_and_ai(self):
        job = Job(
            title="Data Engineer",
            company="Acme",
            location="Riyadh, Saudi Arabia",
            url="https://example.com/data",
            source="linkedin",
            tags=["Airflow", "dbt"],
        )
        self.assertEqual(route_job(job), ["ai_ml"])
        self.assertEqual(CHANNELS["ai_ml"]["name"], "🤖 Data & AI")

    def test_generic_tech_role_uses_general_fallback(self):
        job = Job(
            title="Software Engineer",
            company="Acme",
            location="Cairo, Egypt",
            url="https://example.com/swe",
            source="linkedin",
            tags=[],
        )
        self.assertEqual(route_job(job), ["general"])

    def test_unrelated_linkedin_role_is_not_kept_just_for_its_source(self):
        job = Job(
            title="People Operations Coordinator",
            company="Acme",
            location="Cairo, Egypt",
            url="https://www.linkedin.com/jobs/view/1234567890",
            source="linkedin",
            tags=[],
        )
        self.assertEqual(route_job(job), [])

    def test_market_is_metadata_not_an_extra_topic(self):
        job = Job(
            title="Backend Developer",
            company="Acme",
            location="Riyadh, Saudi Arabia",
            url="https://example.com/backend",
            source="linkedin",
        )
        message = format_job_message(job)
        self.assertEqual(route_job(job), ["backend"])
        self.assertIn("#SaudiArabia", message)
        self.assertNotIn("#Egypt", message)


    def test_saudi_eligibility_is_metadata_not_a_topic(self):
        saudi_only = Job(
            title="Backend Developer",
            company="Acme",
            location="Riyadh, Saudi Arabia",
            url="https://example.com/saudi-only",
            source="linkedin",
            eligibility="SAUDI_ONLY",
        )
        message = format_job_message(saudi_only)
        self.assertIn("Eligibility: Saudi nationals only", message)
        self.assertIn("#SaudiOnly", message)
        self.assertEqual(route_job(saudi_only), ["backend"])

        explicitly_open = Job(
            title="Backend Developer",
            company="Acme",
            location="Riyadh, Saudi Arabia",
            url="https://example.com/open",
            source="linkedin",
            eligibility="EXPLICITLY_OPEN",
        )
        open_message = format_job_message(explicitly_open)
        self.assertIn("Explicitly open to non-Saudis", open_message)
        self.assertIn("#OpenEligibility", open_message)

        unspecified = Job(
            title="Backend Developer",
            company="Acme",
            location="Riyadh, Saudi Arabia",
            url="https://example.com/unknown",
            source="linkedin",
        )
        self.assertIn("Eligibility: Not specified", format_job_message(unspecified))

    def test_send_job_records_false_for_unconfigured_topic(self):
        import telegram_sender

        job = Job(
            title="Backend Developer",
            company="Acme",
            location="Remote",
            url="https://example.com/job",
            source="wuzzuf",
            is_remote=True,
        )
        result = telegram_sender.send_job(job, target_topics=["missing_topic_for_test"])
        delivery = result["missing_topic_for_test"]
        self.assertFalse(delivery.success)
        self.assertEqual(delivery.outcome, telegram_sender.CONFIG_ERROR)


if __name__ == "__main__":
    unittest.main()
