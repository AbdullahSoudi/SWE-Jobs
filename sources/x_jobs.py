"""
X (Twitter) — Playwright-based scraper for job posts on x.com.

Scrapes public search results for tech job hashtags and keywords.
Note: X may require login for full search results. If no results are found,
ensure TWITTER_COOKIES_FILE points to a cookies JSON file (exported via a
browser extension like "EditThisCookie") or set X_AUTH_TOKEN env var.
"""

import json
import logging
import os
import re
import time
from core.models import Job
from sources.playwright_utils import get_browser_page

log = logging.getLogger(__name__)

SEARCH_BASE = "https://x.com/search"

# Search queries — sorted by relevance to SWE jobs
SEARCH_QUERIES = [
    '#hiring software engineer -is:reply',
    '#hiring backend developer -is:reply',
    '#hiring frontend developer -is:reply',
    '#hiring devops -is:reply',
    '#hiring flutter developer -is:reply',
    '#techjobs remote developer -is:reply',
    '#hiring data scientist -is:reply',
    '#remotejobs software engineer -is:reply',
    '#hiring mobile developer -is:reply',
]

# How many scroll iterations per search (each scroll loads ~5-10 tweets)
MAX_SCROLLS = 3
SCROLL_PAUSE = 2


def fetch_x_jobs() -> list[Job]:
    """Fetch job posts from X/Twitter search using Playwright."""
    jobs = []
    seen_urls = set()

    cookies_file = os.getenv("TWITTER_COOKIES_FILE", "")
    auth_token = os.getenv("X_AUTH_TOKEN", "")

    try:
        with get_browser_page() as page:
            # Authenticate if credentials provided
            if cookies_file and os.path.isfile(cookies_file):
                _load_cookies(page, cookies_file)
            elif auth_token:
                _set_auth_token(page, auth_token)

            for query in SEARCH_QUERIES:
                try:
                    parsed = _scrape_search(page, query)
                    for job in parsed:
                        if job.url not in seen_urls:
                            seen_urls.add(job.url)
                            jobs.append(job)
                except Exception as e:
                    log.warning(f"X: error on search '{query}': {e}")
                    continue

    except Exception as e:
        log.error(f"X: browser launch failed: {e}")

    log.debug(f"X: fetched {len(jobs)} jobs.")
    return jobs


def _load_cookies(page, cookies_file: str):
    """Load cookies from a JSON file (EditThisCookie export format)."""
    try:
        page.goto("https://x.com", wait_until="domcontentloaded")
        with open(cookies_file, "r") as f:
            cookies = json.load(f)
        # Normalize to Playwright cookie format
        pw_cookies = []
        for c in cookies:
            pw_cookies.append({
                "name": c.get("name", ""),
                "value": c.get("value", ""),
                "domain": c.get("domain", ".x.com"),
                "path": c.get("path", "/"),
                "secure": c.get("secure", True),
                "httpOnly": c.get("httpOnly", False),
                "sameSite": c.get("sameSite", "None"),
            })
        page.context.add_cookies(pw_cookies)
        log.info("X: loaded cookies from file.")
    except Exception as e:
        log.warning(f"X: failed to load cookies: {e}")


def _set_auth_token(page, token: str):
    """Set auth_token cookie for X authentication."""
    try:
        page.goto("https://x.com", wait_until="domcontentloaded")
        page.context.add_cookies([{
            "name": "auth_token",
            "value": token,
            "domain": ".x.com",
            "path": "/",
            "secure": True,
            "httpOnly": True,
            "sameSite": "None",
        }])
        log.info("X: set auth_token cookie.")
    except Exception as e:
        log.warning(f"X: failed to set auth_token: {e}")


def _scrape_search(page, query: str) -> list[Job]:
    """Run a single search query and extract job-like tweets."""
    jobs = []
    params = f"?q={query}&src=typed_query&f=live"
    page.goto(f"{SEARCH_BASE}{params}", wait_until="domcontentloaded")

    # Wait for tweets to load
    try:
        page.wait_for_selector('article[data-testid="tweet"]', timeout=15_000)
    except Exception:
        log.debug(f"X: no tweets found for '{query}'")
        return jobs

    # Scroll to load more tweets
    for _ in range(MAX_SCROLLS):
        page.mouse.wheel(0, 3000)
        time.sleep(SCROLL_PAUSE)

    # Extract all tweet articles
    tweets = page.query_selector_all('article[data-testid="tweet"]')

    for tweet in tweets:
        try:
            job = _parse_tweet(tweet)
            if job:
                jobs.append(job)
        except Exception as e:
            log.debug(f"X: error parsing tweet: {e}")
            continue

    return jobs


def _parse_tweet(tweet) -> Job | None:
    """Parse a tweet element into a Job if it looks like a job posting."""
    # Get tweet text
    text_el = tweet.query_selector('div[data-testid="tweetText"]')
    if not text_el:
        return None
    text = text_el.inner_text().strip()

    if not text or len(text) < 30:
        return None

    # Must contain job-related signals
    text_lower = text.lower()
    job_signals = ["hiring", "looking for", "job opening", "open position",
                   "we're hiring", "we are hiring", "join our team",
                   "apply now", "job alert", "vacancy", "developer needed",
                   "engineer needed"]
    if not any(signal in text_lower for signal in job_signals):
        return None

    # Extract title — first line or text before the first newline
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    title = _extract_title(lines, text_lower)
    if not title:
        return None

    # Get tweet permalink
    time_el = tweet.query_selector("time")
    link_el = time_el.evaluate_handle(
        "el => el.closest('a')"
    ) if time_el else None
    tweet_url = ""
    if link_el:
        href = link_el.get_attribute("href")
        if href:
            tweet_url = f"https://x.com{href}" if not href.startswith("http") else href

    if not tweet_url:
        # Fallback: find any link in the tweet
        links = tweet.query_selector_all('a[href*="/status/"]')
        for link in links:
            href = link.get_attribute("href") or ""
            if "/status/" in href:
                tweet_url = f"https://x.com{href}" if not href.startswith("http") else href
                break

    if not tweet_url:
        return None

    # Extract company from username/display name
    name_el = tweet.query_selector('div[data-testid="User-Name"]')
    company = ""
    if name_el:
        spans = name_el.query_selector_all("span")
        for span in spans:
            txt = span.inner_text().strip()
            if txt and not txt.startswith("@") and txt != "·":
                company = txt
                break

    # Try to extract location from text
    location = _extract_location(text)

    # Check for remote
    is_remote = any(w in text_lower for w in ["remote", "work from home", "wfh",
                                               "anywhere", "distributed"])

    # Extract apply link if present
    apply_url = _extract_apply_link(tweet, text)
    job_url = apply_url or tweet_url

    # Extract salary if mentioned
    salary_raw = _extract_salary(text)

    return Job(
        title=title,
        company=company,
        location=location or ("Remote" if is_remote else ""),
        url=job_url,
        source="x",
        original_source="X (Twitter)",
        salary_raw=salary_raw,
        is_remote=is_remote,
    )


def _extract_title(lines: list[str], text_lower: str) -> str:
    """Try to extract a job title from tweet lines."""
    # Common title patterns in job tweets
    title_patterns = [
        r'(?:hiring|looking for|seeking)\s*(?:a|an)?\s*(.+?)(?:\n|$|!|\.|,)',
        r'(?:position|role|opening):\s*(.+?)(?:\n|$|!|\.|,)',
        r'((?:senior|junior|mid|lead|staff|principal)?\s*(?:software|backend|frontend|full[- ]?stack|mobile|flutter|devops|cloud|data|ml|ai|qa|security|game|blockchain|web)\s*(?:engineer|developer|scientist|analyst|architect|tester))',
    ]
    for pattern in title_patterns:
        match = re.search(pattern, text_lower)
        if match:
            title = match.group(1).strip().title()
            if len(title) > 10:
                return title[:120]

    # Fallback: use first non-empty line that looks like a title
    for line in lines[:3]:
        line_clean = re.sub(r'[#@]\S+', '', line).strip()
        if 10 < len(line_clean) < 120:
            return line_clean

    return ""


def _extract_location(text: str) -> str:
    """Try to pull location info from tweet text."""
    loc_patterns = [
        r'(?:location|based in|located in|office in)[:\s]+([A-Za-z, ]+)',
        r'📍\s*([A-Za-z, ]+)',
    ]
    for pattern in loc_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1).strip()[:80]
    return ""


def _extract_apply_link(tweet, text: str) -> str:
    """Try to find an external apply link in the tweet."""
    # Check for t.co links that are not x.com internal
    links = tweet.query_selector_all('a[href]')
    for link in links:
        href = link.get_attribute("href") or ""
        # External links in tweets use t.co redirects
        if "t.co/" in href:
            displayed = link.inner_text().strip()
            # Skip x.com internal links
            if displayed and not displayed.startswith("x.com") and not displayed.startswith("twitter.com"):
                return href
    return ""


def _extract_salary(text: str) -> str:
    """Try to extract salary info from text."""
    salary_patterns = [
        r'(\$[\d,]+\s*[-–]\s*\$[\d,]+(?:\s*(?:k|K|/yr|/year|per year))?)',
        r'([\d,]+\s*[-–]\s*[\d,]+\s*(?:USD|EUR|GBP|EGP))',
        r'(?:salary|comp|compensation)[:\s]+([^\n]{5,50})',
    ]
    for pattern in salary_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return ""
