"""Fail-closed restoration and read-only verification of Actions snapshots.

Production requires an existing data branch. Missing state is an operator
recovery/bootstrap task, never inferred from a failed Git command.
"""
import argparse
from pathlib import Path
import sqlite3
import subprocess


def verify_snapshot(path: str | Path = "jobs.db") -> None:
    path = Path(path).resolve()
    if not path.is_file() or path.stat().st_size == 0:
        raise RuntimeError("Existing nonempty SQLite snapshot is required")
    conn = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
    try:
        results = conn.execute("PRAGMA integrity_check").fetchall()
        if results != [("ok",)]:
            raise RuntimeError("SQLite snapshot failed integrity_check")
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {"jobs", "source_runs", "metadata"}.issubset(tables):
            raise RuntimeError("Snapshot is missing required bot tables")
    finally:
        conn.close()


def restore_snapshot() -> None:
    subprocess.run(["git", "fetch", "--depth=1", "origin",
                    "refs/heads/data:refs/remotes/origin/data"], check=True)
    subprocess.run(["git", "checkout", "origin/data", "--", "jobs.db"], check=True)
    verify_snapshot("jobs.db")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("restore", "verify"))
    args = parser.parse_args()
    if args.action == "restore":
        restore_snapshot()
    else:
        verify_snapshot()


if __name__ == "__main__":
    main()
