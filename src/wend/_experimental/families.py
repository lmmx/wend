"""What a pipeline knows about its path *families*, before any binding exists
(research prototype; see docs/journal/2026-10-22-symbolic-families.md).

`wend._experimental.knowledge` reasons about rendered paths. Here a fact is
an atom and an *expression*: "for the shared bindings of a run, this atom
held of the path this expression renders". Three relations between two
expressions ``a`` and ``b`` under shared bindings (one value per parameter
name, as one run of a pipeline uses):

- `must_equal`: wherever both render, they render the same path. Judged
  by equal patterns and equal defaults: declarations (type, choices,
  kind) only decide what a binding may be, never what it renders.
- `relation`: whether ``a``'s path can be ``b``'s, or above or below it:
  ``"no"`` (provably never, from `overlaps`), ``"yes"`` (for some binding)
  or ``"maybe"``.
- derived knowledge: if a path exists, its parent exists and is a
  directory; if a path is absent, so is every path below it.

`analyse_families` runs the learn/forget rules of `knowledge` over these
relations: it knows an atom where a fact's expression must equal the
input's, forgets wherever a mutation's relation to a fact is not ``"no"``,
and reports a required atom *refuted* only through must-equal (the check
will fail for every binding), *possibly refuted* through overlap.

`independent(x, y)` says two steps cannot interfere: no mutation of one can
touch a path of the other, nor make a parent the other's creation checks
depend on. Adjacent independent steps commute (see the journal for the
argument and its assumptions).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal

from .._expr import REL, Deferred, PathExpr
from ..conditions import Step
from .effects import _below
from .knowledge import EXCLUSIVE, MUTATING
from .overlap import overlaps


__all__ = [
    "FamilyEntry",
    "FamilyKnowledge",
    "analyse_families",
    "independent",
    "coincide",
    "must_equal",
    "relation",
    "snapshots",
]

Relation = Literal["no", "maybe", "yes"]


def _plain(e: PathExpr) -> PathExpr:
    """``e`` without its declarations (so joining below a File is allowed)."""
    return PathExpr(e.head, e.parts)


def _defaults(e: PathExpr) -> dict[str, object]:
    return {
        n: (type(p.default), repr(p.default))
        for n, p in e.params.items()
        if p.has_default
    }


def must_equal(a: PathExpr, b: PathExpr) -> bool:
    """Whether ``a`` and ``b`` render the same path wherever both render,
    for shared bindings."""
    return a.pattern == b.pattern and _defaults(a) == _defaults(b)


def _split(a: PathExpr, b: PathExpr) -> tuple[PathExpr, PathExpr] | None:
    """``a`` and ``b`` past their common prefix, as relative expressions, if
    they share a head: under shared bindings a common prefix renders one
    string, and joining onto it is injective, so ``a`` and ``b`` coincide,
    or lie above or below each other, exactly when the remainders do."""
    ha, hb = PathExpr(a.head, ()), PathExpr(b.head, ())
    if not must_equal(ha, hb) or isinstance(a.head, Deferred):
        return None
    i = 0
    while i < min(len(a.parts), len(b.parts)):
        pa, pb = PathExpr(REL, (a.parts[i],)), PathExpr(REL, (b.parts[i],))
        if not must_equal(pa, pb):
            break
        i += 1
    return PathExpr(REL, a.parts[i:]), PathExpr(REL, b.parts[i:])


def coincide(a: PathExpr, b: PathExpr) -> Relation:
    """Whether, for some shared binding, ``a`` and ``b`` render one path."""
    if must_equal(a, b):
        return "yes"
    a, b = _plain(a), _plain(b)
    split = _split(a, b)
    if split is not None:
        ra, rb = split
        if not ra.parts and not rb.parts:
            return "yes"
        if not ra.parts or not rb.parts:
            rest = rb if not ra.parts else ra
            return "maybe" if _may_be_empty(rest) else "no"
        a, b = ra, rb
    return overlaps(a, b, shared=True).verdict


def _may_be_empty(e: PathExpr) -> bool:
    return all(p.__class__.__name__ == "Splice" for p in e.parts)


def relation(a: PathExpr, b: PathExpr) -> Relation:
    """Whether, for some shared binding, ``a``'s path is ``b``'s or lies
    above or below it."""
    if must_equal(a, b):
        return "yes"
    a, b = _plain(a), _plain(b)
    split = _split(a, b)
    if split is not None:
        ra, rb = split
        if not ra.parts or not rb.parts:
            return "yes"  # one is the common prefix: the other is at or below it
        a, b = ra, rb
    verdicts = {
        overlaps(a, _below(b), shared=True).verdict,
        overlaps(b, _below(a), shared=True).verdict,
    }
    if "yes" in verdicts:
        return "yes"
    if verdicts == {"no"}:
        return "no"
    return "maybe"


def _below_verdict(e: PathExpr, p: PathExpr) -> Relation:
    """Whether ``e`` may lie at or below ``p``."""
    e, p = _plain(e), _plain(p)
    split = _split(e, p)
    if split is not None:
        re_, rp = split
        if not rp.parts:
            return "yes"
        if not re_.parts:
            return "maybe" if _may_be_empty(rp) else "no"
        e, p = re_, rp
    return overlaps(e, _below(p), shared=True).verdict


def _parents(e: PathExpr) -> list[PathExpr]:
    """The structural parents of ``e``, nearest first (none past a head or a
    SubPath, whose parent is not a fixed number of segments)."""
    out = []
    while e.parts and e.parts[-1].__class__.__name__ == "Seg":
        e = PathExpr(e.head, e.parts[:-1])
        out.append(e)
    return out


@dataclass(frozen=True)
class FamilyFact:
    atom: str
    expr: PathExpr

    def __repr__(self) -> str:
        return f"{self.atom}({self.expr.pattern})"


@dataclass
class FamilyKnowledge:
    facts: list[FamilyFact] = field(default_factory=list)

    def _has(self, atom: str, e: PathExpr) -> bool:
        return any(f.atom == atom and must_equal(f.expr, e) for f in self.facts)

    def knows(self, atom: str, e: PathExpr) -> bool:
        if self._has(atom, e):
            return True
        if atom in ("exists", "dir"):
            # a path below e exists, so e exists as a directory
            for f in self.facts:
                if f.atom == "exists" and any(
                    must_equal(p, e) for p in _parents(f.expr)
                ):
                    return True
        if atom == "absent":
            return any(self._has("absent", p) for p in _parents(e))
        return False

    def refutes(self, atom: str, e: PathExpr) -> bool:
        for a, b in EXCLUSIVE:
            other = b if atom == a else a if atom == b else None
            if other is not None and self.knows(other, e):
                return True
        if atom in ("file", "dir") and self.knows("exists", e):
            return self.knows("dir" if atom == "file" else "file", e)
        return False

    def may_refute(self, atom: str, e: PathExpr) -> list[FamilyFact]:
        """Known facts that refute ``atom`` of ``e`` for the bindings where
        their paths coincide (overlap, not must-equal)."""
        out = []
        for f in self.facts:
            for a, b in EXCLUSIVE:
                other = b if atom == a else a if atom == b else None
                if f.atom == other and coincide(f.expr, e) != "no":
                    out.append(f)
        return out

    def learn(self, atoms: frozenset[str], e: PathExpr) -> None:
        for a in sorted(atoms):
            if not self._has(a, e):
                self.facts.append(FamilyFact(a, _plain(e)))

    def made_parents(self, m: PathExpr) -> list[PathExpr] | None:
        """The parents of ``m`` that making it may also make: those nearer
        than the nearest one known to exist; None (unbounded, up to the
        filesystem root) if none is known to exist."""
        out = []
        for p in _parents(m):
            if self.knows("exists", p):
                return out
            out.append(p)
        return None

    def forget(self, m: PathExpr) -> None:
        made = self.made_parents(m)
        keep = []
        for f in self.facts:
            if relation(f.expr, m) != "no":
                continue
            if (
                f.atom in ("create", "write")
                and not self.knows("exists", f.expr)
                and _may_be_below(f.expr, made)
            ):
                continue
            keep.append(f)
        self.facts = keep


def _may_be_below(e: PathExpr, parents: list[PathExpr] | None) -> bool:
    if parents is None:
        return True
    return any(_below_verdict(e, p) != "no" for p in parents)


@dataclass(frozen=True)
class FamilyEntry:
    """At one step's entry, for one of its paths, for every shared binding
    under which every earlier step completed."""

    step: str
    port: str
    expr: PathExpr
    known: frozenset[str]
    refuted: frozenset[str]
    possibly_refuted: frozenset[str]


def _step(k: FamilyKnowledge, step: Step) -> None:
    for e in step.paths.values():
        k.learn(e.declares.requires, e)
    for e in step.paths.values():
        if e.declares.verbs & MUTATING:
            k.forget(e)
    for e in step.paths.values():
        k.learn(e.declares.ensures, e)


def snapshots(steps: Sequence[tuple[str, Step]]) -> list[FamilyKnowledge]:
    """The knowledge before each step, assuming every earlier step completed."""
    k = FamilyKnowledge()
    out = []
    for _, step in steps:
        out.append(FamilyKnowledge(list(k.facts)))
        _step(k, step)
    return out


def analyse_families(steps: Sequence[tuple[str, Step]]) -> list[FamilyEntry]:
    """What each step will know at entry, for every shared binding under
    which every earlier step completed."""
    out = []
    for (name, step), k in zip(steps, snapshots(steps), strict=True):
        for port, e in step.paths.items():
            req = e.declares.requires
            known = frozenset(a for a in req if k.knows(a, e))
            refuted = frozenset(a for a in req if k.refutes(a, e))
            maybe = frozenset(a for a in req - refuted if k.may_refute(a, e))
            out.append(FamilyEntry(name, port, e, known, refuted, maybe))
    return out


def independent(x: Step, y: Step, k: FamilyKnowledge | None = None) -> bool:
    """Whether no mutation of either step can touch a path of the other, or
    make a parent the other's creation checks depend on (parents known to
    exist in ``k`` are not made)."""
    k = k or FamilyKnowledge()
    for a, b in ((x, y), (y, x)):
        for m in a.paths.values():
            if not m.declares.verbs & MUTATING:
                continue
            made = k.made_parents(m)
            for e in b.paths.values():
                if relation(e, m) != "no":
                    return False
                if e.declares.requires & {"create", "write"} and _may_be_below(e, made):
                    return False
    return True
