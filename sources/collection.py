"""Collection completeness for bounded, multi-page source adapters."""
from collections.abc import Sequence
from dataclasses import dataclass, field
import html
import re

from models import Job


@dataclass
class CollectionResult(Sequence):
    # Sequence access preserves existing consumers without dropping metadata.
    jobs: list[Job] = field(default_factory=list)
    pages_attempted: int = 0
    pages_succeeded: int = 0
    page_errors: list[str] = field(default_factory=list)

    def __len__(self):
        return len(self.jobs)

    def __getitem__(self, index):
        return self.jobs[index]

    def record_page(self, error: str = "") -> None:
        self.pages_attempted += 1
        if error:
            self.page_errors.append(f"page={self.pages_attempted} {error}")
        else:
            self.pages_succeeded += 1

    @property
    def pages_failed(self) -> int:
        return len(self.page_errors)

    @property
    def status(self) -> str:
        if self.pages_attempted and not self.pages_failed:
            return "ok"
        return "partial" if self.pages_succeeded or self.jobs else "failed"

    @property
    def complete(self) -> bool:
        return self.status == "ok"

    @property
    def error(self) -> str:
        return "; ".join(self.page_errors) if self.pages_attempted else "no_pages_attempted"


def is_access_challenge(page: str) -> bool:
    """Recognize structural challenge/login evidence, not words in job titles."""
    return bool(re.search(r'<input\b[^>]*\btype\s*=\s*["\']password["\']', page, re.I)
                or re.search(r'<title\b[^>]*>\s*(?:sign[ -]?in|log[ -]?in|security verification|just a moment|access denied)\b',
                             page, re.I))


def has_empty_results_notice(page: str) -> bool:
    visible = re.sub(r'<(?:script|style)\b[^>]*>.*?</(?:script|style)>', '', page, flags=re.I | re.S)
    visible = html.unescape(visible)
    return bool(re.search(r'>\s*(?:no (?:matching )?jobs found|no results found|لا توجد وظائف|لا توجد نتائج)\s*[.!]?\s*<',
                          visible, re.I))
