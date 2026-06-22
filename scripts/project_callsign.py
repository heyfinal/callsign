#!/usr/bin/env python3
"""
project_callsign.py — deterministic per-PROJECT aviation/military callsign +
terminal-title pinning for Claude Code.

This is INTENTIONALLY separate from the `callsign` iMessage-routing package
(~/.local/share/callsign). That package keys friendly names per SESSION for
iMessage threads. This one keys aviation callsigns per PROJECT (cwd / git root)
for window-title identity. They coexist; this script never touches the daemon.

Modes (dispatched by the Claude Code hook_event_name on stdin, or argv[1]):
  session-start : print hookSpecificOutput JSON (additionalContext + sessionTitle)
                  and write an OSC 2 title escape to /dev/tty.
  stop          : re-assert the OSC 2 title (CC overwrites it with its task
                  summary during the turn; Stop fires after each turn).
  show          : print the resolved callsign for the cwd (human use).
  set <NAME>    : pin a manual override callsign for the cwd's project.

Storage: ~/.claude/callsigns.json  -> { "<project_path>": {"callsign","manual","title"} }
Reads legacy ~/.claude/callsign.json once to seed the current project (keeps RONIN).
"""
import json
import os
import sys
import hashlib
import subprocess
from pathlib import Path

HOME = Path(os.path.expanduser("~"))
STORE = HOME / ".claude" / "callsigns.json"
LEGACY = HOME / ".claude" / "callsign.json"

# Name pool — 3000 REAL human names (boy + girl + a few creative-but-real ones
# like TRINITY / ROOK). NO fantasy / D&D / military-callsign compounds. Daniel's
# spec (2026-06-20): real names only, and the PRIME RULE — no two sessions ever
# share a name; once a name is picked it is burned out of the pool COMPLETELY
# until all 3000 are exhausted (enforced by the __used__ ledger + flock below).
#
# The pool is frozen to callsign_names.txt (generated from census first-name
# corpora). The JSON store only tracks which names have been BURNED. A tiny
# embedded fallback keeps a fresh machine working if the file is ever missing.
_NAMES_FILE = HOME / ".claude" / "scripts" / "callsign_names.txt"
_FALLBACK_NAMES = (
    "STEVEN", "TRINITY", "ROOK", "NORA", "ELLIS", "MAYA", "OWEN", "IVY",
    "FELIX", "CLARA", "MILO", "HAZEL", "JONAS", "RUBY", "SILAS", "ESME",
    "GRANT", "WREN", "VANCE", "WILLA", "DEAN", "IRIS", "ZANE", "CORA",
)


def _load_pool() -> tuple:
    try:
        seen: set = set()
        out: list = []
        for line in _NAMES_FILE.read_text(encoding="utf-8").splitlines():
            n = line.strip().upper()
            if n and n not in seen:
                seen.add(n)
                out.append(n)
        if out:
            return tuple(out)
    except Exception:
        pass
    return _FALLBACK_NAMES


POOL = _load_pool()
WORDLIST = POOL  # back-compat alias for deterministic_callsign / CLI paths


def _git_root(cwd: str) -> str | None:
    try:
        out = subprocess.run(
            ["git", "-C", cwd, "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=3,
        )
        if out.returncode == 0:
            return out.stdout.strip()
    except Exception:
        pass
    return None


def project_root(cwd: str) -> str:
    return _git_root(cwd) or cwd


def project_title(root: str) -> str:
    base = os.path.basename(root.rstrip("/")) or root
    # If it's a git repo, basename is the repo name. Else title-case the dir.
    if _git_root(root):
        return base
    return base.replace("-", " ").replace("_", " ").title()


def deterministic_callsign(root: str) -> str:
    h = hashlib.sha256(root.encode("utf-8")).hexdigest()
    return WORDLIST[int(h, 16) % len(WORDLIST)]


# ── per-SESSION assignment ──────────────────────────────────────────────────
# Daniel runs many parallel Claude Code windows from the SAME project root
# (/Users/daniel). Project-keyed callsigns therefore collapse every agent to
# one name (RONIN). Identity must be keyed per SESSION, with liveness tracking
# so the ~40-name pool recycles and concurrent agents never collide.
_SESSIONS_KEY = "__sessions__"
_LOCK = HOME / ".claude" / "callsigns.lock"


def _pid_alive(pid) -> bool:
    if not pid or int(pid) <= 0:
        return False
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except (ValueError, TypeError):
        return False
    return True


def _session_id_from(hook_in: dict) -> str | None:
    sid = (
        hook_in.get("session_id")
        or os.environ.get("CLAUDE_CODE_SESSION_ID")
        or os.environ.get("CLAUDE_SESSION_ID")
    )
    return sid.strip() if isinstance(sid, str) and sid.strip() else None


def _term_id() -> str | None:
    """Stable per-terminal-window/pane id, inherited identically by the
    SessionStart hook and the statusline subprocess (both spawned by the same
    Claude Code process inside the same terminal pane). This is what lets the
    statusline find ITS OWN session even when Claude Code passes no session_id
    on the statusline stdin — preventing the fallback to a stale project name.
    """
    for k in ("ITERM_SESSION_ID", "TERM_SESSION_ID", "WEZTERM_PANE",
              "KITTY_WINDOW_ID", "TMUX_PANE", "WINDOWID"):
        v = os.environ.get(k)
        if v and v.strip():
            return f"{k}={v.strip()}"
    return None


def _reap_sessions(sessions: dict) -> None:
    # Drop liveness entries for dead sessions. Their callsigns stay BURNED in
    # the __used__ ledger — names are never reissued.
    for sid in [s for s, e in sessions.items() if not _pid_alive(e.get("pid"))]:
        sessions.pop(sid, None)


_USED_KEY = "__used__"


def _pick_unburned(session_id: str, used: set) -> str:
    # Deterministic start index (stable-ish per session_id), linear-probe the
    # 3000-name pool for the first name never burned. Once a name is handed out
    # it is added to `used` permanently and can never be reissued. Numeric
    # suffix only if the entire pool is exhausted (>3000 sessions ever).
    start = int(hashlib.sha256(session_id.encode()).hexdigest(), 16) % len(POOL)
    for i in range(len(POOL)):
        cand = POOL[(start + i) % len(POOL)]
        if cand not in used:
            return cand
    n = 2
    while True:
        cand = f"{POOL[start]}-{n}"
        if cand not in used:
            return cand
        n += 1


def resolve_session(session_id: str, cwd: str, pid: int | None = None) -> tuple[str, str, str]:
    """Return (callsign, project_title, project_root) for ONE session.

    Stable across resume/compact (keyed on session_id). Every name is BURNED on
    first use and never reissued to any future session — even after the owning
    session dies. Serialized via flock so concurrent SessionStart hooks can
    never burn the same name twice.
    """
    import fcntl

    root = project_root(cwd)
    title = project_title(root)
    _LOCK.parent.mkdir(parents=True, exist_ok=True)
    with open(_LOCK, "a+") as lf:
        try:
            fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
        except OSError:
            pass
        data = _load()
        sessions = data.setdefault(_SESSIONS_KEY, {})
        used = set(data.setdefault(_USED_KEY, []))
        _reap_sessions(sessions)
        term = _term_id()
        entry = sessions.get(session_id)
        if entry and entry.get("callsign"):
            entry["pid"] = pid or entry.get("pid")
            entry["title"] = title
            if term:
                entry["term"] = term
            _save(data)
            return entry["callsign"], title, root
        cs = _pick_unburned(session_id, used)
        used.add(cs)
        data[_USED_KEY] = sorted(used)
        sessions[session_id] = {"callsign": cs, "pid": pid, "title": title,
                                "root": root, "term": term}
        _save(data)
        return cs, title, root


def _load() -> dict:
    if STORE.exists():
        try:
            return json.loads(STORE.read_text())
        except Exception:
            return {}
    return {}


def _save(data: dict) -> None:
    STORE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STORE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2))
    tmp.replace(STORE)


# The legacy single-file callsign.json belonged to whatever project was the
# CURRENT cwd at the time this feature was installed. We migrate it exactly
# ONCE, pinning it to that project's root, so RONIN stays put — then every
# other project is purely deterministic. The migration is recorded with a
# marker key so it never re-fires for other projects.
_LEGACY_MARKER = "__legacy_migrated__"


def _maybe_migrate_legacy(root: str, data: dict) -> bool:
    """If legacy callsign.json exists and we haven't migrated yet, pin its
    callsign to `root` (the first project we resolve after install). Returns
    True if it set an entry for `root`."""
    if data.get(_LEGACY_MARKER):
        return False
    if not LEGACY.exists():
        data[_LEGACY_MARKER] = True
        return False
    try:
        cs = json.loads(LEGACY.read_text()).get("callsign")
    except Exception:
        cs = None
    data[_LEGACY_MARKER] = True
    if cs:
        data[root] = {"callsign": cs.upper(), "manual": True, "title": project_title(root)}
        return True
    return False


def resolve(cwd: str) -> tuple[str, str, str]:
    """Return (callsign, project_title, project_root). Persists assignment."""
    root = project_root(cwd)
    data = _load()
    title = project_title(root)
    entry = data.get(root)
    if entry and entry.get("callsign"):
        cs = entry["callsign"]
        if entry.get("title") != title:
            entry["title"] = title
            _save(data)
        return cs, title, root
    # First time we see this project. Run the one-shot legacy migration; if it
    # claimed THIS root, use that, else assign deterministically.
    migrated = _maybe_migrate_legacy(root, data)
    if migrated and root in data:
        cs = data[root]["callsign"]
    else:
        cs = deterministic_callsign(root)
        data[root] = {"callsign": cs, "manual": False, "title": title}
    _save(data)
    return cs, title, root


def set_manual(cwd: str, name: str) -> tuple[str, str]:
    root = project_root(cwd)
    title = project_title(root)
    data = _load()
    data[root] = {"callsign": name.upper(), "manual": True, "title": title}
    _save(data)
    return name.upper(), root


def osc_title(text: str) -> None:
    """Write OSC 2 (window title) to the controlling TTY, if any."""
    seq = f"\033]2;{text}\007"
    for path in ("/dev/tty",):
        try:
            with open(path, "w") as tty:
                tty.write(seq)
                tty.flush()
            return
        except Exception:
            continue


def read_hook_input() -> dict:
    try:
        raw = sys.stdin.read().strip()
        return json.loads(raw) if raw else {}
    except Exception:
        return {}


def do_session_start(hook_in: dict) -> None:
    cwd = hook_in.get("cwd") or os.getcwd()
    sid = _session_id_from(hook_in)
    if sid:
        cs, title, _root = resolve_session(sid, cwd, pid=os.getppid())
    else:
        cs, title, _root = resolve(cwd)  # CLI / no-session fallback
    bar = f"{cs} — {title}"  # "RONIN — project"
    # 1) Native: pin CC's own session/tab title.
    # 2) Native: inject identity into context so the model knows who it is.
    out = {
        "continue": True,
        "suppressOutput": True,
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "sessionTitle": bar,
            "additionalContext": (
                f"Your operational callsign for this project is {cs}. "
                f"You are {cs}. Project: {title}. "
                f"The OS terminal title is pinned to \"{bar}\"."
            ),
        },
    }
    # 3) Belt-and-suspenders: also write the OSC escape directly.
    osc_title(bar)
    sys.stdout.write(json.dumps(out) + "\n")


def lookup_session(session_id: str) -> str | None:
    """Read-only: return the callsign already burned for this session, or None.

    Used by the statusline, which runs frequently — it must never burn a name
    or write to the store.
    """
    if not session_id:
        return None
    data = _load()
    entry = data.get(_SESSIONS_KEY, {}).get(session_id)
    return entry.get("callsign") if entry else None


def lookup_by_term(term: str) -> str | None:
    """Read-only: resolve the callsign for the session running in THIS terminal
    pane. Among entries sharing the term id, prefer a live one (sequential reuse
    of a pane leaves dead entries behind); pick the most recently registered.
    """
    if not term:
        return None
    data = _load()
    sessions = data.get(_SESSIONS_KEY, {})
    matches = [e for e in sessions.values() if e.get("term") == term and e.get("callsign")]
    if not matches:
        return None
    live = [e for e in matches if _pid_alive(e.get("pid"))]
    pick = (live or matches)[-1]  # dicts preserve insertion order → most recent last
    return pick.get("callsign")


def do_statusline(hook_in: dict) -> None:
    """Render the line above the input box: "<CALLSIGN> — <user>".

    Mirrors the OS title-bar identity inside Claude Code. Read-only.
    """
    import getpass

    cwd = hook_in.get("cwd") or os.getcwd()
    sid = _session_id_from(hook_in)
    cs = lookup_session(sid) if sid else None
    if not cs:
        # Claude Code often spawns the statusline subprocess WITHOUT the
        # session_id (not on stdin, not inherited in env). Bind to this session
        # via the terminal pane id, which IS inherited — so the statusline shows
        # the SAME name as the title bar instead of a stale project pin.
        cs = lookup_by_term(_term_id())
    if not cs:
        # Last resort: project-level name for display only (no burn).
        cs, _title, _root = resolve(cwd)
    try:
        user = getpass.getuser()
    except Exception:
        user = os.environ.get("USER") or "user"
    # Bold cyan callsign, dim em-dash, bold username.
    sys.stdout.write(f"\033[1;36m{cs}\033[0m \033[2m—\033[0m \033[1m{user}\033[0m")


def do_stop(hook_in: dict) -> None:
    cwd = hook_in.get("cwd") or os.getcwd()
    sid = _session_id_from(hook_in)
    if sid:
        cs, title, _root = resolve_session(sid, cwd, pid=os.getppid())
    else:
        cs, title, _root = resolve(cwd)
    bar = f"{cs} — {title}"
    osc_title(bar)
    # Stop hooks: terminalSequence is a TOP-LEVEL field. hookSpecificOutput
    # is only valid for PreToolUse / UserPromptSubmit / PostToolUse / PostToolBatch.
    out = {
        "continue": True,
        "suppressOutput": True,
        "terminalSequence": f"\033]2;{bar}\007",
    }
    sys.stdout.write(json.dumps(out) + "\n")


def main() -> int:
    # Mode resolution: explicit argv first, else infer from hook_event_name.
    argv = sys.argv[1:]
    if argv and argv[0] in ("show", "set"):
        if argv[0] == "show":
            where = argv[1] if len(argv) > 1 else os.getcwd()
            cs, title, root = resolve(where)
            print(f"{cs} — {title}   [{root}]")
            return 0
        if argv[0] == "set":
            # usage: set <NAME> [<project_path>]   (path defaults to cwd)
            if len(argv) < 2:
                print("usage: project_callsign.py set <NAME> [<project_path>]", file=sys.stderr)
                return 2
            where = argv[2] if len(argv) > 2 else os.getcwd()
            cs, root = set_manual(where, argv[1])
            print(f"pinned {cs} for {root}")
            osc_title(f"{cs} — {project_title(root)}")
            return 0

    hook_in = read_hook_input()
    mode = argv[0] if argv else None
    event = (hook_in.get("hook_event_name") or "").lower()
    if mode == "session-start" or event == "sessionstart":
        do_session_start(hook_in)
    elif mode == "statusline" or event in ("status", "statusline"):
        do_statusline(hook_in)
    elif mode == "stop" or event == "stop":
        do_stop(hook_in)
    else:
        # default safe payload
        sys.stdout.write(json.dumps({"continue": True, "suppressOutput": True}) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
