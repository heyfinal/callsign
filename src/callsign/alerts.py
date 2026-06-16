"""Failure surfacing that NEVER routes through the primary iMessage path.

The plan review flagged a recursion risk: if our outbound send path is what's
broken, sending an alert about it through that same path silences the alert.
We use osascript (native macOS notification center) plus an append-only
``~/.callsign/alerts.jsonl`` that a SessionStart hook can surface to whoever
opens the next Claude Code window.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import time

from callsign.paths import ALERTS_PATH, ensure_dirs


def _safe(s: str) -> str:
    """Strip control chars + escape quotes for osascript literal."""
    return (
        "".join(c if (c == "\n" or c == "\t" or (0x20 <= ord(c) < 0x7F)) else " "
                for c in (s or ""))
        .replace('"', '\\"')
        .replace("\\n", " ")
    )


def alert(title: str, body: str, kind: str = "callsign") -> None:
    """Append to alerts.jsonl and fire a desktop notification."""
    ensure_dirs()
    payload = {
        "ts": time.time(),
        "kind": kind,
        "title": title,
        "body": body,
    }
    try:
        with ALERTS_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except OSError:
        pass

    osa = shutil.which("osascript")
    if not osa:
        return
    script = (
        f'display notification "{_safe(body)[:300]}" '
        f'with title "{_safe(title)[:80]}" '
        f'subtitle "callsign"'
    )
    try:
        subprocess.run(
            [osa, "-e", script],
            capture_output=True, timeout=3, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        pass
