"""Freshness evidence helpers for job postings.

The bot must not pretend that coarse timestamps are exact.  This module turns
public posting-time signals (for example, "12 minutes ago" or an ISO datetime)
into an interval that preserves the source's uncertainty.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta


PRECISION_EXACT = "EXACT"
PRECISION_MINUTE = "MINUTE"
PRECISION_HOUR = "HOUR"
PRECISION_DAY = "DAY"
PRECISION_NONE = "NONE"

FRESH = "FRESH"
TOO_OLD = "TOO_OLD"
UNCERTAIN = "UNCERTAIN"


@dataclass(frozen=True)
class PublicationEvidence:
    raw: str = ""
    earliest: str = ""
    latest: str = ""
    estimate: str = ""
    precision: str = PRECISION_NONE
    semantics: str = "UNKNOWN"


def utc_now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def iso_utc(value: datetime) -> str:
    return ensure_utc(value).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_iso_publication(value: str, raw_text: str = "") -> PublicationEvidence:
    """Parse a source-provided ISO date/datetime without inventing precision."""
    text = (value or "").strip()
    if not text:
        return PublicationEvidence(raw=raw_text or "")

    # A date-only signal represents the whole UTC day.  Source-local timezone
    # handling can be layered on later once an adapter knows its exact semantics.
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        day = datetime.fromisoformat(text).replace(tzinfo=UTC)
        return PublicationEvidence(
            raw=raw_text or text,
            earliest=iso_utc(day),
            latest=iso_utc(day + timedelta(days=1) - timedelta(seconds=1)),
            estimate=iso_utc(day + timedelta(hours=12)),
            precision=PRECISION_DAY,
            semantics="POSTED",
        )

    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return PublicationEvidence(raw=raw_text or text)

    parsed = ensure_utc(parsed)
    stamp = iso_utc(parsed)
    return PublicationEvidence(
        raw=raw_text or text,
        earliest=stamp,
        latest=stamp,
        estimate=stamp,
        precision=PRECISION_EXACT,
        semantics="POSTED",
    )


def parse_relative_publication(raw_text: str, fetched_at: datetime | None = None) -> PublicationEvidence:
    """Convert an English relative age into a conservative publication interval."""
    raw = (raw_text or "").strip()
    low = raw.lower()
    fetched = ensure_utc(fetched_at or utc_now()).replace(microsecond=0)

    if not raw:
        return PublicationEvidence()

    if "just now" in low or "moments ago" in low:
        return PublicationEvidence(
            raw=raw,
            earliest=iso_utc(fetched - timedelta(minutes=1)),
            latest=iso_utc(fetched),
            estimate=iso_utc(fetched),
            precision=PRECISION_MINUTE,
            semantics="POSTED",
        )

    patterns = (
        (r"(\d+)\s*(?:minute|minutes|min|mins)\s+ago", timedelta(minutes=1), PRECISION_MINUTE),
        (r"(\d+)\s*(?:hour|hours|hr|hrs)\s+ago", timedelta(hours=1), PRECISION_HOUR),
        (r"(\d+)\s*(?:day|days)\s+ago", timedelta(days=1), PRECISION_DAY),
        (r"(\d+)\s*(?:week|weeks)\s+ago", timedelta(weeks=1), PRECISION_DAY),
    )
    for pattern, bucket, precision in patterns:
        match = re.search(pattern, low)
        if not match:
            continue
        amount = int(match.group(1))
        latest = fetched - (bucket * amount)
        earliest = latest - bucket
        return PublicationEvidence(
            raw=raw,
            earliest=iso_utc(earliest),
            latest=iso_utc(latest),
            estimate=iso_utc(latest),
            precision=precision,
            semantics="POSTED",
        )

    return PublicationEvidence(raw=raw)


def parse_utc_iso(value: str) -> datetime | None:
    text = (value or "").strip()
    if not text:
        return None
    try:
        return ensure_utc(datetime.fromisoformat(text.replace("Z", "+00:00")))
    except ValueError:
        return None


def freshness_decision(
    evidence: PublicationEvidence,
    max_age_seconds: int,
    reference_time: datetime | None = None,
) -> str:
    """Classify evidence without turning uncertain timestamps into false precision.

    TOO_OLD: even the newest possible publication time is older than max_age.
    FRESH:   even the oldest possible publication time is inside max_age.
    UNCERTAIN: the interval straddles the cutoff or there is no usable evidence.
    """
    if max_age_seconds <= 0:
        raise ValueError("max_age_seconds must be greater than zero")

    now = ensure_utc(reference_time or utc_now())
    earliest = parse_utc_iso(evidence.earliest)
    latest = parse_utc_iso(evidence.latest)
    if earliest is None or latest is None:
        return UNCERTAIN

    cutoff = now - timedelta(seconds=max_age_seconds)
    if latest < cutoff:
        return TOO_OLD
    if earliest >= cutoff:
        return FRESH
    return UNCERTAIN
