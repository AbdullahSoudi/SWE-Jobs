import unittest

from source_trust import is_official_source, trust_score


class SourceTrustTests(unittest.TestCase):
    def test_official_ats_outranks_boards_and_discovery_sources(self):
        self.assertGreater(trust_score("ats_greenhouse_hala"), trust_score("linkedin"))
        self.assertGreater(trust_score("linkedin"), trust_score("wuzzuf"))
        self.assertGreater(trust_score("wuzzuf"), trust_score("jobzaty"))

    def test_only_ats_keys_are_official(self):
        self.assertTrue(is_official_source("ats_workday_cisco"))
        self.assertFalse(is_official_source("linkedin"))
        self.assertFalse(is_official_source("jobzaty"))


if __name__ == "__main__":
    unittest.main()
