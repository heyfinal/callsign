---
name: callsign
description: Inspect or manage agent callsigns for this and other sessions.
---

When the user types `/callsign`, run `callsign list` and summarise the
result. If they pass an argument:

- `/callsign list`        → `callsign list`
- `/callsign who`         → echo `$CALLSIGN`
- `/callsign retire NAME` → `callsign retire NAME`
- `/callsign send TEXT`   → `callsign send "TEXT"`
- `/callsign route TEXT`  → `callsign route "TEXT"`

Report results plainly. Do not chain other tools unless the user asked.
