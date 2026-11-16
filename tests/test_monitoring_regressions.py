import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import Mock

from admin_monitoring import (ADMIN_ACTIVE_ADAPTER_OUTAGES_KEY, build_daily_digest,
                              sync_adapter_outage_events)
from db import connect, upsert_job, record_source_observation, record_source_run_history, set_metadata, get_metadata
from freshness import iso_utc
from main import run_bot
from models import Job
from source_analytics import build_source_analytics, format_source_analytics
from source_runtime import evaluated_ats_adapters


class MatureCohortTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 16, 12, tzinfo=UTC)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.connection_context = connect(Path(self.tmp.name) / 'jobs.db')
        self.conn = self.connection_context.__enter__()
        self.addCleanup(self.connection_context.__exit__, None, None, None)
        set_metadata(self.conn, 'source_analytics_started_at', iso_utc(self.now - timedelta(days=7)))

    def observation(self, suffix, age, other_delay=None, location='Riyadh, Saudi Arabia', tracked=True):
        job_id, _ = upsert_job(self.conn, Job('Backend Developer', 'Acme', location,
                                            f'https://example.test/{suffix}', 'linkedin_saudi_v2'))
        seen = self.now - timedelta(hours=age)
        record_source_observation(self.conn, job_id, 'linkedin_saudi_v2', observed_at=iso_utc(seen), was_new_job=tracked)
        if other_delay is not None:
            record_source_observation(self.conn, job_id, 'linkedin',
                                      observed_at=iso_utc(seen + timedelta(hours=other_delay)))

    def report(self, **kwargs):
        return build_source_analytics(self.conn, sources=['linkedin_saudi_v2'], reference_time=self.now, **kwargs)[0]

    def test_daily_report_separates_current_activity_and_mature_discoveries(self):
        self.observation('mature', 26)
        self.observation('recent', 2)
        record_source_run_history(self.conn, 'linkedin_saudi_v2', run_at=iso_utc(self.now - timedelta(hours=2)),
                                  status='ok', raw_count=9)
        row = self.report(hours=24)
        self.assertEqual((row.discoveries, row.first_discoveries, row.raw_count), (1, 1, 9))
        self.assertEqual((row.mature_first_discoveries, row.exclusive_24h), (1, 1))
        self.assertIn('matured_in_last=24h', format_source_analytics([row])[0])
        digest = build_daily_digest(self.conn, reference_time=self.now)
        self.assertIn('exclusive 1/1', digest)
        self.assertIn('matured in the last 24h', digest)

    def test_competing_observation_at_deadline_cancels_exclusivity_but_later_does_not(self):
        self.observation('before', 30, other_delay=23)
        self.observation('boundary', 30, other_delay=24)
        self.observation('after', 30, other_delay=25)
        row = self.report(hours=24)
        self.assertEqual((row.mature_first_discoveries, row.exclusive_24h), (3, 1))
        self.assertEqual(row.discoveries, 0)
        self.assertIsNone(row.median_lead_minutes)

    def test_adjacent_daily_cohorts_do_not_repeat_the_maturity_boundary(self):
        self.observation('old_boundary', 48)
        self.observation('current_boundary', 24)
        self.observation('too_young', 23)
        row = self.report(hours=24)
        self.assertEqual((row.mature_first_discoveries, row.exclusive_24h), (1, 1))
        previous = build_source_analytics(self.conn, sources=['linkedin_saudi_v2'], hours=24,
                                         reference_time=self.now - timedelta(hours=24))[0]
        self.assertEqual((previous.mature_first_discoveries, previous.exclusive_24h), (1, 1))

    def test_geography_and_tracking_guards_apply_to_mature_cohort(self):
        self.observation('saudi', 26)
        self.observation('egypt', 26, location='Cairo, Egypt')
        self.observation('legacy', 26, tracked=False)
        row = self.report(hours=24, saudi_only=True)
        self.assertEqual((row.mature_first_discoveries, row.exclusive_24h), (1, 1))
        set_metadata(self.conn, 'source_analytics_started_at', iso_utc(self.now - timedelta(hours=12)))
        self.assertEqual(self.report(hours=24).mature_first_discoveries, 0)

    def test_custom_maturity_duration_uses_matching_cohort_and_label(self):
        self.observation('mature', 14)
        self.observation('recent', 2)
        row = self.report(hours=6, exclusive_window_hours=12)
        self.assertEqual((row.discoveries, row.mature_first_discoveries, row.exclusive_24h), (1, 1, 1))
        self.assertIn('exclusive12h=', format_source_analytics([row])[0])
        self.assertIn('matured_in_last=6h', format_source_analytics([row])[0])

    def test_same_time_competing_source_is_not_exclusive(self):
        self.observation('tie', 26, other_delay=0)
        row = self.report(hours=24)
        self.assertEqual((row.mature_first_discoveries, row.exclusive_24h), (1, 0))

    def test_future_observation_cannot_influence_current_activity_lead(self):
        self.observation('recent', 2, other_delay=5)
        row = self.report(hours=24)
        self.assertEqual(row.first_discoveries, 1)
        self.assertIsNone(row.median_lead_minutes)
        self.assertEqual(row.mature_first_discoveries, 0)


class ObservedRecoveryTests(unittest.TestCase):
    def test_single_incomplete_probe_does_not_qualify_as_recovery(self):
        for status in ('failed', 'partial', 'never'):
            with self.subTest(status=status):
                self.assertEqual(evaluated_ats_adapters({'ats_ashby_one': status}), set())
        self.assertEqual(evaluated_ats_adapters({'ats_ashby_one': 'ok'}), {'ashby'})
        self.assertEqual(evaluated_ats_adapters({'linkedin': 'ok'}), set())

    def test_unobserved_outage_survives_reconnect_without_recovery_event(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'jobs.db'
            with connect(path) as conn:
                self.assertEqual(len(sync_adapter_outage_events(conn, ['ashby'])), 1)
            with connect(path) as conn:
                self.assertEqual(sync_adapter_outage_events(conn, []), [])
                self.assertEqual(get_metadata(conn, ADMIN_ACTIVE_ADAPTER_OUTAGES_KEY), 'ashby')

    def test_only_evaluated_adapters_recover_and_repeated_events_are_suppressed(self):
        with tempfile.TemporaryDirectory() as tmp, connect(Path(tmp) / 'jobs.db') as conn:
            sync_adapter_outage_events(conn, ['ashby', 'lever'])
            self.assertEqual(sync_adapter_outage_events(conn, ['ashby', 'lever']), [])
            events = sync_adapter_outage_events(conn, [], evaluated_adapters=['lever'])
            self.assertEqual(len(events), 1)
            self.assertIn('recovered: lever', events[0])
            self.assertEqual(get_metadata(conn, ADMIN_ACTIVE_ADAPTER_OUTAGES_KEY), 'ashby')
            self.assertEqual(sync_adapter_outage_events(conn, [], evaluated_adapters=['lever']), [])

    def test_runtime_skipped_and_lone_failed_probes_preserve_outage_until_observed_success(self):
        now = datetime(2026, 11, 16, 12, tzinfo=UTC)
        one = Mock(side_effect=RuntimeError('synthetic failure'))
        two = Mock(side_effect=RuntimeError('synthetic failure'))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'jobs.db'
            def run(minutes, fetchers):
                return run_bot(db_path=str(path), fetchers=fetchers, cleanup_func=lambda: None,
                               sender=Mock(), reference_time=now + timedelta(minutes=minutes))
            def active():
                with connect(path) as conn:
                    return get_metadata(conn, ADMIN_ACTIVE_ADAPTER_OUTAGES_KEY)
            both = [('ATS Ashby one', one), ('ATS Ashby two', two)]
            self.assertEqual(run(0, both).ats_adapter_outages, 1)
            skipped = run(5, both)
            self.assertEqual(skipped.sources_skipped_not_due, 2)
            self.assertEqual(active(), 'ashby')
            self.assertEqual(skipped.ats_adapter_outages, 1)
            run(15, both[:1])
            self.assertEqual(active(), 'ashby')
            self.assertEqual(one.call_count, 2)
            self.assertEqual(two.call_count, 1)
            run(30, both)  # Continued complete failures do not recover.
            self.assertEqual(active(), 'ashby')
            one.side_effect = None
            one.return_value = []  # A complete empty ATS poll is a success.
            self.assertEqual(run(45, both[:1]).ats_adapter_outages, 0)
            self.assertEqual(active(), '')
