"""Lightweight bilingual tech-job classifier used by routing and broad-source filtering.

The classifier is intentionally deterministic and auditable. It is not meant to
replace richer enrichment later; it provides a measured baseline that can be
regression-tested before broadening LinkedIn searches.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata

from config import CHANNELS, PRIMARY_TOPIC_ORDER
from models import Job, _flatten_tags

_ARABIC_DIACRITICS = re.compile(r"[\u0610-\u061a\u064b-\u065f\u0670\u06d6-\u06ed]")
_NON_WORD = re.compile(r"[^\w+#.]+", re.UNICODE)

ARABIC_TOPIC_KEYWORDS: dict[str, tuple[str, ...]] = {
    "internships": (
        "متدرب", "تدريب", "تدريب تعاوني", "تمهير", "حديث التخرج", "حديثي التخرج",
        "برنامج خريجين", "برنامج الخريجين", "خريج جديد",
    ),
    "backend": (
        "مطور باك اند", "باك اند", "مطور خلفي", "مطور خلفية", "برمجة خلفية",
        "مطور دوت نت", "مهندس دوت نت", "مطور جافا", "مطور بايثون", "مطور واجهات برمجية",
    ),
    "frontend": (
        "مطور فرونت اند", "فرونت اند", "مطور واجهات امامية", "مطور واجهات أمامية",
        "مطور واجهة مستخدم", "مطور رياكت", "مطور انجولار",
    ),
    "mobile": (
        "مطور تطبيقات", "مطور جوال", "مطور موبايل", "مطور اندرويد", "مطور أندرويد",
        "مطور ايفون", "مطور آيفون", "مطور فلاتر",
    ),
    "ai_ml": (
        "ذكاء اصطناعي", "تعلم آلي", "تعلم الاله", "تعلم الآلة", "علم بيانات", "عالم بيانات",
        "مهندس بيانات", "محلل بيانات", "هندسة البيانات", "ذكاء الاعمال", "ذكاء الأعمال",
    ),
    "devops": (
        "ديف اوبس", "ديف أوبس", "مهندس سحابة", "هندسة سحابية", "بنية تحتية",
        "مهندس منصات", "موثوقية المواقع",
    ),
    "qa": (
        "ضمان الجودة", "اختبار البرمجيات", "مختبر برمجيات", "مهندس اختبار", "اختبار آلي",
        "اختبار تلقائي",
    ),
    "cybersecurity": (
        "امن سيبراني", "أمن سيبراني", "امن المعلومات", "أمن المعلومات", "محلل امن", "محلل أمن",
        "اختبار اختراق", "امن تطبيقات", "أمن تطبيقات",
    ),
    "erp": (
        "تخطيط موارد المؤسسات", "مطور ساب", "استشاري ساب", "مطور اودو", "مطور أودو",
        "استشاري اودو", "استشاري أودو", "داينمكس 365", "ديناميكس 365", "مطور اوراكل", "مطور أوراكل",
    ),
}

ARABIC_GENERAL_TECH = (
    "مهندس برمجيات", "مطور برمجيات", "مبرمج", "تطوير برمجيات", "هندسة برمجيات",
    "مهندس نظم", "محلل نظم", "دعم تطبيقات", "دعم فني", "دعم تقني", "تقنية المعلومات",
    "تكنولوجيا المعلومات", "مهندس شبكات", "مسؤول شبكات", "مدير قواعد بيانات",
    "مطور قواعد بيانات", "مصمم تجربة المستخدم", "مصمم واجهة المستخدم", "محلل اعمال تقني",
    "محلل أعمال تقني", "مدير منتج تقني", "مدير مشروع تقني",
)

# Strong negative evidence. We only use terms that clearly indicate a non-tech
# role so broad searches do not accidentally reject technical hybrids.
NON_TECH_EXCLUSIONS = (
    "human resources", "hr officer", "hr specialist", "recruiter", "talent acquisition",
    "sales representative", "sales executive", "account executive", "cashier", "waiter",
    "nurse", "physician", "pharmacist", "dentist", "civil engineer", "mechanical engineer",
    "electrical engineer", "architectural engineer", "accountant", "bookkeeper",
    "موارد بشرية", "اخصائي موارد بشرية", "أخصائي موارد بشرية", "مسؤول موارد بشرية",
    "مندوب مبيعات", "تنفيذي مبيعات", "محاسب", "ممرض", "ممرضة", "طبيب", "صيدلي",
    "مهندس مدني", "مهندس ميكانيكي", "مهندس كهربائي",
)

GENERAL_TECH_ENGLISH = (
    "software engineer", "software developer", "developer", "programmer", "application engineer",
    "application developer", "application support", "systems engineer", "systems analyst",
    "technical support engineer", "it support", "it engineer", "information technology",
    "network engineer", "database administrator", "database developer", "integration engineer",
    "solutions engineer", "solution architect", "technical product manager", "technical project manager",
    "technical business analyst", "business systems analyst", "ui ux", "ui/ux", "ux designer",
    "product designer",
)


@dataclass(frozen=True)
class Classification:
    is_tech: bool
    topic: str | None
    matched: str = ""
    reason: str = ""


def normalize_text(value: str) -> str:
    text = unicodedata.normalize("NFKC", value or "").lower()
    text = _ARABIC_DIACRITICS.sub("", text)
    text = text.replace("ـ", "")
    text = text.translate(str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ى": "ي", "ؤ": "و", "ئ": "ي"}))
    text = _NON_WORD.sub(" ", text)
    return " ".join(text.split())


def _job_text(job: Job) -> str:
    return normalize_text(f"{job.title} {_flatten_tags(job.tags)}")


def _first_match(text: str, patterns) -> str:
    for pattern in patterns:
        normalized = normalize_text(pattern)
        if normalized and normalized in text:
            return str(pattern)
    return ""


def classify_job(job: Job) -> Classification:
    """Classify one job into the single primary topic used by Telegram."""
    text = _job_text(job)
    if not text:
        return Classification(False, None, reason="empty")

    excluded = _first_match(text, NON_TECH_EXCLUSIONS)
    if excluded:
        return Classification(False, None, excluded, "non_tech_exclusion")

    for topic in PRIMARY_TOPIC_ORDER:
        english = (CHANNELS.get(topic) or {}).get("keywords", [])
        matched = _first_match(text, english)
        if not matched:
            matched = _first_match(text, ARABIC_TOPIC_KEYWORDS.get(topic, ()))
        if matched:
            return Classification(True, topic, matched, "topic_keyword")

    general_match = _first_match(text, GENERAL_TECH_ENGLISH)
    if not general_match:
        general_match = _first_match(text, ARABIC_GENERAL_TECH)
    if general_match:
        return Classification(True, "general", general_match, "general_tech")

    return Classification(False, None, reason="no_tech_signal")


def is_tech_job(job: Job) -> bool:
    return classify_job(job).is_tech
