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
SESSIONS_DIR = ROOT / "sessions"
INBOX_DIR = ROOT / "inbox"
LOG_DIR = ROOT / "logs"
CONFIG_PATH = ROOT / "config.json"


def ensure_dirs() -> None:
    for p in (ROOT, SESSIONS_DIR, INBOX_DIR, LOG_DIR):
        p.mkdir(parents=True, exist_ok=True)
