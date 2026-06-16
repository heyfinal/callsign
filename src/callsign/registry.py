"""SQLite-backed registry of active callsigns.

A "session" is one running agent that has claimed a callsign. The registry
is concurrency-safe via SQLite WAL + UNIQUE constraints; multiple sessions
can call ``assign`` simultaneously without colliding.

Schema is intentionally tiny — adding columns is a migration, not a redesign.
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from callsign import names
from callsign.paths import DB_PATH, ensure_dirs


class NameTakenError(Exception):
    """Raised when an agent tries to claim a name that's already active."""


class InvalidNameError(Exception):
    """Raised when the requested name fails validation."""


SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    callsign     TEXT PRIMARY KEY COLLATE NOCASE,
    platform     TEXT NOT NULL,
    project_path TEXT,
    pid          INTEGER,
    session_uid  TEXT,
    started_at   REAL NOT NULL,
    last_seen    REAL NOT NULL,
    status       TEXT NOT NULL CHECK(status IN ('active','retired')),
    env_json     TEXT
);
CREATE INDEX IF NOT EXISTS sessions_status ON sessions(status);
CREATE INDEX IF NOT EXISTS sessions_project ON sessions(project_path);
CREATE INDEX IF NOT EXISTS sessions_uid ON sessions(session_uid);
"""


@dataclass(frozen=True)
class Session:
    callsign: str
    platform: str
    project_path: str | None
    pid: int | None
    session_uid: str | None
    started_at: float
    last_seen: float
    status: str
    env: dict = field(default_factory=dict)

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Session":
        env = json.loads(row["env_json"]) if row["env_json"] else {}
        return cls(
            callsign=row["callsign"],
            platform=row["platform"],
            project_path=row["project_path"],
            pid=row["pid"],
            session_uid=row["session_uid"],
            started_at=row["started_at"],
            last_seen=row["last_seen"],
            status=row["status"],
            env=env,
        )


def _connect() -> sqlite3.Connection:
    ensure_dirs()
    conn = sqlite3.connect(DB_PATH, isolation_level=None, timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=5000;")
    conn.executescript(SCHEMA)
    # v0.3 migration — additive only. ALTER TABLE ADD COLUMN is no-op via except
    # when column already exists.
    try:
        conn.execute("ALTER TABLE sessions ADD COLUMN claimed_via TEXT DEFAULT 'manual'")
    except sqlite3.OperationalError:
        pass  # column already present
    return conn


def _pid_alive(pid: int | None) -> bool:
    if not pid or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def reap_dead(conn: sqlite3.Connection | None = None) -> int:
    """Mark sessions whose pid is gone as retired. Returns count reaped."""
    own = conn is None
    conn = conn or _connect()
    try:
        rows = conn.execute(
            "SELECT callsign, pid FROM sessions WHERE status='active'"
        ).fetchall()
        n = 0
        now = time.time()
        for r in rows:
            if not _pid_alive(r["pid"]):
                conn.execute(
                    "UPDATE sessions SET status='retired', last_seen=? WHERE callsign=?",
                    (now, r["callsign"]),
                )
                n += 1
        return n
    finally:
        if own:
            conn.close()


def claim(
    name: str,
    platform: str,
    project_path: str | Path | None = None,
    pid: int | None = None,
    session_uid: str | None = None,
    env: dict | None = None,
) -> Session:
    """Claim a SPECIFIC name for the calling session.

    This is the primary, agent-driven path: the model picks its own name
    and asks the registry to reserve it. The name must pass
    ``names.is_valid_name`` and not already be active.

    If ``session_uid`` already has an active row whose callsign matches
    ``name``, the call is idempotent. If the active row has a DIFFERENT
    name, the existing row is retired first (agent is renaming itself).
    """
    ok, reason = names.is_valid_name(name)
    if not ok:
        raise InvalidNameError(reason)

    conn = _connect()
    try:
        reap_dead(conn)
        now = time.time()
        env_json = json.dumps(env or {})
        proj = str(Path(project_path).resolve()) if project_path else None

        if session_uid:
            row = conn.execute(
                "SELECT * FROM sessions WHERE session_uid=? AND status='active'",
                (session_uid,),
            ).fetchone()
            if row:
                if row["callsign"].lower() == name.lower():
                    conn.execute(
                        "UPDATE sessions SET last_seen=?, pid=COALESCE(?,pid) "
                        "WHERE callsign=?",
                        (now, pid, row["callsign"]),
                    )
                    return Session.from_row(
                        conn.execute(
                            "SELECT * FROM sessions WHERE callsign=?",
                            (row["callsign"],),
                        ).fetchone()
                    )
                conn.execute(
                    "UPDATE sessions SET status='retired', last_seen=? WHERE callsign=?",
                    (now, row["callsign"]),
                )

        try:
            conn.execute(
                "INSERT INTO sessions "
                "(callsign, platform, project_path, pid, session_uid, started_at, "
                " last_seen, status, env_json) VALUES (?,?,?,?,?,?,?, 'active', ?)",
                (name, platform, proj, pid, session_uid, now, now, env_json),
            )
        except sqlite3.IntegrityError:
            existing = conn.execute(
                "SELECT callsign, status FROM sessions WHERE callsign=? COLLATE NOCASE",
                (name,),
            ).fetchone()
            if existing and existing["status"] == "active":
                raise NameTakenError(
                    f"'{name}' is already in use by another active session — pick a different name"
                )
            conn.execute(
                "UPDATE sessions SET status='active', platform=?, project_path=?, "
                "pid=?, session_uid=?, started_at=?, last_seen=?, env_json=? "
                "WHERE callsign=? COLLATE NOCASE",
                (platform, proj, pid, session_uid, now, now, env_json, name),
            )

        return Session.from_row(
            conn.execute(
                "SELECT * FROM sessions WHERE callsign=? COLLATE NOCASE", (name,)
            ).fetchone()
        )
    finally:
        conn.close()


def assign(
    platform: str,
    project_path: str | Path | None = None,
    pid: int | None = None,
    session_uid: str | None = None,
    preferred: str | None = None,
    env: dict | None = None,
    reuse_project: bool = True,
) -> Session:
    """Legacy auto-assign path. Agents should call ``claim`` instead.

    Kept for non-interactive callers (Hermes batch jobs, cron workers) that
    can't pick a name for themselves. If ``preferred`` is given it's tried
    first; otherwise a name from ``names.SUGGESTION_POOL`` is auto-picked.
    """
    conn = _connect()
    try:
        reap_dead(conn)
        now = time.time()
        env_json = json.dumps(env or {})
        proj = str(Path(project_path).resolve()) if project_path else None

        if session_uid:
            row = conn.execute(
                "SELECT * FROM sessions WHERE session_uid=? AND status='active'",
                (session_uid,),
            ).fetchone()
            if row:
                conn.execute(
                    "UPDATE sessions SET last_seen=?, pid=COALESCE(?,pid) WHERE callsign=?",
                    (now, pid, row["callsign"]),
                )
                return Session.from_row(
                    conn.execute(
                        "SELECT * FROM sessions WHERE callsign=?", (row["callsign"],)
                    ).fetchone()
                )

        if reuse_project and proj:
            row = conn.execute(
                "SELECT * FROM sessions WHERE project_path=? AND status='active' "
                "ORDER BY last_seen DESC LIMIT 1",
                (proj,),
            ).fetchone()
            if row and _pid_alive(row["pid"]):
                conn.execute(
                    "UPDATE sessions SET last_seen=? WHERE callsign=?",
                    (now, row["callsign"]),
                )
                return Session.from_row(
                    conn.execute(
                        "SELECT * FROM sessions WHERE callsign=?", (row["callsign"],)
                    ).fetchone()
                )

        taken = {
            r["callsign"]
            for r in conn.execute(
                "SELECT callsign FROM sessions WHERE status='active'"
            ).fetchall()
        }

        if preferred and preferred.lower() not in {t.lower() for t in taken}:
            chosen = preferred
        else:
            seed = session_uid or proj or str(pid or os.getpid())
            chosen = names.pick(taken, seed=seed)

        try:
            conn.execute(
                "INSERT INTO sessions "
                "(callsign, platform, project_path, pid, session_uid, started_at, "
                " last_seen, status, env_json) VALUES (?,?,?,?,?,?,?, 'active', ?)",
                (chosen, platform, proj, pid, session_uid, now, now, env_json),
            )
        except sqlite3.IntegrityError:
            return assign(
                platform=platform,
                project_path=project_path,
                pid=pid,
                session_uid=session_uid,
                preferred=None,
                env=env,
                reuse_project=reuse_project,
            )

        return Session.from_row(
            conn.execute(
                "SELECT * FROM sessions WHERE callsign=?", (chosen,)
            ).fetchone()
        )
    finally:
        conn.close()


def lookup_by_session_uid(uid: str) -> Session | None:
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT * FROM sessions WHERE session_uid=? AND status='active' "
            "ORDER BY last_seen DESC LIMIT 1",
            (uid,),
        ).fetchone()
        return Session.from_row(row) if row else None
    finally:
        conn.close()


def lookup_by_project(path: str | Path) -> Session | None:
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT * FROM sessions WHERE project_path=? AND status='active' "
            "ORDER BY last_seen DESC LIMIT 1",
            (str(Path(path).resolve()),),
        ).fetchone()
        return Session.from_row(row) if row else None
    finally:
        conn.close()


def lookup(name: str) -> Session | None:
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT * FROM sessions WHERE callsign=? COLLATE NOCASE", (name,)
        ).fetchone()
        return Session.from_row(row) if row else None
    finally:
        conn.close()


def list_active(reap: bool = True) -> list[Session]:
    conn = _connect()
    try:
        if reap:
            reap_dead(conn)
        rows = conn.execute(
            "SELECT * FROM sessions WHERE status='active' ORDER BY started_at"
        ).fetchall()
        return [Session.from_row(r) for r in rows]
    finally:
        conn.close()


def heartbeat(name: str) -> None:
    conn = _connect()
    try:
        conn.execute(
            "UPDATE sessions SET last_seen=? WHERE callsign=? COLLATE NOCASE",
            (time.time(), name),
        )
    finally:
        conn.close()


def retire(name: str) -> bool:
    conn = _connect()
    try:
        cur = conn.execute(
            "UPDATE sessions SET status='retired', last_seen=? "
            "WHERE callsign=? COLLATE NOCASE AND status='active'",
            (time.time(), name),
        )
        return cur.rowcount > 0
    finally:
        conn.close()


def history(limit: int = 50) -> Iterable[Session]:
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT * FROM sessions ORDER BY last_seen DESC LIMIT ?", (limit,)
        ).fetchall()
        return [Session.from_row(r) for r in rows]
    finally:
        conn.close()
