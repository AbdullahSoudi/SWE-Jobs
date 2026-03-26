"""Working Nomads — RSS feed for development jobs."""

import logging
import xml.etree.ElementTree as ET
from models import Job
from sources.http_utils import get_text

log = logging.getLogger(__name__)

URL = "https://www.workingnomads.com/jobsrss/development"


def fetch_workingnomads() -> list[Job]:
    """Fetch jobs from Working Nomads RSS."""
    xml_text = get_text(URL)
    if not xml_text:
        log.warning("Working Nomads: no data.")
        return []

    jobs = []
    try:
        root = ET.fromstring(xml_text)
        for item in root.findall(".//item"):
            title = item.findtext("title", "")
            link = item.findtext("link", "")
            desc = item.findtext("description", "")
            category = item.findtext("category", "")

            # Try to extract company from description
            company = ""
            if " at " in title:
                parts = title.rsplit(" at ", 1)
                title = parts[0].strip()
                company = parts[1].strip()

            jobs.append(Job(
                title=title,
                company=company,
                location="Remote",
                url=link.strip(),
                source="workingnomads",
                tags=[category] if category else [],
                is_remote=True,
            ))
    except ET.ParseError as e:
        log.warning(f"Working Nomads: XML parse error: {e}")

    log.info(f"Working Nomads: fetched {len(jobs)} jobs.")
    return jobs
