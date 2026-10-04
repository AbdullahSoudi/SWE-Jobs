"""Conservative cross-source job clustering helpers.

The bot prefers false splits over false merges: a duplicate notification is less
harmful than hiding a genuinely different opening.  Automatic clustering is
therefore restricted to strong company, location, title and role evidence.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import json
from pathlib import Path
import re
from typing import Iterable

from classifier import normalize_text
from locations import normalize_saudi_location
from models import Job
from source_trust import trust_score

_ALIAS_FILE = Path(__file__).with_name("companies") / "company_aliases.json"

_NOISE_TOKENS = {
    "hiring", "vacancy", "vacancies", "opening", "openings", "role", "position",
    "job", "jobs", "career", "careers", "opportunity", "opportunities", "urgent",
    "required", "wanted", "needed", "apply", "now",
}

_TOKEN_EXPANSIONS = {
    "sr": "senior",
    "jr": "junior",
    "dev": "developer",
    "eng": "engineer",
    "swe": "software engineer",
    "dotnet": ".net",
    "net": ".net",
}

_SENIORITY = {
    "intern": {"intern", "internship", "trainee", "coop", "co-op", "tamheer", "متدرب", "تدريب", "تمهير"},
    "junior": {"junior", "jr", "entry", "graduate", "fresh", "associate", "حديث", "خريج"},
    "senior": {"senior", "sr", "principal", "staff", "lead", "architect", "سينيور", "خبير", "قائد"},
    "manager": {"manager", "head", "director", "مدير", "رئيس"},
}

_STACK_GROUPS = {
    "dotnet": {".net", "dotnet", "c#", "asp.net"},
    "java": {"java", "spring"},
    "python": {"python", "django", "flask", "fastapi"},
    "php": {"php", "laravel"},
    "go": {"golang", "go"},
    "ruby": {"ruby", "rails"},
    "ios": {"ios", "swift"},
    "android": {"android", "kotlin"},
    "flutter": {"flutter", "dart"},
    "react": {"react", "reactjs", "react.js"},
    "angular": {"angular", "angularjs"},
    "sap": {"sap", "abap"},
    "oracle": {"oracle", "plsql", "pl/sql"},
    "dynamics": {"dynamics", "d365", "crm"},
    "salesforce": {"salesforce", "apex"},
}

_PROGRAM_GROUPS = {
    "internship": {"intern", "internship", "trainee", "coop", "co-op", "tamheer", "متدرب", "تدريب", "تمهير"},
    "graduate": {"graduate", "fresh", "entry", "حديث", "خريج", "graduates"},
}

@dataclass(frozen=True)
class ClusterMatch:
    job_id: int
    method: str
    score: float


def _load_aliases() -> dict[str, str]:
    try:
        raw = json.loads(_ALIAS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    aliases: dict[str, str] = {}
    if isinstance(raw, dict):
        items = raw.items()
    elif isinstance(raw, list):
        items = []
        for row in raw:
            if isinstance(row, dict) and row.get("canonical") and isinstance(row.get("aliases"), list):
                items.extend((alias, row["canonical"]) for alias in row["aliases"])
    else:
        items = []
    for alias, canonical in items:
        a = normalize_text(str(alias))
        c = normalize_text(str(canonical))
        if a and c:
            aliases[a] = c
    return aliases

_COMPANY_ALIASES = _load_aliases()


def normalize_company_key(value: str) -> str:
    """Return a conservative canonical company key."""
    text = normalize_text(value)
    text = re.sub(r"\b(inc|incorporated|ltd|limited|llc|corp|corporation|company|co|gmbh|pvt)\b", " ", text)
    text = " ".join(text.split())
    return _COMPANY_ALIASES.get(text, text)


def title_tokens(value: str) -> tuple[str, ...]:
    """Return normalized, order-insensitive title tokens."""
    text = normalize_text(value)
    expanded: list[str] = []
    for token in text.split():
        replacement = _TOKEN_EXPANSIONS.get(token, token)
        expanded.extend(replacement.split())
    cleaned = [t for t in expanded if t and t not in _NOISE_TOKENS]
    return tuple(sorted(set(cleaned)))


def title_key(value: str) -> str:
    return " ".join(title_tokens(value))


def _present_groups(tokens: set[str], groups: dict[str, set[str]]) -> set[str]:
    found: set[str] = set()
    for name, members in groups.items():
        if tokens.intersection(members):
            found.add(name)
    return found


def _conflicting_signal(a: set[str], b: set[str]) -> bool:
    return bool(a and b and a.isdisjoint(b))


def has_role_veto(title_a: str, title_b: str) -> bool:
    a = set(title_tokens(title_a))
    b = set(title_tokens(title_b))
    if _conflicting_signal(_present_groups(a, _SENIORITY), _present_groups(b, _SENIORITY)):
        return True
    if _conflicting_signal(_present_groups(a, _STACK_GROUPS), _present_groups(b, _STACK_GROUPS)):
        return True
    if _conflicting_signal(_present_groups(a, _PROGRAM_GROUPS), _present_groups(b, _PROGRAM_GROUPS)):
        return True
    return False


def title_similarity(title_a: str, title_b: str) -> float:
    a = set(title_tokens(title_a))
    b = set(title_tokens(title_b))
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def location_key(value: str) -> str:
    """Normalize Saudi locations while keeping non-Saudi matching strict."""
    sa = normalize_saudi_location(value)
    if sa.is_saudi:
        return f"SA:{sa.city_code or 'COUNTRY'}"
    return normalize_text(value)


def locations_compatible(a: str, b: str) -> bool:
    sa = normalize_saudi_location(a)
    sb = normalize_saudi_location(b)
    if sa.is_saudi or sb.is_saudi:
        if not (sa.is_saudi and sb.is_saudi):
            return False
        if sa.city_code and sb.city_code:
            return sa.city_code == sb.city_code
        return True
    return normalize_text(a) == normalize_text(b)


def _parse_iso(value: str) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _time_compatible(job: Job, row, max_days: int = 14) -> bool:
    incoming = _parse_iso(job.published_at_est)
    existing = _parse_iso(str(row["published_at_est"] or ""))
    if incoming and existing:
        return abs((incoming - existing).total_seconds()) <= max_days * 86400
    existing_seen = _parse_iso(str(row["first_seen_at"] or ""))
    if existing_seen is None:
        return True
    # Incoming first_seen is effectively now and is checked by the caller's recent query.
    return True


def source_trust(source: str) -> int:
    """Backward-compatible wrapper around the centralized trust policy."""
    return trust_score(source)


def find_cross_source_match(conn, job: Job, *, recent_since: str) -> ClusterMatch | None:
    """Find a safe existing cluster for a previously unseen posting."""
    company_key = normalize_company_key(job.company)
    incoming_tokens = title_tokens(job.title)
    if not company_key or len(incoming_tokens) < 3:
        return None

    rows = conn.execute(
        """
        SELECT j.id, j.title, j.company, j.location, j.published_at_est, j.first_seen_at
        FROM jobs j
        WHERE j.first_seen_at >= ?
        ORDER BY j.first_seen_at DESC
        """,
        (recent_since,),
    ).fetchall()

    best: ClusterMatch | None = None
    for row in rows:
        if normalize_company_key(str(row["company"] or "")) != company_key:
            continue
        if not locations_compatible(job.location, str(row["location"] or "")):
            continue
        if has_role_veto(job.title, str(row["title"] or "")):
            continue
        if not _time_compatible(job, row):
            continue

        # Only cluster a source that is not already represented in the cluster.
        # A second posting from the same source may be a repost or a genuinely
        # separate requisition with the same title, so fuzzy merging it is unsafe.
        same_source = conn.execute(
            "SELECT 1 FROM job_postings WHERE job_id = ? AND source = ? LIMIT 1",
            (int(row["id"]), job.source),
        ).fetchone()
        if same_source:
            continue

        other = conn.execute(
            "SELECT 1 FROM job_postings WHERE job_id = ? AND source != ? LIMIT 1",
            (int(row["id"]), job.source),
        ).fetchone()
        if not other:
            continue

        score = title_similarity(job.title, str(row["title"] or ""))
        if score < 0.85:
            continue
        match = ClusterMatch(int(row["id"]), "company_location_title", score)
        if best is None or match.score > best.score:
            best = match
    return best
