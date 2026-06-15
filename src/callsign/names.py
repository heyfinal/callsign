"""Curated pool of memorable single-token callsigns.

Names are chosen to be:
  - Single token (no spaces, no compound forms)
  - Distinctive when used as an iMessage trigger ("Frank, do X")
  - Easy to type on a phone keyboard
  - Unambiguous when spoken aloud
  - Free of common-noun collisions ("Cole", "Reed" included only after
    weighing payoff vs. the rare case daniel writes them mid-sentence —
    the trigger is "Name," at message start, which makes collisions rare)
"""
from __future__ import annotations

import hashlib
import random
from typing import Iterable

POOL: tuple[str, ...] = (
    "Atlas", "Axel", "Beck", "Bishop", "Boone", "Brody", "Cael",
    "Cassius", "Cash", "Cole", "Creed", "Cyrus", "Dane", "Dash",
    "Dean", "Diego", "Drake", "Easton", "Enzo", "Felix", "Finn",
    "Ford", "Forge", "Frank", "Gage", "Grayson", "Harlan", "Hawk",
    "Hayes", "Hugo", "Ian", "Ivar", "Jasper", "Jet", "Jude",
    "Kade", "Kai", "Kent", "Knox", "Lane", "Leon", "Levi",
    "Locke", "Maverick", "Marcus", "Mason", "Miles", "Nash",
    "Niko", "Noble", "Oakley", "Orin", "Otto", "Owen", "Pax",
    "Pierce", "Pike", "Quill", "Quincy", "Quinn", "Rafael",
    "Reed", "Reid", "Remy", "Rhodes", "Roman", "Rowan", "Ryker",
    "Sage", "Silas", "Steven", "Storm", "Tanner", "Tate", "Thane",
    "Vance", "Vaughn", "Victor", "Wade", "Wesley", "Wolfe",
    "Wyatt", "Xander", "York", "Zane", "Zeke", "Archer", "Briggs",
    "Caelum", "Donovan", "Elias", "Fabian", "Garrett", "Holden",
    "Ivor", "Jericho", "Killian", "Lyle", "Magnus", "Niall",
    "Orson", "Porter", "Quentin", "Royce", "Sullivan", "Talon",
    "Ulysses", "Vincent", "Warren", "Xavier", "Yates", "Zephyr",
    "Asher", "Barret", "Cassian", "Dexter", "Emmett", "Foster",
    "Griffin", "Hendrix", "Isaiah", "Jonas", "Kingston", "Lawson",
    "Maddox", "Nolan", "Oscar", "Phelan",
)


def pick(taken: Iterable[str], seed: str | None = None) -> str:
    """Return a name not in ``taken``. Deterministic when ``seed`` is given."""
    taken_lower = {n.strip().lower() for n in taken}
    free = [n for n in POOL if n.lower() not in taken_lower]
    if not free:
        raise RuntimeError(
            f"All {len(POOL)} callsigns are in use. Retire some with "
            "`callsign retire <name>` or extend names.POOL."
        )
    if seed is None:
        return random.choice(free)
    digest = hashlib.blake2b(seed.encode("utf-8"), digest_size=8).digest()
    idx = int.from_bytes(digest, "big") % len(free)
    return free[idx]


def is_valid(name: str) -> bool:
    return name.strip().lower() in {n.lower() for n in POOL}
