"""Deterministic ATS URL detection for Saudi company-registry discovery.

This module intentionally performs no network requests. It recognizes public
career-board URLs already observed elsewhere and extracts the identifiers needed
by reusable ATS adapters. Unknown/custom career sites return ``None`` rather
than being guessed.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse


@dataclass(frozen=True)
class ATSDetection:
    ats: str
    tenant: str
    board_url: str
    host: str = ""
    site: str = ""
    locale: str = ""


def _parts(url: str) -> tuple[str, list[str]]:
    parsed = urlparse((url or "").strip())
    host = parsed.netloc.lower().split(":", 1)[0]
    parts = [part for part in parsed.path.split("/") if part]
    return host, parts


def _looks_like_locale(value: str) -> bool:
    return bool(re.fullmatch(r"[a-z]{2}(?:-[A-Z]{2})?", value or ""))


def detect_ats_url(url: str) -> ATSDetection | None:
    """Recognize Greenhouse, Lever, Ashby, or Workday public career URLs."""
    host, parts = _parts(url)
    if not host:
        return None

    if host.endswith(".myworkdayjobs.com"):
        # Internal public CXS endpoint:
        # /wday/cxs/{tenant}/{site}/jobs
        if len(parts) >= 5 and parts[:2] == ["wday", "cxs"]:
            tenant, site = parts[2], parts[3]
            return ATSDetection(
                "workday",
                tenant,
                f"https://{host}/en-US/{site}",
                host=host,
                site=site,
                locale="en-US",
            )

        # Human career URL:
        # /en-US/{site}/job/... or /{site}/job/...
        index = 0
        locale = "en-US"
        if parts and _looks_like_locale(parts[0]):
            locale = parts[0]
            index = 1
        if index < len(parts):
            site = parts[index]
            tenant = host.split(".", 1)[0]
            if site not in {"wday", "job", "jobs"}:
                return ATSDetection(
                    "workday",
                    tenant,
                    f"https://{host}/{locale}/{site}",
                    host=host,
                    site=site,
                    locale=locale,
                )
        return None

    if not parts:
        return None

    if host in {"job-boards.greenhouse.io", "boards.greenhouse.io"}:
        tenant = parts[0]
        return ATSDetection("greenhouse", tenant, f"https://job-boards.greenhouse.io/{tenant}")

    if host == "boards-api.greenhouse.io" and len(parts) >= 3 and parts[:2] == ["v1", "boards"]:
        tenant = parts[2]
        return ATSDetection("greenhouse", tenant, f"https://job-boards.greenhouse.io/{tenant}")

    if host in {"jobs.lever.co", "jobs.eu.lever.co"}:
        tenant = parts[0]
        base = "https://jobs.eu.lever.co" if host.startswith("jobs.eu") else "https://jobs.lever.co"
        return ATSDetection("lever", tenant, f"{base}/{tenant}")

    if host in {"api.lever.co", "api.eu.lever.co"} and len(parts) >= 3 and parts[:2] == ["v0", "postings"]:
        tenant = parts[2]
        base = "https://jobs.eu.lever.co" if host.startswith("api.eu") else "https://jobs.lever.co"
        return ATSDetection("lever", tenant, f"{base}/{tenant}")

    if host == "jobs.ashbyhq.com":
        tenant = parts[0]
        return ATSDetection("ashby", tenant, f"https://jobs.ashbyhq.com/{tenant}")

    if host == "api.ashbyhq.com" and len(parts) >= 3 and parts[:2] == ["posting-api", "job-board"]:
        tenant = parts[2]
        return ATSDetection("ashby", tenant, f"https://jobs.ashbyhq.com/{tenant}")

    return None


def discover_ats_candidates(urls) -> list[ATSDetection]:
    """Return unique deterministic ATS candidates from an iterable of URLs.

    The function is intentionally side-effect free: discovery never mutates the
    live company registry and therefore can never activate a source by accident.
    """
    found: dict[tuple[str, str, str, str], ATSDetection] = {}
    for url in urls:
        detected = detect_ats_url(str(url or ""))
        if not detected:
            continue
        key = (detected.ats, detected.host, detected.tenant, detected.site)
        found.setdefault(key, detected)
    return sorted(found.values(), key=lambda item: (item.ats, item.tenant.lower(), item.site.lower()))
