import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from locations import normalize_saudi_location, saudi_location_hashtags


class SaudiLocationTests(unittest.TestCase):
    def test_bilingual_city_aliases(self):
        self.assertEqual(normalize_saudi_location("الرياض، السعودية").city_code, "RIYADH")
        self.assertEqual(normalize_saudi_location("Al Khobar, Saudi Arabia").city_code, "KHOBAR")
        self.assertEqual(normalize_saudi_location("Jiddah, KSA").city_code, "JEDDAH")

    def test_region_and_country_only(self):
        info = normalize_saudi_location("Saudi Arabia")
        self.assertTrue(info.is_saudi)
        self.assertIsNone(info.city_code)
        self.assertEqual(normalize_saudi_location("Dammam, Eastern Province").region_code, "EASTERN")

    def test_hashtags_are_metadata_not_topics(self):
        self.assertEqual(saudi_location_hashtags("Riyadh, Saudi Arabia"), ["#SaudiArabia", "#Riyadh"])
        self.assertEqual(saudi_location_hashtags("Cairo, Egypt"), [])


if __name__ == "__main__":
    unittest.main()
