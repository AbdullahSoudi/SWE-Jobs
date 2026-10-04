"""Public ATS job-board adapters used by the Saudi company registry.

Only public read endpoints intended to power external careers pages are used.
Each adapter returns normalized Job records and restricts registry feeds to
Saudi locations before the runtime tech classifier sees them.
"""
from __future__ import annotations

import logging
from urllib.parse import urlparse

from freshness import parse_iso_publication
from locations import normalize_saudi_location
from models import Job

try:
    from sources.http_utils import get_json
except ModuleNotFoundError:  # pragma: no cover - flat local imports
    from http_utils import get_json

log = logging.getLogger(__name__)

GREENHOUSE_URL = "https://boards-api.greenhouse.io/v1/boards/{tenant}/jobs"
LEVER_URL = "https://api.lever.co/v0/postings/{tenant}"
ASHBY_URL = "https://api.ashbyhq.com/posting-api/job-board/{tenant}"


def _clean(value) -> str:
    return str(value or "").strip()


def _join_nonempty(values) -> str:
    return " · ".join(value for value in (_clean(v) for v in values) if value)


def _saudi_location(location: str, country: str = "") -> str | None:
    """Return an explicitly Saudi location string, or None for non-Saudi rows."""
    loc = _clean(location)
    country_text = _clean(country)
    combined = _join_nonempty((loc, country_text))
    if normalize_saudi_location(combined).is_saudi:
        if loc and normalize_saudi_location(loc).is_saudi:
            return loc
        if loc:
            return f"{loc}, Saudi Arabia"
        return "Saudi Arabia"
    if country_text.upper() == "SA":
        return f"{loc}, Saudi Arabia" if loc else "Saudi Arabia"
    return None


def _publication_fields(value: str) -> dict[str, str]:
    evidence = parse_iso_publication(value)
    return {
        "published_at_raw": evidence.raw,
        "published_at_earliest": evidence.earliest,
        "published_at_latest": evidence.latest,
        "published_at_est": evidence.estimate,
        "published_precision": evidence.precision,
        "time_semantics": evidence.semantics,
    }


def _source_label(company: str) -> str:
    return f"{company} Careers"


def fetch_greenhouse_company(
    *,
    tenant: str,
    company: str,
    source_key: str,
    target_country: str = "SA",
    http_getter=None,
) -> list[Job]:
    """Fetch a Greenhouse public job board.

    Greenhouse currently exposes ``first_published`` on public list rows. When
    present we use it as exact publication evidence. Older/variant payloads may
    omit it; those rows deliberately fall back to snapshot observation instead
    of treating ``updated_at`` as a publish time.
    """
    getter = http_getter or get_json
    url = GREENHOUSE_URL.format(tenant=tenant)
    payload = getter(url)
    if payload is None:
        raise RuntimeError(f"Greenhouse fetch failed for {company}")
    if not isinstance(payload, dict) or not isinstance(payload.get("jobs"), list):
        raise ValueError(f"Greenhouse returned an unexpected payload for {company}")

    jobs: list[Job] = []
    for row in payload["jobs"]:
        if not isinstance(row, dict):
            continue
        # Greenhouse list rows do not expose a structured country code. Do not
        # assume the registry target country applies to every posting on a global
        # employer board; require Saudi evidence in the location itself.
        location = _saudi_location(
            _clean((row.get("location") or {}).get("name")) if isinstance(row.get("location"), dict) else ""
        )
        if not location:
            continue
        title = _clean(row.get("title"))
        absolute_url = _clean(row.get("absolute_url"))
        source_job_id = _clean(row.get("id"))
        if not title or not absolute_url or not source_job_id:
            continue

        first_published = _clean(row.get("first_published"))
        publication = _publication_fields(first_published) if first_published else {
            "published_at_raw": _clean(row.get("updated_at")),
            "published_at_earliest": "",
            "published_at_latest": "",
            "published_at_est": "",
            "published_precision": "NONE",
            "time_semantics": "UPDATED" if row.get("updated_at") else "UNKNOWN",
        }
        jobs.append(Job(
            title=title,
            company=company,
            location=location,
            url=absolute_url,
            source=source_key,
            source_job_id=source_job_id,
            original_source=_source_label(company),
            **publication,
        ))

    log.info("ATS Greenhouse %s: fetched %s Saudi postings.", company, len(jobs))
    return jobs


def fetch_lever_company(
    *,
    tenant: str,
    company: str,
    source_key: str,
    target_country: str = "SA",
    http_getter=None,
) -> list[Job]:
    """Fetch a Lever public postings site in JSON mode."""
    getter = http_getter or get_json
    url = LEVER_URL.format(tenant=tenant)
    payload = getter(url, params={"mode": "json"})
    if payload is None:
        raise RuntimeError(f"Lever fetch failed for {company}")
    if not isinstance(payload, list):
        raise ValueError(f"Lever returned an unexpected payload for {company}")

    jobs: list[Job] = []
    for row in payload:
        if not isinstance(row, dict):
            continue
        categories = row.get("categories") if isinstance(row.get("categories"), dict) else {}
        location_details = categories.get("locationDetails") if isinstance(categories.get("locationDetails"), dict) else {}
        country_hint = _clean(row.get("country")) or _clean(location_details.get("country"))
        location_candidates = [_clean(categories.get("location"))]
        if isinstance(categories.get("allLocations"), list):
            location_candidates.extend(_clean(value) for value in categories.get("allLocations") if value)
        # Prefer explicit Saudi evidence in any listed location. Only use a
        # structured country hint for the primary location if the text itself
        # is ambiguous; applying one country code to every multi-location label
        # can misclassify a non-Saudi secondary office.
        location = next(
            (matched for candidate in location_candidates if (matched := _saudi_location(candidate))),
            None,
        )
        if not location and location_candidates:
            location = _saudi_location(location_candidates[0], country_hint)
        if not location:
            continue
        title = _clean(row.get("text"))
        source_job_id = _clean(row.get("id"))
        hosted_url = _clean(row.get("hostedUrl"))
        if not title or not source_job_id or not hosted_url:
            continue

        workplace = _clean(row.get("workplaceType"))
        commitment = _clean(categories.get("commitment"))
        tags = [
            _clean(categories.get("team")),
            _clean(categories.get("department")),
            commitment,
            workplace,
        ]
        tags = [tag for tag in tags if tag]
        jobs.append(Job(
            title=title,
            company=company,
            location=location,
            url=hosted_url,
            source=source_key,
            source_job_id=source_job_id,
            original_source=_source_label(company),
            job_type=_join_nonempty((commitment, workplace)),
            tags=tags,
            is_remote=workplace.lower() == "remote",
        ))

    log.info("ATS Lever %s: fetched %s Saudi postings.", company, len(jobs))
    return jobs


def fetch_ashby_company(
    *,
    tenant: str,
    company: str,
    source_key: str,
    target_country: str = "SA",
    http_getter=None,
) -> list[Job]:
    """Fetch an Ashby public job board, preserving its exact publishedAt."""
    getter = http_getter or get_json
    url = ASHBY_URL.format(tenant=tenant)
    payload = getter(url, params={"includeCompensation": "false"})
    if payload is None:
        raise RuntimeError(f"Ashby fetch failed for {company}")
    if not isinstance(payload, dict) or not isinstance(payload.get("jobs"), list):
        raise ValueError(f"Ashby returned an unexpected payload for {company}")

    jobs: list[Job] = []
    for row in payload["jobs"]:
        if not isinstance(row, dict) or row.get("isListed") is False:
            continue
        address = row.get("address") if isinstance(row.get("address"), dict) else {}
        postal = address.get("postalAddress") if isinstance(address.get("postalAddress"), dict) else {}
        country = _clean(postal.get("addressCountry"))
        location = _saudi_location(_clean(row.get("location")), country)
        if not location and isinstance(row.get("secondaryLocations"), list):
            for secondary in row.get("secondaryLocations"):
                if not isinstance(secondary, dict):
                    continue
                secondary_address = secondary.get("address") if isinstance(secondary.get("address"), dict) else {}
                secondary_country = _clean(secondary_address.get("addressCountry"))
                location = _saudi_location(_clean(secondary.get("location")), secondary_country)
                if location:
                    break
        if not location:
            continue

        title = _clean(row.get("title"))
        job_url = _clean(row.get("jobUrl"))
        if not title or not job_url:
            continue
        source_job_id = urlparse(job_url).path.rstrip("/").split("/")[-1]
        if not source_job_id:
            continue

        employment = _clean(row.get("employmentType"))
        workplace = _clean(row.get("workplaceType"))
        tags = [
            _clean(row.get("department")),
            _clean(row.get("team")),
            employment,
            workplace,
        ]
        tags = [tag for tag in tags if tag]
        publication = _publication_fields(_clean(row.get("publishedAt")))
        jobs.append(Job(
            title=title,
            company=company,
            location=location,
            url=job_url,
            source=source_key,
            source_job_id=source_job_id,
            original_source=_source_label(company),
            job_type=_join_nonempty((employment, workplace)),
            tags=tags,
            is_remote=bool(row.get("isRemote")) or workplace.lower() == "remote",
            **publication,
        ))

    log.info("ATS Ashby %s: fetched %s Saudi postings.", company, len(jobs))
    return jobs
