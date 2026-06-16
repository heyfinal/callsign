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
    start_minute: int = 0
    end_hour: int = 6
    end_minute: int = 0
    tz: str = "America/Chicago"
    behavior: str = "queue"  # queue | drop | dispatch_anyway

    def start_minutes(self) -> int:
        return self.start_hour * 60 + self.start_minute

    def end_minutes(self) -> int:
        return self.end_hour * 60 + self.end_minute


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

        def _parse_hm(val: Any, default_h: int, default_m: int) -> tuple[int, int]:
            """Tolerate int hours or 'HH:MM' strings. Preserves minutes."""
            if isinstance(val, int):
                return max(0, min(23, val)), 0
            if isinstance(val, str):
                if ":" in val:
                    try:
                        h_str, m_str = val.split(":", 1)
                        return (
                            max(0, min(23, int(h_str))),
                            max(0, min(59, int(m_str))),
                        )
                    except (ValueError, TypeError):
                        pass
                try:
                    return max(0, min(23, int(val))), 0
                except (ValueError, TypeError):
                    pass
            return default_h, default_m

        sh, sm = _parse_hm(qh_raw.get("start"), 23, 0)
        eh, em = _parse_hm(qh_raw.get("end"), 6, 0)
        qh = QuietHours(
            start_hour=sh, start_minute=sm,
            end_hour=eh, end_minute=em,
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
    """True if wall-clock time is inside the configured quiet window.

    Resolves the configured tz via zoneinfo. If zoneinfo / the tz name is
    unavailable, falls back to the SYSTEM-default tz — explicit so a
    misconfigured tz doesn't silently use UTC.
    """
    cfg = cfg or Config.load()
    from datetime import datetime
    tz = None
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(cfg.quiet_hours.tz)
    except Exception:
        tz = None
    n = now or (datetime.now(tz) if tz else datetime.now().astimezone())
    s = cfg.quiet_hours.start_minutes()
    e = cfg.quiet_hours.end_minutes()
    cur = n.hour * 60 + n.minute
    if s == e:
        return False
    if s < e:
        return s <= cur < e
    # Window crosses midnight (typical: 23:00 → 06:00).
    return cur >= s or cur < e
