import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, patch

import main
import telegram_sender as tg
from db import connect, upsert_job, get_metadata
from models import Job


class Clock:
    def __init__(self):
        self.now = datetime(2026, 11, 15, 12, tzinfo=UTC)
    def __call__(self):
        return self.now
    def sleep(self, seconds):
        self.now += timedelta(seconds=seconds)
    def monotonic(self):
        return self.now.timestamp()


def response(status=200, **body):
    result = Mock(status_code=status, text='')
    result.json.return_value = body or {'ok': True, 'result': {'message_id': 1}}
    return result


class DeliveryClockTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()

    def client(self, responses, interval=0):
        session = Mock()
        session.post.side_effect = responses
        limiter = tg.TelegramRateLimiter(interval, clock=self.clock.monotonic, sleeper=self.clock.sleep)
        client = tg.TelegramClient(bot_token='synthetic', group_id='test', session=session,
                                   limiter=limiter, sleeper=self.clock.sleep)
        return client, session, limiter

    def test_expiration_during_rate_limit_wait_prevents_request(self):
        client, session, limiter = self.client([response()], interval=3)
        limiter.wait()
        result = client.send_message('job', deadline_at=self.clock() + timedelta(seconds=2), clock=self.clock)
        self.assertEqual(result.outcome, 'EXPIRED')
        session.post.assert_not_called()

    def test_expiration_exactly_at_deadline_prevents_request(self):
        client, session, _ = self.client([response()])
        result = client.send_message('job', deadline_at=self.clock(), clock=self.clock)
        self.assertEqual(result.outcome, 'EXPIRED')
        session.post.assert_not_called()

    def test_expiration_during_retry_backoff_prevents_second_request(self):
        client, session, _ = self.client([response(503, description='unavailable'), response()])
        result = client.send_message('job', deadline_at=self.clock() + timedelta(seconds=1), clock=self.clock)
        self.assertEqual(result.outcome, 'EXPIRED')
        self.assertEqual(session.post.call_count, 1)

    def test_plain_fallback_preserves_deadline(self):
        client, session, _ = self.client([response(400, description="can't parse entities"), response()], interval=3)
        result = client.send_message('job', deadline_at=self.clock() + timedelta(seconds=2), clock=self.clock)
        self.assertEqual(result.outcome, 'EXPIRED')
        self.assertEqual(session.post.call_count, 1)

    def test_accepted_response_after_deadline_remains_sent(self):
        def accept(*args, **kwargs):
            self.clock.sleep(3)
            return response()
        client, session, _ = self.client(accept)
        result = client.send_message('job', deadline_at=self.clock() + timedelta(seconds=1), clock=self.clock)
        self.assertEqual(result.outcome, tg.SENT)
        self.assertEqual(session.post.call_count, 1)

    def insert(self, conn, suffix='1', remaining=60):
        job_id, _ = upsert_job(conn, Job('Backend Developer', 'Acme', 'Cairo', 'https://example.test/'+suffix, 'linkedin'))
        first = self.clock() - timedelta(minutes=60) + timedelta(seconds=remaining)
        conn.execute('UPDATE jobs SET first_seen_at=? WHERE id=?', (first.isoformat().replace('+00:00','Z'), job_id))
        conn.commit()
        return job_id

    def test_queue_persists_expiration_from_real_sender_wait(self):
        client, session, limiter = self.client([response()], interval=3)
        limiter.wait()
        with tempfile.TemporaryDirectory() as tmp, connect(Path(tmp)/'jobs.db') as conn, \
             patch.object(tg, 'get_topic_thread_id', return_value=1), \
             patch.object(tg._DEFAULT_CLIENT, 'bot_token', client.bot_token), \
             patch.object(tg._DEFAULT_CLIENT, 'group_id', client.group_id), \
             patch.object(tg._DEFAULT_CLIENT, 'session', session), \
             patch.object(tg._DEFAULT_CLIENT, 'limiter', limiter):
            self.insert(conn, remaining=2)
            main.send_pending_jobs(conn, clock=self.clock)
            session.post.assert_not_called()
            self.assertEqual(conn.execute('SELECT send_status FROM jobs').fetchone()[0], 'expired')
            self.assertEqual(conn.execute('SELECT status FROM job_sends').fetchone()[0], 'expired')
            main.send_pending_jobs(conn, clock=self.clock)
            session.post.assert_not_called()

    def test_retry_after_uses_response_time_and_survives_reconnect(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'jobs.db'
            def sender(job, topics):
                self.clock.sleep(180)
                return {topics[0]: tg.TelegramSendResult(False, tg.RATE_LIMITED, retry_after_s=60)}
            with connect(path) as conn:
                self.insert(conn, remaining=3600)
                main.send_pending_jobs(conn, sender=sender, clock=self.clock)
                self.assertEqual(get_metadata(conn, main.TELEGRAM_BLOCKED_UNTIL_KEY), '2026-11-15T12:04:00Z')
                self.assertEqual(conn.execute('SELECT next_attempt_at FROM job_sends').fetchone()[0], '2026-11-15T12:04:00Z')
            with connect(path) as conn:
                retry = Mock(return_value={'backend': True})
                main.send_pending_jobs(conn, sender=retry, clock=self.clock)
                retry.assert_not_called()
                self.clock.sleep(60)
                main.send_pending_jobs(conn, sender=retry, clock=self.clock)
                retry.assert_called_once()

    def test_later_queue_item_expires_while_previous_send_runs(self):
        with tempfile.TemporaryDirectory() as tmp, connect(Path(tmp)/'jobs.db') as conn:
            self.insert(conn, 'older', remaining=1)
            self.insert(conn, 'newer', remaining=30)
            calls = []
            def sender(job, topics):
                calls.append(job.url)
                self.clock.sleep(2)
                return {topics[0]: True}
            main.send_pending_jobs(conn, sender=sender, clock=self.clock)
            self.assertEqual(calls, ['https://example.test/newer'])
            self.assertEqual(conn.execute("SELECT send_status FROM jobs WHERE url LIKE '%older'").fetchone()[0], 'expired')

    def test_fetch_delay_does_not_freeze_production_delivery_clock(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'jobs.db'
            with connect(path) as conn:
                self.insert(conn, remaining=1)
            def fetch():
                self.clock.sleep(3)
                return []
            sender = Mock(return_value={'backend': True})
            with patch.object(main, 'datetime', wraps=datetime) as dates, \
                 patch.object(main, 'utc_now', self.clock):
                dates.now.side_effect = lambda tz: self.clock()
                main.run_bot(db_path=str(path), fetchers=[('LinkedIn', fetch)], sender=sender,
                             cleanup_func=lambda: None)
            sender.assert_not_called()

    def test_fractional_response_time_rounds_cooldown_up(self):
        self.clock.now = self.clock.now.replace(microsecond=900000)
        with tempfile.TemporaryDirectory() as tmp, connect(Path(tmp)/'jobs.db') as conn:
            self.insert(conn, remaining=3600)
            sender = lambda j, t: {t[0]: tg.TelegramSendResult(False, tg.RATE_LIMITED, retry_after_s=60)}
            main.send_pending_jobs(conn, sender=sender, clock=self.clock)
            self.assertEqual(get_metadata(conn, main.TELEGRAM_BLOCKED_UNTIL_KEY), '2026-11-15T12:01:01Z')
            self.assertEqual(conn.execute('SELECT next_attempt_at FROM job_sends').fetchone()[0], '2026-11-15T12:01:01Z')

    def test_wait_that_finishes_before_deadline_still_sends(self):
        client, session, limiter = self.client([response()], interval=3)
        limiter.wait()
        result = client.send_message('job', deadline_at=self.clock() + timedelta(seconds=4), clock=self.clock)
        self.assertEqual(result.outcome, tg.SENT)
        session.post.assert_called_once()
