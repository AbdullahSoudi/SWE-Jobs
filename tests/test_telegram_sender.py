import unittest
from unittest.mock import Mock

import requests

from telegram_sender import (
    RATE_LIMITED,
    RETRYABLE,
    SENT,
    UNKNOWN,
    TelegramClient,
    TelegramRateLimiter,
)


class FakeResponse:
    def __init__(self, status_code, body=None, text=""):
        self.status_code = status_code
        self._body = body or {}
        self.text = text

    def json(self):
        return self._body


class TelegramDeliveryTests(unittest.TestCase):
    def make_client(self, side_effects, *, retries=0, sleeps=None):
        session = Mock()
        session.post.side_effect = side_effects
        sleeps = sleeps if sleeps is not None else []
        return TelegramClient(
            bot_token="token",
            group_id="-1001",
            session=session,
            limiter=TelegramRateLimiter(0),
            max_inline_retries=retries,
            sleeper=sleeps.append,
        ), session, sleeps

    def test_429_captures_retry_after_without_blind_retry(self):
        client, session, _ = self.make_client([
            FakeResponse(
                429,
                {
                    "ok": False,
                    "error_code": 429,
                    "description": "Too Many Requests",
                    "parameters": {"retry_after": 17},
                },
            )
        ])
        result = client.send_message("hello", 10)
        self.assertFalse(result.success)
        self.assertEqual(result.outcome, RATE_LIMITED)
        self.assertEqual(result.retry_after_s, 17)
        self.assertEqual(session.post.call_count, 1)

    def test_5xx_retries_inline_then_succeeds(self):
        client, session, sleeps = self.make_client(
            [
                FakeResponse(502, {"ok": False, "description": "Bad Gateway"}),
                FakeResponse(200, {"ok": True, "result": {"message_id": 77}}),
            ],
            retries=1,
        )
        result = client.send_message("hello", 10)
        self.assertTrue(result.success)
        self.assertEqual(result.outcome, SENT)
        self.assertEqual(result.message_id, 77)
        self.assertEqual(session.post.call_count, 2)
        self.assertEqual(sleeps, [2])

    def test_read_timeout_is_unknown_and_not_retried(self):
        client, session, _ = self.make_client([requests.ReadTimeout("response lost")], retries=2)
        result = client.send_message("hello", 10)
        self.assertFalse(result.success)
        self.assertEqual(result.outcome, UNKNOWN)
        self.assertEqual(session.post.call_count, 1)

    def test_parse_error_uses_plain_text_fallback_once(self):
        client, session, _ = self.make_client([
            FakeResponse(
                400,
                {"ok": False, "error_code": 400, "description": "Bad Request: can't parse entities"},
            ),
            FakeResponse(200, {"ok": True, "result": {"message_id": 12}}),
        ])
        result = client.send_message('<b>A &amp; B</b> <a href="https://x.test">Apply</a>', 10)
        self.assertTrue(result.success)
        self.assertTrue(result.fallback_used)
        self.assertEqual(session.post.call_count, 2)
        second_payload = session.post.call_args_list[1].kwargs["json"]
        self.assertNotIn("parse_mode", second_payload)
        self.assertIn("Apply: https://x.test", second_payload["text"])

    def test_rate_limiter_enforces_minimum_interval(self):
        now = [100.0]
        slept = []

        def clock():
            return now[0]

        def sleeper(seconds):
            slept.append(seconds)
            now[0] += seconds

        limiter = TelegramRateLimiter(3.0, clock=clock, sleeper=sleeper)
        limiter.wait()
        now[0] += 1.0
        limiter.wait()
        self.assertEqual(slept, [2.0])


if __name__ == "__main__":
    unittest.main()
