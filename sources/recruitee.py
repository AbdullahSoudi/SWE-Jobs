"""Recruitee Public API — fetches from curated tech company boards."""

import logging
from core.models import Job
from sources.http_utils import get_json

log = logging.getLogger(__name__)

BASE = "https://{}.recruitee.com/api/offers/"

# Curated tech company subdomains
COMPANIES = [
    "hotjar", "babbel", "wefox", "tradingview", "wolt",
    "foodpanda", "hometogo", "omio", "depositphotos", "vimeo",
    "pleo", "gorgias", "prezly", "teamtailor", "kenjo",
]


def fetch_recruitee() -> list[Job]:
    """Fetch jobs from Recruitee company boards."""
    jobs = []
    for company in COMPANIES:
        url = BASE.format(company)
        data = get_json(url)
        if not data or "offers" not in data:
            continue

        for item in data["offers"]:
            title = item.get("title", "")
            slug = item.get("slug", "")
            if not title or not slug:
                continue

            careers_url = item.get("careers_url", "")
            if not careers_url:
                careers_url = f"https://{company}.recruitee.com/o/{slug}"

            location = item.get("location", "")
            department = item.get("department", "")
            tags = [department] if department else []

            jobs.append(Job(
                title=title,
                company=company.replace("-", " ").title(),
                location=location or "Unknown",
                url=careers_url,
                source="recruitee",
                original_source=f"recruitee:{company}",
                job_type=item.get("employment_type_code", ""),
                tags=tags,
                is_remote=item.get("remote", False),
            ))
    log.debug(f"Recruitee: fetched {len(jobs)} jobs across {len(COMPANIES)} companies.")
    return jobs
