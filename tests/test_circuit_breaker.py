"""Tests for the circuit breaker with DB-backed state."""

from unittest.mock import patch, MagicMock
from core.circuit_breaker import fetch_with_retry, is_circuit_open


class TestFetchWithRetry:
    @patch("core.circuit_breaker.is_circuit_open", return_value=False)
    @patch("core.circuit_breaker._record_success")
    def test_success_on_first_try(self, mock_record, mock_open):
        def fetcher():
            return [{"title": "Dev"}]

        result = fetch_with_retry("test_source", fetcher)
        assert result == [{"title": "Dev"}]
        mock_record.assert_called_once_with("test_source")

    @patch("core.circuit_breaker.is_circuit_open", return_value=False)
    @patch("core.circuit_breaker._record_failure")
    @patch("core.circuit_breaker._record_success")
    @patch("time.sleep")
    def test_retries_on_failure(self, mock_sleep, mock_success, mock_failure, mock_open):
        call_count = 0
        def fetcher():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise Exception("timeout")
            return [{"title": "Dev"}]

        result = fetch_with_retry("test_source", fetcher, max_retries=3)
        assert result == [{"title": "Dev"}]
        assert call_count == 3

    @patch("core.circuit_breaker.is_circuit_open", return_value=True)
    def test_skips_when_circuit_open(self, mock_open):
        def fetcher():
            return [{"title": "Dev"}]

        result = fetch_with_retry("test_source", fetcher)
        assert result == []

    @patch("core.circuit_breaker.is_circuit_open", return_value=False)
    @patch("core.circuit_breaker._record_failure")
    @patch("time.sleep")
    def test_returns_empty_after_max_retries(self, mock_sleep, mock_failure, mock_open):
        def fetcher():
            raise Exception("always fails")

        result = fetch_with_retry("test_source", fetcher, max_retries=2)
        assert result == []


class TestIsCircuitOpen:
    @patch("core.db.is_source_circuit_open", return_value=True)
    def test_open(self, mock_db):
        assert is_circuit_open("failing_source") is True

    @patch("core.db.is_source_circuit_open", return_value=False)
    def test_closed(self, mock_db):
        assert is_circuit_open("healthy_source") is False
