import json
import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from company_registry import build_ats_fetchers, build_ats_poll_intervals, load_ats_companies


class CompanyRegistryTests(unittest.TestCase):
    def test_initial_registry_is_small_and_all_shadow_by_default(self):
        companies = load_ats_companies()
        self.assertEqual([c.key for c in companies], [
            "hala", "minio", "soum", "sarjai", "echelon",
            "scaleai", "canonical", "incorta", "uipath", "elevenlabs", "cognition", "leantech",
            "cisco", "nttdata", "infobip", "hpe", "workday", "salesforce",
        ])
        self.assertEqual({c.ats for c in companies}, {"greenhouse", "lever", "ashby", "workday"})
        self.assertTrue(all(c.country == "SA" for c in companies))
        self.assertTrue(all(c.source_key.startswith("ats_") for c in companies))


    def test_registry_exposes_safe_poll_intervals(self):
        companies = load_ats_companies()
        intervals = {c.key: c.poll_interval_minutes for c in companies}
        self.assertEqual(intervals, {
            "hala": 30,
            "minio": 60,
            "soum": 30,
            "sarjai": 60,
            "echelon": 60,
            "scaleai": 30,
            "canonical": 60,
            "incorta": 60,
            "uipath": 60,
            "elevenlabs": 60,
            "cognition": 60,
            "leantech": 30,
            "cisco": 60,
            "nttdata": 60,
            "infobip": 60,
            "hpe": 60,
            "workday": 60,
            "salesforce": 60,
        })
        source_intervals = build_ats_poll_intervals()
        self.assertEqual(source_intervals["ats_greenhouse_hala"], 30)
        self.assertEqual(source_intervals["ats_ashby_echelon"], 60)
        self.assertEqual(source_intervals["ats_workday_cisco"], 60)

    def test_fetchers_have_stable_source_names(self):
        fetchers = build_ats_fetchers()
        names = [name for name, _ in fetchers]
        self.assertEqual(
            names,
            [
                "ATS Greenhouse hala",
                "ATS Greenhouse minio",
                "ATS Lever soum",
                "ATS Ashby sarjai",
                "ATS Ashby echelon",
                "ATS Greenhouse scaleai",
                "ATS Greenhouse canonical",
                "ATS Lever incorta",
                "ATS Ashby uipath",
                "ATS Ashby elevenlabs",
                "ATS Ashby cognition",
                "ATS Ashby leantech",
                "ATS Workday cisco",
                "ATS Workday nttdata",
                "ATS Workday infobip",
                "ATS Workday hpe",
                "ATS Workday workday",
                "ATS Workday salesforce",
            ],
        )
        for _, fetcher in fetchers:
            self.assertTrue(callable(fetcher))
            self.assertTrue(fetcher.__name__.startswith("fetch_ats_"))

    def test_workday_registry_requires_host_and_site(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "registry.json"
            path.write_text(json.dumps([{
                "key": "badworkday",
                "company": "Bad Workday",
                "ats": "workday",
                "tenant": "badworkday",
                "country": "SA",
            }]), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "requires host and site"):
                load_ats_companies(path)

    def test_registry_rejects_unknown_ats(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "registry.json"
            path.write_text(json.dumps([
                {
                    "key": "bad",
                    "company": "Bad Co",
                    "ats": "mystery",
                    "tenant": "bad",
                    "country": "SA",
                }
            ]), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Unsupported ATS"):
                load_ats_companies(path)


if __name__ == "__main__":
    unittest.main()
