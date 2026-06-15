#!/usr/bin/env bash
# Claude Code Stop hook companion: opportunistically retire the callsign.
# Safe to omit — `callsign assign` reaps dead PIDs automatically.

set -euo pipefail

CALLSIGN_BIN="${CALLSIGN_BIN:-callsign}"
if ! command -v "${CALLSIGN_BIN}" >/dev/null 2>&1; then
    exit 0
fi
if [ -n "${CALLSIGN:-}" ]; then
    "${CALLSIGN_BIN}" retire "${CALLSIGN}" >/dev/null 2>&1 || true
fi
