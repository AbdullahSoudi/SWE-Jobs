"""Source comparison metrics for shadow/production evaluation.

The important discovery metrics are observation-based instead of processing-order
based. They only use jobs first discovered after schema v6 started recording
per-source observations; historical source order is intentionally not guessed.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from statistics import median
from typing import Iterable

from freshness import ensure_utc, iso_utc
from locations import normalize_saudi_location

ANALYTICS_START_KEY = "source_analytics_started_at"


@dataclass(frozen=True)
class SourceAnalytics:
    source: str
    runs: int = 0
    successful_runs: int = 0
    raw_count: int = 0
    relevant_count: int = 0
    fresh_count: int = 0
    shadow_eligible_count: int = 0
    coverage_gaps: int = 0
    discoveries: int = 0
    first_discoveries: int = 0
    mature_first_discoveries: int = 0
    exclusive_24h: int = 0
    median_lead_minutes: float | None = None

    @property
    def success_rate(self) -> float:
        return (self.successful_runs / self.runs) if self.runs else 0.0

    @property
    def relevant_rate(self) -> float:
        return (self.relevant_count / self.raw_count) if self.raw_count else 0.0

    @property
    def first_discovery_rate(self) -> float:
        return (self.first_discoveries / self.discoveries) if self.discoveries else 0.0

    @property
    def exclusive_rate(self) -> float:
        return (
            self.exclusive_24h / self.mature_first_discoveries
            if self.mature_first_discoveries
            else 0.0
        )


def _parse_iso(value: str) -> datetime:
    text = str(value or "").strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    return ensure_utc(parsed)


def _analytics_start(conn) -> datetime | None:
    row = conn.execute(
        "SELECT value FROM metadata WHERE key = ?", (ANALYTICS_START_KEY,)
    ).fetchone()
    if not row:
        return None
    try:
        return _parse_iso(str(row["value"]))
    except (TypeError, ValueError):
        return None


def _job_is_in_scope(location: str, *, saudi_only: bool) -> bool:
    if not saudi_only:
        return True
    return normalize_saudi_location(location).is_saudi


def build_source_analytics(
    conn,
    *,
    sources: Iterable[str],
    hours: int = 24,
    saudi_only: bool = False,
    exclusive_window_hours: int = 24,
    reference_time: datetime | None = None,
) -> list[SourceAnalytics]:
    """Build comparable metrics for the requested sources.

    Run metrics come from ``source_run_history``. Discovery metrics use
    ``source_observations`` and only consider jobs whose global first_seen_at is
    inside the observation-tracking period. ``exclusive_24h`` is only scored
    once a first discovery has had a full 24-hour opportunity to appear on
    another source.
    """
    now = ensure_utc(reference_time or datetime.now(UTC))
    requested = tuple(dict.fromkeys(str(s) for s in sources))
    if not requested:
        return []

    window_start = now - timedelta(hours=max(1, int(hours)))
    tracking_start = _analytics_start(conn)
    discovery_start = max(window_start, tracking_start) if tracking_start else window_start
    window_start_iso = iso_utc(window_start)
    discovery_start_iso = iso_utc(discovery_start)
    now_iso = iso_utc(now)
    mature_cutoff = now - timedelta(hours=max(1, int(exclusive_window_hours)))

    results: list[SourceAnalytics] = []
    for source in requested:
        run_row = conn.execute(
            """
            SELECT
                COUNT(*) AS runs,
                SUM(CASE WHEN status = 'ok' THEN 1 ELSE 0 END) AS successful_runs,
                COALESCE(SUM(raw_count), 0) AS raw_count,
                COALESCE(SUM(filtered_count), 0) AS relevant_count,
                COALESCE(SUM(fresh_count), 0) AS fresh_count,
                COALESCE(SUM(shadow_eligible_count), 0) AS shadow_eligible_count,
                COALESCE(SUM(coverage_gap), 0) AS coverage_gaps
            FROM source_run_history
            WHERE source = ? AND run_at >= ? AND run_at <= ?
            """,
            (source, window_start_iso, now_iso),
        ).fetchone()

        observation_rows = conn.execute(
            """
            SELECT o.job_id, o.first_seen_at, j.location, j.first_seen_at AS job_first_seen_at
            FROM source_observations o
            JOIN jobs j ON j.id = o.job_id
            WHERE o.source = ?
              AND o.first_seen_at >= ?
              AND o.first_seen_at <= ?
              AND EXISTS (
                  SELECT 1 FROM source_observations tracked
                  WHERE tracked.job_id = o.job_id AND tracked.first_was_new_job = 1
              )
            ORDER BY o.first_seen_at
            """,
            (source, discovery_start_iso, now_iso),
        ).fetchall()

        discoveries = 0
        first_discoveries = 0
        mature_first = 0
        exclusive = 0
        lead_minutes: list[float] = []

        for obs in observation_rows:
            if not _job_is_in_scope(str(obs["location"] or ""), saudi_only=saudi_only):
                continue
            discoveries += 1
            source_seen = _parse_iso(str(obs["first_seen_at"]))
            all_obs = conn.execute(
                """
                SELECT source, first_seen_at
                FROM source_observations
                WHERE job_id = ?
                ORDER BY first_seen_at, source
                """,
                (int(obs["job_id"]),),
            ).fetchall()
            if not all_obs:
                continue
            earliest = min(_parse_iso(str(row["first_seen_at"])) for row in all_obs)
            if source_seen != earliest:
                continue
            first_discoveries += 1

            later_other_times = sorted(
                _parse_iso(str(row["first_seen_at"]))
                for row in all_obs
                if str(row["source"]) != source
                and _parse_iso(str(row["first_seen_at"])) >= source_seen
            )
            if later_other_times:
                lead_minutes.append(
                    max(0.0, (later_other_times[0] - source_seen).total_seconds() / 60.0)
                )

            if source_seen <= mature_cutoff:
                mature_first += 1
                exclusive_deadline = source_seen + timedelta(hours=exclusive_window_hours)
                matched_within_window = any(t <= exclusive_deadline for t in later_other_times)
                if not matched_within_window:
                    exclusive += 1

        results.append(
            SourceAnalytics(
                source=source,
                runs=int(run_row["runs"] or 0),
                successful_runs=int(run_row["successful_runs"] or 0),
                raw_count=int(run_row["raw_count"] or 0),
                relevant_count=int(run_row["relevant_count"] or 0),
                fresh_count=int(run_row["fresh_count"] or 0),
                shadow_eligible_count=int(run_row["shadow_eligible_count"] or 0),
                coverage_gaps=int(run_row["coverage_gaps"] or 0),
                discoveries=discoveries,
                first_discoveries=first_discoveries,
                mature_first_discoveries=mature_first,
                exclusive_24h=exclusive,
                median_lead_minutes=(median(lead_minutes) if lead_minutes else None),
            )
        )
    return results


def format_source_analytics(
    rows: Iterable[SourceAnalytics], *, label: str = "Source analytics"
) -> list[str]:
    """Return compact log lines suitable for GitHub Actions output."""
    output: list[str] = []
    for row in rows:
        lead = "n/a" if row.median_lead_minutes is None else f"{row.median_lead_minutes:.1f}m"
        output.append(
            f"{label} | {row.source}: runs={row.runs}, ok={row.success_rate:.0%}, "
            f"raw={row.raw_count}, relevant={row.relevant_count} ({row.relevant_rate:.0%}), "
            f"fresh={row.fresh_count}, discoveries={row.discoveries}, "
            f"first={row.first_discoveries} ({row.first_discovery_rate:.0%}), "
            f"exclusive24h={row.exclusive_24h}/{row.mature_first_discoveries}, "
            f"median_lead={lead}, gaps={row.coverage_gaps}"
        )
    return output


def main() -> None:
    import argparse
    from db import DB_FILE, connect

    parser = argparse.ArgumentParser(description="Compare job source discovery metrics")
    parser.add_argument("--db", default=DB_FILE)
    parser.add_argument("--hours", type=int, default=168)
    parser.add_argument("--saudi-only", action="store_true")
    parser.add_argument(
        "sources", nargs="*", default=["linkedin", "linkedin_saudi_v2"]
    )
    args = parser.parse_args()

    with connect(args.db) as conn:
        rows = build_source_analytics(
            conn,
            sources=args.sources,
            hours=args.hours,
            saudi_only=args.saudi_only,
        )
    for line in format_source_analytics(rows, label=f"Source analytics {args.hours}h"):
        print(line)


if __name__ == "__main__":
    main()
