import importlib.util
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def load_registry_module():
    spec = importlib.util.spec_from_file_location("source_registry_under_test", PROJECT_ROOT / "sources" / "__init__.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class SourceRegistryTests(unittest.TestCase):
    def setUp(self):
        self.registry = load_registry_module()

    def test_registry_enables_production_sources_plus_measured_shadow_sources(self):
        names = [name for name, _ in self.registry.ALL_FETCHERS]
        self.assertEqual(
            names,
            [
                "WUZZUF",
                "LinkedIn",
                "LinkedIn Saudi V2",
                "Jobzaty",
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


    def test_poll_interval_registry_keeps_core_hot_and_ats_adaptive(self):
        intervals = self.registry.SOURCE_POLL_INTERVAL_MINUTES
        self.assertEqual(intervals["wuzzuf"], 15)
        self.assertEqual(intervals["linkedin"], 15)
        self.assertEqual(intervals["linkedin_saudi_v2"], 15)
        self.assertEqual(intervals["jobzaty"], 60)
        self.assertEqual(intervals["ats_greenhouse_hala"], 30)
        self.assertEqual(intervals["ats_greenhouse_minio"], 60)
        self.assertEqual(intervals["ats_workday_cisco"], 60)

    def test_no_legacy_sources_are_registered(self):
        names = {name.lower() for name, _ in self.registry.ALL_FETCHERS}
        disabled_sources = {
            "remotive",
            "himalayas",
            "jobicy",
            "remoteok",
            "arbeitnow",
            "wwr",
            "working nomads",
            "jsearch",
            "adzuna",
            "the muse",
            "findwork",
            "jooble",
            "reed",
            "usajobs",
        }
        self.assertTrue(names.isdisjoint(disabled_sources))

    def test_registered_fetchers_are_callable(self):
        for name, fetcher in self.registry.ALL_FETCHERS:
            with self.subTest(source=name):
                self.assertTrue(callable(fetcher))

    def test_enabled_source_names_matches_registry_order(self):
        self.assertEqual(
            self.registry.ENABLED_SOURCE_NAMES,
            tuple(name for name, _ in self.registry.ALL_FETCHERS),
        )

    def test_registry_contains_only_expected_core_fetcher_names(self):
        core_names = {fetcher.__name__ for _, fetcher in self.registry.CORE_FETCHERS}
        self.assertEqual(core_names, {"fetch_wuzzuf", "fetch_linkedin", "fetch_linkedin_saudi_v2"})
        self.assertEqual(len(self.registry.SHADOW_BOARD_FETCHERS), 1)
        self.assertEqual(self.registry.SHADOW_BOARD_FETCHERS[0][1].__name__, "fetch_jobzaty")
        self.assertEqual(len(self.registry.ATS_FETCHERS), 18)


if __name__ == "__main__":
    unittest.main()
