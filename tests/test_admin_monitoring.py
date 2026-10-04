import os
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from admin_monitoring import (
    build_daily_digest,
    digest_due,
    format_event_batch,
    health_transition_event,
    mark_digest_sent,
    send_admin_message,
    sync_adapter_outage_events,
    sync_coverage_gap_event,
)
from db import connect, record_source_run_history, update_source_run
from telegram_sender import CONFIG_ERROR, SENT, TelegramSendResult


class AdminMonitoringTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 4, 18, 0, tzinfo=UTC)

    def test_health_transition_only_alerts_bad_boundary_and_recovery(self):
        self.assertIsNone(health_transition_event("linkedin", "HEALTHY", "HEALTHY"))
        degraded = health_transition_event(
            "linkedin", "HEALTHY", "DEGRADED", error="HTTP 429"
        )
        self.assertIn("HEALTHY → DEGRADED", degraded)
        self.assertIn("HTTP 429", degraded)
        recovered = health_transition_event("linkedin", "UNHEALTHY", "HEALTHY")
        self.assertIn("recovered", recovered)
        self.assertIsNone(health_transition_event("ats_x", "IDLE", "HEALTHY"))

    def test_coverage_gap_and_adapter_outage_are_suppressed_until_state_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            with connect(os.path.join(tmp, "jobs.db")) as conn:
                self.assertIn("coverage gap", sync_coverage_gap_event(conn, "linkedin", True))
                self.assertIsNone(sync_coverage_gap_event(conn, "linkedin", True))
                self.assertIn("restored", sync_coverage_gap_event(conn, "linkedin", False))

                first = sync_adapter_outage_events(conn, ["greenhouse"])
                self.assertEqual(len(first), 1)
                self.assertIn("greenhouse", first[0])
                self.assertEqual(sync_adapter_outage_events(conn, ["greenhouse"]), [])
                recovered = sync_adapter_outage_events(conn, [])
                self.assertEqual(len(recovered), 1)
                self.assertIn("recovered", recovered[0])

    def test_digest_due_is_persisted_only_after_successful_send(self):
        with tempfile.TemporaryDirectory() as tmp:
            with connect(os.path.join(tmp, "jobs.db")) as conn:
                self.assertTrue(digest_due(conn, reference_time=self.now))
                mark_digest_sent(conn, reference_time=self.now)
                conn.commit()
                self.assertFalse(
                    digest_due(conn, reference_time=self.now + timedelta(hours=23))
                )
                self.assertTrue(
                    digest_due(conn, reference_time=self.now + timedelta(hours=24))
                )

    def test_daily_digest_summarizes_source_runs_and_current_health(self):
        with tempfile.TemporaryDirectory() as tmp:
            with connect(os.path.join(tmp, "jobs.db")) as conn:
                stamp = "2026-10-04T17:45:00Z"
                update_source_run(
                    conn,
                    "linkedin",
                    "ok",
                    last_run_at=stamp,
                    raw_count=20,
                    filtered_count=10,
                    fresh_count=3,
                    health_status="HEALTHY",
                )
                update_source_run(
                    conn,
                    "linkedin_saudi_v2",
                    "ok",
                    last_run_at=stamp,
                    shadow_mode=True,
                    raw_count=12,
                    filtered_count=8,
                    fresh_count=2,
                    shadow_eligible_count=2,
                    health_status="HEALTHY",
                )
                record_source_run_history(
                    conn,
                    "linkedin",
                    run_at=stamp,
                    status="ok",
                    raw_count=20,
                    filtered_count=10,
                    fresh_count=3,
                    shadow_mode=False,
                    health_status="HEALTHY",
                )
                record_source_run_history(
                    conn,
                    "linkedin_saudi_v2",
                    run_at=stamp,
                    status="ok",
                    raw_count=12,
                    filtered_count=8,
                    fresh_count=2,
                    shadow_eligible_count=2,
                    shadow_mode=True,
                    health_status="HEALTHY",
                )
                conn.commit()

                digest = build_daily_digest(conn, reference_time=self.now)
                self.assertIn("24h Admin Digest", digest)
                self.assertIn("2 tracked", digest)
                self.assertIn("32 fetched", digest)
                self.assertIn("18 relevant", digest)
                self.assertIn("5 fresh", digest)
                self.assertIn("2 shadow candidates", digest)
                self.assertIn("Top shadow candidates", digest)
                self.assertIn("linkedin_saudi_v2: 2", digest)

    def test_send_admin_message_is_safe_when_not_configured_and_uses_private_chat(self):
        missing = send_admin_message("hello", admin_chat_id="", bot_token="token")
        self.assertFalse(missing.success)
        self.assertEqual(missing.outcome, CONFIG_ERROR)

        captured = {}

        class FakeClient:
            def __init__(self, *, bot_token, group_id):
                captured["token"] = bot_token
                captured["group_id"] = group_id

            def send_message(self, message, **kwargs):
                captured["message"] = message
                captured.update(kwargs)
                return TelegramSendResult(True, SENT, message_id=7)

        result = send_admin_message(
            "health ok",
            admin_chat_id="12345",
            bot_token="abc",
            client_factory=FakeClient,
        )
        self.assertTrue(result.success)
        self.assertEqual(captured["group_id"], "12345")
        self.assertEqual(captured["message"], "health ok")
        self.assertFalse(captured["use_html"])

    def test_event_batch_is_one_compact_message(self):
        text = format_event_batch(["one", "two"])
        self.assertIn("Job Bot Health", text)
        self.assertIn("• one", text)
        self.assertIn("• two", text)
        self.assertEqual(format_event_batch([]), "")


if __name__ == "__main__":
    unittest.main()
