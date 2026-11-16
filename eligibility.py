"""Evidence-based Saudi eligibility extraction.

The bot never infers nationality eligibility from company, sector, or silence.
Only explicit text evidence upgrades a job from NOT_SPECIFIED.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from typing import Iterable

SAUDI_ONLY = "SAUDI_ONLY"
EXPLICITLY_OPEN = "EXPLICITLY_OPEN"
NOT_SPECIFIED = "NOT_SPECIFIED"

_MAX_EVIDENCE_CHARS = 280
_ARABIC_DIACRITICS_RE = re.compile(r"[\u0610-\u061A\u064B-\u065F\u0670\u06D6-\u06ED]")
_TAG_RE = re.compile(r"<[^>]+>")
_SPACE_RE = re.compile(r"\s+")
_SEGMENT_SPLIT_RE = re.compile(r"(?:[\r\n]+|[.!?؟؛;•]+)\s*")


def html_to_text(value: str) -> str:
    """Convert small/medium ATS HTML fragments to plain text for internal analysis."""
    if not value:
        return ""
    text = re.sub(r"(?i)<br\s*/?>", "\n", str(value))
    text = re.sub(r"(?i)</(?:p|li|div|h[1-6])>", "\n", text)
    text = _TAG_RE.sub(" ", text)
    text = html.unescape(text)
    lines = []
    for line in text.splitlines():
        clean = _SPACE_RE.sub(" ", line).strip()
        clean = re.sub(r"\s+([.,!?;:؟؛])", r"\1", clean)
        if clean:
            lines.append(clean)
    return "\n".join(line for line in lines if line)


def _normalize_for_match(value: str) -> str:
    text = html_to_text(value).casefold()
    text = _ARABIC_DIACRITICS_RE.sub("", text)
    text = text.replace("ـ", "")
    for src, dst in (("أ", "ا"), ("إ", "ا"), ("آ", "ا"), ("ى", "ي"), ("ة", "ه")):
        text = text.replace(src, dst)
    text = re.sub(r"[_/\\|-]+", " ", text)
    return _SPACE_RE.sub(" ", text).strip()


@dataclass(frozen=True)
class EligibilityResult:
    value: str
    evidence: str = ""
    rule: str = ""


# Match affirmative evidence in both directions; conflicting evidence stays unknown.
_OPEN_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("saudi_or_non_saudi", re.compile(r"\bsaudi(?:s| nationals?)?\s*(?:or|and)\s*non\s*saudi(?:s)?\b", re.I)),
    ("non_saudi_or_saudi", re.compile(r"\bnon\s*saudi(?:s)?\s*(?:or|and)\s*saudi(?:s| nationals?)?\b", re.I)),
    ("all_nationalities", re.compile(r"\b(?:open\s+to\s+)?(?:all|any)\s+nationalit(?:y|ies)\b", re.I)),
    ("non_saudis_welcome", re.compile(r"\bnon\s*saudi(?:s)?\s+(?:are\s+)?welcome\b", re.I)),
    ("visa_sponsorship", re.compile(r"\b(?:work\s+)?visa\s+sponsorship\s+(?:is\s+)?(?:available|provided|offered)\b", re.I)),
    ("work_permit_sponsorship", re.compile(r"\bwork\s+permit\s+sponsorship\s+(?:is\s+)?(?:available|provided|offered)\b", re.I)),
    ("arabic_all_nationalities", re.compile(r"(?:جميع|كافه|كافة)\s+الجنسيات")),
    ("arabic_for_all_nationalities", re.compile(r"لجميع\s+الجنسيات")),
    ("arabic_saudi_and_non_saudi", re.compile(r"السعودي(?:ين|ون)?\s*(?:و|او)\s*غير\s+السعودي(?:ين|ون)?")),
    ("arabic_saudi_or_non_saudi", re.compile(r"سعودي(?:ه|ة|ين|ون)?\s*(?:او|و)\s*غير\s+سعودي(?:ه|ة|ين|ون)?")),
    ("arabic_non_saudi", re.compile(r"لغير\s+السعودي(?:ين|ون)?")),
)

_SAUDI_ONLY_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("non_saudis_need_not_apply", re.compile(r"\bnon\s*saudi(?:s)?\s+(?:need\s+not|should\s+not|must\s+not)\s+apply\b", re.I)),
    ("saudi_nationals_only", re.compile(r"\bsaudi\s+nationals?\s+only\b", re.I)),
    ("only_saudi_nationals", re.compile(r"\bonly\s+saudi\s+nationals?\b", re.I)),
    ("saudis_only", re.compile(r"\bsaudi(?:s)?\s+only\b", re.I)),
    ("must_be_saudi", re.compile(r"\bmust\s+be\s+(?:a\s+)?saudi(?:\s+national)?\b(?!\s+(?:market|based|owned))", re.I)),
    ("saudi_nationality_required", re.compile(r"\bsaudi\s+nationality\s+(?:is\s+)?(?:required|mandatory)\b", re.I)),
    ("restricted_to_saudi", re.compile(r"\b(?:restricted|limited)\s+to\s+saudi\s+nationals?\b", re.I)),
    ("saudization", re.compile(r"\bsaudi[sz]ation\b", re.I)),
    ("tamheer", re.compile(r"\btamheer\b", re.I)),
    ("arabic_saudi_only", re.compile(r"للسعودي(?:ين|ات)?\s+فقط")),
    ("arabic_saudi_nationality", re.compile(r"سعودي(?:ه|ة)?\s+الجنسيه")),
    ("arabic_saudi_nationality_required", re.compile(r"الجنسيه\s+السعوديه\s*(?:مطلوبه|مطلوب|شرط|فقط)")),
    ("arabic_applicant_must_be_saudi", re.compile(r"(?:يشترط|يجب)\s+(?:ان\s+)?(?:يكون|تكون)\s+(?:المتقدم|المتقدمه|المرشح|المرشحه)\s+سعودي(?:ه)?\b")),
    ("arabic_applicant_is_saudi", re.compile(r"ان\s+(?:يكون\s+المتقدم|تكون\s+المتقدمه)\s+سعودي(?:ه|ة)?")),
    ("arabic_tamheer", re.compile(r"تمهير")),
)


def _segments(values: Iterable[str]) -> list[tuple[str, str]]:
    result: list[tuple[str, str]] = []
    for value in values:
        plain = html_to_text(value)
        if not plain:
            continue
        pieces = [piece.strip() for piece in _SEGMENT_SPLIT_RE.split(plain) if piece.strip()]
        if not pieces:
            pieces = [plain.strip()]
        for piece in pieces:
            result.append((piece, _normalize_for_match(piece)))
    return result


def _evidence_text(segment: str) -> str:
    clean = _SPACE_RE.sub(" ", segment).strip()
    if len(clean) <= _MAX_EVIDENCE_CHARS:
        return clean
    return clean[: _MAX_EVIDENCE_CHARS - 1].rstrip() + "…"


def _negated_or_conditional(text: str, match: re.Match) -> bool:
    prefix = re.split(r",|،|\bbut\b|\bhowever\b|ولكن|لكن", text[:match.start()])[-1]
    if re.search(r"\b(?:not|never|no|without|cannot|can't|isn't|doesn't|don't|if|unless|whether|prefer|preferably|preferred|ideally)\b"
                 r"|(?:^|\s)(?:لا|ليس|ليست|غير|بدون|عدم|لم|لن|اذا|يفضل|الافضل)(?:\s|$)", prefix):
        return True
    return bool(re.match(r"\s*(?:(?:is|are)\s+not\b|not\s+(?:required|mandatory)\b|preferred\b|غير\s+مطلوب|يفضل)",
                         text[match.end():]))


def _applicant_scoped(rule: str, text: str, *, label: bool) -> bool:
    if label:
        return True
    applicant = re.search(r"\b(?:applicants?|candidates?|applications?|apply)\b|المتقدم|المرشح|التقديم", text)
    # Demographics, customers and company ownership do not describe applicants.
    if not applicant and re.search(r"\b(?:colleagues|employees|workforce|customers|clients|our staff)\b"
                                   r"|موظفينا|عملائنا|زملائنا"
                                   r"|\b(?:company|business|employer)\s+(?:must\s+be|is|are)\b", text):
        return False
    if rule in {"tamheer", "arabic_tamheer", "saudization"}:
        return bool(re.search(r"\b(?:this|the)\s+(?:role|position|vacancy)\b|هذه\s+(?:الوظيفه|الفرصه)", text))
    if rule in {"all_nationalities", "saudi_or_non_saudi", "non_saudi_or_saudi",
                "arabic_all_nationalities", "arabic_for_all_nationalities",
                "arabic_saudi_and_non_saudi", "arabic_saudi_or_non_saudi", "arabic_non_saudi"}:
        return bool(applicant or re.search(r"\b(?:open|available|welcome|eligible)\b|متاح|الوظيفه|الفرصه", text))
    return True


def classify_eligibility(
    *,
    title: str = "",
    description: str = "",
    tags: Iterable[str] | None = None,
) -> EligibilityResult:
    """Return eligibility only when explicit textual evidence supports it.

    `NOT_SPECIFIED` is deliberately the default. Phrases that merely prefer
    Saudi candidates are not treated as Saudi-only.
    """
    tag_values = [str(tag) for tag in (tags or []) if tag is not None]
    candidates = [(original, normalized, True) for original, normalized in _segments([title, *tag_values])]
    candidates += [(original, normalized, False) for original, normalized in _segments([description])]
    evidence: dict[str, EligibilityResult] = {}
    for value, rules in ((EXPLICITLY_OPEN, _OPEN_RULES), (SAUDI_ONLY, _SAUDI_ONLY_RULES)):
        for rule, pattern in rules:
            for original, normalized, label in candidates:
                for match in pattern.finditer(normalized):
                    if (_applicant_scoped(rule, normalized, label=label)
                            and not _negated_or_conditional(normalized, match)):
                        evidence.setdefault(value, EligibilityResult(value, _evidence_text(original), rule))
    if len(evidence) > 1:
        return EligibilityResult(NOT_SPECIFIED,
                                 _evidence_text(" | ".join(item.evidence for item in evidence.values())),
                                 "conflicting_evidence")
    return next(iter(evidence.values()), EligibilityResult(NOT_SPECIFIED))


def enrich_job_eligibility(job) -> EligibilityResult:
    """Classify a mutable Job and attach normalized eligibility fields."""
    result = classify_eligibility(
        title=getattr(job, "title", "") or "",
        description=getattr(job, "description", "") or "",
        tags=getattr(job, "tags", []) or [],
    )
    job.eligibility = result.value
    job.eligibility_evidence = result.evidence
    job.eligibility_source = (getattr(job, "source", "") or "") if result.value != NOT_SPECIFIED else ""
    return result
