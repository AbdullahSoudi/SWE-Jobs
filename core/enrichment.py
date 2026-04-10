"""
Job enrichment pipeline.
Chains: salary parsing -> seniority detection -> country detection -> topic routing.
"""

import logging
from core.models import Job, _flatten_tags
from core.salary_parser import parse_salary
from core.seniority import detect_seniority
from core.country_detector import detect_country
from core.channels import CHANNELS
from core.geo import EGYPT_PATTERNS, SAUDI_PATTERNS

log = logging.getLogger(__name__)


def _match_keywords(text: str, keywords: list[str]) -> bool:
    """Check if lowered text contains any of the keywords."""
    text_lower = text.lower()
    return any(kw.lower() in text_lower for kw in keywords)


def _is_egypt_location(location: str) -> bool:
    loc = location.lower()
    return any(p in loc for p in EGYPT_PATTERNS)


def _is_saudi_location(location: str) -> bool:
    loc = location.lower()
    return any(p in loc for p in SAUDI_PATTERNS)


def _route_topics(job: Job) -> list[str]:
    """Determine which topics a job should be sent to.

    General topic is a fallback — only used when no specific topic matched.
    """
    topics = []
    fallback_keys = []
    tags_str = _flatten_tags(job.tags)
    searchable = f"{job.title} {job.company} {tags_str}".lower()

    for key, ch in CHANNELS.items():
        match_type = ch.get("match", "")
        if match_type == "ALL":
            fallback_keys.append(key)
        elif match_type == "GEO_EGYPT":
            if _is_egypt_location(job.location):
                topics.append(key)
        elif match_type == "GEO_SAUDI":
            if _is_saudi_location(job.location):
                topics.append(key)
        elif "keywords" in ch:
            if _match_keywords(searchable, ch["keywords"]):
                topics.append(key)

    # Use general/ALL topics only as fallback when nothing else matched
    if not topics:
        topics = fallback_keys

    return topics


def enrich_job(job: Job) -> Job:
    """
    Enrich a job with parsed salary, seniority, country, and topic routing.
    Returns the same Job object with fields updated (mutates in place).
    """
    # 1. Parse salary
    if job.salary_raw and not job.salary_min:
        result = parse_salary(job.salary_raw)
        if result:
            job.salary_min = result["min"]
            job.salary_max = result["max"]
            job.salary_currency = result["currency"]

    # 2. Detect seniority (only if still default)
    if job.seniority == "mid":
        job.seniority = detect_seniority(job.title)

    # 3. Detect country (only if empty)
    if not job.country:
        job.country = detect_country(job.location)

    # 4. Route to topics (always recalculate)
    job.topics = _route_topics(job)

    return job
