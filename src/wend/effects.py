"""Effects across a pipeline, before any binding (docs/SEMANTICS.md §15).

`EffectGraph` takes named steps (`wend.Step`) and relates what each declares it
reads, lists, writes and deletes (`Step.effects`), with `wend.relate`:

- a *dependency* runs from a step that writes a path to one that reads or
  lists it;
- a *hazard* runs from a step that reads or lists a path to one that deletes
  it: the reader has to run first;
- a *conflict* is two steps that write one path, or delete it, or one that
  writes and one that deletes it, or a path declared with no verbs (whose
  effect is unknown) and another: they must not run at once.

A declared path covers what lies below it, since it may be a directory: each
link holds when the two paths are one, or one is inside the other.

Each carries a certainty: ``"always"`` (on every run), ``"sometimes"`` (on
some runs, with an example), or ``"unknown"`` (not ruled out). Pairs the
analysis proves apart are not links at all, and every query but those given
``certain=True`` counts every other link, so a possible conflict is never
taken for independence. By default a parameter name means one value across
every step, as when the pipeline runs with one set of bindings
(``shared=True``)::

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
here. Parents a creation may make (as ``mkdir -p`` does) are not counted: two
steps that create siblings in a missing directory may share a stage, which is
safe when parents are made idempotently (docs/SEMANTICS.md §15.4). Paths are compared as rendered strings, not as filesystem objects, so
two spellings of one file (a symlink, a relative and an absolute path, a
``..``, a hard link) are two paths.
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
_TOUCH: tuple[How, ...] = ("same", "inside", "contains")
_INVERSE: dict[How, How] = {"same": "same", "inside": "contains", "contains": "inside"}
# The subject's path, relative to what the object's port does to its own.
_WHAT: dict[How, str] = {
    "same": "what",
    "inside": "inside what",
    "contains": "a directory holding what",
}

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

    def _how(self) -> How:
        """How the first port's path relates to the second's in the answer
        that gives the link its certainty."""
        for how in self._hows:
            if self._analysis(how) == self.certainty:
                return how
        return self._hows[0]

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
    """``consumer`` reads (``via="read"``) or lists (``via="list"``) a path
    that is, holds, or lies inside one ``producer`` writes."""

    producer: Port = field(kw_only=True)
    consumer: Port = field(kw_only=True)
    via: Via = field(kw_only=True)

    def __repr__(self) -> str:
        return f"<{self.producer} -> {self.consumer} ({self.via}): {self.certainty}>"


@dataclass(frozen=True)
class Hazard(_Link):
    """``deleter`` deletes the path ``reader`` reads or lists, a directory
    above it, or a path inside it: ``reader`` has to run first."""

    reader: Port = field(kw_only=True)
    deleter: Port = field(kw_only=True)

    def __repr__(self) -> str:
        return f"<{self.reader} before {self.deleter}: {self.certainty}>"


@dataclass(frozen=True)
class Conflict(_Link):
    """Two ports that may change what the other touches: two writes, a write
    and a deletion, or two deletions of one path or of paths one inside the
    other, or a port that declares no verbs (so its effect is unknown) and
    any port it touches. The steps must not run at once; for writes, which
    one wins depends on their order, which the graph does not choose."""

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

        # A declared path covers what lies below it (it may be a directory),
        # so two ports touch when their paths are one, or one is inside the
        # other: every link asks all three.
        self.edges: list[Dependency] = []
        for c in inputs:
            for p in suppliers:
                if "read" in c.verbs:
                    self._link(Dependency, (c, p), producer=p, consumer=c, via="read")
                if "list" in c.verbs:
                    self._link(Dependency, (p, c), producer=p, consumer=c, via="list")

        self.hazards: list[Hazard] = []
        for c in inputs:
            for d in deleters:
                if d.step == c.step:
                    continue  # a step that reads its own input, then deletes it
                self._link(Hazard, (c, d), reader=c, deleter=d)

        # Two ports conflict when either may change what the other touches:
        # two writers, a writer and a deleter, two deleters (one may find the
        # path gone), or a port whose verbs are unknown and any other.
        self.conflicts: list[Conflict] = []
        changers = [p for p in self.ports if p.supplies or p.deletes or not p.verbs]
        for n, x in enumerate(changers):
            for y in changers[n + 1 :]:
                self._link(Conflict, (x, y), first=x, second=y)
        for u in self.unassigned:
            for r in inputs:
                if not (r.supplies or r.deletes):
                    self._link(Conflict, (u, r), first=u, second=r)

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
        **ports: Any,
    ) -> None:
        if self._apart(*pair):
            return
        analysis = self._analysis(*pair)
        certainties: list[Certainty] = []
        for how in _TOUCH:
            certainties.append(analysis(how))
            if certainties[-1] == "always":
                break
        certainty = either(*certainties)
        if certainty == "never":
            return
        link = kind(certainty, analysis, _TOUCH, **ports)
        if isinstance(link, Dependency):
            self.edges.append(link)
        elif isinstance(link, Hazard):
            self.hazards.append(link)
        else:
            self.conflicts.append(link)

    # -- reading the graph ---------------------------------------------------------

    def dependencies(self, *, certain: bool = False) -> dict[str, set[str]]:
        """For each step, the steps whose writes it may read or list.

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

    def _after(self, *, certain: bool = False) -> dict[str, set[str]]:
        """For each step, the steps it must follow: those it may depend on,
        and the readers of what it deletes."""
        after = self.dependencies(certain=certain)
        for h in self.hazards:
            if h.reader.step != h.deleter.step:
                if not certain or h.certainty == "always":
                    after[h.deleter.step].add(h.reader.step)
        return after

    def order(self) -> list[str] | None:
        """The steps in an order where each follows every step it may depend
        on, and every deleter follows the readers of what it deletes; ties
        keep the order the steps were given in.

        Every link counts, whatever its certainty: a dependency that holds
        on some runs, or that is only not ruled out, orders the steps as one
        that holds on every run does. None if these links form a cycle:
        `cycles` lists the cycles, and ``cycles(certain=True)`` those made of
        links that hold on every run, which no binding avoids. Conflicts do
        not order steps: which writer wins is the caller's choice, and a port
        that declares no verbs is kept apart from others (`stages`) but not
        ordered."""
        stages = self._layers(self._after())
        return None if stages is None else [s for stage in stages for s in stage]

    def stages(self) -> list[list[str]] | None:
        """The steps in groups that may run at the same time: each group
        follows every step it may depend on, and no two steps in a group
        are joined by any link, whatever its certainty. None if the steps
        form a cycle (see `order`)."""
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
        """Whether no link joins steps ``x`` and ``y``: no dependency, hazard
        or conflict between them holds always, sometimes, or is even not
        ruled out. Their declared paths, compared as strings, then never
        meet nor nest where either one writes, deletes, or declares no verbs.
        Independent steps may run in either order, or at once, so far as
        their declarations go: a step's code may touch paths it does not
        declare, and two spellings of one file are two paths here."""
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
        """Groups of two or more steps that must each run, through the
        others, before themselves, by the dependencies and hazards `order`
        follows. When there is one, `order` and `stages` are None.

        ``certain=True`` keeps the links that hold on every run (under which
        their paths render): a cycle among them is unavoidable. A cycle found
        only without it is possible, not proved: it rests on a link that
        holds on some runs, or is only not ruled out, so it may depend on the
        bindings, as with ``shared=False``, where a step that reads ``{day}``
        and writes ``{day}`` of another run is one."""
        after = self._after(certain=certain)
        return [c for c in _sccs(after) if len(c) > 1]

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
    how = link._how()
    if isinstance(link, Dependency):
        p, c = link.producer, link.consumer
        if link.via == "list":
            # ``how`` is the written path's, relative to the listed one.
            listed, written = c.expr.pattern, p.expr.pattern
            if how == "contains":
                text = (
                    f"{c} lists {listed}, inside {written}, which {p} writes, {phrase}"
                )
            else:
                text = f"{c} lists {listed}, where {p} writes {written}, {phrase}"
        else:
            text = f"{c} reads {_WHAT[how]} {p} writes, {phrase}: {_paths(c, p)}"
    elif isinstance(link, Hazard):
        r, d = link.reader, link.deleter
        verb = "reads" if "read" in r.verbs else "lists"
        text = (
            f"{d} deletes {_WHAT[_INVERSE[how]]} {r} {verb}, {phrase}, so {r.step}"
            f" runs first: {_paths(r, d)}"
        )
    else:
        x, y = link.first, link.second
        if not x.verbs or not y.verbs:
            u, o = (x, y) if not x.verbs else (y, x)
            text = (
                f"{u} declares no verbs, so it is kept apart from {o}, which may"
                f" touch its path, {phrase}: {_paths(x, y)}"
            )
        elif x.supplies != y.supplies:
            w, d = (x, y) if x.supplies else (y, x)
            rel = how if d is x else _INVERSE[how]  # the deleted path's
            text = f"{d} deletes {_WHAT[rel]} {w} writes, {phrase}: {_paths(w, d)}"
        else:
            verb = "write" if x.supplies else "delete"
            if how == "same":
                text = f"{x} and {y} {verb} one path, {phrase}: {_paths(x, y)}"
            else:
                inner, outer = (x, y) if how == "inside" else (y, x)
                text = (
                    f"{inner} {verb}s inside what {outer} {verb}s, {phrase}:"
                    f" {_paths(x, y)}"
                )
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
