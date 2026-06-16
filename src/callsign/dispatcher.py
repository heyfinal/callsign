"""callsign v0.3 dispatcher — the missing middle.

For every routed inbound iMessage:

    1. enqueue in processed.db (idempotent on guid)
    2. acquire SHORT per-session lock (≤ 2s); skip if already replied
    3. release short lock and run ``claude --resume <UID> --print``, with the
       body piped on STDIN (not argv — avoids E2BIG, control bytes, and shell
       injection)
    4. capture stdout, UTF-8 byte-safe chunk it, send each chunk via
       ``imsg send`` with ``[k/N]`` markers when N > 1
    5. mark dispatched_at, chunks_sent, reply_sent_at

Crash recovery semantics:
    received_at set    only           -> claude never ran, replay from step 3
    dispatched_at set, reply_sent_at  -> claude ran but reply not delivered;
        cannot safely re-run claude (would double-charge + re-mutate session
        state); operator must inspect via `callsign status --stuck`
"""
from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import time
from dataclasses import dataclass

from callsign import alerts, chunking, config as cfg_mod, inbox, locks, processed_db
from callsign.registry import Session
from callsign.paths import DEAD_LETTER_DIR, ensure_dirs


@dataclass(frozen=True)
class InboundMessage:
    guid: str
    callsign: str
    sender: str | None
    chat_id: str | None
    body: str


def _claude_path() -> str:
    return shutil.which("claude") or "/usr/local/bin/claude"


def _imsg_path() -> str:
    return shutil.which("imsg") or "/usr/local/bin/imsg"


def _run_claude(session_uid: str, body: str, timeout: int) -> tuple[int, str, str]:
    """Resume the target session, run one turn, return (rc, stdout, stderr).

    Body goes on STDIN. The claude prompt arg is left empty so the CLI reads
    from stdin. Child runs in its own process group so timeout kills any
    grandchildren too.
    """
    cmd = [_claude_path(), "--resume", session_uid, "--print"]
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,  # new process group
        env={**os.environ, "CALLSIGN_INBOUND": "1"},
    )
    try:
        out, err = proc.communicate(input=body.encode("utf-8"), timeout=timeout)
        return proc.returncode, out.decode("utf-8", errors="replace"), err.decode("utf-8", errors="replace")
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
        try:
            out, err = proc.communicate(timeout=2)
        except subprocess.TimeoutExpired:
            out, err = b"", b""
        return 124, out.decode("utf-8", errors="replace"), err.decode("utf-8", errors="replace") + "\n(killed by dispatcher timeout)"


def _send_imsg(to: str, text: str, service: str | None = None,
               retries: int = 3, backoff: float = 1.5) -> tuple[bool, str]:
    imsg = _imsg_path()
    last_err = ""
    for attempt in range(max(1, retries)):
        try:
            cmd = [imsg, "send", "--to", to, "--text", text]
            if service:
                cmd += ["--service", service]
            proc = subprocess.run(cmd, capture_output=True, timeout=20)
            if proc.returncode == 0:
                return True, ""
            last_err = (proc.stderr or proc.stdout).decode("utf-8", errors="replace")
        except (OSError, subprocess.TimeoutExpired) as e:
            last_err = str(e)
        if attempt + 1 < retries:
            time.sleep(backoff * (attempt + 1))
    return False, last_err


def _dead_letter(msg: InboundMessage, reply: str, err: str) -> None:
    ensure_dirs()
    import json as _json
    DEAD_LETTER_DIR.mkdir(parents=True, exist_ok=True)
    path = DEAD_LETTER_DIR / f"{int(time.time())}-{msg.guid[:12]}.json"
    path.write_text(
        _json.dumps(
            {
                "guid": msg.guid,
                "callsign": msg.callsign,
                "sender": msg.sender,
                "chat_id": msg.chat_id,
                "body": msg.body,
                "reply": reply,
                "error": err,
                "ts": time.time(),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def fire(session: Session, msg: InboundMessage, *, dry_run: bool = False,
         cfg: cfg_mod.Config | None = None) -> dict:
    """Run one inbound message end-to-end. Returns a status dict for caller."""
    cfg = cfg or cfg_mod.Config.load()

    # Step 1 — record arrival (idempotent on guid)
    inbox.append(msg.callsign, {
        "guid": msg.guid, "sender": msg.sender, "chat_id": msg.chat_id,
        "body": msg.body, "received_at": time.time(),
    })
    fresh = processed_db.enqueue(msg.guid, msg.callsign, msg.sender, msg.chat_id, msg.body)

    # Step 2 — short lock for state transitions only
    try:
        with locks.acquire(session.session_uid or msg.callsign, timeout=cfg.lock_wait_short):
            if processed_db.is_replied(msg.guid):
                return {"ok": True, "skipped": "already_replied"}
            existing = processed_db.get(msg.guid)
            if existing and existing.dispatched_at and not existing.reply_sent_at:
                # claude already ran but reply delivery never finished.
                # Do NOT re-run claude (it mutated session state). Operator escalation.
                alerts.alert(
                    "callsign: stuck delivery",
                    f"guid={msg.guid[:12]} callsign={msg.callsign} sender={msg.sender}",
                    kind="stuck_delivery",
                )
                return {"ok": False, "stuck": "dispatched_but_not_replied"}
    except locks.LockTimeout:
        alerts.alert(
            "callsign: lock timeout",
            f"could not acquire state lock for {msg.callsign} within {cfg.lock_wait_short}s",
            kind="lock_timeout",
        )
        return {"ok": False, "error": "lock_timeout"}

    if dry_run:
        # Synthetic reply path for smoke tests / quiet hours
        reply = f"(dry-run reply for guid={msg.guid[:8]})"
        rc = 0
        stderr = ""
    else:
        # Step 3 — claude OUTSIDE the lock
        if not session.session_uid:
            alerts.alert(
                "callsign: no session UID",
                f"callsign {msg.callsign} has no session_uid; cannot resume",
                kind="no_uid",
            )
            processed_db.mark_error(msg.guid, "no session_uid")
            _dead_letter(msg, "", "no session_uid")
            return {"ok": False, "error": "no_session_uid"}

        rc, reply, stderr = _run_claude(session.session_uid, msg.body, timeout=cfg.dispatch_timeout)
        processed_db.mark_dispatched(msg.guid)

        if rc != 0:
            err = f"claude rc={rc} stderr={stderr[:500]}"
            processed_db.mark_error(msg.guid, err)
            _dead_letter(msg, reply, err)
            alerts.alert(
                "callsign: claude resume failed",
                f"{msg.callsign}: rc={rc} — see ~/.callsign/dead-letter/",
                kind="claude_failed",
            )
            return {"ok": False, "error": err, "rc": rc}

    # Step 4 — chunk + send
    to = msg.chat_id or msg.sender
    if not to:
        processed_db.mark_error(msg.guid, "no sender or chat_id")
        _dead_letter(msg, reply, "no sender or chat_id")
        alerts.alert(
            "callsign: no reply-to",
            f"{msg.callsign} reply had nowhere to go; dead-lettered",
            kind="no_recipient",
        )
        return {"ok": False, "error": "no_recipient"}

    cs_prefix = f"{msg.callsign}: "
    chunks = chunking.chunked(
        reply,
        max_bytes=cfg.chunk_size_bytes - len(cs_prefix.encode("utf-8")) - 8,
        with_markers=True,
        id_token=msg.guid[:8],
    ) or [reply or "(empty reply)"]

    sent_ok = 0
    for i, chunk in enumerate(chunks, start=1):
        body = f"{cs_prefix}{chunk}"
        if dry_run:
            print(f"[dry-run send] to={to}: {body[:120]}…", file=sys.stderr)
            sent_ok += 1
            processed_db.mark_chunks(msg.guid, sent_ok, len(chunks))
            continue
        ok, err = _send_imsg(to, body, retries=cfg.retry_imsg_send,
                             backoff=cfg.backoff_initial)
        if not ok:
            processed_db.mark_error(msg.guid, f"imsg send failed: {err[:400]}")
            _dead_letter(msg, reply, f"imsg send failed: {err[:400]}")
            alerts.alert(
                "callsign: imsg send failed",
                f"{msg.callsign} → {to}: {err[:120]}",
                kind="imsg_failed",
            )
            return {"ok": False, "error": "imsg_send_failed", "sent": sent_ok, "total": len(chunks)}
        sent_ok += 1
        processed_db.mark_chunks(msg.guid, sent_ok, len(chunks))

    # Step 5 — done
    processed_db.mark_replied(msg.guid)
    return {"ok": True, "sent": sent_ok, "total": len(chunks)}
