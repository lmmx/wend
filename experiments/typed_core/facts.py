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
        for prefix, cs in (("", conds.requires), ("post_", conds.ensures)):
            for c in cs:
                if isinstance(c, _c.Under):
                    atoms.add("Under[str]")
                    if c.base.is_static:
                        atoms.add(f"Under[{c.base.pattern!r}]")
                elif c in _ATOM:
                    atoms.add(prefix + _ATOM[c])
    return Facts(frozenset(atoms), IsFile if _c.declares_file(e) else Unspecified)
