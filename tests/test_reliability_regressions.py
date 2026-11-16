import logging
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

import requests
import cleanup
import main
from db import connect, upsert_job
from models import Job
from telegram_sender import TelegramClient, TelegramRateLimiter, send_job, UNKNOWN, SENT


class TransportRegressionTests(unittest.TestCase):
    def client(self, errors, retries=2):
        session = Mock()
        session.post.side_effect = errors
        return TelegramClient(bot_token='AUDIT_SECRET_123', group_id='test', session=session,
                              limiter=TelegramRateLimiter(0), max_inline_retries=retries,
                              sleeper=lambda _: None), session

    def test_post_accept_reset_is_unknown_and_never_replayed_across_runs(self):
        client, session = self.client([requests.ConnectionError('reset after acceptance')])
        with tempfile.TemporaryDirectory() as tmp, patch('telegram_sender.get_topic_thread_id', return_value=1):
            with connect(Path(tmp) / 'jobs.db') as conn:
                upsert_job(conn, Job('Backend Developer', 'Acme', 'Cairo', 'https://example.test/1', 'linkedin'))
                sender = lambda job, topics: send_job(job, topics, client=client)
                for _ in range(2):
                    main.send_pending_jobs(conn, sender=sender, router=lambda _: ['backend'])
                self.assertEqual(session.post.call_count, 1)
                self.assertEqual(conn.execute('SELECT send_status FROM jobs').fetchone()[0], 'unknown')

    def test_only_connect_timeout_is_retried(self):
        response = Mock(status_code=200)
        response.json.return_value = {'ok': True, 'result': {'message_id': 1}}
        client, session = self.client([requests.ConnectTimeout('not connected'), response])
        self.assertEqual(client.send_message('hello').outcome, SENT)
        self.assertEqual(session.post.call_count, 2)

    def test_transport_errors_never_persist_credentials(self):
        for error_type in (requests.ReadTimeout, requests.ConnectTimeout, requests.ConnectionError,
                           requests.exceptions.ChunkedEncodingError, requests.RequestException):
            with self.subTest(error=error_type.__name__), tempfile.TemporaryDirectory() as tmp:
                client, session = self.client([error_type('https://api.telegram.org/botAUDIT_SECRET_123/sendMessage')], retries=0)
                with connect(Path(tmp) / 'jobs.db') as conn, patch('telegram_sender.get_topic_thread_id', return_value=1):
                    upsert_job(conn, Job('Backend Developer', 'Acme', 'Cairo', 'https://example.test/1', 'linkedin'))
                    with self.assertLogs('telegram_sender', logging.WARNING) as captured:
                        main.send_pending_jobs(conn, sender=lambda j, t: send_job(j, t, client=client), router=lambda _: ['backend'])
                    for table in ('job_sends', 'delivery_attempts'):
                        error = conn.execute(f'SELECT error FROM {table}').fetchone()[0]
                        self.assertNotIn('AUDIT_SECRET_123', error)
                        self.assertIn(error_type.__name__, error)
                    self.assertNotIn('AUDIT_SECRET_123', str(captured.output))

    def test_truncated_response_is_unknown(self):
        client, session = self.client([requests.exceptions.ChunkedEncodingError('response lost')])
        self.assertEqual(client.send_message('hello').outcome, UNKNOWN)
        self.assertEqual(session.post.call_count, 1)

    def test_cleanup_does_not_log_raw_exception(self):
        with patch.object(cleanup, 'TELEGRAM_BOT_TOKEN', 'AUDIT_SECRET_123'), patch.object(cleanup, 'TELEGRAM_GROUP_ID', 'test'), \
             patch.object(cleanup.requests, 'get', side_effect=requests.ConnectionError('botAUDIT_SECRET_123/getUpdates')):
            with self.assertLogs('cleanup', logging.WARNING) as captured:
                cleanup.cleanup_join_messages()
            self.assertNotIn('AUDIT_SECRET_123', str(captured.output))

    def test_http_error_description_redacts_credentials(self):
        response = Mock(status_code=400)
        response.json.return_value = {'description': 'failed /botAUDIT_SECRET_123/sendMessage'}
        client, _ = self.client([response])
        result = client.send_message('hello')
        self.assertNotIn('AUDIT_SECRET_123', result.error)
        self.assertIn('[REDACTED]', result.error)


class SnapshotRegressionTests(unittest.TestCase):
    def test_restore_failures_propagate_before_validation(self):
        from ops.sqlite_snapshot import restore_snapshot
        for effects in ([subprocess.CalledProcessError(1, 'git')], [None, subprocess.CalledProcessError(1, 'git')]):
            with self.subTest(step=len(effects)), patch('ops.sqlite_snapshot.subprocess.run', side_effect=effects) as run, \
                 patch('ops.sqlite_snapshot.verify_snapshot') as verify:
                with self.assertRaises(subprocess.CalledProcessError):
                    restore_snapshot()
                self.assertEqual(run.call_count, len(effects))
                self.assertTrue(all(c.kwargs['check'] for c in run.call_args_list))
                verify.assert_not_called()

    def test_snapshot_requires_existing_valid_bot_database(self):
        from ops.sqlite_snapshot import verify_snapshot
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'jobs.db'
            with self.assertRaises((OSError, RuntimeError, sqlite3.DatabaseError)):
                verify_snapshot(path)
            self.assertFalse(path.exists())
            path.write_bytes(b'')
            with self.assertRaises(RuntimeError):
                verify_snapshot(path)
            path.write_bytes(b'not sqlite')
            with self.assertRaises(sqlite3.DatabaseError):
                verify_snapshot(path)
            path.unlink()
            with connect(path):
                pass
            before = path.read_bytes()
            verify_snapshot(path)
            self.assertEqual(path.read_bytes(), before)

    def test_successful_restore_validates_before_return(self):
        from ops.sqlite_snapshot import restore_snapshot
        with patch('ops.sqlite_snapshot.subprocess.run') as run, patch('ops.sqlite_snapshot.verify_snapshot') as verify:
            restore_snapshot()
            self.assertEqual(run.call_count, 2)
            verify.assert_called_once_with('jobs.db')

    def test_restored_corrupt_snapshot_still_fails_restore(self):
        from ops.sqlite_snapshot import restore_snapshot
        with patch('ops.sqlite_snapshot.subprocess.run'), \
             patch('ops.sqlite_snapshot.verify_snapshot', side_effect=RuntimeError('invalid snapshot')):
            with self.assertRaises(RuntimeError):
                restore_snapshot()

    def test_unrelated_sqlite_database_is_rejected(self):
        from ops.sqlite_snapshot import verify_snapshot
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'other.db'
            with sqlite3.connect(path) as conn:
                conn.execute('CREATE TABLE unrelated (id INTEGER)')
            conn.close()
            with self.assertRaises(RuntimeError):
                verify_snapshot(path)
