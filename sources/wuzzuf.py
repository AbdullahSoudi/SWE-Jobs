"""
Wuzzuf — Playwright-based scraper for wuzzuf.net (Egypt's largest job board).
Scrapes software/tech job listings across multiple search queries.
"""

import logging
import re
from core.models import Job
from sources.playwright_utils import get_browser_page

log = logging.getLogger(__name__)

BASE_URL = "https://wuzzuf.net/search/jobs/"

# Search queries targeting SWE roles in Egypt
SEARCHES = [
    {"q": "software engineer", "a": "hpb"},
    {"q": "software developer", "a": "hpb"},
    {"q": "backend developer", "a": "hpb"},
    {"q": "frontend developer", "a": "hpb"},
    {"q": "full stack developer", "a": "hpb"},
    {"q": "mobile developer", "a": "hpb"},
    {"q": "flutter developer", "a": "hpb"},
    {"q": "devops engineer", "a": "hpb"},
    {"q": "data scientist", "a": "hpb"},
    {"q": "machine learning engineer", "a": "hpb"},
    {"q": "QA engineer", "a": "hpb"},
]


def fetch_wuzzuf() -> list[Job]:
    """Fetch jobs from Wuzzuf using Playwright."""
    jobs = []
    seen_urls = set()

    try:
        with get_browser_page() as page:
            for params in SEARCHES:
                try:
                    query = params["q"].replace(" ", "+")
                    url = f"{BASE_URL}?q={query}&a={params['a']}"
                    page.goto(url, wait_until="domcontentloaded")
                    page.wait_for_selector("div.css-1gatmva", timeout=10_000)

                    cards = page.query_selector_all("div.css-1gatmva")
                    if not cards:
                        # Fallback: try alternate card selector
                        cards = page.query_selector_all("div.css-pkv5jc")

                    for card in cards:
                        try:
                            job = _parse_card(card)
                            if job and job.url not in seen_urls:
                                seen_urls.add(job.url)
                                jobs.append(job)
                        except Exception as e:
                            log.debug(f"Wuzzuf: error parsing card: {e}")
                            continue

                except Exception as e:
                    log.warning(f"Wuzzuf: error on search '{params['q']}': {e}")
                    continue

    except Exception as e:
        log.error(f"Wuzzuf: browser launch failed: {e}")

    log.debug(f"Wuzzuf: fetched {len(jobs)} jobs.")
    return jobs


def _parse_card(card) -> Job | None:
    """Parse a single Wuzzuf job card element into a Job."""
    # Title & URL
    title_el = card.query_selector("h2 a, a.css-o171kl")
    if not title_el:
        return None
    title = title_el.inner_text().strip()
    href = title_el.get_attribute("href") or ""
    if not title or not href:
        return None
    url = href if href.startswith("http") else f"https://wuzzuf.net{href}"

    # Company
    company_el = card.query_selector("a.css-17s97q8, div.css-d7j1kk a")
    company = company_el.inner_text().strip() if company_el else ""

    # Location
    location_el = card.query_selector("span.css-5wys0k, span.css-db2dqe")
    location = location_el.inner_text().strip() if location_el else "Egypt"

    # Job type & experience
    tags = []
    tag_els = card.query_selector_all("div.css-1lh32fc span, span.css-1ve4b7d")
    for tag_el in tag_els:
        tag_text = tag_el.inner_text().strip()
        if tag_text:
            tags.append(tag_text)

    # Salary (rarely shown, but sometimes present)
    salary_raw = ""
    salary_el = card.query_selector("span.css-4xky9y, div.css-3udp1v")
    if salary_el:
        salary_raw = salary_el.inner_text().strip()

    is_remote = "remote" in location.lower() or any("remote" in t.lower() for t in tags)

    # Detect job type from tags
    job_type = ""
    type_keywords = {"full time": "Full-time", "part time": "Part-time",
                     "freelance": "Freelance", "contract": "Contract",
                     "internship": "Internship"}
    for tag in tags:
        for kw, jt in type_keywords.items():
            if kw in tag.lower():
                job_type = jt
                break

    return Job(
        title=title,
        company=company,
        location=location,
        url=url,
        source="wuzzuf",
        salary_raw=salary_raw,
        job_type=job_type,
        is_remote=is_remote,
        country="Egypt",
        tags=tags,
    )
