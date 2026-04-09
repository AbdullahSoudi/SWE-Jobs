"""
Per-source retry with backoff and DB-backed circuit breaker.
State persists in the source_health table across GitHub Actions runs.
"""

import time
import logging
from typing import Callable

from core import db

log = logging.getLogger(__name__)

# Retry delays in seconds (index = retry attempt)
RETRY_DELAYS = [2, 5]


def is_circuit_open(source: str) -> bool:
    """Check if a source's circuit breaker is open (should be skipped)."""
    try:
        return db.is_source_circuit_open(source)
    except Exception as e:
        log.warning(f"Failed to check circuit state for {source}: {e}")
        return False  # If DB is down, try fetching anyway


def _record_success(source: str) -> None:
    """Record a successful fetch — resets circuit breaker."""
    try:
        db.upsert_source_health(source, success=True)
    except Exception as e:
        log.warning(f"Failed to record success for {source}: {e}")


def _record_failure(source: str, error: str) -> None:
    """Record a failed fetch — increments failure count, may open circuit."""
    try:
        db.upsert_source_health(source, success=False, error=error)
    except Exception as e:
        log.warning(f"Failed to record failure for {source}: {e}")


def fetch_with_retry(
    source: str,
    fetcher: Callable,
    max_retries: int = 2,
    timeout: int = 15,
) -> list:
    """
    Fetch jobs from a source with retry and circuit breaker.

    Args:
        source: Source identifier (e.g. 'remotive')
        fetcher: Callable that returns list of jobs
        max_retries: Number of retry attempts after first failure
        timeout: Per-request timeout (passed to fetcher if supported)

    Returns: List of jobs (empty if all attempts fail or circuit is open)
    """
    # Check circuit breaker
    if is_circuit_open(source):
        log.warning(f"⚡ Circuit OPEN for {source} — skipping")
        return []

    last_error = None
    for attempt in range(1 + max_retries):
        try:
            result = fetcher()
            _record_success(source)
            if attempt > 0:
                log.info(f"✓ {source} succeeded on retry {attempt}")
            return result if result else []
        except Exception as e:
            last_error = str(e)
            if attempt < max_retries:
                delay = RETRY_DELAYS[min(attempt, len(RETRY_DELAYS) - 1)]
                log.warning(f"⚠ {source} attempt {attempt + 1} failed: {e}. Retrying in {delay}s...")
                time.sleep(delay)
            else:
                log.error(f"✗ {source} failed after {max_retries + 1} attempts: {e}")

    _record_failure(source, last_error or "unknown")
    return []
