import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eligibility import (
    EXPLICITLY_OPEN,
    NOT_SPECIFIED,
    SAUDI_ONLY,
    classify_eligibility,
    html_to_text,
)


class EligibilityTests(unittest.TestCase):
    def test_saudi_only_english_requires_explicit_restriction(self):
        result = classify_eligibility(
            description="This role is open to Saudi nationals only. Strong Python skills required."
        )
        self.assertEqual(result.value, SAUDI_ONLY)
        self.assertIn("Saudi nationals only", result.evidence)

    def test_saudi_only_arabic_is_detected(self):
        result = classify_eligibility(description="هذه الفرصة للسعوديين فقط ونرحب بالخريجين الجدد")
        self.assertEqual(result.value, SAUDI_ONLY)
        self.assertIn("للسعوديين فقط", result.evidence)

    def test_all_nationalities_is_explicitly_open(self):
        result = classify_eligibility(description="Applications are open to all nationalities.")
        self.assertEqual(result.value, EXPLICITLY_OPEN)

    def test_saudi_or_non_saudi_is_open_not_saudi_only(self):
        result = classify_eligibility(description="Saudi or non-Saudi applicants may apply.")
        self.assertEqual(result.value, EXPLICITLY_OPEN)

    def test_non_saudis_need_not_apply_is_saudi_only(self):
        result = classify_eligibility(description="Non-Saudis need not apply for this position.")
        self.assertEqual(result.value, SAUDI_ONLY)

    def test_visa_sponsorship_is_explicit_open_evidence(self):
        result = classify_eligibility(description="Work visa sponsorship is provided for the right candidate.")
        self.assertEqual(result.value, EXPLICITLY_OPEN)

    def test_preference_is_not_misrepresented_as_restriction(self):
        result = classify_eligibility(description="Saudi nationals preferred, but all candidates are considered.")
        # No strong restriction/open phrase: do not infer.
        self.assertEqual(result.value, NOT_SPECIFIED)

    def test_tamheer_title_is_saudi_only_signal(self):
        result = classify_eligibility(title="Software Engineer - Tamheer Program")
        self.assertEqual(result.value, SAUDI_ONLY)

    def test_html_is_converted_to_plain_text_before_matching(self):
        text = html_to_text("<p>Open to <strong>all nationalities</strong>.</p><p>Riyadh</p>")
        self.assertEqual(text, "Open to all nationalities.\nRiyadh")
        result = classify_eligibility(description=text)
        self.assertEqual(result.value, EXPLICITLY_OPEN)

    def test_silence_defaults_to_not_specified(self):
        result = classify_eligibility(description="Build APIs and work with PostgreSQL.")
        self.assertEqual(result.value, NOT_SPECIFIED)
        self.assertEqual(result.evidence, "")


if __name__ == "__main__":
    unittest.main()
