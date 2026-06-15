"""Intro-banner renderer. ASCII + unicode box-drawing only — no emoji."""
from __future__ import annotations

_PLATFORM_LABEL = {
    "claude-code": "Claude Code",
    "claude": "Claude",
    "hermes": "Hermes",
}


def _pretty_platform(platform: str) -> str:
    return _PLATFORM_LABEL.get(platform.lower(), platform)


def awaiting_claim(platform: str = "Claude Code") -> str:
    label = _pretty_platform(platform)
    line1 = "  CALLSIGN ▸ (awaiting your choice)"
    line2 = f"  ⸺ {label} session: pick a name for yourself."
    line3 = "  run:  callsign claim <YourName>"
    line4 = "  see suggestions:  callsign suggest"
    inner = max(len(line1), len(line2), len(line3), len(line4)) + 2
    bar = "━" * (inner + 2)
    return (
        f"\n{bar}\n"
        f"┃{line1.ljust(inner)}┃\n"
        f"┃{line2.ljust(inner)}┃\n"
        f"┃{line3.ljust(inner)}┃\n"
        f"┃{line4.ljust(inner)}┃\n"
        f"{bar}\n"
    )


def intro(callsign: str, platform: str = "Claude Code") -> str:
    name = callsign.upper()
    label = _pretty_platform(platform)
    line1 = f"  CALLSIGN ▸ {name}"
    line2 = f"  ⸺ {label} session reporting in, sir."
    line3 = f"  reply with '{callsign}, ...' to route iMessages here."
    inner = max(len(line1), len(line2), len(line3)) + 2
    bar = "━" * (inner + 2)
    return (
        f"\n{bar}\n"
        f"┃{line1.ljust(inner)}┃\n"
        f"┃{line2.ljust(inner)}┃\n"
        f"┃{line3.ljust(inner)}┃\n"
        f"{bar}\n"
    )


def awaiting_claim_context(platform: str = "Claude Code", suggestions: list[str] | None = None) -> str:
    """The additionalContext block injected when no callsign has been claimed yet.

    Tells the agent: pick your OWN name and run ``callsign claim``.
    """
    sug = ""
    if suggestions:
        sug = (
            "\n\nIf you want examples (not a constraint), here are a few unused "
            f"options: {', '.join(suggestions)}. You may pick any name you like — "
            "single token, 2–20 chars, letters only."
        )
    return (
        "## Callsign — pick your own name\n\n"
        "**This session does not yet have a callsign.** Before doing anything else,\n"
        "choose a single human name for yourself (any name — Frank, Vesper, Maverick,\n"
        "anything that feels right) and claim it by running:\n\n"
        "```bash\n"
        "callsign claim <YourName>\n"
        "```\n\n"
        "Why: daniel runs several Claude/Hermes sessions in parallel and addresses\n"
        "them by name. Your callsign is how he routes messages to *you* specifically.\n\n"
        "Rules:\n\n"
        "- Pick a name you haven't claimed yet — run `callsign list` to see who's\n"
        "  already in use across other sessions.\n"
        "- If `claim` returns `name_taken`, pick a different name and try again.\n"
        "- Don't pick `Brodie` (legacy reserved trigger).\n"
        "- Once claimed, **introduce yourself in chat** with the name you picked\n"
        "  (e.g. `I'll be Frank for this session, sir.`).\n"
        "- For every outbound iMessage, use `callsign send '<text>'` (or\n"
        "  `imsg-callsign '<text>'`). The wrapper auto-prefixes with your name —\n"
        "  **do not restate your name inside the message body**. The prefix carries it.\n"
        "  - Right: `callsign send \"patched and pushed, sir.\"`\n"
        "  - Wrong: `callsign send \"Frank here, patched and pushed.\"`\n"
        f"- Platform: {_pretty_platform(platform)}"
        f"{sug}\n"
    )


def context_block(callsign: str, platform: str = "Claude Code") -> str:
    """Markdown block injected into the session's additionalContext."""
    return (
        f"## Callsign\n\n"
        f"Your callsign for this session is **{callsign}**.\n\n"
        f"- When daniel iMessages `{callsign}, ...` (or `{callsign}:`), "
        f"the message is for you. Other sessions have different names.\n"
        f"- When YOU send daniel an iMessage, route through "
        f"`callsign send '<text>'` (or `imsg-callsign '<text>'`). The wrapper "
        f"automatically prefixes the message with `{callsign}: ` — daniel "
        f"already sees who's speaking from the prefix, so **do not restate "
        f"your name inside the message body**. Write the message body as you "
        f"would speak it, no self-introduction.\n"
        f"  - Right: `callsign send \"patched and pushed, sir.\"`  "
        f"→ daniel sees `{callsign}: patched and pushed, sir.`\n"
        f"  - Wrong: `callsign send \"{callsign} here — patched and pushed.\"` "
        f"→ daniel sees `{callsign}: {callsign} here — patched and pushed.` "
        f"(redundant)\n"
        f"- Platform: {platform}\n"
    )
