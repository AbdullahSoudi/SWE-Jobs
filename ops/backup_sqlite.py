"""Create verified compressed SQLite backups for persistent hosts."""
from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta
import gzip
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile


def _utc_stamp(now: datetime) -> str:
    return now.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


def _verify_sqlite(path: Path) -> None:
    conn = sqlite3.connect(str(path))
    try:
        row = conn.execute("PRAGMA integrity_check").fetchone()
        result = str(row[0]) if row else ""
        if result.lower() != "ok":
            raise RuntimeError(f"backup integrity_check failed: {result}")
    finally:
        conn.close()


def _rotate_backups(backup_dir: Path, *, cutoff: datetime) -> int:
    removed = 0
    cutoff_ts = cutoff.timestamp()
    for path in backup_dir.glob("jobs-*.db.gz"):
        try:
            if path.stat().st_mtime < cutoff_ts:
                path.unlink()
                removed += 1
        except FileNotFoundError:
            continue
    return removed


def create_backup(
    db_path: str | Path,
    backup_dir: str | Path,
    *,
    retention_days: int = 14,
    reference_time: datetime | None = None,
) -> Path:
    """Create an online SQLite backup, verify it, gzip it, and rotate old files."""
    source = Path(db_path)
    if not source.exists():
        raise FileNotFoundError(f"SQLite database not found: {source}")

    destination_dir = Path(backup_dir)
    destination_dir.mkdir(parents=True, exist_ok=True)
    now = (reference_time or datetime.now(UTC)).astimezone(UTC).replace(microsecond=0)
    final_path = destination_dir / f"jobs-{_utc_stamp(now)}.db.gz"

    with tempfile.TemporaryDirectory(prefix="swe-jobs-backup-") as tmp:
        snapshot = Path(tmp) / "jobs.db"
        src_conn = sqlite3.connect(str(source), timeout=30)
        dst_conn = sqlite3.connect(str(snapshot))
        try:
            src_conn.backup(dst_conn)
        finally:
            dst_conn.close()
            src_conn.close()

        _verify_sqlite(snapshot)
        temp_gzip = destination_dir / f".{final_path.name}.tmp"
        try:
            with snapshot.open("rb") as src, gzip.open(temp_gzip, "wb", compresslevel=6) as dst:
                shutil.copyfileobj(src, dst)
            os.replace(temp_gzip, final_path)
        finally:
            temp_gzip.unlink(missing_ok=True)

    _rotate_backups(
        destination_dir,
        cutoff=now - timedelta(days=max(1, int(retention_days))),
    )
    return final_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Back up the SWE Jobs SQLite database")
    parser.add_argument("--db", default=os.getenv("JOBS_DB_PATH", "jobs.db"))
    parser.add_argument("--backup-dir", default=os.getenv("BACKUP_DIR", "backups"))
    parser.add_argument(
        "--retention-days",
        type=int,
        default=int(os.getenv("BACKUP_RETENTION_DAYS", "14")),
    )
    args = parser.parse_args()
    path = create_backup(
        args.db,
        args.backup_dir,
        retention_days=args.retention_days,
    )
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
