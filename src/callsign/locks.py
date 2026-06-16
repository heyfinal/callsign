"""Per-session-UID flock with path-safe filenames.

The plan review flagged a UID-as-filename injection risk (slashes / unicode /
control chars). We slugify aggressively and cap length. The flock acquire is
non-blocking with a polled wait so we can report timeout cleanly.
"""
from __future__ import annotations

import fcntl
import re
import time
from contextlib import contextmanager
from pathlib import Path

from callsign.paths import LOCKS_DIR, ensure_dirs


_SAFE = re.compile(r"[^A-Za-z0-9_-]")


class LockTimeout(RuntimeError):
    pass


def _path_for(key: str) -> Path:
    ensure_dirs()
    safe = _SAFE.sub("_", key)[:64] or "_default"
    return LOCKS_DIR / f"{safe}.lock"


@contextmanager
def acquire(key: str, timeout: float = 5.0, poll: float = 0.05):
    """Block until exclusive flock on ``key`` is held, or LockTimeout."""
    path = _path_for(key)
    fd = open(path, "a+")
    deadline = time.time() + max(0.0, timeout)
    try:
        while True:
            try:
                fcntl.flock(fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.time() >= deadline:
                    raise LockTimeout(f"lock '{key}' held by another process > {timeout}s")
                time.sleep(poll)
        try:
            yield fd
        finally:
            try:
                fcntl.flock(fd.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
    finally:
        fd.close()
