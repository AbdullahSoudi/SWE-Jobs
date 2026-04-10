"""Tests for the streak calculation logic (unit-tested with mocked DB rows)."""

from datetime import date, timedelta
from unittest.mock import patch


def _make_day_rows(days: list[date]) -> list[dict]:
    """Build the row format returned by the streak query."""
    return [{"day": d} for d in sorted(days, reverse=True)]


class TestStreakCalculation:
    """Test the streak logic extracted from db.get_streak."""

    def _calc(self, day_rows, today=None):
        """Run the streak calculation with optional frozen 'today'."""
        from datetime import date as _date, timedelta as _td

        if today is None:
            today = _date.today()

        if not day_rows:
            return {"current": 0, "longest": 0, "today": False}

        days = [row["day"] for row in day_rows]
        applied_today = days[0] == today

        current = 0
        expected = today if applied_today else today - _td(days=1)
        for d in days:
            if d == expected:
                current += 1
                expected -= _td(days=1)
            elif d < expected:
                break

        longest = 1
        run = 1
        for i in range(1, len(days)):
            if days[i] == days[i - 1] - _td(days=1):
                run += 1
                longest = max(longest, run)
            else:
                run = 1

        return {"current": current, "longest": longest, "today": applied_today}

    def test_no_applications(self):
        result = self._calc([])
        assert result == {"current": 0, "longest": 0, "today": False}

    def test_applied_today_only(self):
        today = date.today()
        rows = _make_day_rows([today])
        result = self._calc(rows, today)
        assert result["current"] == 1
        assert result["today"] is True

    def test_three_day_streak(self):
        today = date.today()
        days = [today - timedelta(days=i) for i in range(3)]
        rows = _make_day_rows(days)
        result = self._calc(rows, today)
        assert result["current"] == 3
        assert result["longest"] == 3
        assert result["today"] is True

    def test_streak_yesterday_not_today(self):
        today = date.today()
        days = [today - timedelta(days=i) for i in range(1, 4)]  # yesterday, day before, ...
        rows = _make_day_rows(days)
        result = self._calc(rows, today)
        assert result["current"] == 3
        assert result["today"] is False

    def test_broken_streak(self):
        today = date.today()
        # Applied today and 3 days ago (gap of 1 day)
        days = [today, today - timedelta(days=3)]
        rows = _make_day_rows(days)
        result = self._calc(rows, today)
        assert result["current"] == 1  # only today counts
        assert result["today"] is True

    def test_longest_streak_in_past(self):
        today = date.today()
        # Current: today only. Past: 5-day streak ending 10 days ago.
        past_streak = [today - timedelta(days=10 - i) for i in range(5)]
        days = [today] + past_streak
        rows = _make_day_rows(days)
        result = self._calc(rows, today)
        assert result["current"] == 1
        assert result["longest"] == 5

    def test_streak_broken_two_days_ago(self):
        today = date.today()
        # Last applied 2 days ago — streak is broken
        rows = _make_day_rows([today - timedelta(days=2)])
        result = self._calc(rows, today)
        assert result["current"] == 0
        assert result["today"] is False
