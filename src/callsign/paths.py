"""Filesystem layout for callsign state. XDG-friendly."""
from __future__ import annotations

import os
from pathlib import Path


def _home() -> Path:
    return Path(os.path.expanduser("~"))


XDG_DATA_HOME = Path(os.environ.get("XDG_DATA_HOME") or _home() / ".local" / "share")
XDG_STATE_HOME = Path(os.environ.get("XDG_STATE_HOME") or _home() / ".local" / "state")

ROOT = Path(os.environ.get("CALLSIGN_HOME") or _home() / ".callsign")
DB_PATH = ROOT / "registry.db"
PROCESSED_DB_PATH = ROOT / "processed.db"
SESSIONS_DIR = ROOT / "sessions"
INBOX_DIR = ROOT / "inbox"
LOCKS_DIR = ROOT / "locks"
LOG_DIR = ROOT / "logs"
DEAD_LETTER_DIR = ROOT / "dead-letter"
ALERTS_PATH = ROOT / "alerts.jsonl"
CONFIG_PATH = ROOT / "config.toml"
CONFIG_PATH_JSON = ROOT / "config.json"  # legacy fallback


def ensure_dirs() -> None:
    for p in (ROOT, SESSIONS_DIR, INBOX_DIR, LOCKS_DIR, LOG_DIR, DEAD_LETTER_DIR):
        p.mkdir(parents=True, exist_ok=True)
    # Lock down to user-only — closes the local-process trust boundary that
    # the v0.3 review flagged. Idempotent.
    try:
        ROOT.chmod(0o700)
        for p in (SESSIONS_DIR, INBOX_DIR, LOCKS_DIR, LOG_DIR, DEAD_LETTER_DIR):
            p.chmod(0o700)
    except OSError:
        # Best-effort; don't crash session-start hook on permission edge cases.
        pass
