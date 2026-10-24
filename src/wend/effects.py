"""Effects across a pipeline, before any binding (docs/SEMANTICS.md §15).

`EffectGraph` takes named steps (`wend.Step`) and relates what each declares it
reads, lists, writes and deletes (`Step.effects`), with `wend.relate`:

- a *dependency* runs from a step that writes a path to one that reads it,
  or lists the directory it is in;
- a *hazard* runs from a step that reads a path to one that deletes it, or a
  directory above it: the reader has to run first;
- a *conflict* is two steps that write one path, or one that writes a path
  another deletes.

Each carries a certainty: ``"always"`` (on every run), ``"sometimes"`` (on
some runs, with an example), or ``"unknown"`` (not ruled out). Pairs the
analysis proves apart are not links at all. By default a parameter name means
one value across every step, as when the pipeline runs with one set of
bindings (``shared=True``)::

    from wend import Creatable, Exists, P, Param, Readable, Step, T
    from wend.effects import EffectGraph

    root, day = Param("root"), Param("day")
    raw = P(root) / "raw" / T(t"{day}.csv")
    clean = P(root) / "clean" / T(t"{day}.parquet")
    graph = EffectGraph({
        "ingest": Step(out=raw.ensures(Exists)),
        "clean": Step(src=raw.requires(Readable), dst=clean.requires(Creatable)),
    })
    graph.order()  # ['ingest', 'clean']

What the graph knows is what the steps declare: a step's code can read or
write anything, and a path read without ``Readable`` declared is not an input
here. Paths are compared as strings, so two spellings of one file (a symlink,
a relative and an absolute path, a ``..``) are two paths.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

from ._expr import Deferred, HeadParam, PathExpr, Root, Seg, _Rel
from ._relate import (
    Analysis,
    Certainty,
    Example,
    How,
    Relation,
    _key,
    _value_key,
    either,
    relate,
)
from .conditions import Step


SUPPLY_VERBS = frozenset({"create", "write"})
DELETE_VERBS = frozenset({"delete"})
INPUT_VERBS = frozenset({"read", "list"})
Via = Literal["read", "list"]

_PHRASE = {
    "always": "on every run",
    "sometimes": "on some runs",
    "unknown": "possibly (not ruled out)",
}


@dataclass(frozen=True)
class Port:
    """One declared path of one step, with the verbs it declares."""

    step: str
    name: str
    expr: PathExpr
    verbs: frozenset[str]

    @property
    def supplies(self) -> bool:
        """Whether the step writes or creates this path."""
        return bool(self.verbs & SUPPLY_VERBS)

    @property
    def deletes(self) -> bool:
        """Whether the step deletes this path."""
        return bool(self.verbs & DELETE_VERBS)

    @property
    def is_input(self) -> bool:
        """Whether the step reads this path or lists it."""
        return bool(self.verbs & INPUT_VERBS)

    def __str__(self) -> str:
        return f"{self.step}.{self.name}"

    def __repr__(self) -> str:
        verbs = ", ".join(sorted(self.verbs)) or "no verbs"
        return f"<{self}: {verbs} {self.expr.pattern}>"


@dataclass(frozen=True)
class _Link:
    certainty: Certainty
    _analysis: Analysis = field(repr=False, compare=False)
    _hows: tuple[How, ...] = field(repr=False, compare=False)

    def example(self) -> Example | None:
        """Bindings under which the link shows, when it holds always or
        sometimes: the paths both ports render with them."""
        for how in self._hows:
            if self._analysis(how) in ("always", "sometimes"):
                ex = self._analysis.example(how)
                if ex is not None:
                    return ex
        return None


@dataclass(frozen=True)
class Dependency(_Link):
    """``consumer`` reads the path ``producer`` writes (``via="read"``), or
    lists the directory it is in (``via="list"``)."""

    producer: Port = field(kw_only=True)
    consumer: Port = field(kw_only=True)
    via: Via = field(kw_only=True)

    def __repr__(self) -> str:
        return f"<{self.producer} -> {self.consumer} ({self.via}): {self.certainty}>"


@dataclass(frozen=True)
class Hazard(_Link):
    """``deleter`` deletes the path ``reader`` reads or lists, or a directory
    above it: ``reader`` has to run first."""

    reader: Port = field(kw_only=True)
    deleter: Port = field(kw_only=True)

    def __repr__(self) -> str:
        return f"<{self.reader} before {self.deleter}: {self.certainty}>"


@dataclass(frozen=True)
class Conflict(_Link):
    """Two ports that write one path, or a write and a deletion of it (or of
    a directory above it): the steps must not run at once, and which one
    wins depends on their order."""

    first: Port = field(kw_only=True)
    second: Port = field(kw_only=True)

    def __repr__(self) -> str:
        return f"<{self.first} x {self.second}: {self.certainty}>"


class EffectGraph:
    """What a set of named steps declare they do to their paths, related
    before any binding (see the module docstring).

    ``shared=True`` (the default) gives a parameter name one value across
    every step; ``shared=False`` relates every binding of one step to every
    binding of another, as when steps run with bindings of their own.
    ``builtin_values=True`` assumes bound values are of builtin types, which
    proves more paths apart (`wend.relate`).
    """

    def __init__(
        self,
        steps: Mapping[str, Step],
        *,
        shared: bool = True,
        builtin_values: bool = False,
    ) -> None:
        self.steps: dict[str, Step] = dict(steps)
        self.shared = shared
        self.builtin_values = builtin_values
        self.ports: list[Port] = [
            Port(name, e.name, e.expr, e.verbs)
            for name, step in self.steps.items()
            for e in step.effects()
        ]
        self.unassigned: list[Port] = [p for p in self.ports if not p.verbs]
        self._analyses: dict[tuple[int, int], Analysis] = {}
        self._memo: dict[int, tuple[Any, Any]] = {}
        self._index = {id(p): self._index_key(p.expr) for p in self.ports}
        suppliers = [p for p in self.ports if p.supplies]
        deleters = [p for p in self.ports if p.deletes]
        inputs = [p for p in self.ports if p.is_input]

        self.edges: list[Dependency] = []
        for c in inputs:
            for p in suppliers:
                if "read" in c.verbs:
                    self._link(
                        Dependency,
                        (c, p),
                        ("same",),
                        producer=p,
                        consumer=c,
                        via="read",
                    )
                if "list" in c.verbs:
                    hows: tuple[How, ...] = ("same", "inside")
                    self._link(
                        Dependency, (p, c), hows, producer=p, consumer=c, via="list"
                    )

        self.hazards: list[Hazard] = []
        for c in inputs:
            for d in deleters:
                if d.step == c.step:
                    continue  # a step that reads its own input, then deletes it
                hows = ("same", "inside")
                if "list" in c.verbs:
                    hows = ("same", "inside", "contains")
                self._link(Hazard, (c, d), hows, reader=c, deleter=d)

        self.conflicts: list[Conflict] = []
        writers = suppliers + [d for d in deleters if not d.supplies]
        for n, x in enumerate(writers):
            for y in writers[n + 1 :]:
                if x.deletes and y.deletes:
                    continue  # two deletions of one path do not conflict
                if x.supplies and y.supplies:
                    self._link(Conflict, (x, y), ("same",), first=x, second=y)
                else:
                    s, d = (x, y) if x.supplies else (y, x)
                    self._link(Conflict, (s, d), ("same", "inside"), first=x, second=y)

    def _index_key(self, e: Any) -> tuple[Any, tuple[str, ...]] | None:
        """The head (with its default, if any) and the literal segments after
        it, up to the first part that is not one; None for a path whose head
        cannot be compared this way."""
        if not isinstance(e, PathExpr) or isinstance(e.head, Deferred):
            return None
        if not self.shared and not isinstance(e.head, (Root, _Rel)):
            return None
        head: Any = _key(e.head, self._memo)
        if isinstance(e.head, HeadParam) and e.head.param.has_default:
            head = (head, _value_key(e.head.param.default))
        literal = []
        for part in e.parts:
            if not (isinstance(part, Seg) and part.literal is not None):
                break
            literal.append(part.literal)
        return head, tuple(literal)

    def _apart(self, a: Port, b: Port) -> bool:
        """Whether two ports are apart by their literal segments alone: one
        head, then two different segments at one position (`wend.relate`'s
        divergence, without building an analysis)."""
        ka, kb = self._index[id(a)], self._index[id(b)]
        if ka is None or kb is None or ka[0] != kb[0]:
            return False
        k = min(len(ka[1]), len(kb[1]))
        return ka[1][:k] != kb[1][:k]

    def _analysis(self, a: Port, b: Port) -> Analysis:
        key = (id(a.expr), id(b.expr))
        if key not in self._analyses:
            self._analyses[key] = Analysis(
                a.expr,
                b.expr,
                shared=self.shared,
                builtin_values=self.builtin_values,
                memo=self._memo,
            )
        return self._analyses[key]

    def _link(
        self,
        kind: type[Dependency] | type[Hazard] | type[Conflict],
        pair: tuple[Port, Port],
        hows: tuple[How, ...],
        **ports: Any,
    ) -> None:
        if self._apart(*pair):
            return
        analysis = self._analysis(*pair)
        certainties: list[Certainty] = [analysis(how) for how in hows]
        certainty = either(*certainties)
        if certainty == "never":
            return
        link = kind(certainty, analysis, hows, **ports)
        if isinstance(link, Dependency):
            self.edges.append(link)
        elif isinstance(link, Hazard):
            self.hazards.append(link)
        else:
            self.conflicts.append(link)

    # -- reading the graph ---------------------------------------------------------

    def dependencies(self, *, certain: bool = False) -> dict[str, set[str]]:
        """For each step, the steps whose writes it may read.

        ``certain=True`` keeps the dependencies that hold on every run (under
        which both steps' paths render). Use the default, which also counts
        those that hold on some runs or are not ruled out, to decide what may
        run independently."""
        deps: dict[str, set[str]] = {s: set() for s in self.steps}
        for e in self.edges:
            if certain and e.certainty != "always":
                continue
            if e.producer.step != e.consumer.step:
                deps[e.consumer.step].add(e.producer.step)
        return deps

    def _after(self) -> dict[str, set[str]]:
        """For each step, the steps it must follow: those it may depend on,
        and the readers of what it deletes."""
        after = self.dependencies()
        for h in self.hazards:
            after[h.deleter.step].add(h.reader.step)
        return after

    def order(self) -> list[str] | None:
        """The steps in an order where each follows every step it may depend
        on, and every deleter follows the readers of what it deletes; ties
        keep the order the steps were given in. None if they form a cycle
        (`cycles`). Conflicts do not order steps: which writer wins is the
        caller's choice."""
        stages = self._layers(self._after())
        return None if stages is None else [s for stage in stages for s in stage]

    def stages(self) -> list[list[str]] | None:
        """The steps in groups that may run at the same time: each group
        follows every step it may depend on, and no two steps in a group
        conflict. None if the steps form a cycle."""
        layers = self._layers(self._after())
        if layers is None:
            return None
        clash: dict[str, set[str]] = {s: set() for s in self.steps}
        for c in self.conflicts:
            if c.first.step != c.second.step:
                clash[c.first.step].add(c.second.step)
                clash[c.second.step].add(c.first.step)
        out: list[list[str]] = []
        for layer in layers:
            groups: list[list[str]] = []
            for s in layer:
                for g in groups:
                    if not clash[s] & set(g):
                        g.append(s)
                        break
                else:
                    groups.append([s])
            out.extend(groups)
        return out

    def _layers(self, after: dict[str, set[str]]) -> list[list[str]] | None:
        done: set[str] = set()
        left = list(self.steps)
        layers: list[list[str]] = []
        while left:
            ready = [s for s in left if after[s] - {s} <= done]
            if not ready:
                return None
            layers.append(ready)
            done.update(ready)
            left = [s for s in left if s not in done]
        return layers

    def independent(self, x: str, y: str) -> bool:
        """Whether steps ``x`` and ``y`` cannot interact: neither may read
        what the other writes, nor delete what it reads, nor write what it
        writes or deletes. Independent steps may run in either order, or at
        once."""
        return not self.links(x, y)

    def links(
        self, x: str, y: str | None = None
    ) -> list[Dependency | Hazard | Conflict]:
        """The dependencies, hazards and conflicts between ``x`` and ``y``, in
        either direction; with ``y`` omitted, every one involving ``x``."""

        def steps(link: Dependency | Hazard | Conflict) -> set[str]:
            if isinstance(link, Dependency):
                return {link.producer.step, link.consumer.step}
            if isinstance(link, Hazard):
                return {link.reader.step, link.deleter.step}
            return {link.first.step, link.second.step}

        return [
            link
            for link in [*self.edges, *self.hazards, *self.conflicts]
            if (x in steps(link) if y is None else steps(link) == {x, y})
        ]

    def explain(self, x: str, y: str | None = None) -> list[str]:
        """One sentence per link between ``x`` and ``y`` (or involving ``x``):
        which port relates to which, how surely, and an example when one is
        known."""
        return [_sentence(link) for link in self.links(x, y)]

    def cycles(self, *, certain: bool = False) -> list[list[str]]:
        """Groups of two or more steps that each depend, through the others,
        on themselves. A cycle among declarations need not be a cycle on a
        run: with ``shared=False``, a step that reads ``{day}`` and writes
        ``{day}`` of another is one."""
        deps = self.dependencies(certain=certain)
        return [c for c in _sccs(deps) if len(c) > 1]

    def self_loops(self) -> list[Dependency]:
        """Dependencies from a step to itself: it may read what it writes."""
        return [e for e in self.edges if e.producer.step == e.consumer.step]

    def external_inputs(self) -> list[Port]:
        """Inputs no step writes: the paths the pipeline needs from outside."""
        fed = {id(e.consumer) for e in self.edges}
        return [p for p in self.ports if p.is_input and id(p) not in fed]

    def terminal_outputs(self) -> list[Port]:
        """Paths written that no step reads: the pipeline's results."""
        used = {id(e.producer) for e in self.edges}
        return [p for p in self.ports if p.supplies and id(p) not in used]

    def compare(self, records: Iterable[Any]) -> dict[str, list[tuple[str, str]]]:
        """Observed lineage (the `wend.lineage.Record` objects a `Ledger`
        writes) against the declarations. A record names its step by
        ``operation`` (``repr(step)``, as `Ledger.run` records it).

        Returns ``undeclared``: observed dependencies (a record's input was a
        record's output) between steps the graph proves apart, which means a
        declaration is wrong or incomplete; and ``unobserved``: dependencies
        declared to hold on every run that no record shows (informational: a
        run need not exercise them). Raises ValueError if two steps have one
        repr, since their records would be indistinguishable."""
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
        certain = self.dependencies(certain=True)
        unobserved = sorted(
            (p, c) for c, ps in certain.items() for p in ps if (p, c) not in observed
        )
        return {"undeclared": undeclared, "unobserved": unobserved}

    def __repr__(self) -> str:
        counts = ", ".join(
            _count(n, *words)
            for n, words in (
                (len(self.steps), ("step", "steps")),
                (len(self.edges), ("dependency", "dependencies")),
                (len(self.hazards), ("hazard", "hazards")),
                (len(self.conflicts), ("conflict", "conflicts")),
            )
        )
        return f"EffectGraph({counts})"


def _count(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def _sentence(link: Dependency | Hazard | Conflict) -> str:
    phrase = _PHRASE[link.certainty]
    if isinstance(link, Dependency):
        p, c = link.producer, link.consumer
        if link.via == "list":
            text = f"{c} lists {c.expr.pattern}, where {p} writes {p.expr.pattern}, {phrase}"
        else:
            text = f"{c} reads what {p} writes, {phrase}: {_paths(c, p)}"
    elif isinstance(link, Hazard):
        r, d = link.reader, link.deleter
        text = (
            f"{d} deletes what {r} reads, {phrase}, so {r.step} runs first:"
            f" {_paths(r, d)}"
        )
    else:
        x, y = link.first, link.second
        if x.deletes or y.deletes:
            w, d = (y, x) if x.deletes else (x, y)
            text = f"{d} deletes what {w} writes, {phrase}: {_paths(w, d)}"
        else:
            text = f"{x} and {y} write one path, {phrase}: {_paths(x, y)}"
    ex = link.example()
    if ex is not None:
        bindings = {**ex.a_bindings, **ex.b_bindings}
        shown = ", ".join(f"{k}={v!r}" for k, v in sorted(bindings.items()))
        rendered = (
            ex.a_path if ex.a_path == ex.b_path else f"{ex.a_path} and {ex.b_path}"
        )
        text += f" (e.g. {shown}: {rendered})"
    return text


def _paths(x: Port, y: Port) -> str:
    if x.expr.pattern == y.expr.pattern:
        return x.expr.pattern
    return f"{x.expr.pattern} and {y.expr.pattern}"


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


__all__ = [
    "Certainty",
    "Conflict",
    "Dependency",
    "EffectGraph",
    "Example",
    "Hazard",
    "Port",
    "Relation",
    "relate",
]
