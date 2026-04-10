"""Tests for the job enrichment pipeline."""

from core.enrichment import enrich_job
from core.models import Job


def _make_job(**kwargs) -> Job:
    defaults = {"title": "", "company": "", "location": "", "url": "http://x.com", "source": "test"}
    defaults.update(kwargs)
    return Job(**defaults)


class TestEnrichJob:
    def test_parses_salary(self):
        job = _make_job(title="Dev", salary_raw="$80,000 - $120,000")
        enriched = enrich_job(job)
        assert enriched.salary_min == 80000
        assert enriched.salary_max == 120000
        assert enriched.salary_currency == "USD"

    def test_detects_seniority(self):
        job = _make_job(title="Senior Python Developer")
        enriched = enrich_job(job)
        assert enriched.seniority == "senior"

    def test_detects_country(self):
        job = _make_job(title="Dev", location="Cairo, Egypt")
        enriched = enrich_job(job)
        assert enriched.country == "EG"

    def test_routes_topics(self):
        job = _make_job(title="Flutter Developer", location="Cairo, Egypt")
        enriched = enrich_job(job)
        assert "mobile" in enriched.topics
        assert "egypt" in enriched.topics
        assert "general" not in enriched.topics  # general is fallback only

    def test_general_fallback_when_no_topic_matched(self):
        job = _make_job(title="Miscellaneous Role", location="Unknown")
        enriched = enrich_job(job)
        assert enriched.topics == ["general"]

    def test_no_salary_leaves_none(self):
        job = _make_job(title="Dev", salary_raw="Competitive")
        enriched = enrich_job(job)
        assert enriched.salary_min is None

    def test_preserves_existing_fields(self):
        job = _make_job(title="Dev", company="Acme", tags=["python"])
        enriched = enrich_job(job)
        assert enriched.company == "Acme"
        assert enriched.tags == ["python"]
