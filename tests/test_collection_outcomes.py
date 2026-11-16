import tempfile
import unittest
import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, patch

import requests
from db import (connect, get_source_state, get_metadata, update_source_run, record_source_run_history,
                mark_source_baselined, upsert_job)
from models import Job
from main import fetch_all_jobs, run_bot
from sources.linkedin import fetch_linkedin
from sources.linkedin_saudi_v2 import fetch_linkedin_saudi_v2
from sources.jobzaty import fetch_jobzaty
from sources.http_utils import get_text


LINKEDIN = '''<li><a href="/jobs/view/backend-1234567890"></a>
<h3 class="base-search-card__title">Backend Developer</h3>
<h4 class="base-search-card__subtitle">Acme</h4>
<span class="job-search-card__location">Cairo, Egypt</span></li>'''
JOBZATY = '<a href="/job/backend-123">مطور باك اند</a><div>Acme</div><span>الرياض</span>'
SEARCHES = [{'keywords': 'backend'}, {'keywords': 'frontend'}]
FEEDS = [('https://example.test/one', 'تقنية المعلومات'), ('https://example.test/two', 'تقنية المعلومات')]


def linkedin(pages):
    return fetch_linkedin(searches=SEARCHES, request_delay=0, http_getter=Mock(side_effect=pages))


def jobzaty(pages):
    return fetch_jobzaty(category_feeds=FEEDS, http_getter=Mock(side_effect=pages))


class CollectionOutcomeTests(unittest.TestCase):
    def test_http_helper_distinguishes_transport_failure_from_empty_body(self):
        response = Mock(text='')
        response.raise_for_status.return_value = None
        with patch('sources.http_utils._session.get', return_value=response):
            self.assertEqual(get_text('https://example.test/jobs'), '')
        with patch('sources.http_utils._session.get', side_effect=requests.Timeout('synthetic')):
            self.assertIsNone(get_text('https://example.test/jobs'))

    def test_total_failure_is_not_success_for_either_adapter(self):
        for name, collect in (('linkedin', linkedin), ('jobzaty', jobzaty)):
            with self.subTest(source=name):
                jobs, metrics = fetch_all_jobs(None, [(name, lambda: collect([None, None]))])
                self.assertEqual(jobs, [])
                self.assertEqual(metrics[name].status, 'failed')
                self.assertEqual(metrics[name].pages_attempted, 2)
                self.assertEqual(metrics[name].pages_failed, 2)

    def test_partial_pages_keep_jobs_and_failure_counts(self):
        for name, collect, page in (('linkedin', linkedin, LINKEDIN), ('jobzaty', jobzaty, JOBZATY)):
            with self.subTest(source=name):
                jobs, metrics = fetch_all_jobs(None, [(name, lambda: collect([page, None]))])
                self.assertEqual(len(jobs), 1)
                self.assertEqual(metrics[name].status, 'partial')
                self.assertEqual(metrics[name].pages_succeeded, 1)
                self.assertEqual(metrics[name].pages_failed, 1)
                self.assertIn('page=2', metrics[name].error)

    def test_raised_transport_failure_does_not_discard_other_pages(self):
        for collect, page in ((linkedin, LINKEDIN), (jobzaty, JOBZATY)):
            with self.subTest(collect=collect.__name__):
                result = collect([requests.Timeout('synthetic request failed'), page])
                self.assertEqual(len(result), 1)
                self.assertEqual(result.status, 'partial')
                self.assertEqual(result.pages_attempted, 2)

    def test_login_challenge_and_unrecognized_html_are_failures(self):
        for collect in (linkedin, jobzaty):
            for page in ('<html><form><input type="password"></form></html>',
                         '<html><title>Security verification</title>CAPTCHA</html>',
                         '<html><h1>Unexpected page layout</h1></html>'):
                with self.subTest(collect=collect.__name__, page=page):
                    self.assertEqual(collect([page, page]).status, 'failed')

    def test_legitimate_empty_pages_are_successful(self):
        for collect, page in ((linkedin, ''), (linkedin, '<ul></ul>'),
                              (linkedin, '<p>No matching jobs found</p>'),
                              (jobzaty, '<p>لا توجد وظائف</p>')):
            with self.subTest(collect=collect.__name__, page=page):
                result = collect([page, page])
                self.assertEqual(len(result), 0)
                self.assertEqual(result.status, 'ok')
                self.assertEqual(result.pages_succeeded, 2)

    def test_all_filtered_closed_cards_still_count_as_valid_pages(self):
        result = linkedin([LINKEDIN.replace('</li>', '<span>Closed</span></li>')] * 2)
        self.assertEqual(len(result), 0)
        self.assertEqual(result.status, 'ok')

    def test_malformed_card_exposes_partial_schema_failure_and_keeps_valid_job(self):
        result = linkedin([LINKEDIN + '<li><h3 class="base-search-card__title">Broken</h3></li>', None])
        self.assertEqual(len(result), 1)
        self.assertEqual(result.status, 'partial')
        self.assertEqual(result.pages_failed, 2)

    def test_v2_preserves_outcome_when_relabelling_jobs(self):
        result = fetch_linkedin_saudi_v2(searches=SEARCHES, max_pages_per_search=1,
                                        request_delay=0, http_getter=Mock(side_effect=[LINKEDIN, None]))
        self.assertEqual(result[0].source, 'linkedin_saudi_v2')
        self.assertEqual(result.status, 'partial')

    def test_jobzaty_malformed_card_keeps_other_jobs_and_exposes_failure(self):
        result = jobzaty([JOBZATY + '<a href="/job/broken"></a>', None])
        self.assertEqual(len(result), 1)
        self.assertEqual(result.status, 'partial')
        self.assertEqual(result.pages_failed, 2)

    def test_invalid_required_fields_do_not_look_like_valid_empty_pages(self):
        for collect, page in ((linkedin, LINKEDIN.replace('Backend Developer', '<span></span>')),
                              (jobzaty, '<a href="/job/?query=1">Backend Developer</a>')):
            with self.subTest(collect=collect.__name__):
                result = collect([page, page])
                self.assertEqual(len(result), 0)
                self.assertEqual(result.status, 'failed')

    def test_empty_notice_in_script_cannot_establish_success(self):
        for collect in (linkedin, jobzaty):
            with self.subTest(collect=collect.__name__):
                page = '<html><script>"<p>No jobs found</p>"</script></html>'
                self.assertEqual(collect([page, page]).status, 'failed')

    def test_none_return_is_not_a_successful_empty_legacy_fetch(self):
        _, metrics = fetch_all_jobs(None, [('Broken', lambda: None), ('Quiet', lambda: [])])
        self.assertEqual(metrics['broken'].status, 'failed')
        self.assertEqual(metrics['quiet'].status, 'ok')


class CollectionStateTests(unittest.TestCase):
    def test_v10_migration_preserves_existing_state_and_unknown_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'jobs.db'
            with connect(path) as conn:
                job_id, _ = upsert_job(conn, Job('Backend Developer', 'Acme', 'Cairo',
                                                'https://example.test/1', 'linkedin'))
                conn.execute("UPDATE jobs SET send_status='sent' WHERE id=?", (job_id,))
                update_source_run(conn, 'linkedin', 'ok', last_run_at='2026-11-15T10:00:00Z')
                mark_source_baselined(conn, 'linkedin', baselined_at='2026-11-15T10:00:00Z')
                record_source_run_history(conn, 'linkedin', run_at='2026-11-15T10:00:00Z', status='ok')
            # Reconstruct v10 by removing only the new additive columns.
            with closing(sqlite3.connect(path)) as raw:
                for counter in ('pages_attempted', 'pages_succeeded', 'pages_failed'):
                    raw.execute(f'ALTER TABLE source_runs DROP COLUMN last_{counter}')
                    raw.execute(f'ALTER TABLE source_run_history DROP COLUMN {counter}')
                raw.execute("UPDATE metadata SET value='10' WHERE key='schema_version'")
                raw.commit()
            for _ in range(2):  # Migration must be safe on reconnect too.
                with connect(path) as conn:
                    self.assertEqual(get_metadata(conn, 'schema_version'), '11')
                    state = get_source_state(conn, 'linkedin')
                    self.assertEqual(state['last_success_at'], '2026-11-15T10:00:00Z')
                    self.assertEqual(state['baselined_at'], '2026-11-15T10:00:00Z')
                    self.assertIsNone(state['last_pages_attempted'])
                    self.assertIsNone(conn.execute('SELECT pages_failed FROM source_run_history').fetchone()[0])
                    self.assertEqual(conn.execute('SELECT send_status FROM jobs WHERE id=?', (job_id,)).fetchone()[0], 'sent')

    def test_multiple_runs_preserve_baseline_success_and_partial_evidence(self):
        start = datetime(2026, 11, 15, 12, tzinfo=UTC)
        sender = Mock(side_effect=lambda job, topics: {topics[0]: True})
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'jobs.db'
            def run(step, pages):
                return run_bot(db_path=str(path), fetchers=[('LinkedIn', lambda: linkedin(pages)),
                               ('Other', lambda: [])], sender=sender, cleanup_func=lambda: None,
                               reference_time=start + timedelta(hours=step),
                               source_poll_intervals={'linkedin': 60})
            def state():
                with connect(path) as conn:
                    return dict(get_source_state(conn, 'linkedin'))

            first = run(0, [None, None])
            self.assertEqual(first.source_failures, 1)
            self.assertEqual(first.sources_baselined, 1)  # Other source still completes.
            self.assertIsNone(state()['last_success_at'])
            self.assertIsNone(state()['baselined_at'])
            run(1, [LINKEDIN, None])
            partial = state()
            self.assertEqual(partial['status'], 'partial')
            self.assertEqual(partial['consecutive_failures'], 2)
            self.assertEqual(partial['next_poll_at'], '2026-11-15T13:15:00Z')
            self.assertIsNone(partial['last_success_at'])
            self.assertIsNone(partial['baselined_at'])
            self.assertEqual(partial['last_nonempty_at'], '2026-11-15T13:00:00Z')
            sender.assert_not_called()

            complete = run(2, ['', ''])
            self.assertEqual(complete.sources_baselined, 1)
            self.assertEqual(state()['last_success_at'], '2026-11-15T14:00:00Z')
            self.assertEqual(state()['next_poll_at'], '2026-11-15T15:00:00Z')
            run(3, [LINKEDIN.replace('1234567890', '1234567891'), None])
            sender.assert_called_once()  # Usable fresh partial results from an established source.
            self.assertEqual(state()['last_success_at'], '2026-11-15T14:00:00Z')
            self.assertEqual(state()['last_pages_failed'], 1)
            run(4, [None, None])
            self.assertEqual(state()['last_success_at'], '2026-11-15T14:00:00Z')
            self.assertEqual(state()['consecutive_failures'], 2)
            run(5, ['', ''])
            self.assertEqual(state()['consecutive_failures'], 0)
            with connect(path) as conn:
                history = conn.execute("SELECT * FROM source_run_history WHERE source='linkedin' ORDER BY id").fetchall()
                self.assertEqual([row['status'] for row in history], ['failed', 'partial', 'ok', 'partial', 'failed', 'ok'])
                self.assertEqual((history[1]['pages_attempted'], history[1]['pages_succeeded'], history[1]['pages_failed']), (2, 1, 1))
                self.assertEqual(history[1]['health_status'], 'DEGRADED')
                self.assertEqual(get_metadata(conn, 'schema_version'), '11')

    def test_jobzaty_failure_cannot_baseline_discovery_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'jobs.db'
            summary = run_bot(db_path=str(path), fetchers=[('Jobzaty', lambda: jobzaty([None, None]))],
                              cleanup_func=lambda: None, sender=Mock(),
                              reference_time=datetime(2026, 11, 15, 12, tzinfo=UTC))
            self.assertEqual(summary.source_failures, 1)
            with connect(path) as conn:
                state = get_source_state(conn, 'jobzaty')
                self.assertIsNone(state['baselined_at'])
                self.assertIsNone(state['last_success_at'])
