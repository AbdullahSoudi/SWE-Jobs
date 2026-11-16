"""Telegram formatting, routing, and resilient delivery.

The sender owns Telegram-specific rate limiting and error classification.  It
returns structured results so the persistence layer can decide whether a
failed delivery is retryable, permanent, rate-limited, or ambiguous.
"""

from __future__ import annotations

import html
import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Callable

import requests
from telegram_errors import redact_telegram_error, transport_error
from freshness import ensure_utc, utc_now

from models import Job
from classifier import classify_job
from locations import normalize_location, saudi_location_hashtags
from eligibility import SAUDI_ONLY, EXPLICITLY_OPEN, NOT_SPECIFIED
from config import (
    CHANNELS,
    PRIMARY_TOPIC_ORDER,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_GROUP_ID,
    TELEGRAM_MAX_INLINE_RETRIES,
    TELEGRAM_REQUEST_TIMEOUT_SECONDS,
    TELEGRAM_SEND_DELAY,
    get_topic_thread_id,
)

log = logging.getLogger(__name__)

SENT = "SENT"
RATE_LIMITED = "RATE_LIMITED"
RETRYABLE = "RETRYABLE"
NON_RETRYABLE = "NON_RETRYABLE"
CONFIG_ERROR = "CONFIG_ERROR"
UNKNOWN = "UNKNOWN"
EXPIRED = "EXPIRED"


@dataclass(frozen=True)
class TelegramSendResult:
    success: bool
    outcome: str
    error: str = ""
    http_status: int | None = None
    tg_error_code: int | None = None
    retry_after_s: int | None = None
    message_id: int | None = None
    fallback_used: bool = False

    def __bool__(self) -> bool:  # convenient for callers/tests
        return self.success


class TelegramRateLimiter:
    """Simple process-local per-chat limiter.

    Telegram topics share the same supergroup budget, so limiting must happen
    before every sendMessage request rather than once per job.
    """

    def __init__(
        self,
        min_interval_seconds: float,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self.min_interval_seconds = max(0.0, float(min_interval_seconds))
        self._clock = clock
        self._sleeper = sleeper
        self._last_send_at: float | None = None

    def wait(self) -> None:
        now = self._clock()
        if self._last_send_at is not None:
            remaining = self.min_interval_seconds - (now - self._last_send_at)
            if remaining > 0:
                self._sleeper(remaining)
                now = self._clock()
        self._last_send_at = now


# One limiter for the one Telegram supergroup used by this process.
_RATE_LIMITER = TelegramRateLimiter(TELEGRAM_SEND_DELAY)


# ─── Topic Routing ────────────────────────────────────────────

def _match_keywords(text: str, keywords: list[str]) -> bool:
    text_lower = text.lower()
    return any(kw.lower() in text_lower for kw in keywords)


def _is_egypt_job(job: Job) -> bool:
    return normalize_location(job.location).country_code == "EG"


def _is_saudi_job(job: Job) -> bool:
    return normalize_location(job.location).country_code == "SA"


def route_job(job: Job) -> list[str]:
    """Return exactly one measured primary topic for a relevant tech job."""
    result = classify_job(job)
    return [result.topic] if result.is_tech and result.topic else []


# ─── Message Formatting ──────────────────────────────────────

def _market_hashtags(job: Job) -> list[str]:
    tags: list[str] = saudi_location_hashtags(job.location)
    if not tags and _is_egypt_job(job):
        tags.append("#Egypt")

    if _is_saudi_job(job):
        if job.eligibility == SAUDI_ONLY:
            tags.append("#SaudiOnly")
        elif job.eligibility == EXPLICITLY_OPEN:
            tags.append("#OpenEligibility")

    location = (job.location or "").lower()
    if job.is_remote or "remote" in location or "عن بعد" in location:
        tags.append("#Remote")
    return tags


def format_job_message(job: Job) -> str:
    emoji = job.emoji
    title = _escape_html(job.title)
    company = _escape_html(job.company) if job.company else "Unknown"
    location = _escape_html(job.location) if job.location else "Not specified"
    discovery_source = _escape_html(job.discovery_source_display)
    apply_source = _escape_html(job.apply_source_display)

    lines = [
        f"{emoji} <b>{title}</b>",
        f"🏢 {company}",
        f"📍 {location}",
    ]

    if job.salary:
        lines.append(f"💰 {_escape_html(job.salary)}")
    if job.job_type:
        lines.append(f"📋 {_escape_html(job.job_type)}")
    if job.is_remote:
        lines.append("🌍 Remote")

    if _is_saudi_job(job):
        if job.eligibility == SAUDI_ONLY:
            lines.append("🇸🇦 Eligibility: Saudi nationals only (stated)")
        elif job.eligibility == EXPLICITLY_OPEN:
            lines.append("🌍 Eligibility: Explicitly open to non-Saudis (stated)")
        else:
            lines.append("👤 Eligibility: Not specified")

    lines.append("")
    apply_label = "Apply on official careers" if job.apply_is_official else "Apply Now"
    lines.append(f'🔗 <a href="{_escape_html(job.url, quote=True)}">{apply_label}</a>')

    apply_key = (job.apply_source_key or job.source or "").strip().lower()
    discovery_key = (job.source or "").strip().lower()
    if job.apply_is_official and apply_key != discovery_key:
        lines.append(f"📡 Discovered via: {discovery_source} · Apply: {apply_source} (official)")
    elif job.apply_is_official:
        lines.append(f"📡 Source: {apply_source} (official)")
    else:
        lines.append(f"📡 Source: {apply_source}")

    market_tags = _market_hashtags(job)
    if market_tags:
        lines.append(" ".join(market_tags))

    return "\n".join(lines)


def _plain_text_fallback(message: str, limit: int = 4000) -> str:
    """Convert our small HTML subset to safe plain text and keep under limit."""
    text = re.sub(r"<a\s+href=\"([^\"]*)\">([^<]*)</a>", r"\2: \1", message)
    text = re.sub(r"</?b>", "", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    return text[:limit]


# ─── Sending ─────────────────────────────────────────────────

def _telegram_body(resp: requests.Response) -> dict:
    try:
        body = resp.json()
        return body if isinstance(body, dict) else {}
    except (ValueError, TypeError):
        return {}


def _error_result(resp: requests.Response, bot_token: str = "") -> TelegramSendResult:
    body = _telegram_body(resp)
    error_code = body.get("error_code")
    description = redact_telegram_error(
        str(body.get("description") or resp.text or "Telegram request failed"), bot_token
    )
    parameters = body.get("parameters") or {}
    retry_after = parameters.get("retry_after")
    try:
        retry_after = int(retry_after) if retry_after is not None else None
    except (TypeError, ValueError):
        retry_after = None

    status = int(resp.status_code)
    description_lower = description.lower()

    if status == 429 or error_code == 429:
        outcome = RATE_LIMITED
    elif status >= 500:
        outcome = RETRYABLE
    elif status in (401, 403):
        outcome = CONFIG_ERROR
    elif status == 400 and any(
        marker in description_lower
        for marker in (
            "message thread not found",
            "chat not found",
            "bot was kicked",
            "not enough rights",
        )
    ):
        outcome = CONFIG_ERROR
    else:
        outcome = NON_RETRYABLE

    return TelegramSendResult(
        success=False,
        outcome=outcome,
        error=description,
        http_status=status,
        tg_error_code=int(error_code) if isinstance(error_code, int) else None,
        retry_after_s=retry_after,
    )


class TelegramClient:
    def __init__(
        self,
        *,
        bot_token: str = TELEGRAM_BOT_TOKEN,
        group_id: str = TELEGRAM_GROUP_ID,
        session=requests,
        limiter: TelegramRateLimiter = _RATE_LIMITER,
        timeout_seconds: float = TELEGRAM_REQUEST_TIMEOUT_SECONDS,
        max_inline_retries: int = TELEGRAM_MAX_INLINE_RETRIES,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self.bot_token = bot_token
        self.group_id = group_id
        self.session = session
        self.limiter = limiter
        self.timeout_seconds = timeout_seconds
        self.max_inline_retries = max(0, int(max_inline_retries))
        self.sleeper = sleeper

    @property
    def api_url(self) -> str:
        return f"https://api.telegram.org/bot{self.bot_token}/sendMessage"

    def send_message(
        self,
        message: str,
        thread_id: int | None = None,
        *,
        allow_plain_fallback: bool = True,
        use_html: bool = True,
        deadline_at: datetime | None = None,
        clock: Callable[[], datetime] = utc_now,
    ) -> TelegramSendResult:
        if not self.bot_token or not self.group_id:
            return TelegramSendResult(False, CONFIG_ERROR, "Telegram bot token/group ID is not configured")

        payload = {
            "chat_id": self.group_id,
            "text": message,
            "disable_web_page_preview": True,
        }
        if use_html:
            payload["parse_mode"] = "HTML"
        if thread_id is not None:
            payload["message_thread_id"] = thread_id

        retry_number = 0
        while True:
            if deadline_at is not None and ensure_utc(clock()) >= ensure_utc(deadline_at):
                return TelegramSendResult(False, EXPIRED, "send_queue_deadline_exceeded")
            self.limiter.wait()
            # A limiter wait, inline backoff, or recursive plain-text fallback
            # must never allow another request once the queue budget is over.
            if deadline_at is not None and ensure_utc(clock()) >= ensure_utc(deadline_at):
                return TelegramSendResult(False, EXPIRED, "send_queue_deadline_exceeded")
            try:
                resp = self.session.post(self.api_url, json=payload, timeout=self.timeout_seconds)
            except requests.ReadTimeout as exc:
                # Telegram may have accepted the request before the response was lost.
                return TelegramSendResult(False, UNKNOWN, transport_error(exc))
            except requests.ConnectTimeout as exc:
                # ConnectTimeout specifically establishes that no connection was
                # made. Generic ConnectionError may happen after acceptance.
                result = TelegramSendResult(False, RETRYABLE, transport_error(exc))
            except requests.RequestException as exc:
                return TelegramSendResult(False, UNKNOWN, transport_error(exc))
            else:
                if resp.status_code == 200:
                    body = _telegram_body(resp)
                    message_id = None
                    if isinstance(body.get("result"), dict):
                        raw_id = body["result"].get("message_id")
                        message_id = int(raw_id) if isinstance(raw_id, int) else None
                    return TelegramSendResult(True, SENT, http_status=200, message_id=message_id)
                result = _error_result(resp, self.bot_token)

                if result.outcome == NON_RETRYABLE and allow_plain_fallback:
                    description = result.error.lower()
                    if "parse entities" in description or "message is too long" in description:
                        fallback = _plain_text_fallback(message)
                        fallback_result = self.send_message(
                            fallback,
                            thread_id,
                            allow_plain_fallback=False,
                            use_html=False,
                            deadline_at=deadline_at,
                            clock=clock,
                        )
                        return TelegramSendResult(
                            fallback_result.success,
                            fallback_result.outcome,
                            fallback_result.error,
                            fallback_result.http_status,
                            fallback_result.tg_error_code,
                            fallback_result.retry_after_s,
                            fallback_result.message_id,
                            fallback_used=True,
                        )

            # 429 must be deferred using Telegram's explicit retry_after.  UNKNOWN
            # is deliberately not retried because doing so may duplicate a message.
            if result.outcome in (RATE_LIMITED, UNKNOWN, NON_RETRYABLE, CONFIG_ERROR):
                return result

            if retry_number >= self.max_inline_retries:
                return result

            retry_number += 1
            self.sleeper(2 ** retry_number)


_DEFAULT_CLIENT = TelegramClient()


def _send_to_topic(
    message: str,
    thread_id: int | None = None,
    *,
    client: TelegramClient = _DEFAULT_CLIENT,
    deadline_at: datetime | None = None,
    clock: Callable[[], datetime] = utc_now,
) -> TelegramSendResult:
    if deadline_at is None:
        return client.send_message(message, thread_id)
    return client.send_message(message, thread_id, deadline_at=deadline_at, clock=clock)


def send_job(
    job: Job,
    target_topics: list[str] | None = None,
    *,
    client: TelegramClient = _DEFAULT_CLIENT,
    deadline_at: datetime | None = None,
    clock: Callable[[], datetime] = utc_now,
) -> dict[str, TelegramSendResult]:
    """Route and send a job, returning a structured result per attempted topic.

    When Telegram rate-limits the chat, no further topic attempts are made in
    this call.  The runtime also stops the wider queue for that run.
    """
    if target_topics is None:
        target_topics = route_job(job)
    results: dict[str, TelegramSendResult] = {}

    if not target_topics:
        log.debug("No matching topics for: %s", job.title)
        return results

    message = format_job_message(job)

    for topic_key in target_topics:
        thread_id = get_topic_thread_id(topic_key)
        topic_name = CHANNELS.get(topic_key, {}).get("name", topic_key)
        if thread_id is None:
            result = TelegramSendResult(False, CONFIG_ERROR, f"Topic is not configured: {topic_key}")
        else:
            if deadline_at is None:
                result = _send_to_topic(message, thread_id, client=client)
            else:
                result = _send_to_topic(message, thread_id, client=client, deadline_at=deadline_at, clock=clock)

        results[topic_key] = result

        if result.success:
            log.info("  ✓ Sent to %s: %s", topic_name, job.title)
        else:
            log.warning("  ✗ %s %s: %s", result.outcome, topic_name, result.error or job.title)

        if result.outcome == RATE_LIMITED:
            break

    return results


def send_jobs(jobs: list[Job]) -> int:
    """Compatibility helper. Runtime persistence uses send_job directly."""
    total_sent = 0
    for job in jobs:
        results = send_job(job)
        total_sent += sum(1 for result in results.values() if result.success)
        if any(result.outcome == RATE_LIMITED for result in results.values()):
            break
    return total_sent


def _escape_html(text, *, quote: bool = False) -> str:
    if text is None:
        return ""
    if isinstance(text, list):
        text = ", ".join(str(t) for t in text)
    return html.escape(str(text), quote=quote)
