"""Single-instance process locking for persistent bot hosts."""
from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path
from typing import Iterator, TextIO


@contextmanager
def try_process_lock(lock_path: str | Path | None = None) -> Iterator[bool]:
    """Try to take a non-blocking exclusive lock for one bot run.

    On Linux this uses ``flock`` through :mod:`fcntl`.  The context yields
    ``False`` when another process already holds the lock, allowing a timer
    invocation to exit successfully instead of overlapping the active run.
    """
    path = Path(lock_path or os.getenv("BOT_LOCK_FILE", "/tmp/swe-jobs.lock"))
    path.parent.mkdir(parents=True, exist_ok=True)
    handle: TextIO = path.open("a+", encoding="utf-8")
    acquired = False
    try:
        try:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            acquired = True
            handle.seek(0)
            handle.truncate()
            handle.write(str(os.getpid()))
            handle.flush()
        except BlockingIOError:
            acquired = False
        yield acquired
    finally:
        if acquired:
            try:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
        handle.close()
