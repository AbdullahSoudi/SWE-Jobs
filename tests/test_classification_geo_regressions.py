import tempfile
import unittest
import json
from pathlib import Path

from classifier import classify_job
from db import connect, upsert_job
from dedup import locations_compatible
from locations import normalize_saudi_location, saudi_location_hashtags
from main import should_keep_job
from models import Job, passes_geo_filter
from sources.ats import _saudi_location, fetch_lever_company
from telegram_sender import format_job_message, route_job


def job(title='Senior Backend Software Engineer', location='Cairo, Egypt', **kwargs):
    return Job(title, 'Acme', location, kwargs.pop('url', 'https://example.test/job'),
               kwargs.pop('source', 'linkedin'), **kwargs)


class TechnicalRelevanceTests(unittest.TestCase):
    def test_existing_bilingual_corpus_keeps_every_expected_topic(self):
        cases = json.loads(Path(__file__).with_name('classifier_cases.json').read_text(encoding='utf-8'))
        for case in cases:
            with self.subTest(title=case['title']):
                result = classify_job(job(case['title']))
                self.assertEqual(result.topic if result.is_tech else None, case['expected'])

    def test_nontechnical_career_stage_does_not_establish_relevance(self):
        for title in ('International Sales Manager', 'Internal Auditor', 'Marketing Intern',
                      'Junior Marketing Coordinator', 'Business Developer', 'Graduate Marketing Coordinator',
                      'Intern', 'Junior', 'متدرب تسويق', 'برنامج خريجين مبيعات'):
            with self.subTest(title=title):
                self.assertFalse(should_keep_job(job(title)))
                self.assertEqual(route_job(job(title)), [])

    def test_internal_does_not_override_role(self):
        self.assertEqual(route_job(job('Senior Backend Engineer - Internal Tools')), ['backend'])

    def test_technical_career_stage_has_one_topic(self):
        for title in ('Backend Developer Intern', 'Junior Software Engineer',
                      'Graduate Firmware Engineer', 'Entry-level .NET Developer',
                      'متدرب تطوير برمجيات', 'برنامج خريجين - تقنية المعلومات'):
            with self.subTest(title=title):
                self.assertTrue(should_keep_job(job(title)))
                self.assertEqual(route_job(job(title)), ['internships'])

    def test_bounded_phrases_preserve_languages_and_symbols(self):
        for title, topic in (('مطور جافا', 'backend'), ('مطور جافاسكريبت', 'frontend'),
                             ('C# Developer', 'backend'), ('C++ Engineer', 'general'), ('C++ Developer', 'general'),
                             ('Senior .NET Developer', 'backend'), ('Front-end Developer', 'frontend'),
                             ('Full-stack Developer', 'backend'), ('JavaScript Developer', 'frontend'),
                             ('مُطوّر واجهات أمامية', 'frontend')):
            with self.subTest(title=title):
                self.assertEqual(classify_job(job(title)).topic, topic)

    def test_tags_supply_technical_evidence_but_not_stage_alone(self):
        self.assertEqual(route_job(job('Intern', tags=['software engineer'])), ['internships'])
        self.assertEqual(route_job(job('Marketing Coordinator', tags=['internship'])), [])


class CountryAwareLocationTests(unittest.TestCase):
    def test_foreign_city_collisions_fail_all_local_market_checks(self):
        for location in ('Bangkok, Thailand', 'Medina, Ohio', 'Medina, OH, USA',
                         'Alexandria, Virginia', 'Alexandria, VA, United States',
                         'Cairo, Georgia', 'Hail, United Kingdom', 'Riyadh, United States',
                         'New Cairoton', 'Hailsville', 'Alexandria, Unknown Country'):
            with self.subTest(location=location):
                candidate = job(location=location, eligibility='SAUDI_ONLY')
                self.assertFalse(passes_geo_filter(candidate))
                self.assertFalse(normalize_saudi_location(location).is_saudi)
                message = format_job_message(candidate)
                self.assertNotIn('#SaudiArabia', message)
                self.assertNotIn('#Egypt', message)
                self.assertNotIn('Eligibility:', message)

    def test_saudi_aliases_agree_across_filter_ats_and_formatting(self):
        for location, city in (('Madinah', 'MADINAH'), ('Jiddah', 'JEDDAH'), ('Jizan', 'JAZAN'),
                               ('حائل', 'HAIL'), ('Al Khobar', 'KHOBAR'), ('الرياض', 'RIYADH'),
                               ('المدينة المنورة', 'MADINAH'), ('Al Madinah', 'MADINAH')):
            with self.subTest(location=location):
                self.assertTrue(passes_geo_filter(job(location=location)))
                self.assertEqual(normalize_saudi_location(location).city_code, city)
                self.assertIsNotNone(_saudi_location(location))
                self.assertIn('#SaudiArabia', format_job_message(job(location=location)))
                self.assertIn('Eligibility:', format_job_message(job(location=location)))

    def test_country_hints_override_city_only_inference_without_erasing_conflicts(self):
        for location, country in (('Medina', 'US'), ('Riyadh', 'US'), ('Cairo', 'EG'),
                                  ('Bangkok, Thailand', 'SA'), ('London, United Kingdom', 'SA')):
            with self.subTest(location=location, country=country):
                self.assertIsNone(_saudi_location(location, country))
        self.assertEqual(_saudi_location('Unlisted District', 'SA'), 'Unlisted District, Saudi Arabia')

    def test_supported_egypt_places_and_remote_exceptions_remain(self):
        for location in ('القاهرة، مصر', 'Alexandria, Egypt', 'New Cairo', 'أسوان', 'Giza',
                         'Dammam, Eastern Province', 'Qassim', 'Saudi Arabia'):
            with self.subTest(location=location):
                self.assertTrue(passes_geo_filter(job(location=location)))
        self.assertTrue(passes_geo_filter(job(location='London, United Kingdom', is_remote=True)))
        self.assertTrue(passes_geo_filter(job(location='Remote')))

    def test_location_conflicts_and_aliases_in_dedup(self):
        self.assertFalse(locations_compatible('Bangkok, Thailand', 'Hail, Saudi Arabia'))
        self.assertFalse(locations_compatible('Medina, Ohio', 'Madinah, Saudi Arabia'))
        self.assertFalse(locations_compatible('Alexandria, Virginia', 'Alexandria, Egypt'))
        self.assertFalse(locations_compatible('Riyadh / Jeddah', 'Riyadh'))
        self.assertTrue(locations_compatible('Jiddah', 'Jeddah, Saudi Arabia'))
        self.assertTrue(locations_compatible('Madinah', 'المدينة، السعودية'))

    def test_foreign_and_saudi_postings_remain_separate_clusters(self):
        with tempfile.TemporaryDirectory() as tmp, connect(Path(tmp) / 'jobs.db') as conn:
            first, _ = upsert_job(conn, job(location='Bangkok, Thailand', url='https://example.test/th'))
            second, is_new = upsert_job(conn, job(location='Hail, Saudi Arabia',
                                                url='https://example.test/sa', source='ats_acme'))
            self.assertTrue(is_new)
            self.assertNotEqual(first, second)
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM jobs').fetchone()[0], 2)

    def test_equivalent_saudi_aliases_still_merge(self):
        with tempfile.TemporaryDirectory() as tmp, connect(Path(tmp) / 'jobs.db') as conn:
            first, _ = upsert_job(conn, job(location='Jiddah', url='https://example.test/1'))
            second, is_new = upsert_job(conn, job(location='Jeddah, Saudi Arabia',
                                                url='https://example.test/2', source='ats_acme'))
            self.assertFalse(is_new)
            self.assertEqual(first, second)

    def test_structured_foreign_country_is_applied_to_primary_ats_location(self):
        row = {'id': '1', 'text': 'Backend Developer', 'hostedUrl': 'https://example.test/1',
               'country': 'US', 'categories': {'location': 'Medina'}}
        self.assertEqual(fetch_lever_company(company='Acme', tenant='acme', source_key='ats_acme',
                                            http_getter=lambda *a, **k: [row]), [])

    def test_conflicting_countries_do_not_get_saudi_metadata(self):
        self.assertEqual(saudi_location_hashtags('Riyadh, Saudi Arabia / United States'), [])
        self.assertFalse(passes_geo_filter(job(location='Riyadh, Saudi Arabia / United States')))
