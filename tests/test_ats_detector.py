import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ats_detector import detect_ats_url


class ATSDetectorTests(unittest.TestCase):
    def test_detects_greenhouse_board_and_job_urls(self):
        detected = detect_ats_url("https://job-boards.greenhouse.io/scaleai/jobs/4732430005?gh_src=x")
        self.assertEqual((detected.ats, detected.tenant), ("greenhouse", "scaleai"))
        self.assertEqual(detected.board_url, "https://job-boards.greenhouse.io/scaleai")

    def test_detects_lever_board_and_posting_urls(self):
        detected = detect_ats_url("https://jobs.lever.co/incorta/cea6cded-3d61-4df8-b846-320fe50dbc50")
        self.assertEqual((detected.ats, detected.tenant), ("lever", "incorta"))
        self.assertEqual(detected.board_url, "https://jobs.lever.co/incorta")

    def test_detects_ashby_board_and_job_urls_preserving_tenant_case(self):
        detected = detect_ats_url("https://jobs.ashbyhq.com/LeanTech/f82276bf-e861-4908-9513-49381561ecf1")
        self.assertEqual((detected.ats, detected.tenant), ("ashby", "LeanTech"))
        self.assertEqual(detected.board_url, "https://jobs.ashbyhq.com/LeanTech")

    def test_detects_public_api_urls(self):
        self.assertEqual(
            detect_ats_url("https://boards-api.greenhouse.io/v1/boards/hala/jobs").tenant,
            "hala",
        )
        self.assertEqual(
            detect_ats_url("https://api.lever.co/v0/postings/soum?mode=json").tenant,
            "soum",
        )
        self.assertEqual(
            detect_ats_url("https://api.ashbyhq.com/posting-api/job-board/sarjai").tenant,
            "sarjai",
        )

    def test_unknown_custom_career_site_is_not_guessed(self):
        self.assertIsNone(detect_ats_url("https://careers.example.com/jobs/123"))


if __name__ == "__main__":
    unittest.main()
