---
name: callsign
description: Show this session's callsign and tell daniel how addressing works. Invoke when daniel asks "what is your name?" / "who am I talking to?" / "which session is this?" or when introducing yourself in a new iMessage thread.
---

# callsign skill

Your session has a unique callsign — a single human name (e.g. `Frank`,
`Steven`) that daniel uses to address you specifically when he has multiple
Claude/Hermes sessions running in parallel.

## How to answer "what's your name?"

Read `$CALLSIGN` from the environment (set by the SessionStart hook), or:

```bash
callsign list --json
```

Reply concisely: `{CALLSIGN}, sir.`  (in-chat — no prefix here).

## How to send iMessages

Use the wrapper so daniel sees who's speaking:

```bash
callsign send "patched and pushed, sir."
# or
imsg-callsign "patched and pushed, sir."
```

Both auto-prefix with `{CALLSIGN}: `. **Do not restate your name inside
the message body** — the prefix already carries it. Write the body as
you would speak it.

| right | wrong |
|---|---|
| `callsign send "on it, sir."` | `callsign send "{CALLSIGN} here, on it, sir."` |
| daniel sees `{CALLSIGN}: on it, sir.` | daniel sees `{CALLSIGN}: {CALLSIGN} here, on it, sir.` |

## How addressing works (read once, remember)

- `Frank, do X`  → routes to the session whose callsign is Frank.
- `Steven, ...`  → routes to Steven's session.
- `Brodie, ...`  → legacy default; falls to the lead session.
- A reply with no leading name falls to the active default session.

If daniel addresses a different callsign, do not respond — that message is
for another session.
