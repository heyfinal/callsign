"""Hermes integration shim.

Hermes agents import this at boot to claim a callsign and learn how to
sign their iMessage replies. Mirrors the Claude Code SessionStart hook.

Typical use inside a Hermes agent::

    from callsign.hermes import HermesCallsign

    cs = HermesCallsign.boot(agent_id="lead", project_path=cwd)
    print(cs.banner())               # logged to console
    cs.send_imessage("on it, sir.")  # auto-prefixed with the callsign
"""
from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from callsign import banner as _banner
from callsign import registry


@dataclass(frozen=True)
class HermesCallsign:
    callsign: str
    session_uid: str
    project_path: str | None
    pid: int

    @classmethod
    def boot(
        cls,
        agent_id: str,
        project_path: str | Path | None = None,
        pid: int | None = None,
        preferred: str | None = None,
    ) -> "HermesCallsign":
        uid = os.environ.get("HERMES_SESSION_ID") or f"hermes-{agent_id}-{os.getpid()}"
        sess = registry.assign(
            platform="hermes",
            project_path=project_path,
            pid=pid or os.getpid(),
            session_uid=uid,
            preferred=preferred,
            env={"agent_id": agent_id},
        )
        os.environ["CALLSIGN"] = sess.callsign
        os.environ["CALLSIGN_PLATFORM"] = "hermes"
        return cls(
            callsign=sess.callsign,
            session_uid=uid,
            project_path=sess.project_path,
            pid=sess.pid or os.getpid(),
        )

    def banner(self) -> str:
        return _banner.intro(self.callsign, platform="Hermes")

    def context_block(self) -> str:
        return _banner.context_block(self.callsign, platform="Hermes")

    def prefix(self, text: str) -> str:
        return f"{self.callsign}: {text}"

    def send_imessage(
        self,
        text: str,
        to: str | None = None,
        service: str | None = None,
    ) -> int:
        target = to or os.environ.get("CALLSIGN_DEFAULT_TO") or "+14053151310"
        cmd = ["imsg", "send", "--to", target, "--text", self.prefix(text)]
        if service:
            cmd += ["--service", service]
        return subprocess.run(cmd).returncode

    def heartbeat(self) -> None:
        registry.heartbeat(self.callsign)

    def retire(self) -> None:
        registry.retire(self.callsign)
