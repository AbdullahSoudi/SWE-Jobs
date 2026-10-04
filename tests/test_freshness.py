import unittest
from datetime import UTC, datetime

from freshness import (
    BASELINE,
    FALLBACK_RECENT_OBSERVATION,
    FALLBACK_SOURCE_WINDOW,
    FRESH,
    TOO_OLD,
    UNCERTAIN,
    evaluate_new_posting,
    freshness_decision,
    parse_iso_publication,
    parse_relative_publication,
)


class FreshnessEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 4, 15, 0, tzinfo=UTC)

    def test_minutes_are_stored_as_interval_not_fake_exact_timestamp(self):
        evidence = parse_relative_publication("12 minutes ago", fetched_at=self.now)
        self.assertEqual(evidence.precision, "MINUTE")
        self.assertEqual(evidence.earliest, "2026-10-04T14:47:00Z")
        self.assertEqual(evidence.latest, "2026-10-04T14:48:00Z")
        self.assertEqual(evidence.estimate, "2026-10-04T14:48:00Z")

    def test_hour_bucket_can_be_uncertain_around_cutoff(self):
        evidence = parse_relative_publication("1 hour ago", fetched_at=self.now)
        self.assertEqual(evidence.earliest, "2026-10-04T13:00:00Z")
        self.assertEqual(evidence.latest, "2026-10-04T14:00:00Z")
        self.assertEqual(freshness_decision(evidence, 90 * 60, reference_time=self.now), UNCERTAIN)

    def test_exact_iso_timestamp_can_be_proven_fresh_or_old(self):
        fresh = parse_iso_publication("2026-10-04T14:50:00Z", "10 minutes ago")
        old = parse_iso_publication("2026-10-04T12:00:00Z", "3 hours ago")
        self.assertEqual(freshness_decision(fresh, 3600, reference_time=self.now), FRESH)
        self.assertEqual(freshness_decision(old, 3600, reference_time=self.now), TOO_OLD)

    def test_missing_timestamp_is_uncertain(self):
        evidence = parse_relative_publication("", fetched_at=self.now)
        self.assertEqual(freshness_decision(evidence, 3600, reference_time=self.now), UNCERTAIN)

    def test_date_only_keeps_day_precision(self):
        evidence = parse_iso_publication("2026-10-04", "Posted today")
        self.assertEqual(evidence.precision, "DAY")
        self.assertEqual(evidence.earliest, "2026-10-04T00:00:00Z")
        self.assertEqual(evidence.latest, "2026-10-04T23:59:59Z")

    def test_invalid_max_age_is_rejected(self):
        evidence = parse_relative_publication("5 minutes ago", fetched_at=self.now)
        with self.assertRaises(ValueError):
            freshness_decision(evidence, 0, reference_time=self.now)

    def test_first_fetch_is_always_baseline_even_with_fresh_timestamp(self):
        evidence = parse_relative_publication("5 minutes ago", fetched_at=self.now)
        result = evaluate_new_posting(
            evidence,
            source_was_baselined=False,
            previous_success_at=None,
            max_age_seconds=3600,
            uncertain_fallback=FALLBACK_SOURCE_WINDOW,
            reference_time=self.now,
        )
        self.assertEqual(result.status, BASELINE)
        self.assertFalse(result.send_eligible)

    def test_fresh_timestamp_is_send_eligible_after_baseline(self):
        evidence = parse_relative_publication("5 minutes ago", fetched_at=self.now)
        result = evaluate_new_posting(
            evidence,
            source_was_baselined=True,
            previous_success_at="2026-10-04T14:45:00Z",
            max_age_seconds=3600,
            reference_time=self.now,
        )
        self.assertEqual(result.status, FRESH)
        self.assertTrue(result.send_eligible)

    def test_uncertain_timestamp_can_use_recent_observation_fallback(self):
        result = evaluate_new_posting(
            parse_relative_publication("", fetched_at=self.now),
            source_was_baselined=True,
            previous_success_at="2026-10-04T14:45:00Z",
            max_age_seconds=3600,
            uncertain_fallback=FALLBACK_RECENT_OBSERVATION,
            reference_time=self.now,
        )
        self.assertEqual(result.status, FRESH)
        self.assertEqual(result.reason, "recent_observation_after_success")
        self.assertTrue(result.send_eligible)

    def test_uncertain_fallback_is_rejected_after_coverage_gap(self):
        result = evaluate_new_posting(
            parse_relative_publication("", fetched_at=self.now),
            source_was_baselined=True,
            previous_success_at="2026-10-04T13:00:00Z",
            max_age_seconds=3600,
            uncertain_fallback=FALLBACK_SOURCE_WINDOW,
            reference_time=self.now,
        )
        self.assertEqual(result.status, UNCERTAIN)
        self.assertEqual(result.reason, "coverage_gap_too_large")
        self.assertFalse(result.send_eligible)


if __name__ == "__main__":
    unittest.main()
