"""Staged-state idempotency store for inbound iMessages.

Three timestamps per message — `received_at`, `dispatched_at`, `reply_sent_at`
— give us exactly-once semantics that survives daemon crashes. The plan-review
verdict from GPT-5.4 + DeepSeek killed single-bit dedupe.

States:
    received_at set                                       -> queued
    received_at + dispatched_at set                       -> claude ran, reply not yet delivered
    received_at + dispatched_at + reply_sent_at set       -> done (true dedup target)
    any row with `error` non-null                         -> failed; do not retry without operator review

On daemon restart, ``recover_stuck()`` finds rows with reply_sent_at IS NULL
and replays from the appropriate stage.
"""
from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator

from callsign.paths import PROCESSED_DB_PATH, ensure_dirs


SCHEMA = """
CREATE TABLE IF NOT EXISTS processed (
    guid              TEXT PRIMARY KEY,
    callsign          TEXT NOT NULL,
    sender            TEXT,
    chat_id           TEXT,
    body              TEXT,
    received_at       REAL NOT NULL,
    dispatched_at     REAL,
    reply_sent_at     REAL,
    chunks_sent       INTEGER NOT NULL DEFAULT 0,
    chunks_total      INTEGER NOT NULL DEFAULT 0,
    error             TEXT
);
CREATE INDEX IF NOT EXISTS processed_state ON processed(reply_sent_at, dispatched_at);
CREATE INDEX IF NOT EXISTS processed_callsign ON processed(callsign);
"""


@dataclass(frozen=True)
class Row:
    guid: str
    callsign: str
    sender: str | None
    chat_id: str | None
    body: str | None
    received_at: float
    dispatched_at: float | None
    reply_sent_at: float | None
    chunks_sent: int
    chunks_total: int
    error: str | None

    @classmethod
    def from_row(cls, r: sqlite3.Row) -> "Row":
        return cls(
            guid=r["guid"],
            callsign=r["callsign"],
            sender=r["sender"],
            chat_id=r["chat_id"],
            body=r["body"],
            received_at=r["received_at"],
            dispatched_at=r["dispatched_at"],
            reply_sent_at=r["reply_sent_at"],
            chunks_sent=r["chunks_sent"],
            chunks_total=r["chunks_total"],
            error=r["error"],
        )


@contextmanager
def _conn() -> Iterator[sqlite3.Connection]:
    ensure_dirs()
    c = sqlite3.connect(PROCESSED_DB_PATH, isolation_level=None, timeout=10.0)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL;")
    c.execute("PRAGMA busy_timeout=5000;")
    c.executescript(SCHEMA)
    try:
        yield c
    finally:
        c.close()


def enqueue(guid: str, callsign: str, sender: str | None, chat_id: str | None,
            body: str | None) -> bool:
    """Record the inbound message at received_at. Idempotent on guid PK."""
    with _conn() as c:
        try:
            c.execute(
                "INSERT INTO processed (guid, callsign, sender, chat_id, body, received_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (guid, callsign, sender, chat_id, body, time.time()),
            )
            return True
        except sqlite3.IntegrityError:
            return False  # already enqueued


def mark_dispatched(guid: str) -> None:
    with _conn() as c:
        c.execute(
            "UPDATE processed SET dispatched_at=? WHERE guid=?",
            (time.time(), guid),
        )


def mark_chunks(guid: str, chunks_sent: int, chunks_total: int) -> None:
    with _conn() as c:
        c.execute(
            "UPDATE processed SET chunks_sent=?, chunks_total=? WHERE guid=?",
            (chunks_sent, chunks_total, guid),
        )


def mark_replied(guid: str) -> None:
    with _conn() as c:
        c.execute(
            "UPDATE processed SET reply_sent_at=? WHERE guid=?",
            (time.time(), guid),
        )


def mark_error(guid: str, err: str) -> None:
    with _conn() as c:
        c.execute(
            "UPDATE processed SET error=? WHERE guid=?",
            (err[:2000], guid),
        )


def is_replied(guid: str) -> bool:
    with _conn() as c:
        r = c.execute(
            "SELECT reply_sent_at FROM processed WHERE guid=?", (guid,)
        ).fetchone()
        return bool(r and r["reply_sent_at"])


def get(guid: str) -> Row | None:
    with _conn() as c:
        r = c.execute("SELECT * FROM processed WHERE guid=?", (guid,)).fetchone()
        return Row.from_row(r) if r else None


def stuck(limit: int = 100) -> list[Row]:
    """Rows enqueued but not yet fully delivered (for recovery on restart)."""
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM processed WHERE reply_sent_at IS NULL AND error IS NULL "
            "ORDER BY received_at LIMIT ?",
            (limit,),
        ).fetchall()
        return [Row.from_row(r) for r in rows]


def stats() -> dict:
    with _conn() as c:
        total = c.execute("SELECT COUNT(*) c FROM processed").fetchone()["c"]
        replied = c.execute(
            "SELECT COUNT(*) c FROM processed WHERE reply_sent_at IS NOT NULL"
        ).fetchone()["c"]
        errored = c.execute(
            "SELECT COUNT(*) c FROM processed WHERE error IS NOT NULL"
        ).fetchone()["c"]
        last = c.execute(
            "SELECT MAX(received_at) m FROM processed"
        ).fetchone()["m"]
        return {
            "total": total,
            "replied": replied,
            "errored": errored,
            "pending": total - replied - errored,
            "last_received_at": last,
        }
