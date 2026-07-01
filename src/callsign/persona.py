"""Alicia -> MARLOWE persona relay.

Daniel's routing spec (via MARLOWE, 2026-07-01):
  1. Alicia's iMessage handle is bound DIRECTLY to MARLOWE as its own default
     operator. Every inbound from her handle routes to MARLOWE automatically —
     she NEVER types a "MARLOWE," callsign prefix; bare text from her = MARLOWE.
     She is a human sender, not a machine-alert.
  2. The RESPONSE is produced by the MARLOWE session itself: we deliver her
     message to a MARLOWE (maestro-lane) invocation and relay back EXACTLY what
     MARLOWE emits — which MAY be nothing. We do NOT synthesize a separate
     canned auto-reply.
  3. NO politeness-gate / trigger-word logic lives here or in the router. That
     is a model-side secret applied by the MARLOWE session downstream. Our job
     is only: route her -> MARLOWE, relay MARLOWE's output to her thread. Empty
     output -> send nothing (no error, no placeholder, no "?").
  4. MARLOWE answers as a humanized "Marlowe" (warm, few words, plain), never
     exposes agents/system internals, and Alicia gets ZERO system access
     (conversation only). She never reaches the tool-enabled dispatch /
     session_inject path — the caller routes her here BEFORE the operator
     allowlist, and this module runs MARLOWE with MCP servers stripped.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

_TRANSCRIPT_DIR = Path.home() / ".callsign" / "persona_transcripts"
_HISTORY_TURNS = 6
_MAESTRO_LANE = "maestro"
_DEFAULT_TIMEOUT = 120

# The persona name external humans see. Never the callsign/agent machinery.
PERSONA_NAME = "Marlowe"


def _norm(s: str) -> str:
    """Phones -> last 10 digits; emails -> lowercase-exact. Mirrors cli._norm_sender."""
    s = (s or "").strip().lower()
    digits = "".join(ch for ch in s if ch.isdigit())
    return digits[-10:] if len(digits) >= 10 else s


def persona_senders() -> set[str]:
    """Normalized handle->MARLOWE bindings (conversational-only). Default: Alicia.

    These senders route to MARLOWE and get a persona reply and NOTHING else —
    they never reach dispatch / session_inject / any tool-enabled path.
    """
    raw = os.environ.get("CALLSIGN_PERSONA_SENDERS") or "+19034316755"
    return {_norm(x) for x in raw.split(",") if x.strip()}


def is_persona_sender(sender: str | None) -> bool:
    return bool(sender) and _norm(sender) in persona_senders()


def _transcript_path(sender: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_+@.-]", "_", sender or "unknown")
    return _TRANSCRIPT_DIR / f"{safe}.jsonl"


def recent_history(sender: str) -> str:
    """Last few exchanges, formatted for the delivery preamble (continuity)."""
    p = _transcript_path(sender)
    if not p.exists():
        return ""
    try:
        lines = p.read_text(encoding="utf-8").splitlines()[-_HISTORY_TURNS:]
    except OSError:
        return ""
    parts: list[str] = []
    for ln in lines:
        try:
            e = json.loads(ln)
        except json.JSONDecodeError:
            continue
        if e.get("in"):
            parts.append(f"Alicia: {e['in']}")
        if e.get("out"):
            parts.append(f"Marlowe: {e['out']}")
    return "\n".join(parts)


def record(sender: str, inbound: str, reply: str) -> None:
    try:
        _TRANSCRIPT_DIR.mkdir(parents=True, exist_ok=True)
        with _transcript_path(sender).open("a", encoding="utf-8") as f:
            f.write(json.dumps({"in": inbound, "out": reply}) + "\n")
    except OSError:
        pass


def _claude_bin() -> str:
    p = shutil.which("claude")
    if p:
        return p
    for c in ("/opt/homebrew/bin/claude", f"{os.path.expanduser('~')}/.local/bin/claude",
              "/usr/local/bin/claude"):
        if os.path.exists(c):
            return c
    return "claude"


# Tooling/hook noise that must be stripped from MARLOWE's captured stdout so only
# the message text is relayed. (Mirrors responder._NOISE.)
_NOISE = re.compile(r"(SessionEnd hook|Hook cancelled|_R=|bun-runner|worker-service|"
                    r"^\s*your callsign is\b|^\s*\[callsign\])", re.IGNORECASE)


def _clean(out: str) -> str:
    kept = [ln for ln in out.splitlines() if ln.strip() and not _NOISE.search(ln)]
    return "\n".join(kept).strip()


def _delivery_prompt(text: str, history: str) -> str:
    """Frame Alicia's inbound for the MARLOWE session. Contains NO gate/trigger
    logic — it defers to MARLOWE's own standing rules for whether to answer."""
    hist = f"\nRecent conversation with her:\n{history}\n" if history else ""
    return (
        "An inbound personal iMessage just arrived from Alicia. She is someone "
        "you look after for Daniel — she is not on the team, has no system "
        "access, and this is a personal conversation only.\n"
        f"{hist}"
        "\nReply to her AS Marlowe: warm, plain, everyday words, a few sentences "
        "at most. Never mention or hint at AI, agents, systems, apps, code, "
        "tools, settings, or how anything works — you're simply a person helping "
        "her. If she raises something you can't personally fix, acknowledge it "
        "kindly and tell her you'll get it looked after. Follow your own standing "
        "rules; if those rules mean you should not respond, output nothing at all.\n"
        "\nYour entire output is sent to her verbatim as a text message. Write "
        "ONLY the message text — no preamble, no quotes, no name label, no sign-"
        "off unless it reads naturally.\n"
        f"\nAlicia's message: {text}"
    )


def ask_marlowe(text: str, *, history: str = "",
                timeout: int = _DEFAULT_TIMEOUT) -> tuple[bool, str]:
    """Deliver Alicia's message to a MARLOWE session; return (ok, reply).

    Runs `claude --agent maestro` (MARLOWE's brain + rules) headless, with MCP
    servers stripped (--strict-mcp-config) so the conversation-only reply can't
    reach external tools. Empty output (MARLOWE chose silence, or nothing to
    say) -> (False, "") and the caller sends NOTHING. No gate logic here.
    """
    prompt = _delivery_prompt(text, history)
    cmd = [
        _claude_bin(), "--agent", _MAESTRO_LANE,
        "--strict-mcp-config", "--model", "claude-haiku-4-5",
        "-p", prompt,
    ]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, timeout=timeout,
            env={**os.environ, "CALLSIGN_INBOUND": "1"},
        )
    except (subprocess.TimeoutExpired, OSError):
        return False, ""
    reply = _clean(proc.stdout.decode("utf-8", "replace"))
    if proc.returncode != 0 and not reply:
        return False, ""
    return (bool(reply), reply)


def _imsg_bin() -> str:
    p = shutil.which("imsg")
    if p:
        return p
    for c in ("/opt/homebrew/bin/imsg", f"{os.path.expanduser('~')}/.local/bin/imsg",
              "/usr/local/bin/imsg"):
        if os.path.exists(c):
            return c
    return "imsg"


def send(to: str, text: str, service: str | None = None) -> bool:
    """Send MARLOWE's reply to Alicia's own thread — RAW (no callsign prefix)."""
    if not to or not text:
        return False
    if os.environ.get("CALLSIGN_PERSONA_DRYRUN") == "1":
        return True  # test/inspection: do not actually send
    cmd = [_imsg_bin(), "send", "--to", to, "--text", text]
    if service:
        cmd += ["--service", service]
    try:
        return subprocess.run(cmd, capture_output=True, timeout=25).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def handle(sender: str, text: str) -> dict:
    """Route Alicia's inbound to MARLOWE and relay MARLOWE's output to her thread.

    Sends nothing when MARLOWE emits nothing. Returns a small log dict (no
    secrets, no internals).
    """
    hist = recent_history(sender)
    ok, reply = ask_marlowe(text, history=hist)
    if not ok or not reply:
        # MARLOWE stayed silent / had nothing to say -> send NOTHING.
        return {"persona": True, "ok": True, "sent": False, "silent": True}
    sent = send(sender, reply)
    if sent:
        record(sender, text, reply)
    return {"persona": True, "ok": sent, "sent": sent, "reply": reply[:160]}
