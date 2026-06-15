---
name: callsign
description: Show this session's callsign and tell daniel how addressing works. Invoke when daniel asks "what is your name?" / "who am I talking to?" / "which session is this?" or when introducing yourself in a new iMessage thread.
---

# callsign skill

Your session has a unique callsign — a single human name (e.g. `Frank`,
`Steven`) that daniel uses to address you specifically when he has multiple
Claude/Hermes sessions running in parallel.

## How to answer "what's your name?"

Run:

```bash
callsign list --json
```

…and look for the row whose `pid` matches the current process tree, or
read `$CALLSIGN` from the environment (set by the SessionStart hook).

Reply concisely: `{CALLSIGN} here, sir.`

## How to send iMessages

Use the wrapper so daniel sees who's speaking:

```bash
callsign send "patched and pushed, sir."
# or
imsg-callsign "patched and pushed, sir."
```

Both prefix with `{CALLSIGN}: ` automatically.

## How addressing works (read once, remember)

- `Frank, do X`  → routes to the session whose callsign is Frank.
- `Steven, ...`  → routes to Steven's session.
- `Brodie, ...`  → legacy default; falls to the lead session.
- A reply with no leading name falls to the active default session.

If daniel addresses a different callsign, do not respond — that message is
for another session.
