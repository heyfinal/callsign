"""Runtime config for callsign v0.3 (router + dispatcher + quiet hours).

Loaded from ``~/.callsign/config.toml``. All fields have safe defaults so the
daemon starts even on a never-configured box. Environment overrides win over
the file (so ``CALLSIGN_DISPATCH_TIMEOUT=30 callsign smoke-test`` works).
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from callsign.paths import CONFIG_PATH

if sys.version_info >= (3, 11):
    import tomllib
else:
    try:
        import tomli as tomllib  # type: ignore
    except ImportError:
        tomllib = None  # type: ignore


@dataclass(frozen=True)
class QuietHours:
    start_hour: int = 23
    end_hour: int = 6
    tz: str = "America/Chicago"
    behavior: str = "queue"  # queue | drop | dispatch_anyway


@dataclass(frozen=True)
class Config:
    chunk_size_bytes: int = 3500
    dispatch_timeout: int = 600
    concurrency_cap: int = 4
    lock_wait_short: float = 2.0       # short lock for state transitions
    lock_wait_dispatch: float = 5.0    # admission to dispatcher
    retry_imsg_send: int = 3
    backoff_initial: float = 2.0
    backoff_cap: float = 300.0
    quiet_hours: QuietHours = field(default_factory=QuietHours)
    # No fallback_recipient — the v0.3 review killed silent exfil paths. If a
    # message has no sender/chat_id we dead-letter + osascript alert locally.

    @classmethod
    def load(cls, path: Path | None = None) -> "Config":
        path = path or CONFIG_PATH
        data: dict[str, Any] = {}
        if path.exists() and tomllib is not None:
            try:
                with path.open("rb") as f:
                    data = tomllib.load(f)
            except (OSError, ValueError):
                data = {}

        qh_raw = data.get("quiet_hours") or {}
        # Tolerate "HH:MM" strings as well as ints.
        def _parse_hour(val: Any, default: int) -> int:
            if isinstance(val, int):
                return max(0, min(23, val))
            if isinstance(val, str) and ":" in val:
                try:
                    return max(0, min(23, int(val.split(":", 1)[0])))
                except ValueError:
                    pass
            return default

        qh = QuietHours(
            start_hour=_parse_hour(qh_raw.get("start"), 23),
            end_hour=_parse_hour(qh_raw.get("end"), 6),
            tz=str(qh_raw.get("tz") or "America/Chicago"),
            behavior=str(qh_raw.get("behavior") or "queue"),
        )

        default = data.get("default") or data
        cfg = cls(
            chunk_size_bytes=int(default.get("chunk_size_bytes")
                                 or os.environ.get("CALLSIGN_CHUNK_SIZE_BYTES")
                                 or 3500),
            dispatch_timeout=int(os.environ.get("CALLSIGN_DISPATCH_TIMEOUT")
                                 or default.get("dispatch_timeout") or 600),
            concurrency_cap=int(default.get("concurrency_cap") or 4),
            lock_wait_short=float(default.get("lock_wait_short") or 2.0),
            lock_wait_dispatch=float(default.get("lock_wait_dispatch") or 5.0),
            retry_imsg_send=int(default.get("retry_imsg_send") or 3),
            backoff_initial=float(default.get("backoff_initial") or 2.0),
            backoff_cap=float(default.get("backoff_cap") or 300.0),
            quiet_hours=qh,
        )
        return cfg


def in_quiet_hours(cfg: Config | None = None, now=None) -> bool:
    """True if wall-clock time is inside the configured quiet window."""
    cfg = cfg or Config.load()
    from datetime import datetime
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(cfg.quiet_hours.tz)
    except Exception:
        tz = None
    n = now or (datetime.now(tz) if tz else datetime.now())
    s = cfg.quiet_hours.start_hour
    e = cfg.quiet_hours.end_hour
    h = n.hour
    if s == e:
        return False
    if s < e:
        return s <= h < e
    # Window crosses midnight (typical: 23 → 06).
    return h >= s or h < e
