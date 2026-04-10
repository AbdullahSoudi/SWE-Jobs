"""
Shared Playwright browser helpers for scrapers that need JS rendering.

Usage:
    from sources.playwright_utils import get_browser_page

    with get_browser_page() as page:
        page.goto("https://example.com")
        html = page.content()
"""

import logging
from contextlib import contextmanager
from playwright.sync_api import sync_playwright

log = logging.getLogger(__name__)

# Default timeout for page loads (ms)
PAGE_TIMEOUT = 30_000


@contextmanager
def get_browser_page(headless: bool = True):
    """
    Context manager that yields a Playwright page.
    Launches Chromium, creates a single page, and tears everything down on exit.
    """
    pw = sync_playwright().start()
    try:
        browser = pw.chromium.launch(headless=headless)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 900},
            locale="en-US",
        )
        page = context.new_page()
        page.set_default_timeout(PAGE_TIMEOUT)
        yield page
    except Exception as e:
        log.error(f"Playwright browser error: {e}")
        raise
    finally:
        try:
            browser.close()
        except Exception:
            pass
        pw.stop()
