"""Claude Code SessionStart hook entry — auto-claim a callsign for the new session.

Invoked by ``~/.claude/hooks/callsign_session_start.sh`` for every SessionStart
subtype (startup, clear, resume, compact). Idempotent: if the session UID already
has an active callsign, just re-emit context.

Outputs a single JSON line to stdout in the Claude Code hook protocol shape:
    {"continue": true, "suppressOutput": false, "additionalContext": "..."}

On any internal failure, falls through to a "continue" reply so the session
boots regardless. Errors go to stderr so they surface to daniel.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

from callsign import names, registry
from callsign.paths import SESSIONS_DIR, ensure_dirs


_UID_RE = re.compile(r"[^a-zA-Z0-9_-]")


def _detect_uid() -> str | None:
    for k in (
        "CLAUDE_SESSION_ID",
        "CLAUDE_CODE_SESSION_ID",
        "HERMES_SESSION_ID",
        "CALLSIGN_SESSION_UID",
    ):
        v = os.environ.get(k, "").strip()
        if v:
            return v
    return None


def _safe_uid_filename(uid: str) -> str:
    return _UID_RE.sub("_", uid)[:64]


def _write_env_file(uid: str, callsign: str, platform: str, project: str | None, pid: int | None) -> None:
    ensure_dirs()
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    path = SESSIONS_DIR / f"{_safe_uid_filename(uid)}.env"
    path.write_text(
        f"CALLSIGN={callsign}\n"
        f"CALLSIGN_PLATFORM={platform}\n"
        f"CALLSIGN_PROJECT={project or ''}\n"
        f"CALLSIGN_PID={pid or ''}\n"
    )


def _build_context(callsign: str, project: str, fresh: bool) -> str:
    if fresh:
        return (
            f"## Callsign — assigned\n\n"
            f"Your callsign for this session is **{callsign}**, auto-bound to your session UID.\n\n"
            f"- When daniel iMessages `{callsign}, ...` (or `{callsign}: ...`), the message routes to you.\n"
            f"- Your replies go back to that iMessage thread via `callsign send '<text>'` "
            f"(auto-prefixed with `{callsign}: `).\n"
            f"- **Do not restate your name inside the message body** — the prefix carries it.\n"
            f"- To override the name: run `callsign claim <NewName>` once and announce the change.\n"
            f"- Project: {project}\n"
        )
    return (
        f"## Callsign — resumed\n\n"
        f"You are **{callsign}** for this session (claimed previously, still active).\n\n"
        f"- iMessages prefixed `{callsign}, ...` route to you.\n"
        f"- Send via `callsign send '<text>'` (prefix is automatic).\n"
        f"- Project: {project}\n"
    )


def _emit(payload: dict) -> None:
    sys.stdout.write(json.dumps(payload) + "\n")
    sys.stdout.flush()


def main() -> int:
    project = os.environ.get("CLAUDE_PROJECT_DIR") or os.environ.get("PWD") or os.getcwd()
    uid = _detect_uid()
    platform = "claude-code"
    no_autoclaim = os.environ.get("CALLSIGN_NO_AUTOCLAIM", "").strip() in {"1", "true", "yes"}

    if uid:
        existing = registry.lookup_by_session_uid(uid)
        if existing:
            try:
                _write_env_file(
                    uid, existing.callsign, existing.platform,
                    existing.project_path, existing.pid,
                )
            except Exception as e:
                print(f"callsign hook: env file write failed: {e}", file=sys.stderr)
            _emit({
                "continue": True,
                "suppressOutput": False,
                "additionalContext": _build_context(existing.callsign, project, fresh=False),
            })
            return 0

    if no_autoclaim:
        taken = {s.callsign for s in registry.list_active()}
        free = names.suggest(taken, n=8)
        body = (
            "## Callsign — pick your own\n\n"
            "This session does not have a callsign yet, and auto-claim is disabled.\n"
            "Claim one before you do anything else:\n\n"
            "```bash\n"
            "callsign claim <YourName>\n"
            "```\n\n"
            f"Unused suggestions: {', '.join(free)}\n"
        )
        _emit({
            "continue": True,
            "suppressOutput": False,
            "additionalContext": body,
        })
        return 0

    # CALLSIGN_PARENT_PID is the bash hook's $PPID (= Claude Code itself),
    # passed in by the bash wrapper. Without it, os.getppid() resolves to
    # the bash hook PID which dies on exit → reap_dead retires the session.
    parent_pid_env = os.environ.get("CALLSIGN_PARENT_PID", "").strip()
    try:
        parent_pid = int(parent_pid_env) if parent_pid_env else os.getppid()
    except ValueError:
        parent_pid = os.getppid()

    try:
        sess = registry.assign(
            platform=platform,
            project_path=project,
            pid=parent_pid,
            session_uid=uid,
            preferred=None,
            env={"argv0": "session_start_hook"},
            reuse_project=False,
        )
    except Exception as e:
        print(f"callsign hook: auto-claim failed: {e}", file=sys.stderr)
        _emit({"continue": True, "suppressOutput": True})
        return 0

    try:
        _write_env_file(
            uid or f"pid-{sess.pid}", sess.callsign, sess.platform,
            sess.project_path, sess.pid,
        )
    except Exception as e:
        print(f"callsign hook: env file write failed: {e}", file=sys.stderr)

    _emit({
        "continue": True,
        "suppressOutput": False,
        "additionalContext": _build_context(sess.callsign, project, fresh=True),
    })
    return 0


if __name__ == "__main__":
    sys.exit(main())
