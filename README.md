# callsign

> **Unique per-session agent names + iMessage routing for Claude Code and Hermes.**
> Every session self-assigns a memorable name at boot. You address a specific session by speaking to it by name. Replies come back signed.

[![ci](https://github.com/heyfinal/callsign/actions/workflows/ci.yml/badge.svg)](https://github.com/heyfinal/callsign/actions/workflows/ci.yml)
[![license](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](pyproject.toml)
[![claude code](https://img.shields.io/badge/claude--code-plugin-7c3aed.svg)](https://docs.claude.com/en/docs/claude-code)
[![hermes](https://img.shields.io/badge/hermes-supported-0ea5e9.svg)](#hermes)

---

## The problem

You run several Claude Code (or Hermes) sessions in parallel — one per project. iMessage replies are your remote control:

> *"Brodie, finish that app."*

But which `Brodie` did you mean? You can't pin a reply to a specific session.

## The fix

At session start, `callsign` tells the model: **pick your own name**. The model chooses (any single human name — `Frank`, `Vesper`, `Maverick`, anything that fits the agent's vibe), claims it through the registry (`callsign claim <name>`), introduces itself in chat, and from then on every outbound iMessage is auto-prefixed with that name.

You address whichever session you want:

```
Frank, push the wellrx fix to staging.
Steven, the flow path isn't working — proceed as you suggested, sir.
```

A leading-name router resolves each message to the right session.

---

## Demo

```
# session boot — the model is told to pick its own name
$ callsign banner
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
┃  CALLSIGN ▸ (awaiting your choice)                 ┃
┃  ⸺ Claude Code session: pick a name for yourself.  ┃
┃  run:  callsign claim <YourName>                   ┃
┃  see suggestions:  callsign suggest                ┃
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# the agent decides on a name (it can pick ANY single human name) and claims it
$ callsign claim Vesper
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
┃  CALLSIGN ▸ VESPER                                  ┃
┃  ⸺ Claude Code session reporting in, sir.           ┃
┃  reply with 'Vesper, ...' to route iMessages here.  ┃
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# from now on every outbound iMessage is signed
$ callsign send "patched and pushed, sir."
# delivers: "Vesper: patched and pushed, sir."

# inbound routing — daniel addresses a specific session by name
$ callsign route "Frank, redeploy the worker"
Frank → /Users/daniel/AI/wellrx_REDESIGN
redeploy the worker

# collisions are rejected cleanly
$ callsign claim Vesper          # from a different session
'Vesper' is already in use by another active session — pick a different name
  some unused suggestions: Maeve, Atlas, Sloane, Knox, Aurora
```

---

## Install

```bash
git clone https://github.com/heyfinal/callsign ~/GIT/callsign
cd ~/GIT/callsign
./install.sh
```

That writes three launchers into `~/.local/bin`:

| binary | role |
|---|---|
| `callsign` | CLI: `assign`, `list`, `lookup`, `retire`, `route`, `send`, `banner`, `router` |
| `imsg-callsign` | drop-in `imsg send` wrapper that auto-prefixes with `$CALLSIGN` |
| `callsign-router-daemon` | long-running incoming-iMessage router (launchd-friendly) |

…plus a SessionStart hook at `~/.claude/hooks/callsign_session_start.sh`.

Wire it into Claude Code by adding to `~/.claude/settings.json`:

```json
{
  "hooks": {
    "SessionStart": [
      {
        "matcher": "startup",
        "hooks": [{
          "type": "command",
          "command": "bash ~/.claude/hooks/callsign_session_start.sh"
        }]
      }
    ]
  }
}
```

Open a new Claude Code session. You'll see the banner and the model will know its name.

Uninstall: `./install.sh --uninstall`.

---

## How the agent talks back

The SessionStart hook tells the model its callsign and instructs it to use `callsign send` (or `imsg-callsign`) for every outbound iMessage. The wrapper prepends `{CALLSIGN}: ` automatically, so the model writes the body naturally — **without restating its own name**:

| right | wrong |
|---|---|
| `callsign send "patched and pushed, sir."` | `callsign send "Frank here — patched and pushed."` |
| daniel sees `Frank: patched and pushed, sir.` | daniel sees `Frank: Frank here — patched and pushed.` (redundant) |

The prefix is the identity. The body is just the message.

## How addressing works

`callsign route` accepts the conventions you'd actually type on a phone:

| message | resolves to |
|---|---|
| `Frank, do X` | Frank |
| `frank: do X` | Frank (case-insensitive) |
| `FRANK do X` | Frank (single space delimiter) |
| `Frank — do X` | Frank (em/en dash) |
| `Hey Frank, do X` | Frank (single honorific stripped) |
| `do X` | no hit → falls back to the lead session |

The matcher only fires for names that are actually registered as **active** in the registry, so common words don't accidentally route.

---

## Architecture

```
                     ┌────────────────────────────┐
                     │  ~/.callsign/registry.db   │  ◀── single source of truth
                     │   (SQLite, WAL, NOCASE)    │       across all sessions
                     └─────────────┬──────────────┘
                                   │
   ┌──────────────────┬────────────┼────────────┬──────────────────┐
   ▼                  ▼            ▼            ▼                  ▼
 SessionStart       callsign   imsg-callsign   callsign         callsign.hermes
 hook (bash)        CLI         (send wrap)   router daemon     (Python module)
   │                                            │
   │ banner + ctx                               │ imsg watch ──► route ──► log
   ▼                                            ▼
 Claude Code                                  decisions
 session                                      stream
```

Design choices:

- **No daemon required for the core.** Assign / send / route are pure CLI calls against SQLite. The router daemon is optional — it only exists to *log* incoming routing decisions and surface them to the right session.
- **WAL mode + UNIQUE constraint** → assignment is concurrency-safe across simultaneous sessions.
- **Project-stable callsigns.** Reopening the same project gives you the same callsign (until the PID dies). Disable with `--ephemeral`.
- **Dead-PID reaper** runs on every `assign` and `list`, so the pool never leaks.
- **No emojis in agent output.** Banner uses unicode box-drawing only.

---

## Hermes

```python
from callsign.hermes import HermesCallsign

# 1. inject the "pick your own name" context into the agent's system prompt
system_prompt += "\n\n" + HermesCallsign.awaiting_context()

# 2. the agent picks a name and claims it
cs = HermesCallsign.claim("Vesper", agent_id="lead", project_path="/srv/wellrx")
print(cs.banner())                # log on stdout
cs.send_imessage("on it, sir.")   # → "Vesper: on it, sir."

# unattended cron/batch jobs that can't pick can fall back to auto-assign
cs = HermesCallsign.boot_auto(agent_id="nightly", project_path="/srv/wellrx")
```

Same registry, same name pool, same routing semantics.

---

## CLI reference

```
callsign claim    NAME [--platform P] [--project DIR] [--session-uid UID]
                  [--json|--quiet]
                  # PRIMARY path — agent picks its own name and claims it
callsign suggest  [-n COUNT] [--json]
                  # list a few unused example names (NOT a constraint)
callsign assign   [--platform P] [--project DIR] [--session-uid UID]
                  [--preferred NAME] [--ephemeral] [--json|--quiet]
                  # legacy auto-pick — for unattended cron/batch only
callsign list     [--json]
callsign lookup   NAME [--json]
callsign retire   NAME
callsign route    "TEXT" [--json]
callsign banner   [--name NAME] [--platform P]
callsign send     "TEXT" [--callsign N] [--to PHONE] [--service S]
                  [--no-prefix] [--dry-run]
callsign names    [--json]
callsign router                # consume `imsg watch --json` from stdin
callsign init                  # create ~/.callsign dirs
```

Environment knobs:

- `CALLSIGN` — current session's name (set by the hook)
- `CALLSIGN_PLATFORM` — `claude-code` | `hermes` | …
- `CALLSIGN_HOME` — override registry root (default `~/.callsign`)
- `CALLSIGN_DEFAULT_TO` — default iMessage recipient
- `CLAUDE_SESSION_ID` / `HERMES_SESSION_ID` — used as the idempotency key

---

## Names

Names are NOT preset. **Each agent picks its own name** at session start by running `callsign claim <name>`. The only constraints are:

- single token, 2–20 chars, letters (plus optional `-` or `'`)
- must not already be claimed by an active session
- a small reserved set (currently `Brodie`, `all`, `any`, `none`, `default`)

`callsign suggest` returns a handful of unused example names from a curated 180+ mixed-gender pool (`src/callsign/names.py`) for agents that want inspiration — these are *suggestions, not a constraint*. An agent is free to pick any name that passes validation.

---

## Roadmap

- [ ] launchd plist for `callsign-router-daemon` (ship as `~/.callsign/com.heyfinal.callsign-router.plist`).
- [ ] Per-session inbox files so the router can stage messages for sessions that aren't watching the iMessage stream directly.
- [ ] Optional MCP server form (`mcp__callsign__*`) for hosts that prefer MCP over CLI.
- [ ] Web dashboard at `:5151` showing live session map (opt-in).

PRs welcome.

---

## License

MIT — see [LICENSE](LICENSE).
