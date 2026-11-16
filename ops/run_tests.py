"""Run mocked regression tests with temporary state and no external operations."""
from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile
import unittest


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    # Imports must not inherit a developer's production credentials/settings.
    keep = {key: value for key, value in os.environ.items()
            if key.upper() in {"SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "PATH"}}
    os.environ.clear()
    os.environ.update(keep)
    sys.path.insert(0, str(root))
    sys.dont_write_bytecode = True
    os.chdir(root)

    with tempfile.TemporaryDirectory(prefix="swe-jobs-tests-") as directory:
        temporary_root = Path(directory).resolve()
        tempfile.tempdir = directory
        os.environ.update(TEMP=directory, TMP=directory, TMPDIR=directory,
                          JOBS_DB_PATH=str(temporary_root / "unused.db"))

        def guard(event: str, args: tuple) -> None:
            if event in {"socket.connect", "socket.getaddrinfo", "socket.bind",
                         "subprocess.Popen", "os.system"}:
                raise RuntimeError(f"Offline test guard blocked {event}")
            if event == "sqlite3.connect":
                name = str(args[0])
                if name.startswith("file:"):
                    from urllib.parse import urlsplit
                    from urllib.request import url2pathname
                    name = url2pathname(urlsplit(name).path)
                if name != ":memory:" and not Path(name).resolve().is_relative_to(temporary_root):
                    raise RuntimeError("Tests may only open temporary SQLite databases")

        sys.addaudithook(guard)
        suite = unittest.defaultTestLoader.discover(str(root / "tests"))
        result = unittest.TextTestRunner(verbosity=2).run(suite)
        return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
