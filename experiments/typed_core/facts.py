"""What a core expression declares, as the atoms its static type may name:
the abstraction a type must never exceed (soundness.py)."""

from typing import NamedTuple

from wend import IsFile, PathExpr, Unspecified
from wend import conditions as _c


_ATOM = dict(_c.ATOMS)


class Facts(NamedTuple):
    atoms: frozenset[str]
    kind: type[Unspecified]


def facts(e: PathExpr) -> Facts:
    conds = e.conditions
    atoms: set[str] = set()
    if conds is not None:
        # What it requires (the type's C) as plain atoms, what it ensures
        # (the type's Q) with a post_ prefix: one vocabulary for both.
        for prefix, cs in (("", conds.requires), ("post_", conds.ensures)):
            for c in cs:
                if isinstance(c, _c.Under):
                    atoms.add(prefix + "Under[str]")
                    if c.base.is_static:
                        atoms.add(prefix + f"Under[{c.base.pattern!r}]")
                elif c in _ATOM:
                    atoms.add(prefix + _ATOM[c])
    return Facts(frozenset(atoms), IsFile if _c.declares_file(e) else Unspecified)
