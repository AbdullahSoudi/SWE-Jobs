"""SmartRecruiters Job Feed — fetches from curated tech company boards."""

import logging
from core.models import Job
from sources.http_utils import get_json

log = logging.getLogger(__name__)

BASE = "https://api.smartrecruiters.com/v1/companies/{}/postings"

# Curated tech company identifiers
COMPANIES = [
    "Visa", "BOSCH", "Booking", "Spotify", "SAP",
    "DHL", "Siemens", "Zalando", "ING", "Adidas",
    "Philips", "TomTom", "Trivago", "HelloFresh", "SumUp",
]


def fetch_smartrecruiters() -> list[Job]:
    """Fetch jobs from SmartRecruiters company postings."""
    jobs = []
    for company in COMPANIES:
        url = BASE.format(company)
        data = get_json(url)
        if not data or "content" not in data:
            continue

        for item in data["content"]:
            title = item.get("name", "")
            ref_url = item.get("ref", "")
            if not title or not ref_url:
                continue

            # Build the apply URL
            job_id = item.get("id", "")
            company_slug = item.get("company", {}).get("identifier", company)
            apply_url = f"https://jobs.smartrecruiters.com/{company_slug}/{job_id}"

            loc = item.get("location", {}) or {}
            location_parts = [
                loc.get("city", ""),
                loc.get("region", ""),
                loc.get("country", ""),
            ]
            location = ", ".join(p for p in location_parts if p) or "Unknown"

            department = ""
            dept_obj = item.get("department", {})
            if isinstance(dept_obj, dict):
                department = dept_obj.get("label", "")
            tags = [department] if department else []

            is_remote = item.get("remote", False)
            if not is_remote:
                is_remote = "remote" in location.lower()

            jobs.append(Job(
                title=title,
                company=company,
                location=location,
                url=apply_url,
                source="smartrecruiters",
                original_source=f"smartrecruiters:{company}",
                job_type=item.get("typeOfEmployment", {}).get("label", ""),
                tags=tags,
                is_remote=is_remote,
            ))
    log.debug(f"SmartRecruiters: fetched {len(jobs)} jobs across {len(COMPANIES)} companies.")
    return jobs
