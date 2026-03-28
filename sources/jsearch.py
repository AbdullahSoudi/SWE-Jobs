"""JSearch (RapidAPI) — aggregates LinkedIn, Indeed, Glassdoor, etc."""

import logging
from models import Job
from sources.http_utils import get_json
from config import RAPIDAPI_KEY

log = logging.getLogger(__name__)

URL = "https://jsearch.p.rapidapi.com/search"

# Sort by date to get newest first. No date filter — dedup handles freshness.
_R = {"remote_jobs_only": "true", "num_pages": "1"}
_L = {"num_pages": "1"}

SEARCHES = [
    # ── Remote worldwide ──
    {"query": "software engineer remote", **_R},
    {"query": "backend developer remote", **_R},
    {"query": "frontend developer remote", **_R},
    {"query": "full stack developer remote", **_R},
    {"query": "devops engineer remote", **_R},
    {"query": "flutter developer remote", **_R},
    {"query": "react native developer remote", **_R},
    {"query": "mobile app developer remote", **_R},
    {"query": "data scientist remote", **_R},
    {"query": "machine learning engineer remote", **_R},
    {"query": "QA engineer remote", **_R},
    {"query": "react developer remote", **_R},
    # Niche remote
    {"query": "cybersecurity engineer remote", **_R},
    {"query": "penetration tester remote", **_R},
    {"query": "blockchain developer remote", **_R},
    {"query": "solidity developer remote", **_R},
    {"query": "game developer remote", **_R},
    {"query": "unity developer remote", **_R},
    {"query": "odoo developer remote", **_R},
    {"query": "SAP developer remote", **_R},
    {"query": "salesforce developer remote", **_R},
    {"query": "ERP developer remote", **_R},
    {"query": "software intern remote", **_R},
    # ── Egypt ──
    {"query": "software engineer in Egypt", **_L},
    {"query": "software developer in Cairo, Egypt", **_L},
    {"query": "backend developer in Egypt", **_L},
    {"query": "frontend developer in Egypt", **_L},
    {"query": "flutter developer in Egypt", **_L},
    {"query": "mobile developer in Egypt", **_L},
    {"query": "data scientist in Egypt", **_L},
    {"query": "devops engineer in Egypt", **_L},
    {"query": "QA engineer in Egypt", **_L},
    {"query": "odoo developer in Egypt", **_L},
    {"query": "software engineer intern in Egypt", **_L},
    {"query": "junior developer in Egypt", **_L},
    {"query": "python developer in Egypt", **_L},
    {"query": "java developer in Egypt", **_L},
    {"query": "full stack developer in Egypt", **_L},
    # ── Saudi Arabia ──
    {"query": "software engineer in Saudi Arabia", **_L},
    {"query": "software developer in Riyadh, Saudi Arabia", **_L},
    {"query": "backend developer in Saudi Arabia", **_L},
    {"query": "frontend developer in Saudi Arabia", **_L},
    {"query": "flutter developer in Saudi Arabia", **_L},
    {"query": "mobile developer in Saudi Arabia", **_L},
    {"query": "data scientist in Saudi Arabia", **_L},
    {"query": "devops engineer in Saudi Arabia", **_L},
    {"query": "QA engineer in Saudi Arabia", **_L},
    {"query": "SAP developer in Saudi Arabia", **_L},
    {"query": "odoo developer in Saudi Arabia", **_L},
    {"query": "ERP developer in Saudi Arabia", **_L},
    {"query": "cybersecurity in Saudi Arabia", **_L},
    {"query": "java developer in Saudi Arabia", **_L},
    {"query": "python developer in Saudi Arabia", **_L},
    {"query": "full stack developer in Jeddah, Saudi Arabia", **_L},
    # ── Marketing & Growth ──
    {"query": "digital marketing remote", **_R},
    {"query": "social media marketing remote", **_R},
    {"query": "growth marketing remote", **_R},
    {"query": "SEO specialist remote", **_R},
    {"query": "content marketing remote", **_R},
    {"query": "marketing manager remote", **_R},
    {"query": "digital marketing in Egypt", **_L},
    {"query": "social media manager in Egypt", **_L},
    {"query": "marketing in Saudi Arabia", **_L},
    {"query": "digital marketing in Saudi Arabia", **_L},
    # ── Data Engineering ──
    {"query": "data engineer remote", **_R},
    {"query": "data architect remote", **_R},
    {"query": "analytics engineer remote", **_R},
    {"query": "data engineer in Egypt", **_L},
    {"query": "data engineer in Saudi Arabia", **_L},
    # ── Application Support ──
    {"query": "application support engineer remote", **_R},
    {"query": "technical support engineer remote", **_R},
    {"query": "application support in Egypt", **_L},
    {"query": "technical support engineer in Egypt", **_L},
    {"query": "application support in Saudi Arabia", **_L},
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
    for params in SEARCHES:
        data = get_json(URL, params=params, headers=headers)
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
                salary=salary,
                job_type=(item.get("job_employment_type") or "").replace("FULLTIME", "Full Time")
                    .replace("PARTTIME", "Part Time").replace("CONTRACTOR", "Contract")
                    .replace("INTERN", "Internship"),
                tags=[],
                is_remote=item.get("job_is_remote", False),
                original_source=original_source,
            ))
    log.info(f"JSearch: fetched {len(jobs)} jobs.")
    return jobs


def _resolve_publisher(publisher: str) -> str:
    """Map publisher URL to display name."""
    pub = publisher.lower()
    for domain, name in PUBLISHER_MAP.items():
        if domain in pub:
            return name
    return publisher or "JSearch"
