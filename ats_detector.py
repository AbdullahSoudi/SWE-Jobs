"""Deterministic ATS URL detection for Saudi company-registry discovery.

This module intentionally does no network requests. It recognizes public job-board
URLs already observed in LinkedIn/off-site apply links and extracts the tenant
identifier needed by the reusable ATS adapters.
"""
from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse


@dataclass(frozen=True)
class ATSDetection:
    ats: str
    tenant: str
    board_url: str


def _parts(url: str) -> tuple[str, list[str]]:
    parsed = urlparse((url or "").strip())
    host = parsed.netloc.lower().split(":", 1)[0]
    parts = [part for part in parsed.path.split("/") if part]
    return host, parts


def detect_ats_url(url: str) -> ATSDetection | None:
    """Recognize Greenhouse, Lever, or Ashby public board/apply URLs.

    The returned ``tenant`` is suitable for ``companies/saudi_ats.json``.
    Unknown/custom career sites deliberately return ``None`` rather than
    guessing.
    """
    host, parts = _parts(url)
    if not host or not parts:
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
