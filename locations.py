"""Country-aware locations shared by filtering, ATS selection and deduplication.

Explicit countries override city-only inference. Unknown qualifiers and conflicting
countries stay unresolved; this is a bounded alias resolver, not a geocoder.
"""
from __future__ import annotations

from dataclasses import dataclass
import re

from text_normalization import normalize_text, contains_phrase, phrase_pattern


@dataclass(frozen=True)
class Location:
    country_code: str | None = None
    city_code: str | None = None
    city_name: str | None = None
    region_code: str | None = None
    ambiguous: bool = False


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
    "MADINAH": ("Madinah", "MADINAH", ("madinah", "medina", "al madinah", "madinah al munawwarah",
                                        "al madinah al munawwarah", "المدينة", "المدينه",
                                        "المدينة المنورة", "المدينه المنوره")),
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
    "Saudi Arabia", "Saudi", "KSA", "SA", "Kingdom of Saudi Arabia", "السعودية", "المملكة العربية السعودية"
))

_COUNTRY_ALIASES = {
    "SA": _SAUDI_COUNTRY_ALIASES,
    "EG": ("Egypt", "EG", "مصر"),
    "US": ("United States", "United States of America", "USA", "U.S.A.", "US", "U.S.", "الولايات المتحدة"),
    "GB": ("United Kingdom", "UK", "U.K.", "GB", "England", "Britain", "بريطانيا"),
    "TH": ("Thailand", "TH", "تايلاند"),
    "AE": ("United Arab Emirates", "UAE", "AE", "الإمارات"),
    "QA": ("Qatar", "QA", "قطر"),
    "KW": ("Kuwait", "KW", "الكويت"),
    "BH": ("Bahrain", "BH", "البحرين"),
    "OM": ("Oman", "OM", "عمان"),
    "JO": ("Jordan", "JO", "الأردن"),
    "CA": ("Canada", "كندا"),
    "AU": ("Australia", "AU", "أستراليا"),
    "IN": ("India", "الهند"),
    "DE": ("Germany", "DE", "ألمانيا"),
    "FR": ("France", "FR", "فرنسا"),
}

# Compatibility exports for legacy consumers. The resolver owns these aliases.
EGYPT_PATTERNS = {
    "egypt", "مصر", "cairo", "القاهرة", "alexandria", "الإسكندرية",
    "giza", "الجيزة", "minya", "المنيا", "mansoura", "المنصورة",
    "tanta", "طنطا", "aswan", "أسوان", "luxor", "الأقصر",
    "port said", "بورسعيد", "suez", "السويس", "ismailia", "الإسماعيلية",
    "fayoum", "الفيوم", "zagazig", "الزقازيق", "damanhur", "دمنهور",
    "beni suef", "بني سويف", "sohag", "سوهاج", "asyut", "أسيوط",
    "qena", "قنا", "hurghada", "الغردقة", "sharm el sheikh",
    "new cairo", "6th of october", "6 october", "smart village",
    "new capital", "العاصمة الإدارية", "nasr city", "مدينة نصر",
    "maadi", "المعادي", "heliopolis", "مصر الجديدة", "dokki", "الدقي",
    "mohandessin", "المهندسين",
}
_SAUDI_REGIONS = ("qassim", "القصيم", "eastern province", "المنطقة الشرقية")
SAUDI_PATTERNS = set(_SAUDI_COUNTRY_ALIASES) | set(_SAUDI_REGIONS) | {
    alias for _, _, aliases in _CITY_ALIASES.values() for alias in aliases
}
_LOCAL_QUALIFIERS = ("region", "province", "governorate", "greater", "area",
                     "metropolitan", "remote", "hybrid", "on site", "onsite", "عن بعد")


def _country_codes(text: str) -> set[str]:
    return {code for code, aliases in _COUNTRY_ALIASES.items()
            if any(contains_phrase(text, alias) for alias in aliases)}


def normalize_location(location: str, *, country: str = "") -> Location:
    text = normalize_text(location)
    countries = _country_codes(text)
    if country.strip():
        hint = normalize_text(country)
        codes = _country_codes(hint)
        # A structured country field is authoritative even for countries outside
        # our alias list. Never turn a foreign primary ATS office into Saudi.
        countries.update(codes or {hint.upper() if re.fullmatch(r"[a-z]{2}", hint) else "OTHER"})
    if len(countries) > 1:
        return Location(ambiguous=True)
    explicit = next(iter(countries), None)
    if explicit and explicit not in {"SA", "EG"}:
        return Location(country_code=explicit)

    cities = [(code, name, region) for code, (name, region, aliases) in _CITY_ALIASES.items()
              if any(contains_phrase(text, alias) for alias in aliases)]
    saudi = bool(cities or any(contains_phrase(text, alias) for alias in _SAUDI_REGIONS))
    egypt = any(contains_phrase(text, alias) for alias in EGYPT_PATTERNS)
    if explicit is None:
        if saudi and egypt:
            return Location(ambiguous=True)
        # Unknown words alongside a city may be a foreign state/country. Require
        # all qualifiers to be understood before inferring a country from a city.
        remainder = text
        for alias in sorted(SAUDI_PATTERNS | EGYPT_PATTERNS | set(_LOCAL_QUALIFIERS),
                            key=lambda item: len(normalize_text(item)), reverse=True):
            remainder = phrase_pattern(alias).sub(" ", remainder)
        if remainder.strip(" ."):
            return Location()
        explicit = "SA" if saudi else "EG" if egypt else None

    if explicit == "SA":
        if len(cities) > 1:
            return Location(country_code="SA", ambiguous=True)
        if cities:
            code, name, region = cities[0]
            return Location("SA", code, name, region)
    return Location(country_code=explicit)


def normalize_saudi_location(location: str) -> SaudiLocation:
    info = normalize_location(location)
    return SaudiLocation(info.country_code == "SA", info.city_code, info.city_name, info.region_code)


def saudi_location_hashtags(location: str) -> list[str]:
    info = normalize_saudi_location(location)
    if not info.is_saudi:
        return []
    tags = ["#SaudiArabia"]
    if info.city_code:
        tags.append("#" + info.city_code.title().replace("_", ""))
    return tags
