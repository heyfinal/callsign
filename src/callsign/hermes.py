"""Hermes integration.

Hermes agents pick their OWN names too — there is no boot-time auto-assign.
Two-step pattern:

    1. Boot in "awaiting" mode and read the context block::

           from callsign.hermes import HermesCallsign
           ctx = HermesCallsign.awaiting_context()   # inject into system prompt
           print(HermesCallsign.awaiting_banner())   # show on stdout

    2. The agent picks a name and calls::

           cs = HermesCallsign.claim("Vesper", agent_id="lead", project_path=cwd)
           cs.send_imessage("on it, sir.")           # → "Vesper: on it, sir."

For non-interactive Hermes batch jobs that have no agency to pick, fall
back to ``HermesCallsign.boot_auto(...)``, which uses the legacy auto-pick
from ``callsign.assign``.
"""
from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from callsign import banner as _banner
from callsign import names as _names
from callsign import registry


@dataclass(frozen=True)
class HermesCallsign:
    callsign: str
    session_uid: str
    project_path: str | None
    pid: int

    # ---- agent-driven (default) ----------------------------------------------

    @classmethod
    def claim(
        cls,
        name: str,
        agent_id: str,
        project_path: str | Path | None = None,
        pid: int | None = None,
    ) -> "HermesCallsign":
        """Agent picks ``name`` and claims it. Raises on collision / invalid."""
        uid = os.environ.get("HERMES_SESSION_ID") or f"hermes-{agent_id}-{os.getpid()}"
        sess = registry.claim(
            name=name,
            platform="hermes",
            project_path=project_path,
            pid=pid or os.getpid(),
            session_uid=uid,
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

    @staticmethod
    def awaiting_context(suggestions_count: int = 8) -> str:
        taken = {s.callsign for s in registry.list_active()}
        sug = _names.suggest(taken, n=suggestions_count)
        return _banner.awaiting_claim_context(platform="hermes", suggestions=sug)

    @staticmethod
    def awaiting_banner() -> str:
        return _banner.awaiting_claim(platform="hermes")

    # ---- legacy auto-assign (cron / batch only) ------------------------------

    @classmethod
    def boot_auto(
        cls,
        agent_id: str,
        project_path: str | Path | None = None,
        pid: int | None = None,
        preferred: str | None = None,
    ) -> "HermesCallsign":
        """Auto-pick a name. Use for unattended cron / batch only."""
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

    # ---- runtime helpers -----------------------------------------------------

    def banner(self) -> str:
        return _banner.intro(self.callsign, platform="hermes")

    def context_block(self) -> str:
        return _banner.context_block(self.callsign, platform="hermes")

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
