"""Lever Job Postings API — fetches from curated tech company boards."""

import logging
from core.models import Job
from sources.http_utils import get_json

log = logging.getLogger(__name__)

BASE = "https://api.lever.co/v0/postings/{}"

# Curated tech company slugs
COMPANIES = [
    "spotify", "netlify", "docker", "auth0", "netlify",
    "twitch", "robinhood", "lyft", "lever", "segment",
    "nerdwallet", "openai", "anthropic", "figma", "palantir",
    "mongodb", "elastic", "confluent", "databricks", "anduril",
]


def fetch_lever() -> list[Job]:
    """Fetch jobs from Lever company postings."""
    jobs = []
    seen_companies = set()
    for company in COMPANIES:
        if company in seen_companies:
            continue
        seen_companies.add(company)

        url = BASE.format(company)
        data = get_json(url, params={"mode": "json"})
        if not data or not isinstance(data, list):
            continue

        for item in data:
            title = item.get("text", "")
            posting_url = item.get("hostedUrl", "")
            if not title or not posting_url:
                continue

            categories = item.get("categories", {}) or {}
            location = categories.get("location", "")
            team = categories.get("team", "")
            commitment = categories.get("commitment", "")

            tags = []
            if team:
                tags.append(team)

            jobs.append(Job(
                title=title,
                company=company.replace("-", " ").title(),
                location=location or "Unknown",
                url=posting_url,
                source="lever",
                original_source=f"lever:{company}",
                job_type=commitment,
                tags=tags,
                is_remote="remote" in location.lower() if location else False,
            ))
    log.debug(f"Lever: fetched {len(jobs)} jobs across {len(seen_companies)} companies.")
    return jobs
