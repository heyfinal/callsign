"""callsign CLI — argparse only, no heavy deps."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from callsign import banner, names, registry, router
from callsign.paths import SESSIONS_DIR, ensure_dirs
from callsign.version import __version__


def _session_env_path(session_uid: str) -> Path:
    return SESSIONS_DIR / f"{session_uid}.env"


def _detect_session_uid() -> str | None:
    for k in (
        "CLAUDE_SESSION_ID",
        "CLAUDE_CODE_SESSION_ID",
        "HERMES_SESSION_ID",
        "CALLSIGN_SESSION_UID",
    ):
        v = os.environ.get(k)
        if v:
            return v
    return None


def _resolve_callsign(explicit: str | None = None) -> str | None:
    """Find the current session's callsign without requiring $CALLSIGN.

    Order: explicit arg → $CALLSIGN → registry lookup by session UID
    → registry lookup by project path.
    """
    if explicit:
        return explicit
    env = os.environ.get("CALLSIGN")
    if env:
        return env
    uid = _detect_session_uid()
    if uid:
        sess = registry.lookup_by_session_uid(uid)
        if sess:
            return sess.callsign
    proj = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    if proj:
        sess = registry.lookup_by_project(proj)
        if sess:
            return sess.callsign
    return None


def cmd_claim(ns: argparse.Namespace) -> int:
    ensure_dirs()
    if not ns.name:
        print("claim: pass a name or use --auto", file=sys.stderr)
        return 2
    try:
        sess = registry.claim(
            name=ns.name,
            platform=ns.platform,
            project_path=ns.project or os.getcwd(),
            pid=ns.pid or os.getppid(),
            session_uid=ns.session_uid or _detect_session_uid(),
            env={"argv0": sys.argv[0]},
        )
    except registry.InvalidNameError as e:
        msg = f"invalid name: {e}"
        if ns.json:
            print(json.dumps({"ok": False, "error": "invalid_name", "message": str(e)}))
        else:
            print(msg, file=sys.stderr)
        return 2
    except registry.NameTakenError as e:
        if ns.json:
            print(json.dumps({"ok": False, "error": "name_taken", "message": str(e)}))
        else:
            print(str(e), file=sys.stderr)
            taken = {s.callsign for s in registry.list_active()}
            free = names.suggest(taken, n=5)
            if free:
                print(f"  some unused suggestions: {', '.join(free)}", file=sys.stderr)
        return 3

    uid = sess.session_uid or f"pid-{sess.pid}"
    env_path = _session_env_path(uid)
    env_path.write_text(
        f"CALLSIGN={sess.callsign}\nCALLSIGN_PLATFORM={sess.platform}\n"
        f"CALLSIGN_PROJECT={sess.project_path or ''}\nCALLSIGN_PID={sess.pid or ''}\n"
    )
    if ns.json:
        print(json.dumps({
            "ok": True,
            "callsign": sess.callsign,
            "platform": sess.platform,
            "project_path": sess.project_path,
            "pid": sess.pid,
            "session_uid": sess.session_uid,
        }))
    elif ns.quiet:
        print(sess.callsign)
    else:
        print(banner.intro(sess.callsign, platform=sess.platform), file=sys.stderr)
        print(sess.callsign)
    return 0


def cmd_suggest(ns: argparse.Namespace) -> int:
    taken = {s.callsign for s in registry.list_active()}
    free = names.suggest(taken, n=ns.count)
    if ns.json:
        print(json.dumps({"suggestions": free, "note": "these are examples; pick any name"}))
    else:
        if free:
            for n in free:
                print(n)
        else:
            print("(no suggestions available)")
    return 0


def cmd_assign(ns: argparse.Namespace) -> int:
    ensure_dirs()
    sess = registry.assign(
        platform=ns.platform,
        project_path=ns.project or os.getcwd(),
        pid=ns.pid or os.getppid(),
        session_uid=ns.session_uid or _detect_session_uid(),
        preferred=ns.preferred,
        env={"argv0": sys.argv[0]},
        reuse_project=not ns.ephemeral,
    )
    uid = sess.session_uid or f"pid-{sess.pid}"
    env_path = _session_env_path(uid)
    env_path.write_text(
        f"CALLSIGN={sess.callsign}\nCALLSIGN_PLATFORM={sess.platform}\n"
        f"CALLSIGN_PROJECT={sess.project_path or ''}\nCALLSIGN_PID={sess.pid or ''}\n"
    )
    if ns.json:
        print(json.dumps({
            "callsign": sess.callsign,
            "platform": sess.platform,
            "project_path": sess.project_path,
            "pid": sess.pid,
            "session_uid": sess.session_uid,
            "started_at": sess.started_at,
            "env_file": str(env_path),
        }))
    elif ns.quiet:
        print(sess.callsign)
    else:
        print(banner.intro(sess.callsign, platform=sess.platform), file=sys.stderr)
        print(sess.callsign)
    return 0


def cmd_list(ns: argparse.Namespace) -> int:
    rows = registry.list_active()
    if ns.json:
        print(json.dumps([
            {
                "callsign": s.callsign,
                "platform": s.platform,
                "project_path": s.project_path,
                "pid": s.pid,
                "started_at": s.started_at,
                "last_seen": s.last_seen,
            }
            for s in rows
        ], indent=2))
        return 0
    if not rows:
        print("(no active callsigns)")
        return 0
    print(f"{'CALLSIGN':<14} {'PLATFORM':<14} {'PID':<8} PROJECT")
    print("─" * 70)
    for s in rows:
        proj = (s.project_path or "")
        if len(proj) > 36:
            proj = "…" + proj[-35:]
        print(f"{s.callsign:<14} {s.platform:<14} {s.pid or '-':<8} {proj}")
    return 0


def cmd_lookup(ns: argparse.Namespace) -> int:
    sess = registry.lookup(ns.name)
    if not sess:
        print(f"no active session for callsign '{ns.name}'", file=sys.stderr)
        return 1
    if ns.json:
        print(json.dumps({
            "callsign": sess.callsign, "platform": sess.platform,
            "project_path": sess.project_path, "pid": sess.pid,
            "status": sess.status,
        }))
    else:
        print(f"{sess.callsign}  {sess.platform}  pid={sess.pid}  {sess.project_path}")
    return 0


def cmd_retire(ns: argparse.Namespace) -> int:
    ok = registry.retire(ns.name)
    if ok:
        print(f"retired {ns.name}")
        return 0
    print(f"no active session for '{ns.name}'", file=sys.stderr)
    return 1


def cmd_route(ns: argparse.Namespace) -> int:
    hit = router.route(ns.text)
    if not hit:
        if ns.json:
            print(json.dumps({"hit": False}))
        else:
            print("(no callsign match — falls back to default)")
        return 1
    if ns.json:
        print(json.dumps({
            "hit": True, "callsign": hit.callsign,
            "platform": hit.session.platform,
            "project_path": hit.session.project_path,
            "pid": hit.session.pid, "body": hit.body,
        }))
    else:
        print(f"{hit.callsign} → {hit.session.project_path}")
        print(hit.body)
    return 0


def cmd_banner(ns: argparse.Namespace) -> int:
    cs = _resolve_callsign(ns.name)
    if not cs:
        sys.stdout.write(banner.awaiting_claim(platform=ns.platform))
        return 0
    sys.stdout.write(banner.intro(cs, platform=ns.platform))
    return 0


def cmd_send(ns: argparse.Namespace) -> int:
    cs = _resolve_callsign(ns.callsign) or ""
    if not cs and not ns.no_prefix:
        print(
            "no callsign claimed for this session — run `callsign claim <YourName>` first, "
            "or use --no-prefix to send raw",
            file=sys.stderr,
        )
        return 4
    text = ns.text
    if cs and not ns.no_prefix:
        text = f"{cs}: {text}"
    if ns.dry_run:
        print(text)
        return 0
    imsg = shutil.which("imsg")
    if not imsg:
        print("imsg CLI not found on PATH", file=sys.stderr)
        return 127
    to = ns.to or os.environ.get("CALLSIGN_DEFAULT_TO") or "+14053151310"
    cmd = [imsg, "send", "--to", to, "--text", text]
    if ns.service:
        cmd += ["--service", ns.service]
    res = subprocess.run(cmd)
    return res.returncode


def cmd_names(ns: argparse.Namespace) -> int:
    taken = {s.callsign for s in registry.list_active()}
    free = [n for n in names.POOL if n not in taken]
    if ns.json:
        print(json.dumps({"total": len(names.POOL), "taken": sorted(taken), "free": free}))
    else:
        print(f"pool: {len(names.POOL)}  taken: {len(taken)}  free: {len(free)}")
    return 0


def cmd_init(ns: argparse.Namespace) -> int:
    ensure_dirs()
    print(f"callsign home ready: {SESSIONS_DIR.parent}")
    return 0


def cmd_router(ns: argparse.Namespace) -> int:
    """Foreground loop: read incoming imsg stream, route, optionally dispatch.

    Reads JSON lines from stdin (intended target:
        ``imsg watch --json | callsign router --dispatch``).
    Writes one decision per line to ~/.callsign/logs/router.log and to stdout.

    With ``--dispatch`` and the routed callsign is active, also fires the
    dispatcher: resumes the matched Claude Code session via
    ``claude --resume <UID> --print``, captures the reply, and pipes it back
    out as iMessage chunks. Quiet-hours messages are inboxed without dispatch.
    """
    from callsign.paths import LOG_DIR
    from callsign import config as cfg_mod, dispatcher as disp_mod, inbox

    ensure_dirs()
    cfg = cfg_mod.Config.load()
    log_path = LOG_DIR / "router.log"
    with log_path.open("a") as log:
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue

            text = msg.get("text") or msg.get("body") or ""
            sender = msg.get("sender") or msg.get("from") or ""
            chat_id = msg.get("chat_id") or msg.get("chat") or ""
            guid = (msg.get("guid") or msg.get("id")
                    or f"{sender}:{time.time():.6f}:{hash(text) & 0xffffffff:08x}")

            hit = router.route(text)
            decision = {
                "ts": time.time(),
                "sender": sender,
                "chat_id": chat_id,
                "guid": guid,
                "text": text,
                "callsign": hit.callsign if hit else None,
                "project": hit.session.project_path if hit else None,
                "pid": hit.session.pid if hit else None,
            }

            if hit and ns.dispatch:
                inb = disp_mod.InboundMessage(
                    guid=guid, callsign=hit.callsign,
                    sender=sender or None, chat_id=chat_id or None,
                    body=hit.body,
                )
                if cfg_mod.in_quiet_hours(cfg):
                    inbox.append(hit.callsign, {
                        "guid": guid, "sender": sender, "chat_id": chat_id,
                        "body": hit.body, "queued_for_quiet": True,
                    })
                    decision["queued_quiet_hours"] = True
                else:
                    try:
                        result = disp_mod.fire(hit.session, inb, cfg=cfg)
                        decision["dispatch"] = result
                    except Exception as e:
                        decision["dispatch_error"] = str(e)[:400]

            line_out = json.dumps(decision)
            print(line_out, flush=True)
            log.write(line_out + "\n")
            log.flush()
    return 0


def cmd_status(ns: argparse.Namespace) -> int:
    """Health snapshot of the daemon + queues + processed counts."""
    from callsign import processed_db
    from callsign.paths import LOG_DIR, INBOX_DIR

    rows = registry.list_active()
    stats = processed_db.stats()
    inbox_files = list(INBOX_DIR.glob("*.jsonl")) if INBOX_DIR.exists() else []
    inbox_pending = 0
    for p in inbox_files:
        try:
            inbox_pending += sum(1 for _ in p.open("r", encoding="utf-8"))
        except OSError:
            continue

    daemon_pid = _read_daemon_pid()
    daemon_alive = _pid_alive(daemon_pid) if daemon_pid else False

    payload = {
        "daemon": {
            "pid": daemon_pid,
            "alive": daemon_alive,
        },
        "registry": {
            "active": len(rows),
            "callsigns": [s.callsign for s in rows],
        },
        "processed": stats,
        "inbox": {
            "files": len(inbox_files),
            "lines_total": inbox_pending,
        },
    }
    if ns.json:
        print(json.dumps(payload, indent=2))
    else:
        d = payload["daemon"]
        print(f"daemon:    {'up' if d['alive'] else 'down'} (pid {d['pid'] or '-'})")
        print(f"registry:  {payload['registry']['active']} active  "
              f"[{', '.join(payload['registry']['callsigns']) or '-'}]")
        ps = payload["processed"]
        print(f"processed: total={ps['total']}  replied={ps['replied']}  "
              f"errored={ps['errored']}  pending={ps['pending']}")
        print(f"inbox:     {payload['inbox']['files']} files, "
              f"{payload['inbox']['lines_total']} lines")
    return 0 if daemon_alive else 1


def _pid_alive(pid: int | None) -> bool:
    if not pid or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return pid > 0  # PermissionError = exists, we just can't signal


def _read_daemon_pid() -> int | None:
    from callsign.paths import ROOT
    path = ROOT / "router.pid"
    if not path.exists():
        return None
    try:
        return int(path.read_text().strip())
    except (ValueError, OSError):
        return None


def cmd_smoke_test(ns: argparse.Namespace) -> int:
    """Inject a synthetic inbound message through the full pipeline.

    Validates: router parses leading name, dispatcher finds the session,
    chunking + send path executes (dry-run: prints to stderr instead of sending).
    Requires a live callsign claim for the target name.
    """
    from callsign import dispatcher as disp_mod, config as cfg_mod

    target = ns.target or _resolve_callsign(None)
    if not target:
        print("smoke-test: no target callsign — pass --target NAME or claim one first",
              file=sys.stderr)
        return 2
    sess = registry.lookup(target)
    if not sess:
        print(f"smoke-test: no active session for {target}", file=sys.stderr)
        return 3
    cfg = cfg_mod.Config.load()
    msg = disp_mod.InboundMessage(
        guid=f"smoke-{int(time.time())}",
        callsign=sess.callsign,
        sender=ns.sender or "+15555550100",
        chat_id=None,
        body=ns.body or "ping",
    )
    result = disp_mod.fire(sess, msg, dry_run=True, cfg=cfg)
    print(json.dumps(result, indent=2))
    return 0 if result.get("ok") else 1


def cmd_drain(ns: argparse.Namespace) -> int:
    """Drain quiet-hours inbox: re-dispatch queued messages now.

    Intended target: the morning-drain launchd plist (StartCalendarInterval
    + WakeFromSleep). Idempotent — already-replied guids are skipped by
    processed_db.is_replied().
    """
    from callsign import inbox, dispatcher as disp_mod, config as cfg_mod, processed_db

    cfg = cfg_mod.Config.load()
    active = {s.callsign: s for s in registry.list_active()}
    drained = 0
    skipped = 0
    failed = 0
    for cs, sess in active.items():
        for raw in inbox.read_all(cs):
            guid = raw.get("guid") or ""
            if not guid:
                continue
            if processed_db.is_replied(guid):
                skipped += 1
                continue
            if not raw.get("queued_for_quiet"):
                continue
            inb = disp_mod.InboundMessage(
                guid=guid, callsign=cs,
                sender=raw.get("sender") or None,
                chat_id=raw.get("chat_id") or None,
                body=raw.get("body") or "",
            )
            try:
                r = disp_mod.fire(sess, inb, cfg=cfg)
                if r.get("ok"):
                    drained += 1
                else:
                    failed += 1
            except Exception:
                failed += 1
    out = {"drained": drained, "skipped": skipped, "failed": failed}
    print(json.dumps(out, indent=2))
    return 0 if failed == 0 else 1


def cmd_claim_auto_or_named(ns: argparse.Namespace) -> int:
    """Route `callsign claim --auto` to the legacy assign() path."""
    if getattr(ns, "auto", False):
        # Map to assign with no preferred, reuse_project False.
        ensure_dirs()
        sess = registry.assign(
            platform=ns.platform,
            project_path=ns.project or os.getcwd(),
            pid=ns.pid or os.getppid(),
            session_uid=ns.session_uid or _detect_session_uid(),
            preferred=None,
            env={"argv0": sys.argv[0], "auto": True},
            reuse_project=False,
        )
        uid = sess.session_uid or f"pid-{sess.pid}"
        _session_env_path(uid).write_text(
            f"CALLSIGN={sess.callsign}\nCALLSIGN_PLATFORM={sess.platform}\n"
            f"CALLSIGN_PROJECT={sess.project_path or ''}\nCALLSIGN_PID={sess.pid or ''}\n"
        )
        if ns.json:
            print(json.dumps({"ok": True, "callsign": sess.callsign,
                              "claimed_via": "auto"}))
        else:
            print(sess.callsign)
        return 0
    return cmd_claim(ns)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="callsign",
        description="Unique per-session agent names for Claude Code and Hermes.",
    )
    p.add_argument("--version", action="version", version=f"callsign {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("claim", help="claim a name for this session (agent-driven, or --auto)")
    a.add_argument("name", nargs="?", default=None,
                   help="the name you (the agent) are picking — omit when using --auto")
    a.add_argument("--auto", action="store_true",
                   help="auto-pick from the pool (used by SessionStart hook)")
    a.add_argument("--platform", default="claude-code")
    a.add_argument("--project", default=None)
    a.add_argument("--pid", type=int, default=None)
    a.add_argument("--session-uid", default=None)
    a.add_argument("--json", action="store_true")
    a.add_argument("--quiet", action="store_true",
                   help="only print the callsign on stdout")
    a.set_defaults(func=cmd_claim_auto_or_named)

    a = sub.add_parser("suggest",
                       help="list a few unused example names (agents may pick any name)")
    a.add_argument("-n", "--count", type=int, default=5)
    a.add_argument("--json", action="store_true")
    a.set_defaults(func=cmd_suggest)

    a = sub.add_parser("assign",
                       help="auto-pick a name (legacy / non-interactive callers)")
    a.add_argument("--platform", default="claude-code")
    a.add_argument("--project", default=None)
    a.add_argument("--pid", type=int, default=None)
    a.add_argument("--session-uid", default=None)
    a.add_argument("--preferred", default=None,
                   help="request a specific name if available")
    a.add_argument("--ephemeral", action="store_true",
                   help="do not reuse an existing project callsign")
    a.add_argument("--json", action="store_true")
    a.add_argument("--quiet", action="store_true",
                   help="only print the callsign on stdout")
    a.set_defaults(func=cmd_assign)

    a = sub.add_parser("list", help="show active callsigns")
    a.add_argument("--json", action="store_true")
    a.set_defaults(func=cmd_list)

    a = sub.add_parser("lookup", help="resolve a callsign to a session")
    a.add_argument("name")
    a.add_argument("--json", action="store_true")
    a.set_defaults(func=cmd_lookup)

    a = sub.add_parser("retire", help="mark a callsign retired")
    a.add_argument("name")
    a.set_defaults(func=cmd_retire)

    a = sub.add_parser("route", help="parse leading callsign in a message")
    a.add_argument("text")
    a.add_argument("--json", action="store_true")
    a.set_defaults(func=cmd_route)

    a = sub.add_parser("banner", help="print intro banner for a callsign")
    a.add_argument("--name", default=None)
    a.add_argument("--platform", default="Claude Code")
    a.set_defaults(func=cmd_banner)

    a = sub.add_parser("send", help="send iMessage prefixed with the callsign")
    a.add_argument("text")
    a.add_argument("--callsign", default=None)
    a.add_argument("--to", default=None,
                   help="phone/email (default: $CALLSIGN_DEFAULT_TO or daniel)")
    a.add_argument("--service", default=None, choices=["imessage", "sms", "auto"])
    a.add_argument("--no-prefix", action="store_true")
    a.add_argument("--dry-run", action="store_true")
    a.set_defaults(func=cmd_send)

    a = sub.add_parser("names", help="show the name pool")
    a.add_argument("--json", action="store_true")
    a.set_defaults(func=cmd_names)

    a = sub.add_parser("init", help="create state directories")
    a.set_defaults(func=cmd_init)

    a = sub.add_parser("router", help="read imsg stream from stdin; log + optionally dispatch")
    a.add_argument("--dispatch", action="store_true",
                   help="run matched messages through claude --resume and reply via imsg")
    a.set_defaults(func=cmd_router)

    a = sub.add_parser("status", help="health snapshot (daemon, registry, processed counts)")
    a.add_argument("--json", action="store_true")
    a.set_defaults(func=cmd_status)

    a = sub.add_parser("smoke-test", help="inject a synthetic inbound message (dry-run)")
    a.add_argument("--target", default=None, help="callsign to deliver to (default: current)")
    a.add_argument("--sender", default=None, help="fake sender phone/handle")
    a.add_argument("--body", default=None, help="message body (default: 'ping')")
    a.set_defaults(func=cmd_smoke_test)

    a = sub.add_parser("drain", help="drain quiet-hours inbox (morning-drain job)")
    a.set_defaults(func=cmd_drain)
    return p


def main(argv: list[str] | None = None) -> int:
    p = build_parser()
    ns = p.parse_args(argv)
    return ns.func(ns)


if __name__ == "__main__":
    raise SystemExit(main())
