#!/usr/bin/env bash
# Claude Code SessionStart hook: claim a callsign and inject intro context.
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
#
# Reads CLAUDE_SESSION_ID from env when Claude Code provides it; falls back
# to the project working directory so reopening the same project yields the
# same callsign.

set -euo pipefail

CALLSIGN_BIN="${CALLSIGN_BIN:-callsign}"

if ! command -v "${CALLSIGN_BIN}" >/dev/null 2>&1; then
    printf '{"continue":true,"suppressOutput":true}\n'
    exit 0
fi

PROJECT="${CLAUDE_PROJECT_DIR:-$PWD}"
SESSION_UID="${CLAUDE_SESSION_ID:-}"

ASSIGN_JSON="$("${CALLSIGN_BIN}" assign \
    --platform claude-code \
    --project "${PROJECT}" \
    ${SESSION_UID:+--session-uid "${SESSION_UID}"} \
    --json 2>/dev/null || true)"

CALLSIGN_NAME="$(printf '%s' "${ASSIGN_JSON}" | sed -n 's/.*"callsign": *"\([^"]*\)".*/\1/p' || true)"

if [ -z "${CALLSIGN_NAME}" ]; then
    printf '{"continue":true,"suppressOutput":true}\n'
    exit 0
fi

# Banner to stderr so the user sees it in the terminal.
"${CALLSIGN_BIN}" banner --name "${CALLSIGN_NAME}" --platform "Claude Code" >&2 || true

CTX=$(cat <<EOF
## Callsign

Your callsign for this session is **${CALLSIGN_NAME}**.

- When daniel iMessages \`${CALLSIGN_NAME}, ...\` (or \`${CALLSIGN_NAME}:\`), the message is for you. Other Claude/Hermes sessions have different names — if daniel addresses a different callsign, the message is not for you.
- When YOU send daniel an iMessage, route through \`callsign send '<text>'\` (or the \`imsg-callsign\` wrapper). The wrapper automatically prefixes the message with \`${CALLSIGN_NAME}: \`. **Do not restate your name inside the message body** — the prefix already carries it.
  - Right: \`callsign send "patched and pushed, sir."\` → daniel sees \`${CALLSIGN_NAME}: patched and pushed, sir.\`
  - Wrong: \`callsign send "${CALLSIGN_NAME} here — patched and pushed, sir."\` → daniel sees \`${CALLSIGN_NAME}: ${CALLSIGN_NAME} here — patched and pushed, sir.\` (redundant)
- Write iMessage bodies as you would speak them — no self-introduction, no signature.
- Project: ${PROJECT}
EOF
)

# JSON-escape via python (always available on this box).
python3 - "$CTX" <<'PY'
import json, sys
print(json.dumps({"continue": True, "suppressOutput": False, "additionalContext": sys.argv[1]}))
PY
