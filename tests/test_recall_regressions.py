"""Mandatory B07/B09/B10 examples, independent of aggregate accuracy scores."""
import unittest
from html import escape

from classifier import classify_job
from main import should_keep_job
from models import Job, passes_geo_filter
from sources.linkedin import parse_linkedin_html
from telegram_sender import route_job


def card(*, title='Backend Developer', company='Acme', location='London, UK',
         labels='', attrs='', url='https://www.linkedin.com/jobs/view/1234567890'):
    return f'''<li><div class="base-card" {attrs}>
      <a href="{escape(url, quote=True)}"></a>
      <h3 class="base-search-card__title">{escape(title)}</h3>
      <h4 class="base-search-card__subtitle"><a>{escape(company)}</a></h4>
      <span class="job-search-card__location">{escape(location)}</span>
      {labels}<time>5 minutes ago</time></div></li>'''


class MandatorySoftwareTitleTests(unittest.TestCase):
    def test_software_titles_survive_active_filter_and_route_once(self):
        for title in ('Software Development Engineer', 'Senior Software Development Engineer',
                      'Firmware Engineer', 'Database Engineer', 'C++ Engineer'):
            with self.subTest(title=title):
                job = Job(title, 'Acme', 'Cairo, Egypt', 'https://example.test/job', 'linkedin')
                self.assertTrue(should_keep_job(job))
                self.assertEqual(classify_job(job).topic, 'general')
                self.assertEqual(route_job(job), ['general'])

    def test_graduates_route_after_technical_validation(self):
        for title, expected in (('Graduate Software Engineer', ['internships']),
                                ('Graduate Backend Engineer', ['internships']),
                                ('Graduate Firmware Engineer', ['internships']),
                                ('Graduate Marketing Coordinator', []),
                                ('Graduate Civil Engineer', [])):
            with self.subTest(title=title):
                job = Job(title, 'Acme', 'Cairo, Egypt', 'https://example.test/job', 'linkedin')
                self.assertEqual(route_job(job), expected)


class LinkedInFieldEvidenceTests(unittest.TestCase):
    def parse_one(self, **kwargs):
        jobs = parse_linkedin_html(card(**kwargs))
        self.assertEqual(len(jobs), 1)
        return jobs[0]

    def test_company_names_never_close_jobs(self):
        for company in ('Undisclosed', 'ClosedLoop', 'Closed', 'Expired',
                        'No longer accepting applications'):
            with self.subTest(company=company):
                self.parse_one(company=company)

    def test_title_or_attributes_never_close_jobs(self):
        self.parse_one(title='Closed Loop Software Engineer', attrs='data-status="closed"')
        self.parse_one(title='No longer accepting applications')

    def test_visible_complete_status_labels_still_close_jobs(self):
        for label in ('No longer accepting applications', 'This job is no longer accepting applications',
                      'Job is no longer available', 'Closed', 'Expired',
                      'No longer <strong>accepting applications</strong>'):
            with self.subTest(label=label):
                self.assertEqual(parse_linkedin_html(card(labels=f'<span>{label}</span>')), [])

    def test_hidden_status_text_is_ignored(self):
        for markup in ('<span hidden>Closed</span>', '<span aria-hidden="true">Expired</span>',
                       '<script>Closed</script>', '<span style="display: none">Closed</span>'):
            with self.subTest(markup=markup):
                self.parse_one(labels=markup)

    def test_employers_do_not_set_remote_or_workplace_tags(self):
        for company in ('RemotePass', 'Remote', 'Worldwide', 'Anywhere', 'Hybrid', 'Internship'):
            with self.subTest(company=company):
                job = self.parse_one(company=company, labels='<span>On-site</span>')
                self.assertFalse(job.is_remote)
                self.assertEqual(job.job_type, 'On-site')
                self.assertEqual(job.tags, ['On-site'])
                self.assertFalse(passes_geo_filter(job))

    def test_urls_attributes_and_hidden_text_do_not_set_remote(self):
        job = self.parse_one(url='https://www.linkedin.com/jobs/view/remote-at-x-1234567890',
                             attrs='data-workplace="remote" title="Remote"',
                             labels='<span hidden>Remote</span><span aria-hidden="true">Remote</span>')
        self.assertFalse(job.is_remote)
        self.assertNotIn('Remote', job.tags)
        self.assertFalse(passes_geo_filter(job))

    def test_explicit_remote_fields_and_badges_survive(self):
        for fields in ({'location': 'Remote'}, {'title': 'Backend Developer (Remote)'},
                       {'title': 'Hybrid Cloud Engineer (Remote)'},
                       {'labels': '<span>Remote</span>'},
                       {'labels': '<span>Work <b>from home</b></span>'}):
            with self.subTest(fields=fields):
                job = self.parse_one(**fields)
                self.assertTrue(job.is_remote)
                self.assertIn('Remote', job.tags)
                self.assertTrue(passes_geo_filter(job))

    def test_remote_query_is_supported_without_an_explicit_conflict(self):
        job = parse_linkedin_html(card(), {'f_WT': '2'})[0]
        self.assertTrue(job.is_remote)

    def test_explicit_onsite_or_hybrid_wins_over_remote_query_and_title(self):
        for workplace in ('On-site', 'Hybrid'):
            with self.subTest(workplace=workplace):
                with self.assertLogs('sources.linkedin', level='WARNING') as logs:
                    job = parse_linkedin_html(card(title='Backend Developer (Remote)',
                                                    labels=f'<span>{workplace}</span>'), {'f_WT': '2'})[0]
                self.assertFalse(job.is_remote)
                self.assertNotIn('Remote', job.tags)
                self.assertFalse(passes_geo_filter(job))
                self.assertTrue(any('conflicting workplace' in line for line in logs.output))

    def test_missing_location_without_remote_evidence_stays_unknown(self):
        job = self.parse_one(location='')
        self.assertFalse(job.is_remote)
        self.assertFalse(passes_geo_filter(job))


if __name__ == '__main__':
    unittest.main()
