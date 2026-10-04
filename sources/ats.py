"""Public ATS job-board adapters used by the Saudi company registry.

Only public read endpoints intended to power external careers pages are used.
Each adapter returns normalized Job records and restricts registry feeds to
Saudi locations before the runtime tech classifier sees them.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime
from urllib.parse import urlparse

from freshness import parse_iso_publication, parse_relative_publication
from locations import normalize_saudi_location
from models import Job

try:
    from sources.http_utils import get_json, post_json
except ModuleNotFoundError:  # pragma: no cover - flat local imports
    from http_utils import get_json, post_json

log = logging.getLogger(__name__)

GREENHOUSE_URL = "https://boards-api.greenhouse.io/v1/boards/{tenant}/jobs"
LEVER_URL = "https://api.lever.co/v0/postings/{tenant}"
ASHBY_URL = "https://api.ashbyhq.com/posting-api/job-board/{tenant}"
WORKDAY_PAGE_SIZE = 20
WORKDAY_DEFAULT_MAX_PAGES_PER_TERM = 3


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



def _workday_public_url(host: str, locale: str, site: str, external_path: str) -> str:
    base = f"https://{host.strip().strip('/')}"
    locale_part = (locale or "en-US").strip().strip("/")
    site_part = site.strip().strip("/")
    path = "/" + external_path.strip().lstrip("/")
    return f"{base}/{locale_part}/{site_part}{path}"


def _workday_source_job_id(row: dict, external_path: str) -> str:
    """Return a stable Workday listing identity without requiring detail calls."""
    for key in ("jobReqId", "jobRequisitionId", "jobPostingId"):
        value = _clean(row.get(key))
        if value:
            return value
    # externalPath is tenant-scoped and stable enough for list-only polling.
    return external_path.strip().strip("/")


def fetch_workday_company(
    *,
    host: str,
    tenant: str,
    site: str,
    company: str,
    source_key: str,
    target_country: str = "SA",
    locale: str = "en-US",
    search_terms: tuple[str, ...] | list[str] | None = None,
    max_pages_per_term: int = WORKDAY_DEFAULT_MAX_PAGES_PER_TERM,
    http_poster=None,
    fetched_at: datetime | None = None,
) -> list[Job]:
    """Fetch Saudi jobs from a public Workday CXS careers board.

    Workday's public list endpoint has a hard page size of 20. Large global
    tenants can expose thousands of jobs, so the registry supplies a small set
    of Saudi-oriented search terms (for example Riyadh/Saudi Arabia/KSA). Every
    returned row is still location-validated locally before it enters the bot.

    ``postedOn`` is usually a coarse relative string. We preserve that evidence
    when useful, but Workday remains an ATS snapshot source, so newly appearing
    rows can use recent-observation freshness after the initial baseline.
    """
    if max_pages_per_term < 1:
        raise ValueError("max_pages_per_term must be >= 1")
    clean_host = (host or "").strip().strip("/")
    if not clean_host or not tenant or not site:
        raise ValueError(f"Workday host/tenant/site are required for {company}")

    poster = http_poster or post_json
    endpoint = f"https://{clean_host}/wday/cxs/{tenant}/{site}/jobs"
    terms = tuple(dict.fromkeys(
        term.strip() for term in (search_terms or ("Riyadh", "Saudi Arabia", "KSA")) if term and term.strip()
    ))
    if not terms:
        terms = ("Riyadh", "Saudi Arabia", "KSA")

    fetched = fetched_at or datetime.now(UTC)
    jobs: list[Job] = []
    seen_paths: set[str] = set()

    for term in terms:
        offset = 0
        first_total: int | None = None
        for _page in range(max_pages_per_term):
            request_payload = {
                "appliedFacets": {},
                "limit": WORKDAY_PAGE_SIZE,
                "offset": offset,
                "searchText": term,
            }
            payload = poster(
                endpoint,
                payload=request_payload,
                headers={"Referer": f"https://{clean_host}/{locale}/{site}"},
            )
            if payload is None:
                raise RuntimeError(f"Workday fetch failed for {company} (search={term!r})")
            if not isinstance(payload, dict) or not isinstance(payload.get("jobPostings"), list):
                raise ValueError(f"Workday returned an unexpected payload for {company}")

            rows = payload["jobPostings"]
            if first_total is None:
                try:
                    first_total = int(payload.get("total"))
                except (TypeError, ValueError):
                    first_total = None

            for row in rows:
                if not isinstance(row, dict):
                    continue
                external_path = _clean(row.get("externalPath"))
                if not external_path or external_path in seen_paths:
                    continue

                location = _saudi_location(_clean(row.get("locationsText")))
                if not location:
                    continue
                title = _clean(row.get("title"))
                if not title:
                    continue

                seen_paths.add(external_path)
                posted_on = _clean(row.get("postedOn"))
                publication = parse_relative_publication(posted_on, fetched_at=fetched)
                tags = [
                    _clean(value)
                    for value in (row.get("bulletFields") if isinstance(row.get("bulletFields"), list) else [])
                    if _clean(value)
                ]
                jobs.append(Job(
                    title=title,
                    company=company,
                    location=location,
                    url=_workday_public_url(clean_host, locale, site, external_path),
                    source=source_key,
                    source_job_id=_workday_source_job_id(row, external_path),
                    original_source=_source_label(company),
                    tags=tags,
                    published_at_raw=publication.raw,
                    published_at_earliest=publication.earliest,
                    published_at_latest=publication.latest,
                    published_at_est=publication.estimate,
                    published_precision=publication.precision,
                    time_semantics=publication.semantics,
                ))

            offset += WORKDAY_PAGE_SIZE
            if len(rows) < WORKDAY_PAGE_SIZE:
                break
            if first_total is not None and offset >= first_total:
                break
            if offset >= max_pages_per_term * WORKDAY_PAGE_SIZE:
                # Observation freshness is only safe when this Saudi-oriented
                # search can be enumerated completely. Refuse a truncated
                # snapshot instead of later treating an old re-ranked row as new.
                if first_total is None or offset < first_total:
                    raise RuntimeError(
                        f"Workday search saturated for {company} (search={term!r}, total={first_total})"
                    )

    log.info("ATS Workday %s: fetched %s Saudi postings.", company, len(jobs))
    return jobs
