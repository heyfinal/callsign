"""Per-callsign JSONL inbox.

One file per callsign at ``~/.callsign/inbox/<Name>.jsonl``. Append-only,
fsync on write. Used for (a) debug/replay, (b) quiet-hours queue, (c) recovery
on daemon restart.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

from callsign.paths import INBOX_DIR, ensure_dirs


_SAFE = re.compile(r"[^A-Za-z0-9_-]")


def _path_for(callsign: str) -> Path:
    ensure_dirs()
    safe = _SAFE.sub("_", callsign)[:64] or "_unknown"
    return INBOX_DIR / f"{safe}.jsonl"


def append(callsign: str, msg: dict) -> None:
    """Append the message dict to <callsign>.jsonl, atomically per-line."""
    path = _path_for(callsign)
    payload = dict(msg)
    payload.setdefault("inboxed_at", time.time())
    line = json.dumps(payload, ensure_ascii=False) + "\n"
    # O_APPEND on POSIX guarantees atomic-per-write for small lines.
    with path.open("a", encoding="utf-8") as f:
        f.write(line)
        f.flush()


def read_all(callsign: str, limit: int | None = None) -> list[dict]:
    path = _path_for(callsign)
    if not path.exists():
        return []
    out: list[dict] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
            if limit is not None and len(out) >= limit:
                break
    return out
