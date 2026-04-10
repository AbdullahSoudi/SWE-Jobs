"""Workable Widget API — fetches from curated tech company boards."""

import logging
from core.models import Job
from sources.http_utils import get_json

log = logging.getLogger(__name__)

BASE = "https://apply.workable.com/api/v1/widget/accounts/{}"

# Curated tech company subdomains
COMPANIES = [
    "rappi", "factorial", "taxfix", "beat", "blueground",
    "solarisbank", "grammarly", "pipe", "miro", "deepl",
    "typeform", "personio", "contentful", "messagebird", "cabify",
]


def fetch_workable() -> list[Job]:
    """Fetch jobs from Workable company boards."""
    jobs = []
    for company in COMPANIES:
        url = BASE.format(company)
        data = get_json(url)
        if not data or "jobs" not in data:
            continue

        for item in data["jobs"]:
            title = item.get("title", "")
            shortcode = item.get("shortcode", "")
            if not title or not shortcode:
                continue

            job_url = item.get("url", "")
            if not job_url:
                job_url = f"https://apply.workable.com/{company}/j/{shortcode}/"

            location = item.get("location", "")
            if isinstance(location, dict):
                parts = [
                    location.get("city", ""),
                    location.get("region", ""),
                    location.get("country", ""),
                ]
                location = ", ".join(p for p in parts if p)
            location = location or "Unknown"

            department = item.get("department", "")
            tags = [department] if department else []

            jobs.append(Job(
                title=title,
                company=company.replace("-", " ").title(),
                location=location,
                url=job_url,
                source="workable",
                original_source=f"workable:{company}",
                job_type=item.get("employment_type", ""),
                tags=tags,
                is_remote=item.get("telecommuting", False),
            ))
    log.debug(f"Workable: fetched {len(jobs)} jobs across {len(COMPANIES)} companies.")
    return jobs
