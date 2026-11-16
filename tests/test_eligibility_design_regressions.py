import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from classifier import classify_job
from config import CHANNELS, get_topic_thread_id
from db import connect, upsert_job, get_jobs_for_sending
from eligibility import classify_eligibility, enrich_job_eligibility, NOT_SPECIFIED, SAUDI_ONLY, EXPLICITLY_OPEN
from main import should_keep_job, send_pending_jobs
from models import Job
from telegram_sender import route_job, send_job, TelegramSendResult, SENT


def job(title):
    return Job(title, 'Acme', 'Riyadh, Saudi Arabia', 'https://example.test/job', 'linkedin')


class EligibilityScopeTests(unittest.TestCase):
    def test_preferences_and_market_expertise_remain_unknown(self):
        for text in ('Preferably Saudi nationals only', 'يفضل أن يكون المتقدم سعودي الجنسية',
                     'Saudi nationals only preferred', 'Applicants must be Saudi-market experts'):
            with self.subTest(text=text):
                self.assertEqual(classify_eligibility(description=text).value, NOT_SPECIFIED)

    def test_ats_enrichment_does_not_propagate_unsupported_nationality(self):
        for text, expected in (('We employ colleagues of all nationalities', NOT_SPECIFIED),
                               ('الجنسية السعودية مطلوبة', SAUDI_ONLY)):
            with self.subTest(text=text), tempfile.TemporaryDirectory() as tmp, connect(Path(tmp) / 'jobs.db') as conn:
                primary = job('Senior Backend Software Engineer')
                job_id, _ = upsert_job(conn, primary)
                ats = Job(primary.title, primary.company, primary.location, 'https://example.test/ats',
                          'ats_acme', description=text)
                enrich_job_eligibility(ats)
                matched_id, is_new = upsert_job(conn, ats)
                self.assertEqual(matched_id, job_id)
                self.assertFalse(is_new)
                self.assertEqual(conn.execute('SELECT eligibility FROM jobs WHERE id=?', (job_id,)).fetchone()[0], expected)

    def test_negation_does_not_create_affirmative_eligibility(self):
        for description in ('Not restricted to Saudi nationals', 'Not open to all nationalities',
                            'Visa sponsorship is not available', 'غير متاح لغير السعوديين',
                            'لا يشترط أن يكون المتقدم سعودي الجنسية',
                            'Saudi nationals only is not a requirement'):
            with self.subTest(description=description):
                self.assertEqual(classify_eligibility(description=description).value, NOT_SPECIFIED)

    def test_negated_open_clause_does_not_override_explicit_requirement(self):
        result = classify_eligibility(description='Not open to all nationalities; Saudi nationals only')
        self.assertEqual(result.value, SAUDI_ONLY)

    def test_company_demographics_and_market_experience_are_not_applicant_requirements(self):
        for description in ('We employ colleagues of all nationalities',
                            'Our workforce includes all nationalities',
                            'يشترط خبرة في السوق السعودي', 'يجب معرفة السوق السعودي',
                            'The company must be Saudi owned',
                            'We serve Saudi and non-Saudi customers'):
            with self.subTest(description=description):
                self.assertEqual(classify_eligibility(description=description).value, NOT_SPECIFIED)
        result = classify_eligibility(description='We employ colleagues of all nationalities. This role is Saudi nationals only.')
        self.assertEqual(result.value, SAUDI_ONLY)

    def test_conflicting_affirmative_evidence_stays_unknown(self):
        result = classify_eligibility(title='Software Engineer - Saudi nationals only',
                                      description='Applications are open to all nationalities.')
        self.assertEqual(result.value, NOT_SPECIFIED)
        self.assertEqual(result.rule, 'conflicting_evidence')

    def test_standard_arabic_nationality_requirements_and_spelling_variants(self):
        for description in ('سعودي الجنسية', 'سعودي الجنسيه', 'الجنسية السعودية مطلوبة',
                            'الجنسيه السعوديه مطلوبه', 'يشترط أن يكون المتقدم سعودي',
                            'يجب أن تكون المتقدمة سعودية'):
            with self.subTest(description=description):
                self.assertEqual(classify_eligibility(description=description).value, SAUDI_ONLY)

    def test_role_scoped_open_evidence_and_local_negation(self):
        for description in ('Saudi and non-Saudi applicants may apply',
                            'التقديم متاح لغير السعوديين', 'الوظيفة متاحة لجميع الجنسيات',
                            'No prior experience required. Visa sponsorship is available for this role.'):
            with self.subTest(description=description):
                self.assertEqual(classify_eligibility(description=description).value, EXPLICITLY_OPEN)

    def test_eligibility_is_metadata_only(self):
        for description in ('Saudi nationals only', 'Open to all nationalities', 'Not restricted to Saudi nationals'):
            with self.subTest(description=description):
                candidate = job('Backend Developer')
                candidate.description = description
                enrich_job_eligibility(candidate)
                self.assertTrue(should_keep_job(candidate))
                self.assertEqual(route_job(candidate), ['backend'])


class RestoredDesignTests(unittest.TestCase):
    def test_design_titles_survive_filter_and_route_once(self):
        for title in ('UI/UX Designer', 'UX Designer', 'UI Designer', 'Graphic Designer',
                      'Senior Graphic Designer', 'Product Designer', 'Visual Designer',
                      'UX Researcher', 'Motion Graphics Designer', 'مصمم جرافيك',
                      'مصمم تجربة المستخدم', 'مصمم واجهة المستخدم'):
            with self.subTest(title=title):
                self.assertTrue(should_keep_job(job(title)))
                self.assertEqual(route_job(job(title)), ['design'])

    def test_stage_and_frontend_priorities_are_preserved(self):
        for title, topic in (('Junior Graphic Designer', 'internships'),
                             ('UI/UX Design Intern', 'internships'),
                             ('UI Developer', 'frontend'), ('Frontend Developer', 'frontend')):
            with self.subTest(title=title):
                self.assertEqual(route_job(job(title)), [topic])
        candidate = job('Graphic Designer')
        candidate.tags = ['CSS', 'Figma']
        self.assertEqual(route_job(candidate), ['design'])

    def test_generic_unrelated_design_does_not_establish_relevance(self):
        for title in ('Fashion Designer', 'Interior Designer', 'Designer', 'Marketing Intern'):
            with self.subTest(title=title):
                self.assertFalse(classify_job(job(title)).is_tech)

    def test_existing_design_secret_is_used_for_actual_send(self):
        client = Mock()
        client.send_message.return_value = TelegramSendResult(True, SENT, message_id=42)
        with patch.dict(os.environ, {'TOPIC_DESIGN': '7654321'}):
            self.assertEqual(CHANNELS['design']['thread_env'], 'TOPIC_DESIGN')
            self.assertEqual(get_topic_thread_id('design'), 7654321)
            result = send_job(job('Graphic Designer'), client=client)
        self.assertTrue(result['design'].success)
        self.assertEqual(client.send_message.call_args.args[1], 7654321)
        client.send_message.assert_called_once()

    def test_missing_design_configuration_is_reported_without_sending_elsewhere(self):
        with patch.dict(os.environ, {'TOPIC_DESIGN': ''}):
            client = Mock()
            results = send_job(job('UX Designer'), client=client)
            self.assertEqual(set(results), {'design'})
            self.assertEqual(results['design'].outcome, 'CONFIG_ERROR')
            client.send_message.assert_not_called()

    def test_previously_delivered_general_job_is_not_reposted_to_design(self):
        with tempfile.TemporaryDirectory() as tmp, connect(Path(tmp) / 'jobs.db') as conn:
            job_id, _ = upsert_job(conn, job('UX Designer'))
            from db import record_topic_send
            record_topic_send(conn, job_id, 'general', True)
            sender = Mock()
            send_pending_jobs(conn, sender=sender)
            sender.assert_not_called()
            self.assertEqual(conn.execute('SELECT send_status FROM jobs WHERE id=?', (job_id,)).fetchone()[0], 'sent')
