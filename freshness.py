"""Freshness evidence and send-gating helpers for job postings.

The bot must not pretend that coarse timestamps are exact. This module turns
public posting-time signals into intervals, then combines that evidence with
source state so newly discovered jobs can be sent without replaying stale ones.
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
BASELINE = "BASELINE"

FALLBACK_NONE = "NONE"
FALLBACK_RECENT_OBSERVATION = "RECENT_OBSERVATION"
FALLBACK_SOURCE_WINDOW = "SOURCE_WINDOW"


@dataclass(frozen=True)
class PublicationEvidence:
    raw: str = ""
    earliest: str = ""
    latest: str = ""
    estimate: str = ""
    precision: str = PRECISION_NONE
    semantics: str = "UNKNOWN"


@dataclass(frozen=True)
class FreshnessGateDecision:
    """Decision for one newly inserted posting."""

    status: str
    reason: str
    send_eligible: bool


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

    # A date-only signal represents the whole UTC day. Source-local timezone
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
        (r"(\d+)\+?\s*(?:day|days)\s+ago", timedelta(days=1), PRECISION_DAY),
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
    """Classify publication evidence without inventing false precision.

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


def evaluate_new_posting(
    evidence: PublicationEvidence,
    *,
    source_was_baselined: bool,
    previous_success_at: str | None,
    max_age_seconds: int,
    uncertain_fallback: str = FALLBACK_NONE,
    reference_time: datetime | None = None,
) -> FreshnessGateDecision:
    """Return the send gate for one newly discovered posting.

    A source's first successful fetch is always a no-send baseline. After that,
    exact/relative timestamp evidence is authoritative. When timestamp evidence
    is uncertain, selected sources may use one of two explicit fallbacks:

    - SOURCE_WINDOW means the adapter itself queried a bounded current window
      (for example LinkedIn f_TPR=r3600). The current result set is freshness
      evidence on its own and does not depend on the previous poll being recent.
    - RECENT_OBSERVATION means freshness is inferred only from seeing a new item
      shortly after a prior successful snapshot. A long coverage gap disables
      that observation-only fallback.
    """
    if max_age_seconds <= 0:
        raise ValueError("max_age_seconds must be greater than zero")

    if not source_was_baselined:
        return FreshnessGateDecision(BASELINE, "initial_source_baseline", False)

    now = ensure_utc(reference_time or utc_now())
    evidence_decision = freshness_decision(
        evidence,
        max_age_seconds=max_age_seconds,
        reference_time=now,
    )

    if evidence_decision == FRESH:
        return FreshnessGateDecision(FRESH, "publication_time_fresh", True)
    if evidence_decision == TOO_OLD:
        return FreshnessGateDecision(TOO_OLD, "publication_time_too_old", False)

    fallback = (uncertain_fallback or FALLBACK_NONE).upper()
    if fallback == FALLBACK_NONE:
        return FreshnessGateDecision(UNCERTAIN, "insufficient_time_evidence", False)

    # A true source-window adapter has already constrained this *current* result
    # set to max_age_seconds at the upstream query boundary. Missing/coarse card
    # timestamps therefore do not become stale merely because a previous poll
    # was delayed. The gap can still mean jobs were missed between polls, but it
    # does not invalidate items returned by the current bounded window.
    if fallback == FALLBACK_SOURCE_WINDOW:
        return FreshnessGateDecision(FRESH, "source_window_current_result", True)

    if fallback != FALLBACK_RECENT_OBSERVATION:
        raise ValueError(f"Unsupported uncertain_fallback: {uncertain_fallback}")

    previous = parse_utc_iso(previous_success_at or "")
    if previous is None:
        return FreshnessGateDecision(UNCERTAIN, "no_previous_success", False)

    gap_seconds = (now - previous).total_seconds()
    if gap_seconds < 0:
        return FreshnessGateDecision(UNCERTAIN, "previous_success_in_future", False)
    if gap_seconds > max_age_seconds:
        return FreshnessGateDecision(UNCERTAIN, "coverage_gap_too_large", False)

    return FreshnessGateDecision(FRESH, "recent_observation_after_success", True)
