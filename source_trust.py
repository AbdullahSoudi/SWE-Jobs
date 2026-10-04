"""Source trust policy for canonical apply-link selection.

The discovery source and the best apply source are different concerns. A job may
be discovered first on LinkedIn but later matched to the employer's official ATS.
This module centralizes the trust ordering so deduplication, persistence, and
Telegram formatting make the same decision.
"""

from __future__ import annotations

import re


OFFICIAL_ATS_SCORE = 100
LINKEDIN_SCORE = 80
LINKEDIN_SHADOW_SCORE = 75
WUZZUF_SCORE = 70
DISCOVERY_SCORE = 40
DEFAULT_SCORE = 50


def normalize_source_key(source: str) -> str:
    text = str(source or "").strip().lower().replace("-", "_").replace(" ", "_")
    return re.sub(r"_+", "_", text)


def trust_score(source: str) -> int:
    """Return a stable trust score for apply-link preference.

    Higher means the link is closer to the employer and should win when the same
    real-world opening is observed from multiple sources.
    """
    key = normalize_source_key(source)
    if key.startswith("ats_"):
        return OFFICIAL_ATS_SCORE
    if key == "linkedin":
        return LINKEDIN_SCORE
    if key == "linkedin_saudi_v2":
        return LINKEDIN_SHADOW_SCORE
    if key == "wuzzuf":
        return WUZZUF_SCORE
    if key == "jobzaty":
        return DISCOVERY_SCORE
    return DEFAULT_SCORE


def is_official_source(source: str) -> bool:
    """Return whether the source is an employer/ATS posting rather than a board."""
    return normalize_source_key(source).startswith("ats_")
