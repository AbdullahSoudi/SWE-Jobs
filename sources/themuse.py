"""The Muse — free API for job listings and company profiles."""

import logging
from models import Job
from sources.http_utils import get_json

log = logging.getLogger(__name__)

URL = "https://www.themuse.com/api/public/v2/jobs"

PARAMS_LIST = [
    {"category": "Software Engineering", "level": "Entry Level", "page": 0},
    {"category": "Software Engineering", "level": "Mid Level", "page": 0},
    {"category": "Software Engineering", "level": "Senior Level", "page": 0},
    {"category": "Data Science", "page": 0},
]


def fetch_themuse() -> list[Job]:
    """Fetch jobs from The Muse API."""
    jobs = []
    for params in PARAMS_LIST:
        data = get_json(URL, params=params)
        if not data or "results" not in data:
            continue
        for item in data["results"]:
            # Extract locations
            locations = item.get("locations", [])
            loc_names = [l.get("name", "") for l in locations if l.get("name")]
            location = ", ".join(loc_names) if loc_names else "Not specified"

            # Extract level
            levels = item.get("levels", [])
            level = levels[0].get("name", "") if levels else ""

            # Check remote
            is_remote = any("remote" in l.lower() or "flexible" in l.lower()
                          for l in loc_names)

            # Company
            company_obj = item.get("company", {})
            company = company_obj.get("name", "") if company_obj else ""

            jobs.append(Job(
                title=item.get("name", ""),
                company=company,
                location=location,
                url=item.get("refs", {}).get("landing_page", ""),
                source="themuse",
                job_type=level,
                tags=item.get("categories", []) or [],
                is_remote=is_remote,
            ))
    log.info(f"The Muse: fetched {len(jobs)} jobs.")
    return jobs
