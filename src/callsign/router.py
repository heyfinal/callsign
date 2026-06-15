"""Parse leading-callsign addressing from incoming messages.

Match conventions accepted:
    "Frank, do X"        -> Frank
    "frank: do X"        -> frank
    "FRANK do X"         -> FRANK   (only if FRANK is a known callsign)
    "Frank — do X"       -> Frank   (em/en dash separator)
    "Hey Frank, do X"    -> Frank   (single leading honorific)

A message with no recognised leading callsign returns ``None``; the caller
is responsible for the fallback (typically the legacy "Brodie," lead).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from callsign import registry

_LEADING_HONORIFICS = ("hey", "yo", "sir", "ok", "okay")
_SEPARATORS = r"[,:\-—–‒‐]"

_PATTERN = re.compile(
    rf"^\s*(?P<name>[A-Za-z][A-Za-z\-']{{1,18}})\s*(?:{_SEPARATORS}\s*|\s+)",
    re.UNICODE,
)


@dataclass(frozen=True)
class RouteHit:
    callsign: str
    session: "registry.Session"
    body: str


def parse_leading_name(text: str) -> tuple[str | None, str]:
    """Return (candidate_name, remainder) — no registry check."""
    if not text:
        return None, ""
    raw = text.lstrip()

    lower = raw.lower()
    for hon in _LEADING_HONORIFICS:
        if lower.startswith(hon + " "):
            raw = raw[len(hon) + 1:].lstrip()
            break

    m = _PATTERN.match(raw)
    if not m:
        return None, text
    name = m.group("name")
    remainder = raw[m.end():]
    return name, remainder


def route(text: str) -> RouteHit | None:
    """Resolve an incoming message to an active session, if addressed."""
    name, body = parse_leading_name(text)
    if not name:
        return None
    sess = registry.lookup(name)
    if sess is None or sess.status != "active":
        return None
    return RouteHit(callsign=sess.callsign, session=sess, body=body)
