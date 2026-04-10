"""
Bot command handlers.
All commands use interactive inline keyboards instead of free-text parsing.
"""

import logging
from telegram import Update
from telegram.ext import ContextTypes

from core import db
from core.models import Job
from bot.sender import format_job_message
from bot.keyboards import (
    topic_selection_keyboard, job_buttons, pagination_keyboard,
)

log = logging.getLogger(__name__)

HELP_TEXT = """
🤖 <b>Programming Jobs Bot</b>

<b>Commands:</b>
/subscribe — Set up personalized job alerts
/unsubscribe — Remove all subscriptions
/mysubs — View your current filters
/search — Search jobs interactively
/saved — View your saved jobs
/applied — View your application history
/streak — Your daily application streak
/blacklist — Manage blocked companies/keywords
/stats — Bot statistics
/top — Top jobs this week
/salary — Salary insights
/help — This message
"""


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "👋 Welcome! I post programming jobs from 23 sources.\n\n"
        "Use /subscribe to get personalized alerts, or /help for all commands.",
        parse_mode="HTML",
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(HELP_TEXT, parse_mode="HTML")


async def cmd_subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Start the interactive subscription flow."""
    context.user_data["sub_topics"] = set()
    await update.message.reply_text(
        "Step 1/4: Select topics you're interested in:\n"
        "(tap to toggle, then press Done)",
        reply_markup=topic_selection_keyboard(),
    )


async def cmd_unsubscribe(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    db_user = db.get_or_create_user(user.id, user.username or "")
    db.update_user_subscriptions(user.id, {})
    await update.message.reply_text("✅ All subscriptions removed.")


async def cmd_mysubs(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    db_user = db.get_or_create_user(user.id, user.username or "")
    subs = db_user.get("subscriptions", {})

    if not subs or not subs.get("topics"):
        await update.message.reply_text("No active subscriptions. Use /subscribe to set up alerts.")
        return

    lines = ["📋 <b>Your Subscriptions:</b>\n"]
    if subs.get("topics"):
        lines.append(f"Topics: {', '.join(subs['topics'])}")
    if subs.get("seniority"):
        lines.append(f"Seniority: {', '.join(subs['seniority'])}")
    if subs.get("locations"):
        from bot.keyboards import LOCATION_OPTIONS
        label_map = dict(LOCATION_OPTIONS)
        lines.append(f"Locations: {', '.join(label_map.get(l, l) for l in subs['locations'])}")
    if subs.get("sources"):
        from bot.keyboards import SOURCE_OPTIONS
        label_map = dict(SOURCE_OPTIONS)
        lines.append(f"Sources: {', '.join(label_map.get(s, s) for s in subs['sources'])}")
    if subs.get("keywords"):
        lines.append(f"Keywords: {', '.join(subs['keywords'])}")
    if subs.get("min_salary"):
        lines.append(f"Min salary: ${subs['min_salary']:,}/year")

    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


async def cmd_search(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Search jobs. Usage: /search <query>"""
    args = context.args
    if not args:
        await update.message.reply_text(
            "Usage: /search <keywords>\n"
            "Example: /search python remote\n"
            "Example: /search react senior"
        )
        return

    query = " ".join(args)
    try:
        results = db._fetchall(
            """SELECT * FROM jobs
               WHERE created_at > now() - make_interval(days := 14)
                 AND (title ILIKE %s OR %s = ANY(tags))
               ORDER BY created_at DESC
               LIMIT 5""",
            (f"%{query}%", query.lower()),
        )
    except Exception as e:
        log.error(f"Search failed: {e}")
        results = []

    if not results:
        await update.message.reply_text(f"No jobs found for '{query}'. Try broader keywords.")
        return

    await update.message.reply_text(f"🔍 Found {len(results)} jobs for '{query}':")
    for row in results:
        job = Job.from_db_row(row)
        msg = format_job_message(job)
        await update.message.reply_text(
            msg, parse_mode="HTML",
            disable_web_page_preview=True,
            reply_markup=job_buttons(row["id"]),
        )


async def cmd_saved(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show saved jobs."""
    user = update.effective_user
    await _show_saved_page(update, user, page=1)


async def _show_saved_page(update_or_query, user, page: int) -> None:
    """Show a page of saved jobs. Works with both Update and CallbackQuery."""
    per_page = 5
    offset = (page - 1) * per_page

    db_user = db.get_or_create_user(user.id, user.username or "")
    saved = db.get_saved_jobs(db_user["id"], limit=per_page + 1, offset=offset)

    has_more = len(saved) > per_page
    saved = saved[:per_page]

    if not saved:
        text = "No saved jobs yet. Tap 💾 Save on any job post!"
        if hasattr(update_or_query, "message") and update_or_query.message:
            await update_or_query.message.reply_text(text)
        else:
            await update_or_query.edit_message_text(text)
        return

    total_pages = page + (1 if has_more else 0)  # Approximate
    header = f"💾 <b>Saved Jobs</b> (page {page}):\n"

    if hasattr(update_or_query, "message") and update_or_query.message:
        send_fn = update_or_query.message.reply_text
    else:
        send_fn = update_or_query.edit_message_text

    await send_fn(header, parse_mode="HTML")
    for row in saved:
        job = Job.from_db_row(row)
        msg = format_job_message(job)
        if hasattr(update_or_query, "message") and update_or_query.message:
            await update_or_query.message.reply_text(
                msg, parse_mode="HTML",
                disable_web_page_preview=True,
            )


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show bot statistics."""
    try:
        today = db._fetchone(
            "SELECT COUNT(*) as count FROM jobs WHERE created_at > now() - make_interval(days := 1)"
        )
        week = db._fetchone(
            "SELECT COUNT(*) as count FROM jobs WHERE created_at > now() - make_interval(days := 7)"
        )
        total = db._fetchone("SELECT COUNT(*) as count FROM jobs")
        sources = db._fetchall(
            """SELECT source, COUNT(*) as count FROM jobs
               WHERE created_at > now() - make_interval(days := 7)
               GROUP BY source ORDER BY count DESC LIMIT 5"""
        )
    except Exception as e:
        await update.message.reply_text(f"Stats unavailable: {e}")
        return

    lines = [
        "📊 <b>Bot Statistics</b>\n",
        f"Today: {today['count']} jobs",
        f"This week: {week['count']} jobs",
        f"All time: {total['count']} jobs",
        "\n<b>Top sources (7 days):</b>",
    ]
    for s in sources:
        lines.append(f"  {s['source']}: {s['count']}")

    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


async def cmd_top(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show top jobs this week by engagement."""
    try:
        top_jobs = db._fetchall(
            """SELECT j.*, COUNT(jf.id) as engagement
               FROM jobs j
               LEFT JOIN job_feedback jf ON j.id = jf.job_id
               LEFT JOIN user_saved_jobs usj ON j.id = usj.job_id
               WHERE j.created_at > now() - make_interval(days := 7)
               GROUP BY j.id
               ORDER BY engagement DESC, j.created_at DESC
               LIMIT 5"""
        )
    except Exception as e:
        await update.message.reply_text(f"Top jobs unavailable: {e}")
        return

    if not top_jobs:
        await update.message.reply_text("No jobs this week yet.")
        return

    await update.message.reply_text("🏆 <b>Top Jobs This Week:</b>", parse_mode="HTML")
    for row in top_jobs:
        job = Job.from_db_row(row)
        msg = format_job_message(job)
        await update.message.reply_text(
            msg, parse_mode="HTML",
            disable_web_page_preview=True,
            reply_markup=job_buttons(row["id"]),
        )


async def cmd_salary(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show salary insights. Usage: /salary <role>"""
    args = context.args
    if not args:
        await update.message.reply_text(
            "Usage: /salary <role>\n"
            "Example: /salary python\n"
            "Example: /salary backend"
        )
        return

    query = " ".join(args)
    try:
        stats = db._fetchone(
            """SELECT
                 COUNT(*) as count,
                 AVG(salary_min) as avg_min,
                 AVG(salary_max) as avg_max,
                 MIN(salary_min) as lowest,
                 MAX(salary_max) as highest
               FROM jobs
               WHERE salary_min IS NOT NULL
                 AND title ILIKE %s
                 AND created_at > now() - make_interval(days := 30)""",
            (f"%{query}%",),
        )
    except Exception as e:
        await update.message.reply_text(f"Salary data unavailable: {e}")
        return

    if not stats or not stats["count"] or stats["count"] == 0:
        await update.message.reply_text(f"No salary data for '{query}'.")
        return

    lines = [
        f"💰 <b>Salary Insights: {query}</b>\n",
        f"Based on {stats['count']} jobs (last 30 days)\n",
        f"Average: ${int(stats['avg_min']):,} - ${int(stats['avg_max']):,}/year",
        f"Range: ${int(stats['lowest']):,} - ${int(stats['highest']):,}/year",
    ]
    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


# ── Application tracking ────────────────────────────────────


async def cmd_applied(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show the user's application history."""
    user = update.effective_user
    db_user = db.get_or_create_user(user.id, user.username or "")

    total = db.get_application_count(db_user["id"])
    if total == 0:
        await update.message.reply_text(
            "No applications tracked yet.\n"
            "Tap ✅ Applied on any job post to start tracking!"
        )
        return

    rows = db.get_application_history(db_user["id"], limit=10)

    lines = [f"📋 <b>Application History</b> ({total} total)\n"]
    for row in rows:
        title = _escape_html(row["title"])
        company = _escape_html(row.get("company", ""))
        applied_at = row["applied_at"].strftime("%b %d")
        lines.append(f"• <b>{title}</b> at {company} — {applied_at}")

    streak = db.get_streak(db_user["id"])
    lines.append(f"\n🔥 Current streak: {streak['current']} day{'s' if streak['current'] != 1 else ''}")

    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


async def cmd_streak(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show the user's application streak."""
    user = update.effective_user
    db_user = db.get_or_create_user(user.id, user.username or "")

    streak = db.get_streak(db_user["id"])
    total = db.get_application_count(db_user["id"])

    if total == 0:
        await update.message.reply_text(
            "No applications tracked yet.\n"
            "Tap ✅ Applied on any job post to start your streak!"
        )
        return

    today_check = "✅ Applied today!" if streak["today"] else "⬜ Not yet applied today"

    lines = [
        "🔥 <b>Application Streak</b>\n",
        f"Current streak: <b>{streak['current']}</b> day{'s' if streak['current'] != 1 else ''}",
        f"Longest streak: <b>{streak['longest']}</b> day{'s' if streak['longest'] != 1 else ''}",
        f"Total applications: <b>{total}</b>",
        f"\n{today_check}",
    ]

    # Motivational nudge
    if streak["current"] >= 7:
        lines.append("\n🏆 Amazing consistency! Keep it up!")
    elif streak["current"] >= 3:
        lines.append("\n💪 Great momentum! Don't break the chain!")
    elif not streak["today"]:
        lines.append("\n👉 Apply to a job today to keep your streak alive!")

    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


# ── Blacklist ───────────────────────────────────────────────


def _escape_html(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


async def cmd_blacklist(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Manage blacklisted companies and keywords.

    Usage:
        /blacklist                      — view current blacklist
        /blacklist add company Acme     — block a company
        /blacklist add keyword recruiter — block a keyword
        /blacklist remove company Acme  — unblock a company
        /blacklist remove keyword recruiter — unblock a keyword
        /blacklist clear                — clear entire blacklist
    """
    user = update.effective_user
    db_user = db.get_or_create_user(user.id, user.username or "")
    args = context.args or []

    bl = db.get_blacklist(db_user["id"])

    # No args — show current blacklist
    if not args:
        if not bl["companies"] and not bl["keywords"]:
            await update.message.reply_text(
                "Your blacklist is empty.\n\n"
                "<b>Usage:</b>\n"
                "/blacklist add company Acme Corp\n"
                "/blacklist add keyword recruiter\n"
                "/blacklist remove company Acme Corp\n"
                "/blacklist clear",
                parse_mode="HTML",
            )
            return

        lines = ["🚫 <b>Your Blacklist</b>\n"]
        if bl["companies"]:
            lines.append("<b>Companies:</b>")
            for c in bl["companies"]:
                lines.append(f"  • {_escape_html(c)}")
        if bl["keywords"]:
            lines.append("<b>Keywords:</b>")
            for k in bl["keywords"]:
                lines.append(f"  • {_escape_html(k)}")
        lines.append("\nJobs matching these are excluded from your DM alerts.")
        await update.message.reply_text("\n".join(lines), parse_mode="HTML")
        return

    action = args[0].lower()

    if action == "clear":
        db.update_blacklist(db_user["id"], {"companies": [], "keywords": []})
        await update.message.reply_text("✅ Blacklist cleared.")
        return

    if action not in ("add", "remove") or len(args) < 3:
        await update.message.reply_text(
            "Usage: /blacklist add|remove company|keyword <value>\n"
            "Example: /blacklist add company Acme Corp"
        )
        return

    category = args[1].lower()
    value = " ".join(args[2:])

    if category not in ("company", "keyword"):
        await update.message.reply_text("Category must be 'company' or 'keyword'.")
        return

    list_key = "companies" if category == "company" else "keywords"

    if action == "add":
        if value.lower() not in [v.lower() for v in bl[list_key]]:
            bl[list_key].append(value)
            db.update_blacklist(db_user["id"], bl)
            await update.message.reply_text(f"✅ Added {category} '{_escape_html(value)}' to blacklist.", parse_mode="HTML")
        else:
            await update.message.reply_text(f"Already blacklisted.")

    elif action == "remove":
        lower_values = [v.lower() for v in bl[list_key]]
        if value.lower() in lower_values:
            idx = lower_values.index(value.lower())
            bl[list_key].pop(idx)
            db.update_blacklist(db_user["id"], bl)
            await update.message.reply_text(f"✅ Removed {category} '{_escape_html(value)}' from blacklist.", parse_mode="HTML")
        else:
            await update.message.reply_text(f"'{_escape_html(value)}' not found in blacklist.", parse_mode="HTML")
