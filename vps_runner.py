"""Persistent-host entrypoint for one scheduled bot cycle."""
from __future__ import annotations

import logging
import os

from db import DB_FILE
from main import run_bot
from runtime_lock import try_process_lock

log = logging.getLogger(__name__)


def main() -> int:
    lock_path = os.getenv("BOT_LOCK_FILE", f"{DB_FILE}.lock")
    with try_process_lock(lock_path) as acquired:
        if not acquired:
            log.warning("Another bot run is still active; skipping this timer tick.")
            return 0
        run_bot(db_path=DB_FILE)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
