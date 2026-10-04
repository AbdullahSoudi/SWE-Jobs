"""Saudi location normalization helpers.

This is intentionally conservative: only aliases we can map confidently are
normalized. Unknown Saudi locations still keep country-level classification.
"""
from __future__ import annotations

from dataclasses import dataclass

from classifier import normalize_text


@dataclass(frozen=True)
class SaudiLocation:
    is_saudi: bool
    city_code: str | None = None
    city_name: str | None = None
    region_code: str | None = None


_CITY_ALIASES: dict[str, tuple[str, str, tuple[str, ...]]] = {
    "RIYADH": ("Riyadh", "RIYADH", ("riyadh", "ar riyadh", "الرياض")),
    "JEDDAH": ("Jeddah", "MAKKAH", ("jeddah", "jiddah", "جدة")),
    "MAKKAH": ("Makkah", "MAKKAH", ("makkah", "mecca", "مكة", "مكه")),
    "MADINAH": ("Madinah", "MADINAH", ("madinah", "medina", "المدينة", "المدينه")),
    "DAMMAM": ("Dammam", "EASTERN", ("dammam", "الدمام")),
    "KHOBAR": ("Khobar", "EASTERN", ("khobar", "al khobar", "alkhobar", "الخبر")),
    "DHAHRAN": ("Dhahran", "EASTERN", ("dhahran", "الظهران")),
    "JUBAIL": ("Jubail", "EASTERN", ("jubail", "al jubail", "الجبيل")),
    "TABUK": ("Tabuk", "TABUK", ("tabuk", "تبوك")),
    "NEOM": ("NEOM", "TABUK", ("neom", "نيوم")),
    "TAIF": ("Taif", "MAKKAH", ("taif", "الطائف")),
    "ABHA": ("Abha", "ASIR", ("abha", "أبها", "ابها")),
    "YANBU": ("Yanbu", "MADINAH", ("yanbu", "ينبع")),
    "HAIL": ("Hail", "HAIL", ("hail", "حائل")),
    "JAZAN": ("Jazan", "JAZAN", ("jazan", "jizan", "جازان", "جيزان")),
    "NAJRAN": ("Najran", "NAJRAN", ("najran", "نجران")),
    "AL_KHARJ": ("Al Kharj", "RIYADH", ("al kharj", "alkharj", "الخرج")),
}

_SAUDI_COUNTRY_ALIASES = tuple(normalize_text(x) for x in (
    "Saudi Arabia", "Saudi", "KSA", "Kingdom of Saudi Arabia", "السعودية", "المملكة العربية السعودية"
))


def normalize_saudi_location(location: str) -> SaudiLocation:
    text = normalize_text(location)
    if not text:
        return SaudiLocation(False)

    for code, (name, region, aliases) in _CITY_ALIASES.items():
        for alias in aliases:
            if normalize_text(alias) in text:
                return SaudiLocation(True, code, name, region)

    if any(alias in text for alias in _SAUDI_COUNTRY_ALIASES):
        return SaudiLocation(True)
    return SaudiLocation(False)


def saudi_location_hashtags(location: str) -> list[str]:
    info = normalize_saudi_location(location)
    if not info.is_saudi:
        return []
    tags = ["#SaudiArabia"]
    if info.city_code:
        tags.append("#" + info.city_code.title().replace("_", ""))
    return tags
