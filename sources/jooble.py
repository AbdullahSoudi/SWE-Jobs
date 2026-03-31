"""Jooble — global job search API (POST-based, free key)."""

import logging
from models import Job
from sources.http_utils import post_json
from config import JOOBLE_API_KEY

log = logging.getLogger(__name__)

BASE = "https://jooble.org/api"

SEARCHES = [
    # Remote
    {"keywords": "software engineer", "location": "remote"},
    {"keywords": "backend developer", "location": "remote"},
    {"keywords": "frontend developer", "location": "remote"},
    {"keywords": "flutter developer", "location": "remote"},
    {"keywords": "mobile app developer", "location": "remote"},
    {"keywords": "data scientist", "location": "remote"},
    {"keywords": "machine learning engineer", "location": "remote"},
    {"keywords": "cybersecurity engineer", "location": "remote"},
    {"keywords": "blockchain developer", "location": "remote"},
    {"keywords": "game developer", "location": "remote"},
    {"keywords": "odoo developer", "location": "remote"},
    {"keywords": "SAP developer", "location": "remote"},
    {"keywords": "ERP developer", "location": "remote"},
    # Egypt
    {"keywords": "software engineer", "location": "Egypt"},
    {"keywords": "software developer", "location": "Cairo, Egypt"},
    {"keywords": "backend developer", "location": "Egypt"},
    {"keywords": "frontend developer", "location": "Egypt"},
    {"keywords": "flutter developer", "location": "Egypt"},
    {"keywords": "mobile developer", "location": "Egypt"},
    {"keywords": "python developer", "location": "Egypt"},
    {"keywords": "odoo developer", "location": "Egypt"},
    {"keywords": "QA engineer", "location": "Egypt"},
    {"keywords": "intern developer", "location": "Egypt"},
    # Saudi Arabia
    {"keywords": "software engineer", "location": "Saudi Arabia"},
    {"keywords": "software developer", "location": "Riyadh, Saudi Arabia"},
    {"keywords": "backend developer", "location": "Saudi Arabia"},
    {"keywords": "frontend developer", "location": "Saudi Arabia"},
    {"keywords": "flutter developer", "location": "Saudi Arabia"},
    {"keywords": "mobile developer", "location": "Saudi Arabia"},
    {"keywords": "SAP developer", "location": "Saudi Arabia"},
    {"keywords": "odoo developer", "location": "Saudi Arabia"},
    {"keywords": "ERP developer", "location": "Saudi Arabia"},
    {"keywords": "cybersecurity", "location": "Saudi Arabia"},
    {"keywords": "data scientist", "location": "Saudi Arabia"},
    # Marketing & Growth
    {"keywords": "digital marketing", "location": "remote"},
    {"keywords": "social media marketing", "location": "remote"},
    {"keywords": "growth marketing", "location": "remote"},
    {"keywords": "digital marketing", "location": "Egypt"},
    {"keywords": "social media manager", "location": "Egypt"},
    {"keywords": "digital marketing", "location": "Saudi Arabia"},
    # Data Engineering
    {"keywords": "data engineer", "location": "remote"},
    {"keywords": "analytics engineer", "location": "remote"},
    {"keywords": "data engineer", "location": "Egypt"},
    {"keywords": "data engineer", "location": "Saudi Arabia"},
    # Application Support
    {"keywords": "application support", "location": "remote"},
    {"keywords": "application support", "location": "Egypt"},
    {"keywords": "application support", "location": "Saudi Arabia"},
    # UI/UX & Graphic Design
    {"keywords": "UX designer", "location": "remote"},
    {"keywords": "graphic designer", "location": "remote"},
    {"keywords": "UX designer", "location": "Egypt"},
    {"keywords": "graphic designer", "location": "Egypt"},
    {"keywords": "UX designer", "location": "Saudi Arabia"},
    # Business & Product
    {"keywords": "business analyst", "location": "remote"},
    {"keywords": "product owner", "location": "remote"},
    {"keywords": "business analyst", "location": "Egypt"},
    {"keywords": "business analyst", "location": "Saudi Arabia"},
    {"keywords": "product manager", "location": "Saudi Arabia"},
    # Data Analysis
    {"keywords": "data analyst", "location": "remote"},
    {"keywords": "data analyst", "location": "Egypt"},
    {"keywords": "data analyst", "location": "Saudi Arabia"},
]


def fetch_jooble() -> list[Job]:
    """Fetch jobs from Jooble across multiple searches."""
    if not JOOBLE_API_KEY:
        log.warning("Jooble: API key not set — skipping.")
        return []

    url = f"{BASE}/{JOOBLE_API_KEY}"
    jobs = []

    for search in SEARCHES:
        payload = {
            "keywords": search["keywords"],
            "location": search["location"],
            "page": 1,
        }
        data = post_json(url, payload=payload)
        if not data or "jobs" not in data:
            continue

        for item in data["jobs"]:
            location = item.get("location", "")
            is_remote = "remote" in location.lower() or "remote" in search["location"].lower()

            # Clean snippet HTML
            snippet = item.get("snippet", "")
            salary = item.get("salary", "")

            jobs.append(Job(
                title=item.get("title", ""),
                company=item.get("company", ""),
                location=location or search["location"],
                url=item.get("link", ""),
                source="jooble",
                salary=salary,
                job_type=item.get("type", ""),
                tags=[],
                is_remote=is_remote,
            ))
    log.info(f"Jooble: fetched {len(jobs)} jobs.")
    return jobs
