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


def _norm_sender(s: str) -> str:
    """Canonicalize an iMessage sender for allowlist comparison.

    Phones -> last 10 digits (ignores +1 / formatting); email handles ->
    lowercase-exact.
    """
    s = (s or "").strip().lower()
    digits = "".join(ch for ch in s if ch.isdigit())
    return digits[-10:] if len(digits) >= 10 else s


def _allowed_senders() -> set[str]:
    """Normalized allowlist from $CALLSIGN_ALLOWED_SENDERS, default owner number."""
    raw = os.environ.get("CALLSIGN_ALLOWED_SENDERS") or "+14053151310"
    return {_norm_sender(x) for x in raw.split(",") if x.strip()}


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
    # Canonical identity is the project_callsign name daniel sees (RONIN, ...).
    if uid:
        from callsign import project_link
        name = project_link.session_to_name(uid)
        if name:
            return name
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


def cmd_resume(ns: argparse.Namespace) -> int:
    """Resume a live Claude Code session by its displayed callsign.

    Resolves callsign -> session_id (project_callsign store first, then the
    package registry) and execs `claude --resume <session_id>`.
    """
    from callsign import project_link

    link = project_link.name_to_session(ns.name)
    sid = link["session_id"] if link else None
    if not sid:
        sess = registry.lookup(ns.name)
        sid = sess.session_uid if sess and sess.status == "active" else None
    if not sid:
        print(f"no live session named '{ns.name}' — try `callsign list`", file=sys.stderr)
        return 1
    if ns.print_id:
        print(sid)
        return 0
    claude = shutil.which("claude")
    if not claude:
        for cand in ("/opt/homebrew/bin/claude",
                     f"{os.path.expanduser('~')}/.local/bin/claude",
                     "/usr/local/bin/claude"):
            if os.path.exists(cand):
                claude = cand
                break
        else:
            claude = "claude"
    os.execvp(claude, [claude, "--resume", sid])  # replaces this process
    return 0  # unreachable


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
    from callsign import config as cfg_mod, dispatcher as disp_mod, inbox, persona
    from callsign import transports

    ensure_dirs()
    cfg = cfg_mod.Config.load()

    # INPUT-ADAPTER SEAM — this daemon reads ONE transport's raw stream from
    # stdin; $CALLSIGN_TRANSPORT names it (default "imessage" = `imsg watch
    # --json`). transports.adapt() normalizes the raw payload into a transport-
    # neutral InboundEnvelope; transports.authz() applies that transport's OWN
    # trust basis. Adding terminal/dropbox/tablet later = a new adapter+authz in
    # transports.py with NO change here. SECURITY: each transport carries its own
    # authz (iMessage = sender allowlist); unwired transports DENY by default, so
    # a new surface can never silently inherit iMessage trust or open an
    # unauthenticated RCE channel.
    transport = os.environ.get("CALLSIGN_TRANSPORT", "imessage")

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

            env = transports.adapt(msg, transport)
            if env is None:
                # Unknown transport shape — skip (don't guess, don't dispatch).
                continue

            # SELF-FILTER (2026-07-01) — NEVER process our own outbound. An
            # is_from_me message is something WE (or Daniel from this account)
            # already sent; routing/replying to it is how self-feedback loops
            # start. This is transport-agnostic and cheap; it also permanently
            # forecloses the class of loop the removed 👀 ACK caused.
            if msg.get("is_from_me") or msg.get("isFromMe") or msg.get("from_me"):
                continue
            text = env.text
            sender = env.sender or ""
            chat_id = env.chat_id or ""
            guid = env.guid

            # LAYER 1 — Watermark: skip backlog messages from before daemon started.
            # Prevents boot-storm when `imsg watch --json` replays historical messages.
            # Messages are filtered by timestamp (chat.db "date" field).
            from callsign import watermark as wm_mod
            msg_timestamp = msg.get("date")  # Cocoa format from imsg watch --json
            if not wm_mod.should_process_message(msg_timestamp):
                # Backlog message — skip it. Log for observability.
                decision = {
                    "ts": time.time(),
                    "transport": env.transport,
                    "sender": sender,
                    "chat_id": chat_id,
                    "guid": guid,
                    "text": text,
                    "skipped_watermark": True,
                    "msg_timestamp": msg_timestamp,
                }
                log_out = json.dumps(decision)
                print(log_out, flush=True)
                log.write(log_out + "\n")
                log.flush()
                continue

            # ── PERSONA PATH (Alicia / external humans) ─────────────────────
            # Daniel's PRIME MESSAGING RULE: a conversational-only sender
            # (CALLSIGN_PERSONA_SENDERS, default Alicia) gets a warm MARLOWE-
            # persona reply and NOTHING else. She must NEVER reach the
            # authz/dispatch/session_inject path below — that drops text into a
            # live tool-enabled agent session (RCE-equivalent) = ZERO system
            # access for her. Reply is tool-less, gate-free, sent to HER thread
            # only. Short-circuits before routing so there is no other surface.
            if ns.dispatch and text.strip() and persona.is_persona_sender(sender) \
                    and not router.is_machine_alert(text):
                from callsign import processed_db as _pdb
                _pdb.enqueue(guid, "MARLOWE", sender or None, chat_id or None, text)
                pdecision = {
                    "ts": time.time(), "transport": env.transport,
                    "sender": sender, "chat_id": chat_id, "guid": guid,
                    "text": text, "callsign": "MARLOWE",
                }
                if _pdb.is_replied(guid):
                    pdecision["persona"] = {"skipped": "already_replied"}
                elif not _pdb.try_claim_dispatch(guid):
                    pdecision["persona"] = {"skipped": "claimed_by_other"}
                else:
                    # Deliver to MARLOWE; relay MARLOWE's output (or nothing) to
                    # her thread. ok==True covers both a sent reply AND MARLOWE
                    # deliberately staying silent (send nothing) — both are a
                    # completed handling, so claim the guid. ok==False == a send
                    # failure worth retrying.
                    res = persona.handle(sender or chat_id or "", text)
                    pdecision["persona"] = res
                    if res.get("ok"):
                        _pdb.mark_replied(guid)
                    else:
                        _pdb.mark_error(guid, "persona relay/send failed")
                line_out = json.dumps(pdecision)
                print(line_out, flush=True)
                log.write(line_out + "\n")
                log.flush()
                continue

            hit = router.route(text)
            decision = {
                "ts": time.time(),
                "transport": env.transport,
                "sender": sender,
                "chat_id": chat_id,
                "guid": guid,
                "text": text,
                "callsign": hit.callsign if hit else None,
                "project": hit.session.project_path if hit else None,
                "pid": hit.session.pid if hit else None,
            }

            if hit and ns.dispatch:
                ok_auth, why = transports.authz(env)
                if not ok_auth:
                    decision["blocked_unauthorized_sender"] = True
                    decision["authz_reason"] = why
                    line_out = json.dumps(decision)
                    print(line_out, flush=True)
                    log.write(line_out + "\n")
                    log.flush()
                    continue

            if hit and ns.dispatch:
                inb = disp_mod.InboundMessage(
                    guid=guid, callsign=hit.callsign,
                    sender=sender or None, chat_id=chat_id or None,
                    body=hit.body,
                )
                quiet = cfg_mod.in_quiet_hours(cfg)

                # 👀 READ-RECEIPT (F2) REMOVED 2026-07-01 (Daniel via MARLOWE).
                # The eyes-emoji ACK caused a self-feedback loop (it re-read its
                # own outbound 👀 as a new inbound and ack'd again, ~1/sec, which
                # starved real routing). Per Daniel's direction it is ripped out
                # entirely — no tapback, no reply-with-👀, no ACK reaction. A
                # proper NATIVE tapback read-receipt is reassigned to a macOS/
                # Apple-native specialist. The operator now routes + replies with
                # NO read-ACK indicator.

                if quiet:
                    inbox.append(hit.callsign, {
                        "guid": guid, "sender": sender, "chat_id": chat_id,
                        "body": hit.body, "queued_for_quiet": True,
                    })
                    decision["queued_quiet_hours"] = True
                elif os.environ.get("CALLSIGN_SESSION_AWARE", "1") == "1":
                    # SESSION-AWARE delivery (Daniel 2026-06-25). Deliver the
                    # inbound INTO the agent's own Claude Code session rather than
                    # a stateless headless one-shot:
                    #   PATH A — callsign has a LIVE iTerm session: inject the
                    #     text into that exact session + submit, as if Daniel
                    #     typed it. The agent continues its conversation with full
                    #     context.
                    #   PATH B — no live session: open a NEW iTerm window AS that
                    #     callsign (claude-as --new --prompt) and deliver the
                    #     inbound as the opening prompt.
                    # GATE: both paths load MEMORY.md and run the agent's OWN
                    # politeness gate on the injected text — this is gate-
                    # PRESERVING (unlike the headless `-p` responder, which the
                    # KB notes does NOT enforce the gate). We send nothing back;
                    # the agent answers in its own session via its own tools.
                    # Idempotency: claim the guid so the same inbound isn't
                    # injected twice across daemon restarts / duplicate stream
                    # lines.
                    from callsign import session_inject, processed_db as _pdb
                    _pdb.enqueue(guid, hit.callsign, sender or None,
                                 chat_id or None, hit.body)
                    if _pdb.is_replied(guid):
                        decision["session_aware"] = {"skipped": "already_delivered"}
                    elif not _pdb.try_claim_dispatch(guid):
                        decision["session_aware"] = {"skipped": "claimed_by_other"}
                    else:
                        try:
                            # B2(b): pass the originating chat.db guid + verified
                            # sender so the executor can verify owner identity for
                            # protected-class actions (the relay no longer strips
                            # it). The sender already passed the per-transport
                            # allowlist (authz) above.
                            res = session_inject.deliver(
                                hit.callsign, hit.body,
                                origin_guid=guid,
                                origin_sender=sender or None,
                            )
                            decision["session_aware"] = res
                            if res.get("ok"):
                                _pdb.mark_replied(guid)
                            else:
                                _pdb.mark_error(guid, f"session_inject path {res.get('path')}: {res.get('detail','')[:300]}")
                        except Exception as e:
                            decision["session_aware_error"] = str(e)[:400]
                            _pdb.mark_error(guid, str(e)[:300])
                elif os.environ.get("CALLSIGN_RESPONDER_ENABLED") == "1":
                    # Reply-as-agent: spawn the addressed agent FRESH (no session
                    # resume — MARLOWE's live terminal is untouched), capture its
                    # in-voice reply, send back "NAME: ...". One spawn per
                    # addressed text; gated on the router hit above so the alert
                    # flood never spawns anything.
                    #
                    # OFF BY DEFAULT (opt-in via CALLSIGN_RESPONDER_ENABLED=1).
                    # SECURITY: the politeness gate is NOT enforced in
                    # `claude --agent … -p` headless mode (verified 2026-06-23 —
                    # `claude -p "what is 2+2"` answers "4" with no trigger word).
                    # So enabling this responder = an always-answer channel that
                    # effectively bypasses Daniel's inbound gate. That bypass is
                    # NOT authorized, so the responder stays disabled until Daniel
                    # explicitly authorizes the gate exemption. Until then the
                    # operator still ROUTES, but does not auto-reply.
                    try:
                        result = disp_mod.fire_reply_as_agent(inb, cfg=cfg)
                        decision["dispatch"] = result
                    except Exception as e:
                        decision["dispatch_error"] = str(e)[:400]
                else:
                    decision["responder_disabled"] = "CALLSIGN_RESPONDER_ENABLED!=1 (gate not enforceable in headless -p; awaiting Daniel auth)"

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
    from callsign import router as router_mod
    from callsign.paths import INBOX_DIR

    cfg = cfg_mod.Config.load()
    # Legacy registry sessions (old-style claims) ...
    active = {s.callsign: s for s in registry.list_active()}
    # ... PLUS any callsign with a queued inbox file that resolves to a LIVE
    # project_callsign session (MARLOWE, SHANDIE, ...). The registry is no
    # longer the source of truth for live sessions, so without this the new
    # operator's queued quiet-hours messages would never drain.
    if INBOX_DIR.exists():
        for p in INBOX_DIR.glob("*.jsonl"):
            cs = p.stem
            if cs in active:
                continue
            hit = router_mod.route(f"{cs}, drain")
            if hit and hit.session.session_uid:
                active[cs] = hit.session
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

    a = sub.add_parser("resume", help="resume a live session by its callsign (execs claude --resume <uuid>)")
    a.add_argument("name", help="the callsign you see on screen, e.g. RONIN")
    a.add_argument("--print-id", action="store_true", help="print the session UUID instead of resuming")
    a.set_defaults(func=cmd_resume)

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
