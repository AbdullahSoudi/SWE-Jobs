"""WUZZUF source adapter.

Fetches public WUZZUF category/search pages and converts visible job cards into
our normalized Job model. This module intentionally keeps messages short and
stores only public card-level information: title, company, location, URL,
job type/workplace, and lightweight tags.
"""

from __future__ import annotations

import html
import logging
import re
from dataclasses import dataclass
from typing import Callable
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

from models import Job

try:  # final project layout
    from sources.http_utils import get_text
except ModuleNotFoundError:  # local flat-file test layout
    from http_utils import get_text

log = logging.getLogger(__name__)

BASE_URL = "https://wuzzuf.net"

# Public category/search pages that map to the existing Telegram community topics.
# Keep this list intentionally narrow to avoid crawling the whole site.
WUZZUF_SEARCH_URLS = [
    "https://wuzzuf.net/a/Software-Development-Jobs-in-Egypt",
    "https://wuzzuf.net/a/Software-Engineering-Jobs-in-Egypt",
    "https://wuzzuf.net/a/Information-Technology-IT-Jobs-in-Egypt",
    "https://wuzzuf.net/a/Android-Jobs-in-Egypt",
    "https://wuzzuf.net/a/Marketing-PR-Advertising-Jobs-in-Egypt",
    "https://wuzzuf.net/a/Creative-Design-Art-Jobs-in-Egypt",
    "https://wuzzuf.net/a/Analyst-Research-Jobs-in-Egypt",
    "https://wuzzuf.net/a/Project-Program-Management-Jobs-in-Egypt",
    "https://wuzzuf.net/a/Internships-in-Egypt",
    "https://wuzzuf.net/a/work-from-home",
]

JOB_LINK_RE = re.compile(
    r'<a\b[^>]*href=["\'](?P<href>[^"\']*/jobs/p/[^"\']+)["\'][^>]*>(?P<title>.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)
CAREER_LINK_RE = re.compile(
    r'<a\b[^>]*href=["\'][^"\']*/jobs/careers/[^"\']+["\'][^>]*>(?P<company>.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)
SPAN_RE = re.compile(r"<span\b[^>]*>(.*?)</span>", re.IGNORECASE | re.DOTALL)
TAG_RE = re.compile(r"<a\b[^>]*>(.*?)</a>|<span\b[^>]*>(.*?)</span>", re.IGNORECASE | re.DOTALL)
JOB_ID_RE = re.compile(r"/jobs/p/([^/?#]+)")

JOB_TYPE_PATTERNS = (
    "Full Time",
    "Part Time",
    "Internship",
    "Freelance / Project",
    "Freelance",
    "Shift Based",
    "Volunteering",
    "Full Time",
    "دوام كامل",
    "دوام جزئي",
    "تدريب عملي",
)
WORKPLACE_PATTERNS = (
    "Remote",
    "Hybrid",
    "On-site",
    "Work From Home",
    "عمل عن بُعد",
    "عمل من المنزل",
    "عمل من مقر الشركة",
    "هجين",
)
REMOTE_MARKERS = ("remote", "work from home", "عمل عن بُعد", "عمل من المنزل")


@dataclass(frozen=True)
class WuzzufFetchStats:
    """Small summary used by tests/logs."""

    pages_requested: int
    jobs_found: int


def fetch_wuzzuf(
    search_urls: list[str] | None = None,
    max_pages_per_search: int = 1,
    http_getter: Callable[[str], str | None] | None = None,
) -> list[Job]:
    """Fetch public WUZZUF pages and return normalized jobs.

    Args:
        search_urls: Optional override for tests or targeted runs.
        max_pages_per_search: Number of paginated pages to read per category.
        http_getter: Optional injectable getter for tests. Defaults to shared get_text.
    """
    if max_pages_per_search < 1:
        raise ValueError("max_pages_per_search must be >= 1")

    getter = http_getter or get_text
    urls = search_urls or WUZZUF_SEARCH_URLS
    jobs: list[Job] = []
    seen_urls: set[str] = set()
    pages_requested = 0

    for base_url in urls:
        for page_idx in range(max_pages_per_search):
            url = _with_start(base_url, page_idx * 20)
            pages_requested += 1
            page_html = getter(url)
            if not page_html:
                log.warning("WUZZUF: no response for %s", url)
                continue

            parsed = parse_wuzzuf_html(page_html, page_url=url)
            for job in parsed:
                normalized_url = job.url.rstrip("/").lower()
                if normalized_url in seen_urls:
                    continue
                seen_urls.add(normalized_url)
                jobs.append(job)

    log.info("WUZZUF: fetched %s jobs from %s page requests.", len(jobs), pages_requested)
    return jobs


def parse_wuzzuf_html(page_html: str, page_url: str = BASE_URL) -> list[Job]:
    """Parse visible WUZZUF job cards from a search/category HTML page."""
    if not page_html:
        return []

    matches = list(JOB_LINK_RE.finditer(page_html))
    jobs: list[Job] = []
    seen_urls: set[str] = set()

    for index, match in enumerate(matches):
        href = html.unescape(match.group("href"))
        title = _clean_html(match.group("title"))
        if not title:
            continue

        url = urljoin(BASE_URL, href).split("?")[0]
        if url in seen_urls:
            continue
        seen_urls.add(url)

        next_start = matches[index + 1].start() if index + 1 < len(matches) else len(page_html)
        card_html = page_html[match.end():next_start]
        company, location = _extract_company_location(card_html)
        job_type = _extract_job_type(card_html)
        is_remote = _is_remote_text(card_html)
        tags = _extract_tags(card_html)

        job = Job(
            title=title,
            company=company,
            location=location,
            url=url,
            source="wuzzuf",
            salary="",
            job_type=job_type,
            tags=tags,
            is_remote=is_remote,
        )
        # Dynamic attribute used by db.py if present; Job dataclass has no source_job_id field yet.
        setattr(job, "source_job_id", _extract_source_job_id(url))
        jobs.append(job)

    return jobs


def _extract_company_location(card_html: str) -> tuple[str, str]:
    """Extract company and location from the area after a WUZZUF title link."""
    company = ""
    company_match = CAREER_LINK_RE.search(card_html)
    if company_match:
        company = _clean_html(company_match.group("company")).strip(" -")

    # The location is usually the first span after the company career link.
    search_area = card_html[company_match.end():] if company_match else card_html
    location = ""
    for span_match in SPAN_RE.finditer(search_area):
        candidate = _clean_html(span_match.group(1)).strip(" -")
        if _looks_like_location(candidate):
            location = candidate
            break

    # Fallback for compact/plain snippets: "Company - Cairo, Egypt".
    if not company or not location:
        text = _clean_html(card_html)
        fallback = re.search(r"(?P<company>[^\n|]+?)\s+-\s+(?P<location>[^\n]+?(?:Egypt|مصر|Saudi Arabia|السعودية))", text, re.IGNORECASE)
        if fallback:
            company = company or fallback.group("company").strip()
            location = location or fallback.group("location").strip()

    return company, location


def _extract_job_type(card_html: str) -> str:
    values = []
    text = _clean_html(card_html)
    for pattern in JOB_TYPE_PATTERNS + WORKPLACE_PATTERNS:
        if pattern.lower() in text.lower() and pattern not in values:
            values.append(pattern)
    return " | ".join(values[:3])


def _extract_tags(card_html: str, limit: int = 18) -> list[str]:
    tags: list[str] = []
    blocked = {"apply", "view", "log in", "get started"}

    for match in TAG_RE.finditer(card_html):
        raw = match.group(1) or match.group(2) or ""
        text = _clean_html(raw)
        if not text:
            continue
        if text.lower() in blocked:
            continue
        if _looks_like_noise_tag(text):
            continue
        if text not in tags:
            tags.append(text)
        if len(tags) >= limit:
            break

    return tags


def _with_start(url: str, start: int) -> str:
    """Add/replace WUZZUF pagination start parameter."""
    if start <= 0:
        return url
    split = urlsplit(url)
    pairs = [(k, v) for k, v in parse_qsl(split.query, keep_blank_values=True) if k != "start"]
    pairs.append(("start", str(start)))
    return urlunsplit((split.scheme, split.netloc, split.path, urlencode(pairs), split.fragment))


def _extract_source_job_id(url: str) -> str:
    match = JOB_ID_RE.search(url)
    return match.group(1) if match else ""


def _is_remote_text(raw_html: str) -> bool:
    text = _clean_html(raw_html).lower()
    return any(marker in text for marker in REMOTE_MARKERS)


def _looks_like_location(text: str) -> bool:
    lowered = text.lower()
    location_markers = (
        "egypt",
        "مصر",
        "cairo",
        "giza",
        "alexandria",
        "saudi",
        "riyadh",
        "jeddah",
        "remote",
    )
    return any(marker in lowered for marker in location_markers)


def _looks_like_noise_tag(text: str) -> bool:
    lowered = text.lower()
    if len(text) > 70:
        return True
    if "jobs and careers at" in lowered:
        return True
    if lowered.endswith("ago"):
        return True
    if re.search(r"\b\d+\s*-\s*\d+\s+yrs?\b", lowered):
        return True
    return False


def _clean_html(value: str) -> str:
    """Remove tags/entities and normalize whitespace."""
    value = re.sub(r"<script\b.*?</script>", " ", value, flags=re.IGNORECASE | re.DOTALL)
    value = re.sub(r"<style\b.*?</style>", " ", value, flags=re.IGNORECASE | re.DOTALL)
    value = re.sub(r"<[^>]+>", " ", value)
    value = html.unescape(value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()
