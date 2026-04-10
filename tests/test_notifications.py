"""Tests for subscription matching, source/location filters, and blacklist."""

from core.models import Job
from bot.notifications import _job_matches_subscription, _job_blocked_by_blacklist


def _make_job(**kwargs) -> Job:
    defaults = {
        "title": "Software Engineer",
        "company": "Acme",
        "location": "Cairo, Egypt",
        "url": "http://x.com",
        "source": "test",
        "topics": ["backend"],
        "country": "EG",
    }
    defaults.update(kwargs)
    return Job(**defaults)


class TestJobMatchesSubscription:
    def test_empty_subs_returns_false(self):
        assert not _job_matches_subscription(_make_job(), {})

    def test_topic_match(self):
        subs = {"topics": ["backend"]}
        assert _job_matches_subscription(_make_job(), subs)

    def test_topic_mismatch(self):
        subs = {"topics": ["mobile"]}
        assert not _job_matches_subscription(_make_job(), subs)

    def test_location_egypt_match(self):
        subs = {"topics": ["backend"], "locations": ["EG"]}
        assert _job_matches_subscription(_make_job(country="EG"), subs)

    def test_location_mismatch(self):
        subs = {"topics": ["backend"], "locations": ["US"]}
        assert not _job_matches_subscription(_make_job(country="EG"), subs)

    def test_location_remote_match(self):
        subs = {"topics": ["backend"], "locations": ["remote"]}
        assert _job_matches_subscription(_make_job(is_remote=True), subs)

    def test_location_remote_mismatch(self):
        subs = {"topics": ["backend"], "locations": ["remote"]}
        assert not _job_matches_subscription(_make_job(is_remote=False, country="EG"), subs)

    def test_location_multiple_any_match(self):
        subs = {"topics": ["backend"], "locations": ["EG", "SA"]}
        assert _job_matches_subscription(_make_job(country="SA"), subs)

    def test_no_location_filter_matches_all(self):
        subs = {"topics": ["backend"]}
        assert _job_matches_subscription(_make_job(country="EG"), subs)
        assert _job_matches_subscription(_make_job(country="US"), subs)

    def test_remote_plus_country(self):
        subs = {"topics": ["backend"], "locations": ["remote", "EG"]}
        # Remote job from US should match (remote selected)
        assert _job_matches_subscription(_make_job(country="US", is_remote=True), subs)
        # Onsite Egypt job should match (EG selected)
        assert _job_matches_subscription(_make_job(country="EG", is_remote=False), subs)
        # Onsite US job should NOT match
        assert not _job_matches_subscription(_make_job(country="US", is_remote=False), subs)


class TestSourceFilter:
    def test_source_match(self):
        subs = {"topics": ["backend"], "sources": ["remotive"]}
        assert _job_matches_subscription(_make_job(source="remotive"), subs)

    def test_source_mismatch(self):
        subs = {"topics": ["backend"], "sources": ["remotive"]}
        assert not _job_matches_subscription(_make_job(source="himalayas"), subs)

    def test_no_source_filter_matches_all(self):
        subs = {"topics": ["backend"]}
        assert _job_matches_subscription(_make_job(source="remotive"), subs)
        assert _job_matches_subscription(_make_job(source="himalayas"), subs)

    def test_jsearch_linkedin_match(self):
        """JSearch jobs with original_source=LinkedIn should match 'linkedin' filter."""
        subs = {"topics": ["backend"], "sources": ["linkedin"]}
        assert _job_matches_subscription(
            _make_job(source="jsearch", original_source="LinkedIn"), subs
        )

    def test_jsearch_indeed_no_match_when_linkedin_only(self):
        subs = {"topics": ["backend"], "sources": ["linkedin"]}
        assert not _job_matches_subscription(
            _make_job(source="jsearch", original_source="Indeed"), subs
        )

    def test_multiple_sources(self):
        subs = {"topics": ["backend"], "sources": ["remotive", "linkedin"]}
        assert _job_matches_subscription(_make_job(source="remotive"), subs)
        assert _job_matches_subscription(
            _make_job(source="jsearch", original_source="LinkedIn"), subs
        )
        assert not _job_matches_subscription(_make_job(source="himalayas"), subs)


class TestBlacklist:
    def test_empty_blacklist_allows_all(self):
        assert not _job_blocked_by_blacklist(_make_job(), {})
        assert not _job_blocked_by_blacklist(_make_job(), {"companies": [], "keywords": []})

    def test_company_blocked(self):
        bl = {"companies": ["Acme"], "keywords": []}
        assert _job_blocked_by_blacklist(_make_job(company="Acme Corp"), bl)

    def test_company_case_insensitive(self):
        bl = {"companies": ["acme"], "keywords": []}
        assert _job_blocked_by_blacklist(_make_job(company="ACME Inc"), bl)

    def test_company_not_blocked(self):
        bl = {"companies": ["Acme"], "keywords": []}
        assert not _job_blocked_by_blacklist(_make_job(company="Google"), bl)

    def test_keyword_blocks_title(self):
        bl = {"companies": [], "keywords": ["recruiter"]}
        assert _job_blocked_by_blacklist(_make_job(title="Recruiter Specialist"), bl)

    def test_keyword_blocks_company(self):
        bl = {"companies": [], "keywords": ["staffing"]}
        assert _job_blocked_by_blacklist(_make_job(company="Staffing Solutions"), bl)

    def test_keyword_no_match(self):
        bl = {"companies": [], "keywords": ["recruiter"]}
        assert not _job_blocked_by_blacklist(_make_job(title="Software Engineer", company="Google"), bl)

    def test_combined_blacklist(self):
        bl = {"companies": ["BadCorp"], "keywords": ["intern"]}
        # Company match
        assert _job_blocked_by_blacklist(_make_job(company="BadCorp LLC"), bl)
        # Keyword match
        assert _job_blocked_by_blacklist(_make_job(title="Software Intern", company="Google"), bl)
        # Neither
        assert not _job_blocked_by_blacklist(_make_job(title="Senior Dev", company="Google"), bl)
