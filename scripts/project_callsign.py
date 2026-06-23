#!/usr/bin/env python3
"""project_callsign.py — per-SESSION real-name callsign + terminal-title pinning
for Claude Code, with a 6-month cooldown ledger and resume-by-name.

Identity model (Daniel's spec):
  * Pool = 3000 REAL human names (callsign_names.txt). No fantasy compounds.
  * A name issued to a session is reserved to THAT session for COOLDOWN_DAYS
    (6 months). No other session may use it during the cooldown — the pool does
    NOT replenish a name early. After the cooldown it returns to the pool.
  * Every issue is recorded in a persistent LEDGER: name -> {session_id,
    issued_at}. The ledger survives session death (needed for both the cooldown
    and resume-by-name).
  * `claude --resume <NAME>` resumes the session that holds <NAME> (a shell
    wrapper calls `project_callsign.py resume-id <NAME>` to map name -> id).

Storage: ~/.claude/callsigns.json
  __ledger__   : { "<NAME>": {"session_id","issued_at","title","root"} }
  __sessions__ : { "<session_id>": {"callsign","pid","title","root","term"} }  (live)
  "<proj_path>": {"callsign","manual","title"}                                  (legacy project fallback)

Modes (hook_event_name on stdin, or argv[1]):
  session-start | stop | statusline | show | set <NAME> | resume-id <NAME>
"""
import json
import os
import sys
import hashlib
import subprocess
from datetime import datetime, timezone
from pathlib import Path

HOME = Path(os.path.expanduser("~"))
STORE = HOME / ".claude" / "callsigns.json"
LEGACY = HOME / ".claude" / "callsign.json"

COOLDOWN_DAYS = 183  # 6 months — a name can't be reissued within this window

# ── name pool ────────────────────────────────────────────────────────────────
_NAMES_FILE = HOME / ".claude" / "scripts" / "callsign_names.txt"
_FALLBACK_NAMES = (
    "STEVEN", "TRINITY", "ROOK", "NORA", "ELLIS", "MAYA", "OWEN", "IVY",
    "FELIX", "CLARA", "MILO", "HAZEL", "JONAS", "RUBY", "SILAS", "ESME",
    "GRANT", "WREN", "VANCE", "WILLA", "DEAN", "IRIS", "ZANE", "CORA",
)


def _load_pool() -> tuple:
    try:
        seen, out = set(), []
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
WORDLIST = POOL  # back-compat alias


# ── project helpers ──────────────────────────────────────────────────────────
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
    if _git_root(root):
        return base
    return base.replace("-", " ").replace("_", " ").title()


def deterministic_callsign(root: str) -> str:
    h = hashlib.sha256(root.encode("utf-8")).hexdigest()
    return WORDLIST[int(h, 16) % len(WORDLIST)]


# ── session / ledger plumbing ────────────────────────────────────────────────
_SESSIONS_KEY = "__sessions__"
_LEDGER_KEY = "__ledger__"
_USED_KEY = "__used__"  # legacy; migrated into the ledger
_LOCK = HOME / ".claude" / "callsigns.lock"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _age_days(iso: str | None) -> float:
    if not iso:
        return 1e9
    try:
        t = datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - t).total_seconds() / 86400.0
    except Exception:
        return 1e9


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
    """Stable per-terminal-pane id, inherited identically by the SessionStart
    hook and the statusline subprocess — lets the statusline find its own
    session even when Claude Code passes no session_id."""
    for k in ("ITERM_SESSION_ID", "TERM_SESSION_ID", "WEZTERM_PANE",
              "KITTY_WINDOW_ID", "TMUX_PANE", "WINDOWID"):
        v = os.environ.get(k)
        if v and v.strip():
            return f"{k}={v.strip()}"
    return None


def _available(name: str, ledger: dict) -> bool:
    """A name is available iff never issued, or its cooldown has elapsed."""
    e = ledger.get(name)
    if not e:
        return True
    return _age_days(e.get("issued_at")) > COOLDOWN_DAYS


def _name_for_session(ledger: dict, session_id: str) -> str | None:
    """If this session already holds a (still-valid) name, return it — so a
    resumed/restarted session keeps its identity instead of drawing a new one."""
    for name, e in ledger.items():
        if e.get("session_id") == session_id and _age_days(e.get("issued_at")) <= COOLDOWN_DAYS:
            return name
    return None


def _pick_available(session_id: str, ledger: dict) -> str:
    """Deterministic start index per session_id, linear-probe the pool for the
    first name not in active cooldown. If all 3000 are locked (>3000 sessions in
    6 months), fall back to the least-recently-used name + a short id suffix so
    two live sessions still never share an identity."""
    start = int(hashlib.sha256(session_id.encode()).hexdigest(), 16) % len(POOL)
    for i in range(len(POOL)):
        cand = POOL[(start + i) % len(POOL)]
        if _available(cand, ledger):
            return cand
    oldest = max(POOL, key=lambda n: _age_days(ledger.get(n, {}).get("issued_at")))
    return f"{oldest}-{session_id[:4]}"


def _reap_sessions(sessions: dict) -> None:
    """Drop LIVE-session entries for dead pids. The ledger is NOT touched — names
    stay reserved for the full cooldown regardless of session liveness."""
    for sid in [s for s, e in sessions.items() if not _pid_alive(e.get("pid"))]:
        sessions.pop(sid, None)


def _migrate_used(data: dict) -> None:
    """One-time: fold the legacy permanent __used__ list into the cooldown
    ledger (timestamped now — conservative; mostly retired fantasy names)."""
    if _USED_KEY in data:
        led = data.setdefault(_LEDGER_KEY, {})
        now = _now_iso()
        for n in data.pop(_USED_KEY) or []:
            led.setdefault(n, {"session_id": None, "issued_at": now})
    # carry any live-session callsigns into the ledger if missing
    led = data.setdefault(_LEDGER_KEY, {})
    for sid, e in data.get(_SESSIONS_KEY, {}).items():
        cs = e.get("callsign")
        if cs and cs not in led:
            led[cs] = {"session_id": sid, "issued_at": _now_iso(),
                       "title": e.get("title"), "root": e.get("root")}


def resolve_session(session_id: str, cwd: str, pid: int | None = None) -> tuple[str, str, str]:
    """Return (callsign, project_title, project_root) for ONE session.
    Stable across resume/compact; flock-serialized; 6-month cooldown enforced."""
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
        _migrate_used(data)
        sessions = data.setdefault(_SESSIONS_KEY, {})
        ledger = data.setdefault(_LEDGER_KEY, {})
        _reap_sessions(sessions)

        # already live this session?
        entry = sessions.get(session_id)
        if entry and entry.get("callsign"):
            entry["pid"] = pid or entry.get("pid")
            entry["title"] = title
            term = _term_id()
            if term:
                entry["term"] = term
            # keep the ledger pointer fresh for resume
            led = ledger.get(entry["callsign"])
            if led is not None:
                led["session_id"] = session_id
            _save(data)
            return entry["callsign"], title, root

        # resumed/restarted session that still holds a name?
        cs = _name_for_session(ledger, session_id)
        if cs:
            ledger[cs]["session_id"] = session_id  # keep original issued_at
        else:
            cs = _pick_available(session_id, ledger)
            ledger[cs] = {"session_id": session_id, "issued_at": _now_iso(),
                          "title": title, "root": root}

        sessions[session_id] = {"callsign": cs, "pid": pid, "title": title,
                                "root": root, "term": _term_id()}
        _save(data)
        return cs, title, root


def name_to_session_id(name: str) -> str | None:
    """Map a callsign -> the session_id that holds it (for `--resume <NAME>`).
    Case-insensitive. Returns None if unknown."""
    if not name:
        return None
    data = _load()
    ledger = data.get(_LEDGER_KEY, {})
    target = name.strip().upper()
    e = ledger.get(target)
    if e and e.get("session_id"):
        return e["session_id"]
    # also accept a name currently held by a live session
    for sid, s in data.get(_SESSIONS_KEY, {}).items():
        if (s.get("callsign") or "").upper() == target:
            return sid
    return None


# ── persistence ──────────────────────────────────────────────────────────────
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


# ── legacy project-level fallback (deterministic, for non-session callers) ────
_LEGACY_MARKER = "__legacy_migrated__"


def _maybe_migrate_legacy(root: str, data: dict) -> bool:
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
    """Project-level deterministic callsign (statusline fallback / CLI)."""
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


# ── terminal title + hook I/O ────────────────────────────────────────────────
def osc_title(text: str) -> None:
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
        cs, title, _root = resolve(cwd)
    bar = f"{cs} — {title}"
    out = {
        "continue": True,
        "suppressOutput": True,
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "sessionTitle": bar,
            "additionalContext": (
                f"Your operational callsign for this project is {cs}. "
                f"You are {cs}. Project: {title}. "
                f"The OS terminal title is pinned to \"{bar}\". "
                f"Resume this exact session later with: claude --resume {cs}"
            ),
        },
    }
    osc_title(bar)
    sys.stdout.write(json.dumps(out) + "\n")


def lookup_session(session_id: str) -> str | None:
    if not session_id:
        return None
    data = _load()
    entry = data.get(_SESSIONS_KEY, {}).get(session_id)
    return entry.get("callsign") if entry else None


def lookup_by_term(term: str) -> str | None:
    if not term:
        return None
    data = _load()
    sessions = data.get(_SESSIONS_KEY, {})
    matches = [e for e in sessions.values() if e.get("term") == term and e.get("callsign")]
    if not matches:
        return None
    live = [e for e in matches if _pid_alive(e.get("pid"))]
    return (live or matches)[-1].get("callsign")


def do_statusline(hook_in: dict) -> None:
    import getpass
    cwd = hook_in.get("cwd") or os.getcwd()
    sid = _session_id_from(hook_in)
    cs = lookup_session(sid) if sid else None
    if not cs:
        cs = lookup_by_term(_term_id())
    if not cs:
        cs, _title, _root = resolve(cwd)
    try:
        user = getpass.getuser()
    except Exception:
        user = os.environ.get("USER") or "user"
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
    out = {
        "continue": True,
        "suppressOutput": True,
        "terminalSequence": f"\033]2;{bar}\007",
    }
    sys.stdout.write(json.dumps(out) + "\n")


def main() -> int:
    argv = sys.argv[1:]
    if argv and argv[0] in ("show", "set", "resume-id"):
        if argv[0] == "show":
            where = argv[1] if len(argv) > 1 else os.getcwd()
            cs, title, root = resolve(where)
            print(f"{cs} — {title}   [{root}]")
            return 0
        if argv[0] == "set":
            if len(argv) < 2:
                print("usage: project_callsign.py set <NAME> [<project_path>]", file=sys.stderr)
                return 2
            where = argv[2] if len(argv) > 2 else os.getcwd()
            cs, root = set_manual(where, argv[1])
            print(f"pinned {cs} for {root}")
            osc_title(f"{cs} — {project_title(root)}")
            return 0
        if argv[0] == "resume-id":
            if len(argv) < 2:
                return 2
            sid = name_to_session_id(argv[1])
            if sid:
                print(sid)
                return 0
            return 1

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
        sys.stdout.write(json.dumps({"continue": True, "suppressOutput": True}) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
