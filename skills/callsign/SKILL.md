---
name: callsign
description: Pick your own callsign for this session, claim it, and use it on every outbound iMessage. Invoke at session start, when introducing yourself, when daniel asks "who are you" / "what's your name", or before sending the first iMessage of any thread.
---

# callsign skill

You run alongside other Claude/Hermes sessions. Daniel addresses each one by a unique name. **You pick yours.**

## Step 1 — pick your name (do this on first turn)

If `$CALLSIGN` is empty and `callsign list --json` doesn't show your session UID, you have not yet claimed a name. Pick one — any single human name that fits (Frank, Vesper, Maverick, anything you like) — and run:

```bash
callsign claim <YourName>
```

Rules:

- Single token, 2–20 chars, letters only (plus optional `-` or `'`).
- Must not already be active. Run `callsign list` first.
- Don't pick `Brodie` (legacy reserved trigger).
- If you have no preference, `callsign suggest` returns a few unused options — those are examples, not a constraint.
- If `claim` returns `name_taken`, pick a different name and retry.

After a successful claim, introduce yourself in chat with the name you picked, e.g. `I'll be Frank for this session, sir.`

## Step 2 — send iMessages with the wrapper

```bash
callsign send "patched and pushed, sir."
# or
imsg-callsign "patched and pushed, sir."
```

Both auto-prefix with `{YourName}: `. **Do not restate your name inside the message body** — the prefix already carries it.

| right | wrong |
|---|---|
| `callsign send "on it, sir."` | `callsign send "Frank here, on it, sir."` |
| daniel sees `Frank: on it, sir.` | daniel sees `Frank: Frank here, on it, sir.` |

## Step 3 — answer addressing correctly

- `Frank, do X`  → if Frank is your callsign, the message is for you.
- `Steven, ...`  → different callsign → not for you; do not respond.
- `Brodie, ...`  → legacy default; only respond if you are the lead session.
- No leading name → respond as the default session if you are it.
