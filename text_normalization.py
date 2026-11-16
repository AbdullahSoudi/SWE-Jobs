"""Shared bilingual text normalization without model/config dependencies."""
import re
import unicodedata
from functools import lru_cache

_ARABIC_DIACRITICS = re.compile(r"[\u0610-\u061a\u064b-\u065f\u0670\u06d6-\u06ed]")
_NON_WORD = re.compile(r"[^\w+#.]+", re.UNICODE)


def normalize_text(value: str) -> str:
    text = unicodedata.normalize("NFKC", value or "").lower()
    text = _ARABIC_DIACRITICS.sub("", text)
    text = text.replace("ـ", "")
    text = text.translate(str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ى": "ي", "ؤ": "و", "ئ": "ي"}))
    text = _NON_WORD.sub(" ", text)
    return " ".join(text.split())


@lru_cache(maxsize=1024)
def phrase_pattern(phrase: str) -> re.Pattern:
    # Unlike \b, these boundaries work with .NET, C++ and C# too.
    return re.compile(r"(?<![\w+#.])" + re.escape(normalize_text(phrase)) + r"(?![\w+#])")


def contains_phrase(normalized_text: str, phrase: str) -> bool:
    return bool(normalize_text(phrase) and phrase_pattern(phrase).search(normalized_text))
