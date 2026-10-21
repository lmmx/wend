"""What steps owe each other: declared state, discharged across a graph
(research prototype; see docs/journal/2026-10-21-typed-path-families.md).

The atoms of `wend._experimental.typed.facts` fall into three strata, by
who makes them true:

- *containment* (``Under[...]``): enforced by `render` on every path, so a
  guarantee about the path itself;
- *state* (``exists``, ``absent``, ``file``, ``dir``): a fact about the
  filesystem when a step starts (``post_`` ones when it ends). A step's
  required state is an obligation that some earlier step, or the world,
  must meet;
- *permission* (``read``, ``write``, ``create``, ``list``): what the step
  may do, and what the environment must allow. No other step establishes
  a permission, so it is checked when the step runs, never discharged.

`verbs` computes a port's effect verbs from its atoms alone, so the effect
graph is a function of the same abstraction the static types carry.
`obligations` reads an `EffectGraph` as Hoare composition: an input's
required state is discharged by a supplier whose ensured state covers it.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from .effects import Edge, EffectGraph, Port
from .typed import facts


STATE = frozenset({"exists", "absent", "file", "dir"})
PERMISSIONS = frozenset({"read", "write", "create", "list"})


def verbs(atoms: Iterable[str]) -> frozenset[str]:
    """A port's effect verbs from its declared atoms, as `wend.Step.effects`
    computes them from its conditions: each permission (required or
    ensured), ``create`` for ``post_exists`` without ``exists``, ``delete``
    for ``post_absent`` without ``absent``.

    ``create`` and ``delete`` depend on an atom being *absent*: they are not
    upward closed, so no static type can certify them (a requirement
    ``PathExpr[Literal["post_exists"]]`` also accepts a path that requires
    ``exists`` and so creates nothing)."""
    a = frozenset(atoms)
    out = {v for v in PERMISSIONS if v in a or f"post_{v}" in a}
    if "post_exists" in a and "exists" not in a:
        out.add("create")
    if "post_absent" in a and "absent" not in a:
        out.add("delete")
    return frozenset(out)


def required_state(e) -> frozenset[str]:
    return facts(e).atoms & STATE


def ensured_state(e) -> frozenset[str]:
    return frozenset(a[5:] for a in facts(e).atoms if a.startswith("post_")) & STATE


@dataclass(frozen=True)
class Supply:
    """One supplier that may feed an input, and what of the input's
    required state its ensured state leaves unmet."""

    edge: Edge
    missing: frozenset[str]

    @property
    def verdict(self) -> str:
        return self.edge.verdict


@dataclass(frozen=True)
class Obligation:
    """An input's required state, and who may meet it.

    ``status``:

    - ``"external"``: no declared supplier overlaps; the world must;
    - ``"discharged"``: some supplier with a YES overlap ensures all of it;
    - ``"possible"``: suppliers overlap only with MAYBE, or ensure it only in
      part;
    - ``"unconstrained"``: the input requires no state.
    """

    port: Port
    needs: frozenset[str]
    supplies: tuple[Supply, ...] = field(default=())

    @property
    def status(self) -> str:
        if not self.needs:
            return "unconstrained"
        if not self.supplies:
            return "external"
        if any(s.verdict == "yes" and not s.missing for s in self.supplies):
            return "discharged"
        return "possible"

    def __repr__(self) -> str:
        gaps = "; ".join(
            f"{s.edge.producer.step}.{s.edge.producer.name} ({s.verdict})"
            + (f" lacks {', '.join(sorted(s.missing))}" if s.missing else "")
            for s in self.supplies
        )
        return (
            f"<{self.port.step}.{self.port.name} needs {', '.join(sorted(self.needs)) or 'nothing'}:"
            f" {self.status}{' via ' + gaps if gaps else ''}>"
        )


def obligations(graph: EffectGraph) -> list[Obligation]:
    """Each input port's required state, with the suppliers that may meet it.

    A ``list`` edge feeds a directory through a path written below it: a
    supplier that ensures that path exists ensures the directory exists, as
    a directory, too."""
    out = []
    for p in graph.ports:
        if not p.is_input:
            continue
        needs = required_state(p.expr)
        supplies = []
        for e in graph.edges:
            if e.consumer is not p:
                continue
            have = ensured_state(e.producer.expr)
            if e.via == "list" and "exists" in have:
                have = have | {"exists", "dir"}
            supplies.append(Supply(e, needs - have))
        out.append(Obligation(p, needs, tuple(supplies)))
    return out
