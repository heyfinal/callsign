#!/usr/bin/env bash
# install_launchd.sh — generate + load the two callsign LaunchAgents:
#
#   com.callsign.router         — long-running router/dispatcher daemon
#   com.callsign.morning-drain  — wakes the Mac at 06:00 to drain quiet-hours
#
# Generates plists with ABSOLUTE paths (launchd does NOT expand `~`).
# Idempotent: bootout any prior instance, then bootstrap fresh.

set -uo pipefail

USER_NAME="$(id -un)"
USER_UID="$(id -u)"
HOME_DIR="${HOME}"
ROOT="${HOME_DIR}/.callsign"
LOG_DIR="${ROOT}/logs"
AGENTS_DIR="${HOME_DIR}/Library/LaunchAgents"
mkdir -p "${AGENTS_DIR}" "${LOG_DIR}"
chmod 700 "${ROOT}" 2>/dev/null || true

CALLSIGN_BIN="$(command -v callsign || true)"
[ -z "${CALLSIGN_BIN}" ] && CALLSIGN_BIN="${HOME_DIR}/.local/bin/callsign"
ROUTER_DAEMON="${HOME_DIR}/.local/share/callsign/venv/bin/callsign-router-daemon"
if [ ! -x "${ROUTER_DAEMON}" ]; then
    # Fallback to the source tree script (if running pre-install).
    ROUTER_DAEMON="${HOME_DIR}/GIT/callsign/scripts/callsign-router-daemon"
fi

if [ ! -x "${CALLSIGN_BIN}" ]; then
    echo "FATAL: callsign CLI not found at ${CALLSIGN_BIN}" >&2
    exit 1
fi
if [ ! -x "${ROUTER_DAEMON}" ]; then
    echo "FATAL: callsign-router-daemon not found at ${ROUTER_DAEMON}" >&2
    exit 1
fi

PATH_HEADER="${HOME_DIR}/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"

ROUTER_PLIST="${AGENTS_DIR}/com.callsign.router.plist"
DRAIN_PLIST="${AGENTS_DIR}/com.callsign.morning-drain.plist"

cat > "${ROUTER_PLIST}" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.callsign.router</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>${ROUTER_DAEMON}</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <dict>
        <key>SuccessfulExit</key>
        <false/>
        <key>Crashed</key>
        <true/>
    </dict>
    <key>StandardOutPath</key>
    <string>${LOG_DIR}/router.stdout</string>
    <key>StandardErrorPath</key>
    <string>${LOG_DIR}/router.stderr</string>
    <key>WorkingDirectory</key>
    <string>${HOME_DIR}</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>${PATH_HEADER}</string>
        <key>HOME</key>
        <string>${HOME_DIR}</string>
    </dict>
    <key>ProcessType</key>
    <string>Background</string>
</dict>
</plist>
EOF

cat > "${DRAIN_PLIST}" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.callsign.morning-drain</string>
    <key>ProgramArguments</key>
    <array>
        <string>${CALLSIGN_BIN}</string>
        <string>drain</string>
    </array>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>6</integer>
        <key>Minute</key>
        <integer>0</integer>
    </dict>
    <key>StandardOutPath</key>
    <string>${LOG_DIR}/drain.stdout</string>
    <key>StandardErrorPath</key>
    <string>${LOG_DIR}/drain.stderr</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>${PATH_HEADER}</string>
        <key>HOME</key>
        <string>${HOME_DIR}</string>
    </dict>
</dict>
</plist>
EOF

# Configure pmset so the Mac wakes from sleep at 06:00 to fire the drain job.
# Best-effort — requires authorization; fall back to a warning instead of fatal.
if command -v sudo >/dev/null 2>&1; then
    if security find-generic-password -a daniel -s claude-sudo -w >/dev/null 2>&1; then
        SUDO_PW="$(security find-generic-password -a daniel -s claude-sudo -w 2>/dev/null)"
        echo "${SUDO_PW}" | sudo -S pmset repeat wakeorpoweron MTWRFSU 05:58:00 \
            >/dev/null 2>&1 && echo "pmset: scheduled daily wake at 05:58" \
            || echo "pmset: wake schedule failed (set manually via Energy Saver)"
    else
        echo "pmset: skipped — no Keychain sudo entry; set manually:"
        echo "    sudo pmset repeat wakeorpoweron MTWRFSU 05:58:00"
    fi
fi

# (re)load both agents.
for plist in "${ROUTER_PLIST}" "${DRAIN_PLIST}"; do
    label="$(basename "${plist}" .plist)"
    launchctl bootout "gui/${USER_UID}/${label}" >/dev/null 2>&1 || true
    launchctl bootstrap "gui/${USER_UID}" "${plist}" \
        && echo "loaded: ${label}" \
        || echo "FAILED to load: ${label} (check ${LOG_DIR}/*.stderr)"
done

launchctl enable "gui/${USER_UID}/com.callsign.router" 2>/dev/null || true
launchctl enable "gui/${USER_UID}/com.callsign.morning-drain" 2>/dev/null || true

echo
echo "callsign launchd installed."
echo "    router plist:    ${ROUTER_PLIST}"
echo "    drain  plist:    ${DRAIN_PLIST}"
echo "    daemon script:   ${ROUTER_DAEMON}"
echo "    logs:            ${LOG_DIR}/"
echo
echo "Verify: callsign status"
echo "Unload: launchctl bootout gui/${USER_UID}/com.callsign.router"
