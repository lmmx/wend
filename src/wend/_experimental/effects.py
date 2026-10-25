"""Declared filesystem-effect graphs (experimental; see `wend._experimental`).

Superseded by `wend.effects`, which relates each pair of paths by
`wend.relate`: certain links, prefix cancellation under shared bindings, and
hazards from deleting a directory. This module stays for its tests.

``EffectGraph(steps)`` relates the paths a set of steps (`wend.Step`)
*declare*, through `Step.effects`:

- a port is one path of one step with its verbs. ``create`` and ``write``
  make it a *supplier*, ``read`` an input, and ``list`` an input of every
  path below the directory it lists. ``delete`` makes it a *deleter*, which
  supplies nothing: `wend.lineage.Ledger.run` records a deleted path as an
  output, but a step that reads it does not depend on its deletion. A path
  declaring no verbs has no role and is reported, not guessed;
- an edge runs from a supplier of one step to an input of another (or the
  same) step when `overlaps` does not prove them disjoint. A *hazard* runs
  from an input to a deleter of a path it may read: the reader has to run
  first. A *conflict* is two suppliers, or a supplier and a deleter, that
  may name one path. Its verdict is
  ``yes`` (a witness path both render, so the producer *can* write a path
  the consumer reads) or ``maybe``. Neither means the dependency happens on
  a given run: that depends on the bindings each run uses;
- with ``shared=True`` a parameter name means one value across every step,
  as when a pipeline runs all its steps with one environment, which can
  rule edges out that independent bindings allow.

The contract for MAYBE: it is a possible dependency, conflict or hazard,
and every query treats it as one by default. Only that reading is safe:
a caller that treats MAYBE as "no" may run dependent steps concurrently,
skip a rebuild, or call a read output unused. ``definite_only=True``
keeps only the edges a witness proves (a lower bound for reports); it must
not decide that two steps are independent or that an order is valid.
The guarantee is one-sided: a missing edge (every overlap NO) is sound
under the assumptions below, while a present edge only says the
declarations do not rule the dependency out.

Identity is lexical. `overlaps` asks whether two expressions render the
same path *string*; two strings can name one file. ``/srv/data/x`` and
``data/x`` do when the working directory is ``/srv``, ``a/../b`` and ``b``
do when ``a`` is a directory, and on a case-insensitive filesystem so do
``Data`` and ``data``; a symlink can make any two do. A NO between such
spellings is not a NO between files, so a missing edge is only as good as
the convention that every step spells a file one way.
`EffectGraph.lexical_caveats` lists the ports where that convention is
visibly at risk (a relative path among absolute ones, a ``..`` segment);
case and symlinks it cannot see.

What the graph does not do: it describes declarations, not behaviour. A
step's code can read or write anything; a path read without ``Readable``
declared is not an input here. Scheduling is left to the caller, as
`wend.lineage` leaves it.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

from .._expr import PathExpr
from .._lens import Lens
from ..conditions import Step
from ..errors import WendError
from .overlap import Overlap, _alternatives, _shapes_of, overlaps


SUPPLY_VERBS = frozenset({"create", "write"})
DELETE_VERBS = frozenset({"delete"})
INPUT_VERBS = frozenset({"read", "list"})
Via = Literal["read", "list"]
VIAS: tuple[Via, ...] = ("list", "read")


@dataclass(frozen=True)
class Port:
    """One declared path of one step."""

    step: str
    name: str
    expr: PathExpr
    verbs: frozenset[str]

    @property
    def supplies(self) -> bool:
        return bool(self.verbs & SUPPLY_VERBS)

    @property
    def deletes(self) -> bool:
        return bool(self.verbs & DELETE_VERBS)

    @property
    def is_input(self) -> bool:
        return bool(self.verbs & INPUT_VERBS)

    def __repr__(self) -> str:
        return f"<{self.step}.{self.name}: {', '.join(sorted(self.verbs)) or 'no verbs'} {self.expr.pattern}>"


@dataclass(frozen=True)
class Edge:
    """A supplier that may supply an input (``via`` is ``read`` or ``list``).

    ``target`` is what the consumer sees: its path, or for ``list`` every
    path below the listed directory.
    """

    producer: Port
    consumer: Port
    overlap: Overlap
    via: Via
    target: PathExpr

    @property
    def verdict(self) -> str:
        return self.overlap.verdict

    def lens(self) -> Lens:
        """The producer's layout mapped onto the consumer's: with shared
        bindings, the consumer path for the bindings that wrote a path."""
        return Lens(self.producer.expr, self.target)

    def aligned(self, bindings: Mapping[str, Any]) -> bool | None:
        """Whether, with one set of ``bindings`` for both, the consumer reads
        exactly the path the producer writes (None if either cannot render
        from them)."""
        try:
            wrote = self.producer.expr.render(bindings)
            read = self.target.render(bindings)
        except WendError, ValueError:
            return None
        return wrote == read

    def readers(self, bindings: Mapping[str, Any]) -> list[dict[str, Any]]:
        """The consumer's bindings that read the path the producer writes
        with ``bindings``, by matching it (empty if none, or if the consumer
        cannot be matched)."""
        try:
            path = self.producer.expr.render(bindings)
            return self.target.match_all(path, limit=8)
        except WendError, ValueError:
            return []

    def __repr__(self) -> str:
        return f"<{self.producer.step}.{self.producer.name} -> {self.consumer.step}.{self.consumer.name}: {self.verdict}>"


@dataclass(frozen=True)
class Conflict:
    """Two suppliers, or a supplier and a deleter, that may name one path."""

    first: Port
    second: Port
    overlap: Overlap


@dataclass(frozen=True)
class Hazard:
    """An input that a deleter may remove: ``reader`` has to run first."""

    reader: Port
    deleter: Port
    overlap: Overlap


@dataclass
class EffectGraph:
    steps: Mapping[str, Step]
    shared: bool = False
    builtin_values: bool = False
    ports: list[Port] = field(init=False)
    edges: list[Edge] = field(init=False)
    conflicts: list[Conflict] = field(init=False)
    hazards: list[Hazard] = field(init=False)
    unassigned: list[Port] = field(init=False)

    def __post_init__(self) -> None:
        self.ports = [
            Port(step, e.name, e.expr, e.verbs)
            for step, s in self.steps.items()
            for e in s.effects()
        ]
        self.unassigned = [p for p in self.ports if not p.verbs]
        suppliers = [p for p in self.ports if p.supplies]
        deleters = [p for p in self.ports if p.deletes]
        inputs = [p for p in self.ports if p.is_input]

        def seen_by(i: Port, via: Via) -> PathExpr:
            return i.expr if via == "read" else _below(i.expr)

        self.edges = []
        self.hazards = []
        for i in inputs:
            for via in VIAS:
                if via not in i.verbs:
                    continue
                target = seen_by(i, via)
                for o in suppliers:
                    r = self._overlap(o.expr, target)
                    if r.verdict != "no":
                        self.edges.append(Edge(o, i, r, via, target))
                for d in deleters:
                    if d.step == i.step:
                        continue  # a step reading then deleting its own input
                    r = self._overlap(d.expr, target)
                    if r.verdict != "no":
                        self.hazards.append(Hazard(i, d, r))
        self.conflicts = []
        writers = suppliers + deleters
        for n, x in enumerate(writers):
            for y in writers[n + 1 :]:
                if x.deletes and y.deletes:
                    continue  # two deletions of one path do not conflict
                r = self._overlap(x.expr, y.expr)
                if r.verdict != "no":
                    self.conflicts.append(Conflict(x, y, r))

    def _overlap(self, a: Any, b: Any) -> Overlap:
        return overlaps(a, b, shared=self.shared, builtin_values=self.builtin_values)

    # -- reading the graph -------------------------------------------------------

    def lexical_caveats(self) -> list[tuple[Port, str]]:
        """Ports whose NOs may be NOs between spellings rather than files
        (see the module docstring), with why:

        - ``"relative"``: the port may render a relative path while another
          renders absolute ones, so the two meet only through the working
          directory, which the graph does not know;
        - ``".."``: the port may render a ``..`` segment, so the file it
          names may have another spelling.

        An empty list does not rule out aliasing by case or symlinks.
        """
        anchors: dict[Port, set[str]] = {}
        dotdot: set[Port] = set()
        for p in self.ports:
            if not p.verbs:
                continue
            seen: set[str] = set()
            for alt in _alternatives(p.expr):
                for shape in _shapes_of(alt, self.builtin_values)[0]:
                    seen |= shape.anchors
                    if any(i.lang.accepts("..") for i in shape.items):
                        dotdot.add(p)
            anchors[p] = seen
        absolute = [p for p, a in anchors.items() if a & {"/", "//"}]
        out: list[tuple[Port, str]] = []
        for p, a in anchors.items():
            if "" in a and any(q is not p for q in absolute):
                out.append((p, "relative"))
            if p in dotdot:
                out.append((p, ".."))
        return out

    def external_inputs(self) -> list[Port]:
        """Inputs no declared output can supply (every overlap is NO): the
        files the pipeline needs from outside."""
        fed = {(e.consumer.step, e.consumer.name) for e in self.edges}
        return [p for p in self.ports if p.is_input and (p.step, p.name) not in fed]

    def terminal_outputs(self) -> list[Port]:
        """Suppliers no declared input can read (every overlap is NO)."""
        used = {(e.producer.step, e.producer.name) for e in self.edges}
        return [p for p in self.ports if p.supplies and (p.step, p.name) not in used]

    def dependencies(self, *, definite_only: bool = False) -> dict[str, set[str]]:
        """For each step, the steps whose outputs may supply its inputs.

        ``definite_only`` keeps only ``yes`` edges: the dependencies proved
        by a witness. That is a lower bound, for reporting; use the default
        (MAYBE counts) to decide what may run independently."""
        deps: dict[str, set[str]] = {s: set() for s in self.steps}
        for e in self.edges:
            if definite_only and e.verdict != "yes":
                continue
            if e.producer.step != e.consumer.step:
                deps[e.consumer.step].add(e.producer.step)
        return deps

    def self_loops(self) -> list[Edge]:
        """Edges from a step to itself: it may read what it writes."""
        return [e for e in self.edges if e.producer.step == e.consumer.step]

    def cycles(self, *, definite_only: bool = False) -> list[list[str]]:
        """Strongly connected groups of two or more steps.

        A cycle among patterns need not be a cycle among runs: a step that
        reads ``{day}`` and writes ``{day}`` of another step is a cycle under
        independent bindings even if each day's run only reads earlier days.
        ``shared=True`` removes the cycles that need two values of one name.
        """
        deps = self.dependencies(definite_only=definite_only)
        return [c for c in _sccs(deps) if len(c) > 1]

    def order(self, *, definite_only: bool = False) -> list[str] | None:
        """The steps in an order where each comes after every step that may
        supply it, and every deleter after the readers of what it deletes;
        None if there is a cycle (self-loops aside).

        Only the default is a safe schedule: with ``definite_only`` a MAYBE
        dependency is ignored, so the order may run a consumer before its
        producer."""
        deps = {
            s: set(d) for s, d in self.dependencies(definite_only=definite_only).items()
        }
        for h in self.hazards:
            if definite_only and h.overlap.verdict != "yes":
                continue
            deps[h.deleter.step].add(h.reader.step)
        done: list[str] = []
        left = dict(deps)
        while left:
            ready = sorted(s for s, d in left.items() if d <= set(done))
            if not ready:
                return None
            done += ready
            for s in ready:
                del left[s]
        return done

    def compare(self, records: Iterable[Any]) -> dict[str, list[Any]]:
        """Observed lineage (the `wend.lineage.Record` objects a `Ledger`
        writes) against the declarations. A record names its step by
        ``operation`` (``repr(step)``, as `Ledger.run` records it).

        Returns ``undeclared``: observed dependencies (a record's input was a
        record's output) between steps the graph proves unrelated, which
        means a declaration is wrong or incomplete; and ``unobserved``:
        declared ``yes`` dependencies no record shows (informational only:
        a run need not exercise them). Raises ValueError if two steps have
        one repr, since their records would be indistinguishable.
        """
        names: dict[str, str] = {}
        for n, s in self.steps.items():
            if repr(s) in names:
                raise ValueError(
                    f"steps {names[repr(s)]!r} and {n!r} declare the same paths, so a"
                    " record (which names its step by repr) cannot tell them apart"
                )
            names[repr(s)] = n
        records = list(records)
        made_by = {r.path: names.get(r.operation) for r in records}
        observed: set[tuple[str, str]] = set()
        for r in records:
            consumer = names.get(r.operation)
            for path, _ in r.inputs:
                producer = made_by.get(path)
                if producer is not None and consumer is not None:
                    observed.add((producer, consumer))
        deps = self.dependencies()
        undeclared = sorted(
            (p, c) for p, c in observed if p != c and p not in deps.get(c, set())
        )
        definite = self.dependencies(definite_only=True)
        unobserved = sorted(
            (p, c) for c, ps in definite.items() for p in ps if (p, c) not in observed
        )
        return {"undeclared": undeclared, "unobserved": unobserved}


def _below(directory: PathExpr) -> PathExpr:
    """Every path at or below ``directory``: what listing it can see."""
    from .. import SubPath

    name = "_listed"
    while name in directory.param_names:
        name += "_"
    return directory / SubPath(name)


def _sccs(graph: Mapping[str, set[str]]) -> list[list[str]]:
    """Tarjan's strongly connected components, each sorted."""
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    stack: list[str] = []
    on: set[str] = set()
    out: list[list[str]] = []
    counter = 0

    def visit(v: str) -> None:
        nonlocal counter
        index[v] = low[v] = counter
        counter += 1
        stack.append(v)
        on.add(v)
        for w in sorted(graph.get(v, ())):
            if w not in index:
                visit(w)
                low[v] = min(low[v], low[w])
            elif w in on:
                low[v] = min(low[v], index[w])
        if low[v] == index[v]:
            comp = []
            while True:
                w = stack.pop()
                on.discard(w)
                comp.append(w)
                if w == v:
                    break
            out.append(sorted(comp))

    for v in sorted(graph):
        if v not in index:
            visit(v)
    return out


__all__ = ["Conflict", "Edge", "EffectGraph", "Hazard", "Port"]
