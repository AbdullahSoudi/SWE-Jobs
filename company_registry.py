"""Static Saudi ATS company registry and fetcher construction.

The registry starts deliberately small. Every generated ATS source is shadow
by default because PRODUCTION_SOURCE_KEYS contains only explicitly promoted
sources. This lets the bot measure fresh/exclusive/lead-time value before an
employer feed can create Telegram deliveries.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Callable

from models import Job
from sources.ats import (
    fetch_ashby_company,
    fetch_greenhouse_company,
    fetch_lever_company,
    fetch_workday_company,
)

REGISTRY_PATH = Path(__file__).resolve().parent / "companies" / "saudi_ats.json"


@dataclass(frozen=True)
class ATSCompany:
    key: str
    company: str
    ats: str
    tenant: str
    country: str = "SA"
    careers_url: str = ""
    enabled: bool = True
    poll_interval_minutes: int = 60
    host: str = ""
    site: str = ""
    locale: str = "en-US"
    search_terms: tuple[str, ...] = ()

    @property
    def source_name(self) -> str:
        # main._source_key() turns this into e.g. ats_ashby_sarjai.
        return f"ATS {self.ats.title()} {self.key}"

    @property
    def source_key(self) -> str:
        return self.source_name.lower().replace("-", "_").replace(" ", "_")


_ADAPTERS: dict[str, Callable[..., list[Job]]] = {
    "greenhouse": fetch_greenhouse_company,
    "lever": fetch_lever_company,
    "ashby": fetch_ashby_company,
    "workday": fetch_workday_company,
}


def load_ats_companies(path: str | Path = REGISTRY_PATH) -> list[ATSCompany]:
    """Load and validate enabled companies from the JSON registry."""
    registry_path = Path(path)
    payload = json.loads(registry_path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("ATS company registry must be a JSON list")

    companies: list[ATSCompany] = []
    seen_keys: set[str] = set()
    for index, row in enumerate(payload):
        if not isinstance(row, dict):
            raise ValueError(f"ATS registry row {index} must be an object")

        raw_search_terms = row.get("search_terms") or []
        if not isinstance(raw_search_terms, list):
            raise ValueError(f"ATS registry search_terms for row {index} must be a list")

        company = ATSCompany(
            key=str(row.get("key", "")).strip().lower(),
            company=str(row.get("company", "")).strip(),
            ats=str(row.get("ats", "")).strip().lower(),
            tenant=str(row.get("tenant", "")).strip(),
            country=str(row.get("country", "SA")).strip().upper(),
            careers_url=str(row.get("careers_url", "")).strip(),
            enabled=bool(row.get("enabled", True)),
            poll_interval_minutes=int(row.get("poll_interval_minutes", 60)),
            host=str(row.get("host", "")).strip().lower(),
            site=str(row.get("site", "")).strip(),
            locale=str(row.get("locale", "en-US")).strip() or "en-US",
            search_terms=tuple(str(value).strip() for value in raw_search_terms if str(value).strip()),
        )
        if not company.enabled:
            continue
        if not company.key or not company.company or not company.tenant:
            raise ValueError(f"ATS registry row {index} is missing key/company/tenant")
        if company.ats not in _ADAPTERS:
            raise ValueError(f"Unsupported ATS '{company.ats}' for {company.company}")
        if company.ats == "workday" and (not company.host or not company.site):
            raise ValueError(f"Workday registry entry {company.company} requires host and site")
        if company.country != "SA":
            raise ValueError(f"Saudi registry entry {company.company} must use country=SA")
        if company.poll_interval_minutes < 15:
            raise ValueError(f"ATS registry poll interval for {company.company} must be at least 15 minutes")
        if company.key in seen_keys:
            raise ValueError(f"Duplicate ATS registry key: {company.key}")
        seen_keys.add(company.key)
        companies.append(company)

    return companies


def _make_fetcher(company: ATSCompany) -> Callable[[], list[Job]]:
    adapter = _ADAPTERS[company.ats]
    kwargs = {
        "tenant": company.tenant,
        "company": company.company,
        "source_key": company.source_key,
        "target_country": company.country,
    }
    if company.ats == "workday":
        kwargs.update({
            "host": company.host,
            "site": company.site,
            "locale": company.locale,
            "search_terms": company.search_terms or None,
        })
    fetcher = partial(adapter, **kwargs)
    fetcher.__name__ = f"fetch_{company.source_key}"
    return fetcher


def build_ats_fetchers(path: str | Path = REGISTRY_PATH) -> list[tuple[str, Callable[[], list[Job]]]]:
    """Build source-registry tuples compatible with sources.ALL_FETCHERS."""
    return [(company.source_name, _make_fetcher(company)) for company in load_ats_companies(path)]


def build_ats_poll_intervals(path: str | Path = REGISTRY_PATH) -> dict[str, int]:
    """Return persisted source-key polling intervals for enabled ATS tenants."""
    return {
        company.source_key: company.poll_interval_minutes
        for company in load_ats_companies(path)
    }
