"""LinkedIn source adapter (limited public guest search).

This adapter intentionally uses a small, conservative set of public job-search
requests and parses only visible search-card fields: title, company, location,
URL, and lightweight remote/job-type signals. It does not log in, does not open
job detail pages, and does not collect descriptions or recruiter/member data.
"""

from __future__ import annotations

import html
import logging
import os
import re
import time
from typing import Callable
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

from models import Job

try:  # final project layout
    from sources.http_utils import get_text
except ModuleNotFoundError:  # local flat-file test layout
    from http_utils import get_text

log = logging.getLogger(__name__)

SEARCH_URL = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
BASE_URL = "https://www.linkedin.com"

# Keep this intentionally small. LinkedIn is a high-risk/fragile source, so it
# should enrich WUZZUF rather than dominate the bot's runtime.
# f_TPR=r3600 => last 1 hour; sortBy=DD => newest first.
# We intentionally use a rolling 1-hour freshness window while the workflow runs
# every ~15 minutes. Deduplication in SQLite removes overlap, and the wider
# window reduces the chance of missing jobs when GitHub Actions starts late.
DEFAULT_FRESHNESS_SECONDS = int(os.getenv("LINKEDIN_FRESHNESS_SECONDS", "3600"))
LINKEDIN_DEFAULT_PARAMS = {"f_TPR": f"r{DEFAULT_FRESHNESS_SECONDS}", "sortBy": "DD"}


def _fresh_params(**params: str) -> dict[str, str]:
    merged = dict(LINKEDIN_DEFAULT_PARAMS)
    merged.update(params)
    return merged


LINKEDIN_SEARCHES: list[dict[str, str]] = [
    # Egypt — core community topics
    _fresh_params(keywords="software developer", location="Egypt"),
    _fresh_params(keywords="backend developer", location="Egypt"),
    _fresh_params(keywords="frontend developer", location="Egypt"),
    _fresh_params(keywords="mobile developer", location="Egypt"),
    _fresh_params(keywords="data analyst", location="Egypt"),
    _fresh_params(keywords="digital marketing", location="Egypt"),
    _fresh_params(keywords="graphic designer", location="Egypt"),
    _fresh_params(keywords="business analyst", location="Egypt"),
    _fresh_params(keywords="application support", location="Egypt"),
    _fresh_params(keywords="odoo developer", location="Egypt"),
    _fresh_params(keywords="QA engineer", location="Egypt"),
    _fresh_params(keywords="devops engineer", location="Egypt"),
    _fresh_params(keywords="product manager", location="Egypt"),
    # Saudi — smaller coverage
    _fresh_params(keywords="software developer", location="Saudi Arabia"),
    _fresh_params(keywords="data analyst", location="Saudi Arabia"),
    _fresh_params(keywords="digital marketing", location="Saudi Arabia"),
    _fresh_params(keywords="business analyst", location="Saudi Arabia"),
    _fresh_params(keywords="application support", location="Saudi Arabia"),
    _fresh_params(keywords="SAP developer", location="Saudi Arabia"),
    # Remote — limited, global
    _fresh_params(keywords="software developer", f_WT="2"),
    _fresh_params(keywords="data analyst", f_WT="2"),
    _fresh_params(keywords="digital marketing", f_WT="2"),
    _fresh_params(keywords="ui ux designer", f_WT="2"),
]

DEFAULT_REQUEST_DELAY_SECONDS = float(os.getenv("LINKEDIN_REQUEST_DELAY", "4"))
DEFAULT_MAX_PAGES_PER_SEARCH = int(os.getenv("LINKEDIN_MAX_PAGES_PER_SEARCH", "1"))
PAGE_SIZE = 25

CARD_RE = re.compile(
    r"<li\b[^>]*>(?P<card>.*?)</li>",
    re.IGNORECASE | re.DOTALL,
)
TITLE_RE = re.compile(
    r'class=["\'][^"\']*base-search-card__title[^"\']*["\'][^>]*>(?P<title>.*?)</(?:h3|a|span|div)>',
    re.IGNORECASE | re.DOTALL,
)
COMPANY_RE = re.compile(
    r'class=["\'][^"\']*base-search-card__subtitle[^"\']*["\'][^>]*>(?P<company>.*?)</(?:h4|a|span|div)>',
    re.IGNORECASE | re.DOTALL,
)
LOCATION_RE = re.compile(
    r'class=["\'][^"\']*job-search-card__location[^"\']*["\'][^>]*>(?P<location>.*?)</span>',
    re.IGNORECASE | re.DOTALL,
)
URL_RE = re.compile(
    r'href=["\'](?P<url>https?://[^"\']*linkedin\.com/jobs/view/[^"\']+|/jobs/view/[^"\']+)["\']',
    re.IGNORECASE,
)
JOB_ID_RE = re.compile(r"/jobs/view/(?:[^/?#]*-)?(?P<id>\d+)(?:[/?#]|$)", re.IGNORECASE)
TAG_TEXT_PATTERNS = (
    "Full-time",
    "Part-time",
    "Contract",
    "Temporary",
    "Internship",
    "Volunteer",
    "Remote",
    "Hybrid",
    "On-site",
)
REMOTE_MARKERS = ("remote", "work from home", "wfh", "anywhere", "worldwide")
CLOSED_JOB_MARKERS = (
    "no longer accepting applications",
    "this job is no longer accepting applications",
    "job is no longer available",
    "no longer available",
    "expired",
    "closed",
)


def fetch_linkedin(
    searches: list[dict[str, str]] | None = None,
    max_pages_per_search: int = DEFAULT_MAX_PAGES_PER_SEARCH,
    request_delay: float = DEFAULT_REQUEST_DELAY_SECONDS,
    http_getter: Callable[..., str | None] | None = None,
) -> list[Job]:
    """Fetch a limited set of public LinkedIn guest job-search result cards.

    Args:
        searches: Optional search override for tests/targeted runs.
        max_pages_per_search: Number of result pages to request per search.
        request_delay: Delay between requests; set 0 in tests.
        http_getter: Injectable getter. Defaults to shared get_text.
    """
    if max_pages_per_search < 1:
        raise ValueError("max_pages_per_search must be >= 1")
    if request_delay < 0:
        raise ValueError("request_delay must be >= 0")

    getter = http_getter or get_text
    selected_searches = searches or LINKEDIN_SEARCHES
    jobs: list[Job] = []
    seen_urls: set[str] = set()
    pages_requested = 0

    for base_params in selected_searches:
        for page_idx in range(max_pages_per_search):
            params = dict(base_params)
            params["start"] = str(page_idx * PAGE_SIZE)
            pages_requested += 1

            page_html = getter(SEARCH_URL, params=params, headers=_headers())
            if not page_html:
                log.warning("LinkedIn: no response for %s", _safe_params_for_log(params))
                if request_delay:
                    time.sleep(request_delay)
                continue

            parsed = parse_linkedin_html(page_html, search_params=params, max_age_seconds=DEFAULT_FRESHNESS_SECONDS)
            for job in parsed:
                normalized_url = canonicalize_linkedin_url(job.url)
                if normalized_url in seen_urls:
                    continue
                seen_urls.add(normalized_url)
                jobs.append(job)

            if request_delay:
                time.sleep(request_delay)

    log.info("LinkedIn: fetched %s jobs from %s page requests.", len(jobs), pages_requested)
    return jobs


def parse_linkedin_html(
    page_html: str,
    search_params: dict[str, str] | None = None,
    max_age_seconds: int | None = None,
) -> list[Job]:
    """Parse visible LinkedIn guest search cards into Job objects.

    max_age_seconds is a defensive local freshness guard when the visible card
    contains a relative posting age such as "15 minutes ago" or "2 hours ago".
    Cards without visible age are kept because LinkedIn guest fragments do not
    always include this text; server-side f_TPR remains the primary freshness filter.
    """
    if not page_html:
        return []

    params = search_params or {}
    cards = _extract_cards(page_html)
    jobs: list[Job] = []
    seen_urls: set[str] = set()

    for card in cards:
        if _is_closed_or_inactive_card(card):
            continue
        if max_age_seconds is not None and _card_is_older_than(card, max_age_seconds):
            continue

        title = _clean(_match_group(TITLE_RE, card, "title"))
        raw_url = html.unescape(_match_group(URL_RE, card, "url"))
        if not title or not raw_url:
            continue

        url = canonicalize_linkedin_url(urljoin(BASE_URL, raw_url))
        if url in seen_urls:
            continue
        seen_urls.add(url)

        company = _clean(_match_group(COMPANY_RE, card, "company"))
        location = _clean(_match_group(LOCATION_RE, card, "location")) or params.get("location", "Remote")
        is_remote = params.get("f_WT") == "2" or _contains_remote_signal(f"{title} {location} {card}")
        job_type = _extract_job_type(card)
        tags = _extract_tags(card, job_type=job_type, is_remote=is_remote)

        job = Job(
            title=title,
            company=company,
            location=location,
            url=url,
            source="linkedin",
            salary="",
            job_type=job_type,
            tags=tags,
            is_remote=is_remote,
        )
        setattr(job, "source_job_id", extract_linkedin_job_id(url))
        jobs.append(job)

    return jobs


def _extract_cards(page_html: str) -> list[str]:
    cards = [m.group("card") for m in CARD_RE.finditer(page_html)]
    if cards:
        return cards
    # Fallback for compact fragments returned by LinkedIn when <li> wrappers change.
    return re.findall(
        r'(<div\b[^>]*class=["\'][^"\']*base-card[^"\']*["\'][\s\S]*?</div>\s*</div>\s*</div>)',
        page_html,
        re.IGNORECASE,
    )


def _match_group(pattern: re.Pattern[str], text: str, group: str) -> str:
    match = pattern.search(text)
    return match.group(group) if match else ""


def _extract_job_type(card_html: str) -> str:
    text = _clean(card_html)
    found: list[str] = []
    for pattern in TAG_TEXT_PATTERNS:
        if pattern.lower() in text.lower() and pattern not in found:
            found.append(pattern)
    return " | ".join(found[:3])


def _extract_tags(card_html: str, job_type: str = "", is_remote: bool = False) -> list[str]:
    tags: list[str] = []
    if job_type:
        tags.extend(part.strip() for part in job_type.split("|") if part.strip())
    if is_remote and "Remote" not in tags:
        tags.append("Remote")
    return tags[:8]


def _contains_remote_signal(text: str) -> bool:
    low = text.lower()
    return any(marker in low for marker in REMOTE_MARKERS)



def _is_closed_or_inactive_card(card_html: str) -> bool:
    text = _clean(card_html).lower()
    return any(marker in text for marker in CLOSED_JOB_MARKERS)


def _card_is_older_than(card_html: str, max_age_seconds: int) -> bool:
    age_seconds = _extract_relative_age_seconds(card_html)
    return age_seconds is not None and age_seconds > max_age_seconds


def _extract_relative_age_seconds(card_html: str) -> int | None:
    text = _clean(card_html).lower()
    if "just now" in text or "moments ago" in text:
        return 0

    patterns = [
        (r"(\d+)\s*(?:minute|minutes|min|mins)\s+ago", 60),
        (r"(\d+)\s*(?:hour|hours|hr|hrs)\s+ago", 3600),
        (r"(\d+)\s*(?:day|days)\s+ago", 86400),
        (r"(\d+)\s*(?:week|weeks)\s+ago", 604800),
    ]
    for pattern, multiplier in patterns:
        match = re.search(pattern, text)
        if match:
            return int(match.group(1)) * multiplier
    return None


def canonicalize_linkedin_url(url: str) -> str:
    """Return a mobile-friendly canonical LinkedIn job URL.

    LinkedIn guest cards may return locale/subdomain URLs such as
    eg.linkedin.com/jobs/view/backend-developer-at-x-1234567890?trk=...
    Telegram/mobile app handoff is more reliable with the plain universal-link
    shape: https://www.linkedin.com/jobs/view/<job_id>
    """
    if not url:
        return ""

    split = urlsplit(html.unescape(url.strip()))
    path = split.path.rstrip("/") or split.path
    job_id = extract_linkedin_job_id(path) or extract_linkedin_job_id(url)

    if job_id and "linkedin.com" in split.netloc.lower():
        return f"https://www.linkedin.com/jobs/view/{job_id}"

    # Fallback for unexpected LinkedIn job URLs where the numeric id is absent.
    # Strip volatile params/fragments and normalize any locale host (eg.linkedin.com,
    # sa.linkedin.com, www.linkedin.com) to www.linkedin.com.
    scheme = "https"
    netloc = "www.linkedin.com" if "linkedin.com" in split.netloc.lower() else split.netloc.lower()
    kept_query_pairs = []
    for key, value in parse_qsl(split.query, keep_blank_values=True):
        key_l = key.lower()
        if key_l.startswith("utm_") or key_l in {"refid", "trk", "ref", "trackingid", "position", "pagenum"}:
            continue
        kept_query_pairs.append((key, value))

    return urlunsplit((scheme, netloc, path, urlencode(kept_query_pairs, doseq=True), ""))


def extract_linkedin_job_id(url: str) -> str:
    match = JOB_ID_RE.search(url or "")
    return match.group("id") if match else ""


def _safe_params_for_log(params: dict[str, str]) -> dict[str, str]:
    """Return non-secret params; LinkedIn guest search has no secrets but keep helper explicit."""
    return {k: v for k, v in params.items() if k.lower() not in {"token", "key", "secret"}}


def _headers() -> dict[str, str]:
    return {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/125.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }


def _clean(text: object) -> str:
    if text is None:
        return ""
    value = html.unescape(str(text))
    value = re.sub(r"<[^>]+>", " ", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip(" \n\t-")
