"""End-to-end smoke tests using a temp $CALLSIGN_HOME."""
from __future__ import annotations

import os
import tempfile
import importlib
from pathlib import Path


def _reload_with_home(home: Path):
    os.environ["CALLSIGN_HOME"] = str(home)
    import callsign.paths as paths
    importlib.reload(paths)
    import callsign.registry as registry
    importlib.reload(registry)
    import callsign.router as router
    importlib.reload(router)
    return registry, router


def test_assign_returns_name_and_persists():
    with tempfile.TemporaryDirectory() as td:
        registry, _ = _reload_with_home(Path(td))
        s = registry.assign(platform="test", project_path=td,
                            pid=os.getpid(), session_uid="uid-A")
        assert s.callsign
        assert s.status == "active"
        active = registry.list_active()
        assert any(x.callsign == s.callsign for x in active)


def test_assign_is_idempotent_for_session_uid():
    with tempfile.TemporaryDirectory() as td:
        registry, _ = _reload_with_home(Path(td))
        a = registry.assign(platform="test", project_path=td,
                            pid=os.getpid(), session_uid="uid-B")
        b = registry.assign(platform="test", project_path=td,
                            pid=os.getpid(), session_uid="uid-B")
        assert a.callsign == b.callsign


def test_assign_does_not_collide_across_sessions():
    with tempfile.TemporaryDirectory() as td:
        registry, _ = _reload_with_home(Path(td))
        seen = set()
        for i in range(10):
            s = registry.assign(platform="test",
                                project_path=f"{td}/p{i}",
                                pid=os.getpid(),
                                session_uid=f"uid-{i}")
            assert s.callsign not in seen
            seen.add(s.callsign)


def test_router_parses_common_addressings():
    with tempfile.TemporaryDirectory() as td:
        registry, router = _reload_with_home(Path(td))
        s = registry.assign(platform="test", project_path=td,
                            pid=os.getpid(), session_uid="uid-R",
                            preferred="Frank")
        assert s.callsign == "Frank"

        for msg, expected_body in [
            ("Frank, do the thing", "do the thing"),
            ("frank: do the thing", "do the thing"),
            ("FRANK do the thing", "do the thing"),
            ("Hey Frank, do the thing", "do the thing"),
            ("Frank — do the thing", "do the thing"),
        ]:
            hit = router.route(msg)
            assert hit is not None, f"no match for: {msg!r}"
            assert hit.callsign == "Frank"
            assert hit.body == expected_body

        assert router.route("just some text") is None
        assert router.route("Nobody, do the thing") is None


def test_retire_marks_inactive():
    with tempfile.TemporaryDirectory() as td:
        registry, _ = _reload_with_home(Path(td))
        s = registry.assign(platform="test", project_path=td,
                            pid=os.getpid(), session_uid="uid-X",
                            preferred="Steven")
        assert s.callsign == "Steven"
        assert registry.retire("Steven") is True
        assert registry.lookup("Steven").status == "retired"
