"""End-to-end smoke tests using a temp $CALLSIGN_HOME."""
from __future__ import annotations

import os
import tempfile
import importlib
from pathlib import Path

import pytest


def _reload_with_home(home: Path):
    os.environ["CALLSIGN_HOME"] = str(home)
    import callsign.paths as paths
    importlib.reload(paths)
    import callsign.registry as registry
    importlib.reload(registry)
    import callsign.router as router
    importlib.reload(router)
    return registry, router


def test_claim_returns_chosen_name():
    with tempfile.TemporaryDirectory() as td:
        registry, _ = _reload_with_home(Path(td))
        s = registry.claim(name="Vesper", platform="test",
                           project_path=td, pid=os.getpid(),
                           session_uid="uid-A")
        assert s.callsign == "Vesper"
        assert s.status == "active"


def test_claim_is_idempotent_for_same_session():
    with tempfile.TemporaryDirectory() as td:
        registry, _ = _reload_with_home(Path(td))
        a = registry.claim(name="Maverick", platform="test",
                           project_path=td, pid=os.getpid(),
                           session_uid="uid-B")
        b = registry.claim(name="Maverick", platform="test",
                           project_path=td, pid=os.getpid(),
                           session_uid="uid-B")
        assert a.callsign == b.callsign == "Maverick"


def test_claim_collision_raises_name_taken():
    with tempfile.TemporaryDirectory() as td:
        registry, _ = _reload_with_home(Path(td))
        registry.claim(name="Frank", platform="test",
                       project_path=td, pid=os.getpid(),
                       session_uid="uid-C")
        with pytest.raises(registry.NameTakenError):
            registry.claim(name="frank", platform="test",
                           project_path=f"{td}/other", pid=os.getpid(),
                           session_uid="uid-D")


def test_claim_rejects_invalid_names():
    with tempfile.TemporaryDirectory() as td:
        registry, _ = _reload_with_home(Path(td))
        for bad in ("", "x", "with space", "Brodie", "name!", "a" * 25):
            with pytest.raises(registry.InvalidNameError):
                registry.claim(name=bad, platform="test",
                               project_path=td, pid=os.getpid(),
                               session_uid=f"uid-{bad}")


def test_rename_via_claim_retires_old_name():
    with tempfile.TemporaryDirectory() as td:
        registry, _ = _reload_with_home(Path(td))
        registry.claim(name="Frank", platform="test",
                       project_path=td, pid=os.getpid(),
                       session_uid="uid-E")
        s = registry.claim(name="Vesper", platform="test",
                           project_path=td, pid=os.getpid(),
                           session_uid="uid-E")
        assert s.callsign == "Vesper"
        old = registry.lookup("Frank")
        assert old.status == "retired"


def test_lookup_by_session_uid():
    with tempfile.TemporaryDirectory() as td:
        registry, _ = _reload_with_home(Path(td))
        registry.claim(name="Sloane", platform="test",
                       project_path=td, pid=os.getpid(),
                       session_uid="uid-F")
        s = registry.lookup_by_session_uid("uid-F")
        assert s is not None and s.callsign == "Sloane"


def test_router_parses_common_addressings():
    with tempfile.TemporaryDirectory() as td:
        registry, router = _reload_with_home(Path(td))
        registry.claim(name="Frank", platform="test", project_path=td,
                       pid=os.getpid(), session_uid="uid-R")
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


def test_names_pool_is_mixed_gender_and_large():
    from callsign import names
    importlib.reload(names)
    assert len(names.SUGGESTION_POOL) > 100
    assert len(names._MALE) > 50
    assert len(names._FEMALE) > 50


def test_suggest_returns_unused_names():
    with tempfile.TemporaryDirectory() as td:
        registry, _ = _reload_with_home(Path(td))
        from callsign import names
        importlib.reload(names)
        registry.claim(name="Frank", platform="test", project_path=td,
                       pid=os.getpid(), session_uid="uid-S")
        taken = {s.callsign for s in registry.list_active()}
        suggs = names.suggest(taken, n=5)
        assert len(suggs) == 5
        assert "Frank" not in suggs
