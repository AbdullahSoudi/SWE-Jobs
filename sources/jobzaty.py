"""Low-rate Saudi Jobzaty discovery adapter.

Jobzaty is useful as a Saudi market discovery signal, but its public category
cards do not expose minute-level publication time and many listings aggregate
multiple openings into one announcement.  This adapter therefore stays
``discovery-only``: it is fetched in shadow mode for coverage/dedup/registry
measurement, but it is not eligible to create Telegram deliveries.

Only public category pages are read, at a deliberately low cadence.  No login,
private profile, application endpoint, CAPTCHA, or access-control bypass is
used.
"""
from __future__ import annotations

import html
import logging
import re
from typing import Callable
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

from models import Job

try:  # final project layout
    from sources.http_utils import get_text
except ModuleNotFoundError:  # flat-file test layout
    from http_utils import get_text

log = logging.getLogger(__name__)

BASE_URL = "https://www.jobzaty.com"

# Narrow Saudi tech categories only.  The category label is carried as a tag so
# the bilingual classifier can recognize generic announcement titles such as
# "وظائف تقنية شاغرة" without crawling the whole site.
JOBZATY_CATEGORY_FEEDS: tuple[tuple[str, str], ...] = (
    (f"{BASE_URL}/jobs/category/programming-web-development", "البرمجة وتطوير الويب"),
    (f"{BASE_URL}/jobs/category/cybersecurity-jobs", "الأمن السيبراني"),
    (f"{BASE_URL}/jobs/category/information-technology", "تقنية المعلومات"),
)

JOB_LINK_RE = re.compile(
    r'<a\b[^>]*href=["\'](?P<href>[^"\']*/job/[^"\']+)["\'][^>]*>(?P<title>.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)
JOB_ID_RE = re.compile(r"/job/([^/?#]+)", re.IGNORECASE)

ELIGIBILITY_VALUES = ("سعودي أو مقيم", "سعودي فقط", "غير محدد", "متاحة للجميع")
JOB_TYPE_VALUES = (
    "دوام كامل",
    "دوام جزئي",
    "دوام جزئى",
    "فترة تدريب",
    "متعاقد",
    "موظف مستقل",
    "عن بُعد",
    "عن بعد",
)

# Longest aliases first so "المدينة المنورة" wins over a shorter token.
SAUDI_LOCATION_VALUES = (
    "المدينة المنورة",
    "مناطق متفرقة",
    "خميس مشيط",
    "رأس تنورة",
    "حفر الباطن",
    "ظهران الجنوب",
    "غير محدد",
    "الرياض",
    "جدة",
    "مكة",
    "الدمام",
    "الخبر",
    "الظهران",
    "الأحساء",
    "القطيف",
    "الجبيل",
    "بقيق",
    "ينبع",
    "العلا",
    "تبوك",
    "نيوم",
    "الطائف",
    "أبها",
    "حائل",
    "جازان",
    "نجران",
    "بريدة",
    "عنيزة",
    "الخرج",
    "عن بُعد",
    "عن بعد",
)

_NOISE_LINE_PATTERNS = (
    "بحث",
    "عرض المزيد",
    "عرض الصفحات",
    "الصفحة الرئيسية",
    "وظائف السعودية",
)


def fetch_jobzaty(
    category_feeds: tuple[tuple[str, str], ...] | list[tuple[str, str]] | None = None,
    *,
    max_pages_per_category: int = 1,
    http_getter: Callable[[str], str | None] | None = None,
) -> list[Job]:
    """Fetch a small, public Saudi tech discovery window from Jobzaty.

    ``max_pages_per_category`` defaults to one on purpose.  This is not an
    archive crawler; the source is only being measured as a current discovery
    signal and has no safe minute-level freshness proof yet.
    """
    if max_pages_per_category < 1:
        raise ValueError("max_pages_per_category must be >= 1")

    getter = http_getter or get_text
    feeds = tuple(category_feeds or JOBZATY_CATEGORY_FEEDS)
    jobs: list[Job] = []
    seen_ids: set[str] = set()
    requested = 0

    for base_url, category_tag in feeds:
        for page in range(1, max_pages_per_category + 1):
            url = _with_page(base_url, page)
            requested += 1
            page_html = getter(url)
            if not page_html:
                log.warning("Jobzaty: no response for %s", url)
                continue

            for job in parse_jobzaty_listing(page_html, page_url=url, category_tag=category_tag):
                key = job.source_job_id or job.url.lower().rstrip("/")
                if key in seen_ids:
                    continue
                seen_ids.add(key)
                jobs.append(job)

    log.info("Jobzaty discovery: fetched %s cards from %s page requests.", len(jobs), requested)
    return jobs


def parse_jobzaty_listing(page_html: str, *, page_url: str = BASE_URL, category_tag: str = "") -> list[Job]:
    """Parse public Jobzaty category cards without assuming CSS class names."""
    if not page_html:
        return []

    matches = list(JOB_LINK_RE.finditer(page_html))
    jobs: list[Job] = []
    seen_ids: set[str] = set()

    for index, match in enumerate(matches):
        href = html.unescape(match.group("href"))
        title = _clean_html(match.group("title"))
        if not title:
            continue

        url = urljoin(page_url, href).split("#", 1)[0]
        source_job_id = _source_job_id(url)
        if not source_job_id or source_job_id in seen_ids:
            continue
        seen_ids.add(source_job_id)

        next_start = matches[index + 1].start() if index + 1 < len(matches) else len(page_html)
        card_html = page_html[match.end():next_start]
        lines = _html_lines(card_html)
        location = _find_value(lines, SAUDI_LOCATION_VALUES)
        eligibility = _find_value(lines, ELIGIBILITY_VALUES)
        job_type = _find_value(lines, JOB_TYPE_VALUES)
        company = _find_company(lines, title=title, location=location, eligibility=eligibility, job_type=job_type)

        # Category pages are Saudi-only by product design. Unknown city is kept
        # as country-level Saudi instead of inventing a city.
        normalized_location = "Saudi Arabia" if not location or location == "غير محدد" else f"{location}, Saudi Arabia"
        is_remote = location in {"عن بُعد", "عن بعد"} or job_type in {"عن بُعد", "عن بعد"}
        tags = [value for value in (category_tag, eligibility) if value]

        jobs.append(Job(
            title=title,
            company=company,
            location=normalized_location,
            url=url,
            source="jobzaty",
            source_job_id=source_job_id,
            original_source="Jobzaty",
            job_type=job_type,
            tags=tags,
            is_remote=is_remote,
            # No publication fields on purpose. The listing cards do not prove
            # minute-level freshness, so runtime will keep this source discovery-only.
        ))

    return jobs


def _with_page(url: str, page: int) -> str:
    if page <= 1:
        return url
    split = urlsplit(url)
    pairs = [(k, v) for k, v in parse_qsl(split.query, keep_blank_values=True) if k != "page"]
    pairs.append(("page", str(page)))
    return urlunsplit((split.scheme, split.netloc, split.path, urlencode(pairs), split.fragment))


def _source_job_id(url: str) -> str:
    match = JOB_ID_RE.search(url or "")
    return match.group(1).lower() if match else ""


def _find_value(lines: list[str], values: tuple[str, ...]) -> str:
    for line in lines:
        for value in values:
            if value in line:
                return value
    return ""


def _find_company(lines: list[str], *, title: str, location: str, eligibility: str, job_type: str) -> str:
    blocked = {title, location, eligibility, job_type, *ELIGIBILITY_VALUES, *JOB_TYPE_VALUES}
    for line in lines:
        candidate = line.strip(" -|·")
        if not candidate or candidate in blocked:
            continue
        if any(noise in candidate for noise in _NOISE_LINE_PATTERNS):
            continue
        if any(location_value in candidate for location_value in SAUDI_LOCATION_VALUES):
            continue
        if len(candidate) > 140:
            continue
        return candidate
    return ""


def _html_lines(value: str) -> list[str]:
    text = re.sub(
        r"</?(?:div|p|li|section|article|h[1-6]|br|tr|td|span)\b[^>]*>",
        "\n",
        value,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"<script\b.*?</script>", " ", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<style\b.*?</style>", " ", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    lines = []
    for raw in text.splitlines():
        cleaned = re.sub(r"\s+", " ", raw).strip()
        if cleaned and cleaned not in lines:
            lines.append(cleaned)
    return lines


def _clean_html(value: str) -> str:
    text = re.sub(r"<[^>]+>", " ", value or "")
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()
