"""DevITjobs.uk — UK-focused developer job board API."""

import logging
from core.models import Job
from sources.http_utils import get_json

log = logging.getLogger(__name__)

URL = "https://devitjobs.uk/api/jobsLight"


def fetch_devitjobs() -> list[Job]:
    """Fetch jobs from DevITjobs.uk."""
    data = get_json(URL)
    if not data or not isinstance(data, list):
        log.warning("DevITjobs: no data.")
        return []

    jobs = []
    for item in data:
        title = item.get("title", "")
        url = item.get("url", "")
        if not title or not url:
            continue

        salary_raw = ""
        sal_from = item.get("salaryFrom")
        sal_to = item.get("salaryTo")
        currency = item.get("salaryCurrency", "")
        if sal_from and sal_to:
            salary_raw = f"{currency}{sal_from}-{sal_to}"

        jobs.append(Job(
            title=title,
            company=item.get("companyName", ""),
            location=item.get("locationNames", "UK"),
            url=url,
            source="devitjobs",
            salary_raw=salary_raw,
            salary_min=int(sal_from) if sal_from else None,
            salary_max=int(sal_to) if sal_to else None,
            salary_currency=currency,
            job_type=item.get("employmentType", ""),
            tags=item.get("technologies", []) or [],
            is_remote=item.get("remote", False),
        ))
    log.debug(f"DevITjobs: fetched {len(jobs)} jobs.")
    return jobs
