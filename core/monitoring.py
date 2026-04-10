"""
Run monitoring, alert triggers, and daily digest.
Sends alerts to a separate admin Telegram topic or DM.
"""

import logging
from typing import Optional
from telegram import Bot
from telegram.error import TelegramError

from core.config import ADMIN_TELEGRAM_ID, TELEGRAM_BOT_TOKEN
from core import db

log = logging.getLogger(__name__)


def _escape_html(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


async def send_admin_alert(bot: Bot, message: str) -> bool:
    """Send an alert message to the admin via DM."""
    if not ADMIN_TELEGRAM_ID:
        log.debug("No ADMIN_TELEGRAM_ID set, skipping alert")
        return False

    try:
        await bot.send_message(
            chat_id=int(ADMIN_TELEGRAM_ID),
            text=message,
            parse_mode="HTML",
        )
        return True
    except TelegramError as e:
        log.error(f"Failed to send admin alert: {e}")
        return False


async def check_alerts(bot: Bot, run_id: int) -> list[str]:
    """
    Check alert triggers after a run completes.
    Returns list of alert messages sent.
    """
    alerts = []

    try:
        run = db._fetchone("SELECT * FROM bot_runs WHERE id = %s", (run_id,))
        if not run:
            return alerts

        # Alert: zero jobs fetched (all sources failed)
        if run["jobs_fetched"] == 0:
            msg = "🚨 <b>ALERT: Zero jobs fetched</b>\nAll sources failed this run."
            await send_admin_alert(bot, msg)
            alerts.append(msg)

        # Alert: run took too long
        if run["finished_at"] and run["started_at"]:
            # Duration check via DB
            duration = db._fetchone(
                "SELECT EXTRACT(EPOCH FROM (%s - %s)) as seconds",
                (run["finished_at"], run["started_at"]),
            )
            if duration and duration["seconds"] > 300:
                msg = f"⏰ <b>ALERT: Slow run</b>\nRun took {int(duration['seconds'])}s (threshold: 300s)"
                await send_admin_alert(bot, msg)
                alerts.append(msg)

        # Alert: Telegram send success rate below 80%
        # jobs_sent     = jobs delivered to at least one topic
        # jobs_attempted = jobs we actually tried to send (from source_stats)
        stats = run.get("source_stats") or {}
        if isinstance(stats, str):
            import json as _json
            stats = _json.loads(stats)
        jobs_attempted = stats.get("_jobs_attempted", 0)
        if jobs_attempted > 0:
            success_rate = run["jobs_sent"] / jobs_attempted
            if success_rate < 0.8:
                msg = (
                    f"📉 <b>ALERT: Low send rate</b>\n"
                    f"Delivered {run['jobs_sent']}/{jobs_attempted} jobs "
                    f"({success_rate:.0%} success rate)"
                )
                await send_admin_alert(bot, msg)
                alerts.append(msg)

        # Alert: circuit breaker opened
        broken = db._fetchall(
            "SELECT source FROM source_health WHERE circuit_open_until > now()"
        )
        for row in broken:
            msg = f"⚡ <b>ALERT: Circuit breaker open</b>\nSource: {_escape_html(row['source'])}"
            await send_admin_alert(bot, msg)
            alerts.append(msg)

    except Exception as e:
        log.error(f"Alert check failed: {e}")

    return alerts


async def send_daily_digest(bot: Bot) -> bool:
    """
    Send a daily summary to the admin.
    Call this once per day (e.g. at midnight via a scheduled GitHub Actions job).
    """
    try:
        # Jobs sent today
        today_stats = db._fetchone(
            """SELECT
                 COUNT(*) as total,
                 COUNT(CASE WHEN sent_at IS NOT NULL THEN 1 END) as sent
               FROM jobs
               WHERE created_at > now() - make_interval(days := 1)"""
        )

        # Source health
        sources = db._fetchall(
            """SELECT source, consecutive_failures, circuit_open_until > now() AS is_broken
               FROM source_health
               ORDER BY consecutive_failures DESC"""
        )

        # Error count today
        errors = db._fetchone(
            """SELECT COUNT(*) as count FROM bot_runs
               WHERE started_at > now() - make_interval(days := 1)
                 AND jsonb_array_length(errors) > 0"""
        )

        lines = [
            "📊 <b>Daily Digest</b>\n",
            f"Jobs found today: {today_stats['total']}",
            f"Jobs sent today: {today_stats['sent']}",
            f"Runs with errors: {errors['count']}\n",
            "<b>Source Health:</b>",
        ]

        for s in sources:
            status = "🔴 BROKEN" if s.get("is_broken") else "🟢 OK"
            if s["consecutive_failures"] > 0:
                status = f"🟡 {s['consecutive_failures']} failures"
            lines.append(f"  {s['source']}: {status}")

        msg = "\n".join(lines)
        return await send_admin_alert(bot, msg)

    except Exception as e:
        log.error(f"Daily digest failed: {e}")
        return False
