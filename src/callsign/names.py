"""Optional suggestion pool — agents pick their OWN names by default.

The pool is NOT a constraint. `callsign claim <anyname>` accepts any
valid single-token name (validated by ``is_valid_name``). The pool only
backs the ``callsign suggest`` command, which surfaces a few unused
examples when an agent asks "what should I be called?".
"""
from __future__ import annotations

import hashlib
import random
import re
from typing import Iterable

# Single token, 2-20 chars, alphabetic + apostrophe + hyphen.
_VALID_NAME = re.compile(r"^[A-Za-z][A-Za-z\-']{1,19}$")

# Names reserved by convention (legacy trigger words / pool keywords).
RESERVED: frozenset[str] = frozenset({"brodie", "all", "any", "none", "default"})


def is_valid_name(name: str) -> tuple[bool, str]:
    """Return (ok, reason). reason is empty when ok."""
    if not name:
        return False, "name is empty"
    if len(name) < 2:
        return False, "name must be at least 2 characters"
    if len(name) > 20:
        return False, "name must be 20 characters or fewer"
    if not _VALID_NAME.match(name):
        return False, "name must be letters (plus optional - or '), starting with a letter"
    if name.lower() in RESERVED:
        return False, f"'{name}' is reserved — pick a different name"
    return True, ""


# Mixed-gender suggestion pool. Sizes balanced ~50/50 with a unisex band.
# These are SUGGESTIONS — agents may pick anything that passes is_valid_name.
_MALE: tuple[str, ...] = (
    "Atlas", "Axel", "Beck", "Bishop", "Boone", "Brody", "Cassius",
    "Cole", "Cyrus", "Dane", "Dash", "Dean", "Diego", "Drake",
    "Easton", "Enzo", "Felix", "Finn", "Ford", "Frank", "Gage",
    "Grayson", "Harlan", "Hayes", "Hugo", "Ian", "Ivar", "Jasper",
    "Jude", "Kade", "Knox", "Leon", "Levi", "Locke", "Maverick",
    "Marcus", "Mason", "Miles", "Nash", "Niko", "Otto", "Owen",
    "Pax", "Pierce", "Quincy", "Reid", "Remy", "Roman", "Ryker",
    "Silas", "Steven", "Tanner", "Tate", "Thane", "Vance", "Vaughn",
    "Victor", "Wade", "Wesley", "Wolfe", "Wyatt", "Xander", "Zane",
    "Zeke", "Archer", "Briggs", "Donovan", "Elias", "Garrett",
    "Holden", "Killian", "Magnus", "Orson", "Sullivan", "Vincent",
    "Warren", "Asher", "Cassian", "Emmett", "Foster", "Griffin",
    "Hendrix", "Jonas", "Maddox", "Nolan", "Oscar",
)

_FEMALE: tuple[str, ...] = (
    "Ada", "Anya", "Aria", "Aurora", "Ava", "Beatrix", "Briar",
    "Bryn", "Camille", "Cassia", "Celeste", "Clara", "Cleo", "Cora",
    "Daphne", "Delia", "Edie", "Elara", "Elise", "Eloise", "Esme",
    "Faye", "Fiona", "Flora", "Freya", "Gemma", "Greta", "Hana",
    "Hazel", "Hera", "Imogen", "Iris", "Isla", "Ivy", "Jade",
    "Jane", "Juno", "Kira", "Lark", "Laurel", "Layla", "Lena",
    "Lila", "Liv", "Lottie", "Luna", "Lyra", "Maeve", "Margot",
    "Marina", "Maya", "Mira", "Nadia", "Nina", "Nora", "Nova",
    "Olive", "Ophelia", "Paige", "Pearl", "Petra", "Phoebe",
    "Piper", "Posy", "Rhea", "Rose", "Ruby", "Sadie", "Saoirse",
    "Selene", "Sera", "Sienna", "Sloane", "Stella", "Tessa", "Thea",
    "Tilda", "Vera", "Vesper", "Violet", "Willa", "Wren", "Yara",
    "Zara", "Zelda", "Zoe",
)

_UNISEX: tuple[str, ...] = (
    "Sage", "Quinn", "Phoenix", "Rowan", "Reese", "Riley", "Avery",
    "Blair", "Drew", "Emery", "Jordan", "Morgan", "Parker", "Skylar",
)

SUGGESTION_POOL: tuple[str, ...] = tuple(sorted(set(_MALE + _FEMALE + _UNISEX)))
assert len(SUGGESTION_POOL) > 100, f"pool only has {len(SUGGESTION_POOL)} names"


# Back-compat alias — older callers used POOL.
POOL = SUGGESTION_POOL


def suggest(taken: Iterable[str], n: int = 5, seed: str | None = None) -> list[str]:
    """Return up to ``n`` example names not in ``taken``.

    These are suggestions, not constraints — agents may pick anything
    that passes ``is_valid_name``.
    """
    taken_lower = {x.strip().lower() for x in taken}
    free = [name for name in SUGGESTION_POOL if name.lower() not in taken_lower]
    if not free:
        return []
    if seed is None:
        return random.sample(free, k=min(n, len(free)))
    rng = random.Random(
        int.from_bytes(hashlib.blake2b(seed.encode(), digest_size=8).digest(), "big")
    )
    return rng.sample(free, k=min(n, len(free)))


def pick(taken: Iterable[str], seed: str | None = None) -> str:
    """Legacy auto-pick (used by `callsign assign --auto` and Hermes batch jobs).

    Agents themselves should call `callsign claim <name>` instead — the
    whole point of the redesign is that names are not pre-set.
    """
    free = suggest(taken, n=len(SUGGESTION_POOL), seed=seed)
    if not free:
        raise RuntimeError("suggestion pool exhausted; pick a name yourself")
    return free[0]
