"""Intro-banner renderer. ASCII + unicode box-drawing only — no emoji."""
from __future__ import annotations

_PLATFORM_LABEL = {
    "claude-code": "Claude Code",
    "claude": "Claude",
    "hermes": "Hermes",
}


def _pretty_platform(platform: str) -> str:
    return _PLATFORM_LABEL.get(platform.lower(), platform)


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


def context_block(callsign: str, platform: str = "Claude Code") -> str:
    """Markdown block injected into the session's additionalContext."""
    return (
        f"## Callsign\n\n"
        f"Your callsign for this session is **{callsign}**.\n\n"
        f"- When daniel iMessages `{callsign}, ...` (or `{callsign}:`), "
        f"the message is for you. Other sessions have different names.\n"
        f"- When YOU send daniel an iMessage, prefix it with `{callsign}: ` "
        f"so he knows which session is speaking. Use the `imsg-callsign` "
        f"wrapper or call `callsign send '<text>'`.\n"
        f"- On first contact in a new thread, introduce yourself: "
        f'"{callsign} here, sir."\n'
        f"- Platform: {platform}\n"
    )
