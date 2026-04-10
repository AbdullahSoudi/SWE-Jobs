"""JSearch (RapidAPI) — aggregates LinkedIn, Indeed, Glassdoor, etc."""

import logging
import time
from core.models import Job
from sources.http_utils import get_json
from core.config import RAPIDAPI_KEY

log = logging.getLogger(__name__)

URL = "https://jsearch.p.rapidapi.com/search"

# Delay (seconds) between consecutive JSearch API calls to avoid 429s.
REQUEST_DELAY = 2.0

# Sort by date to get newest first. No date filter — dedup handles freshness.
_BASE_REMOTE = {"remote_jobs_only": "true", "num_pages": "1"}
_BASE_LOCAL = {"num_pages": "1"}

# Consolidated queries — broader terms cover more roles per request.
SEARCHES = [
    # Remote worldwide (broad terms that cover sub-specialties)
    {"query": "software engineer remote", **_BASE_REMOTE},
    {"query": "backend developer remote", **_BASE_REMOTE},
    {"query": "frontend developer remote", **_BASE_REMOTE},
    {"query": "mobile developer remote", **_BASE_REMOTE},
    {"query": "devops engineer remote", **_BASE_REMOTE},
    {"query": "data scientist machine learning remote", **_BASE_REMOTE},
    # Egypt onsite
    {"query": "software developer in Egypt", **_BASE_LOCAL},
    {"query": "mobile developer in Egypt", **_BASE_LOCAL},
    # Saudi Arabia onsite
    {"query": "software developer in Saudi Arabia", **_BASE_LOCAL},
    {"query": "backend developer in Saudi Arabia", **_BASE_LOCAL},
]

# Map publisher names for display
PUBLISHER_MAP = {
    "linkedin.com": "LinkedIn",
    "indeed.com": "Indeed",
    "glassdoor.com": "Glassdoor",
    "ziprecruiter.com": "ZipRecruiter",
    "monster.com": "Monster",
}


def fetch_jsearch() -> list[Job]:
    """Fetch jobs from JSearch across multiple queries."""
    if not RAPIDAPI_KEY:
        log.warning("JSearch: RAPIDAPI_KEY not set — skipping.")
        return []

    headers = {
        "X-RapidAPI-Key": RAPIDAPI_KEY,
        "X-RapidAPI-Host": "jsearch.p.rapidapi.com",
    }

    jobs = []
    for i, params in enumerate(SEARCHES):
        if i > 0:
            log.debug(f"JSearch: waiting {REQUEST_DELAY}s before query {i+1}/{len(SEARCHES)}")
            time.sleep(REQUEST_DELAY)
        data = get_json(URL, params=params, headers=headers, timeout=30)
        if not data or "data" not in data:
            continue
        for item in data["data"]:
            publisher = item.get("job_publisher", "")
            original_source = _resolve_publisher(publisher)

            salary = ""
            if item.get("job_min_salary") and item.get("job_max_salary"):
                cur = item.get("job_salary_currency", "USD")
                salary = f"{cur} {item['job_min_salary']:,.0f}–{item['job_max_salary']:,.0f}"

            location = item.get("job_city", "")
            if item.get("job_state"):
                location = f"{location}, {item['job_state']}" if location else item["job_state"]
            if item.get("job_country"):
                location = f"{location}, {item['job_country']}" if location else item["job_country"]

            jobs.append(Job(
                title=item.get("job_title", ""),
                company=item.get("employer_name", ""),
                location=location or "Not specified",
                url=item.get("job_apply_link", ""),
                source="jsearch",
                salary_raw=salary,
                job_type=(item.get("job_employment_type") or "").replace("FULLTIME", "Full Time")
                    .replace("PARTTIME", "Part Time").replace("CONTRACTOR", "Contract")
                    .replace("INTERN", "Internship"),
                tags=[],
                is_remote=item.get("job_is_remote", False),
                original_source=original_source,
            ))
    log.debug(f"JSearch: fetched {len(jobs)} jobs.")
    return jobs


def _resolve_publisher(publisher: str) -> str:
    """Map publisher URL to display name."""
    pub = publisher.lower()
    for domain, name in PUBLISHER_MAP.items():
        if domain in pub:
            return name
    return publisher or "JSearch"
