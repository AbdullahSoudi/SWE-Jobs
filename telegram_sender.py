"""
Telegram message formatting and sending.
Formats job as HTML and sends to a Telegram channel via Bot API.
"""

import time
import logging
import requests
from models import Job
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHANNEL_ID, TELEGRAM_SEND_DELAY

log = logging.getLogger(__name__)

TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"


def format_job_message(job: Job) -> str:
    """Format a Job as an HTML Telegram message."""
    emoji = job.emoji
    title = _escape_html(job.title)
    company = _escape_html(job.company) if job.company else "Unknown"
    location = _escape_html(job.location) if job.location else "Not specified"
    source = _escape_html(job.display_source)

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

    lines.append("")  # blank line before link
    lines.append(f'🔗 <a href="{job.url}">Apply Now</a>')
    lines.append(f"📡 Source: {source}")

    return "\n".join(lines)


def send_job(job: Job) -> bool:
    """Send a single job to the Telegram channel. Returns True on success."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHANNEL_ID:
        log.warning("Telegram credentials not set — skipping send.")
        return False

    message = format_job_message(job)

    try:
        resp = requests.post(
            f"{TELEGRAM_API}/sendMessage",
            json={
                "chat_id": TELEGRAM_CHANNEL_ID,
                "text": message,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=10,
        )
        if resp.status_code == 200:
            log.info(f"Sent: {job.title} @ {job.company}")
            return True
        else:
            log.error(f"Telegram error {resp.status_code}: {resp.text}")
            return False
    except requests.RequestException as e:
        log.error(f"Telegram request failed: {e}")
        return False


def send_jobs(jobs: list[Job]) -> int:
    """Send multiple jobs with delay. Returns count of successfully sent."""
    sent = 0
    for i, job in enumerate(jobs):
        success = send_job(job)
        if success:
            sent += 1
        if i < len(jobs) - 1:
            time.sleep(TELEGRAM_SEND_DELAY)
    return sent


def _escape_html(text: str) -> str:
    """Escape HTML special characters for Telegram."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
