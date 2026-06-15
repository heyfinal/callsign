#!/usr/bin/env bash
# install.sh — callsign installer / uninstaller (AIO standard).
# Idempotent. Auto-installs deps. Creates a venv. Symlinks launchers.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PREFIX_DATA="${XDG_DATA_HOME:-$HOME/.local/share}/callsign"
PREFIX_BIN="${HOME}/.local/bin"
CALLSIGN_HOME="${CALLSIGN_HOME:-$HOME/.callsign}"
CLAUDE_HOOKS="${HOME}/.claude/hooks"
HOOK_PATH="${CLAUDE_HOOKS}/callsign_session_start.sh"

banner() {
    local title="$1"
    local bar
    bar="$(printf '━%.0s' $(seq 1 56))"
    printf '\n%s\n' "$bar"
    printf '  %s\n' "$title"
    printf '%s\n\n' "$bar"
}

need() {
    if ! command -v "$1" >/dev/null 2>&1; then
        echo "missing: $1" >&2
        return 1
    fi
}

ensure_python() {
    if command -v python3.12 >/dev/null 2>&1; then
        PYBIN="$(command -v python3.12)"
    elif command -v python3.11 >/dev/null 2>&1; then
        PYBIN="$(command -v python3.11)"
    elif command -v python3 >/dev/null 2>&1; then
        PYBIN="$(command -v python3)"
    else
        echo "python3 not found; install Python 3.10+" >&2
        return 1
    fi
}

do_install() {
    banner "CALLSIGN ▸ install"
    need git || true
    ensure_python
    mkdir -p "$PREFIX_DATA" "$PREFIX_BIN" "$CALLSIGN_HOME"/{sessions,inbox,logs} "$CLAUDE_HOOKS"

    if [ ! -d "$PREFIX_DATA/venv" ]; then
        echo "→ creating venv at $PREFIX_DATA/venv"
        "$PYBIN" -m venv "$PREFIX_DATA/venv"
    fi
    "$PREFIX_DATA/venv/bin/pip" install --upgrade pip >/dev/null
    "$PREFIX_DATA/venv/bin/pip" install -e "$REPO_ROOT" >/dev/null

    # Launcher: callsign
    cat >"$PREFIX_BIN/callsign" <<EOF
#!/usr/bin/env bash
exec "$PREFIX_DATA/venv/bin/callsign" "\$@"
EOF
    chmod +x "$PREFIX_BIN/callsign"

    # Launcher: imsg-callsign
    install -m 0755 "$REPO_ROOT/scripts/imsg-callsign" "$PREFIX_BIN/imsg-callsign"

    # Launcher: callsign-router-daemon
    install -m 0755 "$REPO_ROOT/scripts/callsign-router-daemon" "$PREFIX_BIN/callsign-router-daemon"

    # SessionStart hook for Claude Code
    install -m 0755 "$REPO_ROOT/src/callsign/hooks/session_start.sh" "$HOOK_PATH"

    "$PREFIX_BIN/callsign" init >/dev/null
    "$PREFIX_BIN/callsign" --version

    banner "CALLSIGN ▸ ready"
    cat <<EOF
  installed:
    $PREFIX_BIN/callsign
    $PREFIX_BIN/imsg-callsign
    $PREFIX_BIN/callsign-router-daemon
    $HOOK_PATH

  next steps:
    1. Add this hook to ~/.claude/settings.json under "hooks":
       "SessionStart": [{
         "matcher": "startup",
         "hooks": [{ "type": "command",
                     "command": "bash $HOOK_PATH" }]
       }]
    2. Open a new Claude Code session — the banner appears.
    3. (Optional) Run \`callsign-router-daemon &\` to route incoming iMessages.

  uninstall:  $0 --uninstall
EOF
}

do_uninstall() {
    banner "CALLSIGN ▸ uninstall"
    rm -f "$PREFIX_BIN/callsign" "$PREFIX_BIN/imsg-callsign" "$PREFIX_BIN/callsign-router-daemon"
    rm -f "$HOOK_PATH"
    rm -rf "$PREFIX_DATA/venv"
    echo "removed launchers, venv, and Claude Code hook."
    echo "state kept at: $CALLSIGN_HOME  (rm -rf to wipe)"
}

case "${1:-install}" in
    -h|--help)
        echo "usage: $0 [install|--uninstall]"; exit 0;;
    --uninstall|uninstall)
        do_uninstall;;
    install|*)
        do_install;;
esac
