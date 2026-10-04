import json
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from classifier import classify_job, normalize_text
from models import Job


class ClassifierTests(unittest.TestCase):
    def test_normalization_handles_arabic_variants(self):
        self.assertEqual(normalize_text("أمنُ المعلومات"), "امن المعلومات")
        self.assertEqual(normalize_text("مُطوّر  برمجيات"), "مطور برمجيات")

    def test_golden_classifier_set_has_high_precision_and_recall(self):
        cases = json.loads((Path(__file__).with_name("classifier_cases.json")).read_text(encoding="utf-8"))
        tp = fp = fn = category_correct = tech_total = 0
        failures = []
        for index, case in enumerate(cases):
            expected = case["expected"]
            job = Job(
                title=case["title"], company="Test", location="Riyadh, Saudi Arabia",
                url=f"https://example.com/{index}", source="linkedin_saudi_v2",
            )
            result = classify_job(job)
            predicted = result.topic if result.is_tech else None
            expected_tech = expected is not None
            if result.is_tech and expected_tech:
                tp += 1
            elif result.is_tech and not expected_tech:
                fp += 1
            elif not result.is_tech and expected_tech:
                fn += 1
            if expected_tech:
                tech_total += 1
                if predicted == expected:
                    category_correct += 1
            if predicted != expected:
                failures.append((case["title"], expected, predicted, result.reason, result.matched))

        precision = tp / (tp + fp) if (tp + fp) else 1.0
        recall = tp / (tp + fn) if (tp + fn) else 1.0
        category_accuracy = category_correct / tech_total if tech_total else 1.0
        self.assertGreaterEqual(precision, 0.97, failures)
        self.assertGreaterEqual(recall, 0.97, failures)
        self.assertGreaterEqual(category_accuracy, 0.95, failures)

    def test_nontech_exclusion_wins_over_generic_engineer(self):
        job = Job("Electrical Engineer", "Acme", "Riyadh", "https://x/1", "linkedin")
        self.assertFalse(classify_job(job).is_tech)


if __name__ == "__main__":
    unittest.main()
