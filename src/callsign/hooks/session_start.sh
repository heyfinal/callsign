#!/usr/bin/env bash
# Claude Code SessionStart hook: DOES NOT auto-assign a callsign.
#
# Instead, it tells the agent — in additionalContext — to pick its own
# name and claim it via `callsign claim <name>`. This keeps name choice
# in the agent's hands rather than imposing one from a fixed list.
#
# Wire into ~/.claude/settings.json:
#
#   "hooks": {
#     "SessionStart": [
#       { "matcher": "startup",
#         "hooks": [{ "type": "command",
#                     "command": "bash ~/.claude/hooks/callsign_session_start.sh" }] }
#     ]
#   }

set -euo pipefail

CALLSIGN_BIN="${CALLSIGN_BIN:-callsign}"

if ! command -v "${CALLSIGN_BIN}" >/dev/null 2>&1; then
    printf '{"continue":true,"suppressOutput":true}\n'
    exit 0
fi

PROJECT="${CLAUDE_PROJECT_DIR:-$PWD}"
SESSION_UID="${CLAUDE_SESSION_ID:-}"

# Did this session already claim a callsign in a prior turn?
EXISTING_JSON=""
if [ -n "${SESSION_UID}" ]; then
    EXISTING_JSON="$("${CALLSIGN_BIN}" list --json 2>/dev/null || true)"
fi
EXISTING_NAME="$(printf '%s' "${EXISTING_JSON}" | python3 - "${SESSION_UID}" "${PROJECT}" <<'PY' || true
import json, sys
uid = sys.argv[1] if len(sys.argv) > 1 else ""
proj = sys.argv[2] if len(sys.argv) > 2 else ""
try:
    rows = json.loads(sys.stdin.read() or "[]")
except Exception:
    rows = []
for r in rows:
    if uid and r.get("session_uid") == uid:
        print(r["callsign"]); break
    if proj and r.get("project_path") == proj:
        print(r["callsign"]); break
PY
)"

# Banner to stderr so daniel sees what state the session is in.
if [ -n "${EXISTING_NAME}" ]; then
    "${CALLSIGN_BIN}" banner --name "${EXISTING_NAME}" --platform "Claude Code" >&2 || true
else
    "${CALLSIGN_BIN}" banner --platform "Claude Code" >&2 || true
fi

# Build additionalContext for the model.
python3 - "${EXISTING_NAME}" "${PROJECT}" <<'PY'
import json, sys, subprocess
existing = sys.argv[1]
project = sys.argv[2]

if existing:
    body = (
        f"## Callsign\n\n"
        f"Your callsign for this session is **{existing}** (claimed previously).\n\n"
        f"- When daniel iMessages `{existing}, ...` (or `{existing}:`), the message is for you.\n"
        f"- Send iMessages with `callsign send '<text>'` — auto-prefixed with `{existing}: `.\n"
        f"- **Do not restate your name inside the message body** — the prefix carries it.\n"
        f"- Project: {project}\n"
    )
else:
    try:
        sug_raw = subprocess.run(
            ["callsign", "suggest", "--json", "-n", "8"],
            capture_output=True, text=True, timeout=3,
        ).stdout
        suggestions = json.loads(sug_raw or "{}").get("suggestions", [])
    except Exception:
        suggestions = []
    sug_line = ""
    if suggestions:
        sug_line = (
            "\n\nIf you'd like inspiration (not a constraint), some unused "
            f"options right now: {', '.join(suggestions)}. You may pick anything — "
            "single token, 2-20 chars, letters only."
        )
    body = (
        "## Callsign — pick your own name\n\n"
        "**This session does not yet have a callsign.** Before doing anything else,\n"
        "choose a single human name for yourself (any name you like — Frank, Vesper,\n"
        "Maverick, anything that fits) and claim it by running:\n\n"
        "```bash\n"
        "callsign claim <YourName>\n"
        "```\n\n"
        "Why: daniel runs several Claude/Hermes sessions in parallel and addresses\n"
        "them by name. Your callsign is how he routes messages to *you* specifically.\n\n"
        "Rules:\n\n"
        "- Pick a name not already in use — run `callsign list` to see what's taken.\n"
        "- If `claim` returns `name_taken`, pick a different name and retry.\n"
        "- Don't pick `Brodie` (legacy reserved trigger).\n"
        "- Once claimed, introduce yourself in chat with the name you picked\n"
        "  (e.g. \"I'll be Frank for this session, sir.\").\n"
        "- For every outbound iMessage use `callsign send '<text>'` (or `imsg-callsign`).\n"
        "  The wrapper auto-prefixes with your name — **do not restate your name\n"
        "  inside the message body**. The prefix already carries it.\n"
        "  - Right: `callsign send \"patched and pushed, sir.\"`\n"
        "  - Wrong: `callsign send \"Frank here, patched and pushed.\"`\n"
        f"- Project: {project}"
        f"{sug_line}\n"
    )

print(json.dumps({
    "continue": True,
    "suppressOutput": False,
    "additionalContext": body,
}))
PY
