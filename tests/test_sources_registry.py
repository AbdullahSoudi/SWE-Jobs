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

    def test_registry_enables_only_wuzzuf_and_linkedin(self):
        names = [name for name, _ in self.registry.ALL_FETCHERS]
        self.assertEqual(names, ["WUZZUF", "LinkedIn"])

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
        self.assertEqual(self.registry.ENABLED_SOURCE_NAMES, ("WUZZUF", "LinkedIn"))

    def test_registry_does_not_import_disabled_fetchers(self):
        fetcher_names = {fetcher.__name__ for _, fetcher in self.registry.ALL_FETCHERS}
        self.assertEqual(fetcher_names, {"fetch_wuzzuf", "fetch_linkedin"})


if __name__ == "__main__":
    unittest.main()
