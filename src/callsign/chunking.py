"""UTF-8 byte-safe message chunking with grapheme-aware boundaries.

Splitting Python strings naively can corrupt multi-byte sequences when the
iMessage transport re-encodes. The plan review flagged this. We:

1. Cap each chunk to ``max_bytes`` of UTF-8.
2. Prefer sentence boundaries, then whitespace, then a code-point boundary
   (never split inside a code point).
3. Prepend ``[k/N]`` markers when more than one chunk.

We do NOT do full grapheme-cluster awareness (which would need ``regex`` or
``grapheme``); we settle for code-point safety, which is the minimum required
to keep emoji and BMP CJK intact end-to-end.
"""
from __future__ import annotations

import re
from typing import Iterable, List


_SENT_BREAK = re.compile(r"(?<=[.!?])\s+")
_WS_BREAK = re.compile(r"\s+")


def _encode_len(s: str) -> int:
    return len(s.encode("utf-8"))


def _split_one(text: str, max_bytes: int) -> tuple[str, str]:
    """Return (head, tail) where head encodes to <= max_bytes."""
    if _encode_len(text) <= max_bytes:
        return text, ""

    # Walk backward from the byte budget to a safe split point.
    # First find the longest prefix that fits.
    enc = text.encode("utf-8")
    cut = max_bytes
    # Backtrack to a UTF-8 code-point boundary (skip 0b10xxxxxx continuation bytes).
    while cut > 0 and (enc[cut] & 0xC0) == 0x80:
        cut -= 1
    head_candidate = enc[:cut].decode("utf-8", errors="ignore")

    # Prefer the last sentence break inside head_candidate.
    matches = list(_SENT_BREAK.finditer(head_candidate))
    if matches:
        idx = matches[-1].end()
        return head_candidate[:idx].rstrip(), head_candidate[idx:] + text[len(head_candidate):]

    # Fall back to last whitespace.
    ws = list(_WS_BREAK.finditer(head_candidate))
    if ws:
        idx = ws[-1].start()
        return head_candidate[:idx].rstrip(), head_candidate[idx:].lstrip() + text[len(head_candidate):]

    # Hard split at code-point boundary.
    return head_candidate, text[len(head_candidate):]


def chunked(text: str, max_bytes: int = 3500, with_markers: bool = True,
            id_token: str | None = None) -> List[str]:
    """Split ``text`` into iMessage-safe chunks.

    Each chunk is <= max_bytes when UTF-8 encoded. When multiple chunks
    result and ``with_markers`` is True, prepend ``[k/N{id}]`` to each so
    the recipient can re-sequence and dedupe on retry.
    """
    text = (text or "").strip()
    if not text:
        return []

    # Reserve room for the longest marker we might prepend. "[NN/NN:guid12] "
    # is ~ 24 bytes. Be conservative.
    marker_reserve = 32 if with_markers else 0
    budget = max(64, max_bytes - marker_reserve)

    parts: list[str] = []
    rest = text
    while rest:
        head, rest = _split_one(rest, budget)
        if not head:
            break
        parts.append(head.strip())
        rest = rest.strip()

    if not with_markers or len(parts) <= 1:
        return parts

    id_part = f":{id_token[:8]}" if id_token else ""
    N = len(parts)
    return [f"[{i+1}/{N}{id_part}] {p}" for i, p in enumerate(parts)]


def by_lines(messages: Iterable[str]) -> str:
    return "\n".join(messages)
