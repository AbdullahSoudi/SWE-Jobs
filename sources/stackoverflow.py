"""Stack Overflow Jobs RSS feed."""

import logging
import xml.etree.ElementTree as ET
from core.models import Job
from sources.http_utils import get_text

log = logging.getLogger(__name__)

RSS_URL = "https://stackoverflow.com/jobs/feed"


def fetch_stackoverflow() -> list[Job]:
    """Fetch jobs from Stack Overflow Jobs RSS feed."""
    xml_text = get_text(RSS_URL)
    if not xml_text:
        log.warning("StackOverflow Jobs: no data (feed may be discontinued).")
        return []

    jobs = []
    try:
        root = ET.fromstring(xml_text)
        for item in root.findall(".//item"):
            title = item.findtext("title", "").strip()
            link = item.findtext("link", "").strip()
            if not title or not link:
                continue

            # Extract author/company
            # RSS uses <author> or <dc:creator>
            company = ""
            for tag in ("author", "{http://purl.org/dc/elements/1.1/}creator"):
                company = item.findtext(tag, "").strip()
                if company:
                    break

            # Extract location from <location> or category tags
            location = item.findtext("location", "").strip()
            if not location:
                location = item.findtext(
                    "{http://stackoverflow.com/jobs/}location", ""
                ).strip() or "Unknown"

            # Collect category tags
            tags = [
                cat.text.strip()
                for cat in item.findall("category")
                if cat.text and cat.text.strip()
            ]

            jobs.append(Job(
                title=title,
                company=company,
                location=location,
                url=link,
                source="stackoverflow",
                tags=tags,
                is_remote="remote" in location.lower(),
            ))
    except ET.ParseError as e:
        log.warning(f"StackOverflow Jobs: XML parse error: {e}")

    log.debug(f"StackOverflow Jobs: fetched {len(jobs)} jobs.")
    return jobs
