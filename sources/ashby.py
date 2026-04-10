"""Ashby Job Board API — fetches from curated tech company boards."""

import logging
from core.models import Job
from sources.http_utils import get_json

log = logging.getLogger(__name__)

BASE = "https://api.ashbyhq.com/posting-api/job-board/{}"

# Curated tech company board slugs
BOARDS = [
    "ramp", "notion", "linear", "vercel", "retool",
    "replit", "render", "supabase", "dbt-labs", "clerk",
    "resend", "cal", "neon", "railway", "tinybird",
]


def fetch_ashby() -> list[Job]:
    """Fetch jobs from Ashby company boards."""
    jobs = []
    for board in BOARDS:
        url = BASE.format(board)
        data = get_json(url)
        if not data or "jobs" not in data:
            continue

        company_name = data.get("organizationName", board.replace("-", " ").title())

        for item in data["jobs"]:
            title = item.get("title", "")
            job_id = item.get("id", "")
            if not title or not job_id:
                continue

            job_url = item.get("jobUrl", "")
            if not job_url:
                job_url = f"https://jobs.ashbyhq.com/{board}/{job_id}"

            location = item.get("location", "")
            department = item.get("department", "")
            team = item.get("team", "")
            tags = []
            if department:
                tags.append(department)
            if team and team != department:
                tags.append(team)

            is_remote = item.get("isRemote", False)
            if not is_remote and isinstance(location, str):
                is_remote = "remote" in location.lower()

            jobs.append(Job(
                title=title,
                company=company_name,
                location=location or "Unknown",
                url=job_url,
                source="ashby",
                original_source=f"ashby:{board}",
                tags=tags,
                is_remote=is_remote,
            ))
    log.debug(f"Ashby: fetched {len(jobs)} jobs across {len(BOARDS)} boards.")
    return jobs
