import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from models import Job
from telegram_sender import route_job
from config import CHANNELS


class TelegramRoutingTests(unittest.TestCase):
    def test_linkedin_all_channel_is_configured(self):
        channel = CHANNELS.get("linkedin_all")
        self.assertIsInstance(channel, dict)
        self.assertEqual(channel.get("thread_env"), "TOPIC_LINKEDIN_ALL")
        self.assertEqual(channel.get("match"), "SOURCE_LINKEDIN")
        self.assertIn("LinkedIn", channel.get("name", ""))

    def test_any_linkedin_job_routes_to_linkedin_all_even_without_category_match(self):
        job = Job(
            title="People Operations Coordinator",
            company="Acme",
            location="Cairo, Egypt",
            url="https://www.linkedin.com/jobs/view/1234567890",
            source="linkedin",
            tags=[],
            is_remote=False,
        )
        routed = route_job(job)
        self.assertIn("linkedin_all", routed)
        # This confirms the special LinkedIn topic is source-based, not category-based.
        self.assertNotIn("backend", routed)
        self.assertNotIn("frontend", routed)

    def test_linkedin_job_still_keeps_normal_category_routing(self):
        job = Job(
            title="Backend Developer",
            company="Acme",
            location="Cairo, Egypt",
            url="https://www.linkedin.com/jobs/view/1234567890",
            source="linkedin",
            tags=[],
            is_remote=False,
        )
        routed = route_job(job)
        self.assertIn("linkedin_all", routed)
        self.assertIn("backend", routed)
        self.assertIn("egypt", routed)
        self.assertIn("general", routed)

    def test_non_linkedin_job_does_not_route_to_linkedin_all(self):
        job = Job(
            title="Backend Developer",
            company="Acme",
            location="Cairo, Egypt",
            url="https://wuzzuf.net/jobs/p/test",
            source="wuzzuf",
            tags=[],
            is_remote=False,
        )
        routed = route_job(job)
        self.assertNotIn("linkedin_all", routed)
        self.assertIn("backend", routed)
        self.assertIn("egypt", routed)

    def test_source_matching_is_case_and_whitespace_insensitive(self):
        job = Job(
            title="Unclassified Fresh Role",
            company="Acme",
            location="Remote",
            url="https://www.linkedin.com/jobs/view/1234567890",
            source="  LinkedIn  ",
            tags=[],
            is_remote=True,
        )
        self.assertIn("linkedin_all", route_job(job))

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
        self.assertEqual(result, {"missing_topic_for_test": False})


if __name__ == "__main__":
    unittest.main()
