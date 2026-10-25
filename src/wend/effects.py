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
    graph = EffectGraph(
        {
            "ingest": Step(out=raw.ensures(Exists)),
            "clean": Step(src=raw.requires(Readable), dst=clean.requires(Creatable)),
        },
        existing=[P(root)],  # the data root exists before the pipeline runs
    )
    graph.order()  # ['ingest', 'clean']

A step that creates a path may make its missing parents. The graph assumes it
does so idempotently (as ``os.makedirs(..., exist_ok=True)`` does) unless it
declares the directory as a port of its own. A check that a path may be
created or written (``Creatable``, ``Writable``) then conflicts with a creation
below a directory above both that may be missing. A port requiring a
directory to exist follows the steps that may make it. ``existing`` names the
paths known to exist, which bounds both (docs/SEMANTICS.md §15.4).

What the graph knows is what the steps declare, and its guarantees hold only
as far as the declarations describe what each step's code does: a step's
code can read or write anything, and a path read without ``Readable``
declared is not an input here. Two steps in one stage cannot interfere
through their declared effects; that is no promise about effects a step has
and does not declare. Paths are compared as rendered strings, not as filesystem objects, so
two spellings of one file (a symlink, a relative and an absolute path, a
``..``, a hard link) are two paths.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from ._expr import Deferred, HeadParam, P, PathExpr, Root, Seg, _Rel
from ._relate import (
    Analysis,
    Certainty,
    Example,
    How,
    Relation,
    _common,
    _key,
    _static,
    _value_key,
    _view,
    either,
    relate,
)
from .conditions import Step


SUPPLY_VERBS = frozenset({"create", "write"})
DELETE_VERBS = frozenset({"delete"})
INPUT_VERBS = frozenset({"read", "list"})
CHECKS_CREATION = frozenset({"create", "write"})
Via = Literal["read", "list", "exists"]
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

    @property
    def requires(self) -> frozenset[str]:
        """The atoms the step requires of this path before it runs."""
        return self.expr.declares.requires

    @property
    def observes(self) -> bool:
        """Whether the step requires this path to exist (``Exists``): it
        follows any step that may create it, as a path or as a directory
        above one, and precedes any step that may delete it."""
        return "exists" in self.requires

    @property
    def checks_creation(self) -> bool:
        """Whether the step checks that it may create or write this path
        (``Creatable`` or ``Writable``). For a missing path the answer
        depends on which directories above it exist."""
        return bool(self.requires & CHECKS_CREATION)

    def __str__(self) -> str:
        return f"{self.step}.{self.name}"

    def __repr__(self) -> str:
        verbs = ", ".join(sorted(self.verbs)) or "no verbs"
        return f"<{self}: {verbs} {self.expr.pattern}>"


@dataclass(frozen=True)
class _Link:
    certainty: Certainty
    _analysis: Analysis = field(repr=False, compare=False)
    # The answer each relation gave the link, in the order asked.
    _answers: tuple[tuple[How, Certainty], ...] = field(repr=False, compare=False)

    def _how(self) -> How:
        """How the first port's path relates to the second's in the answer
        that gives the link its certainty."""
        for how, c in self._answers:
            if c == self.certainty:
                return how
        return self._answers[0][0] if self._answers else "same"

    def example(self) -> Example | None:
        """Bindings under which the link shows, when it holds always or
        sometimes: the paths both ports render with them."""
        for how, c in self._answers:
            if c in ("always", "sometimes"):
                ex = self._analysis.example(how)
                if ex is not None:
                    return ex
        return None


@dataclass(frozen=True)
class Dependency(_Link):
    """``consumer`` reads (``via="read"``) or lists (``via="list"``) a path
    that is, holds, or lies inside one ``producer`` writes; or requires a
    path to exist (``via="exists"``) that ``producer`` may create, as that
    path or as a directory above one it creates."""

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
    any port it touches (``via="path"``). Or two creations below a directory
    that may be missing, where one checks whether it may create its path:
    making the directory changes what that check finds (``via="parent"``;
    ``parent`` is the directory, when it is known). The steps must not run
    at once; for writes, which one wins depends on their order, which the
    graph does not choose."""

    first: Port = field(kw_only=True)
    second: Port = field(kw_only=True)
    via: Literal["path", "parent"] = field(default="path", kw_only=True)
    parent: PathExpr | None = field(default=None, kw_only=True, compare=False)

    def __repr__(self) -> str:
        return f"<{self.first} x {self.second}: {self.certainty}>"


ObligationStatus = Literal["discharged", "refuted", "at risk", "external"]

# The atoms a run can know of a path once a check of them passed, until a
# declared mutation may change it. Whether a path may be created or written
# depends on its ancestors and permissions at the moment, so those checks are
# never discharged.
_KEPT = frozenset({"exists", "absent", "file", "dir", "read", "list"})
# Atoms one path cannot have at once. File and Dir exclude each other only for
# a path that exists (§10: both hold of a missing path).
_EXCLUSIVE = (
    ("exists", "absent"),
    ("absent", "read"),
    ("absent", "list"),
    ("file", "list"),
)
ASSUMPTIONS = frozenset({"closed world", "declared effects", "lexical identity"})
"""What every `Obligation` rests on (docs/SEMANTICS.md §15.6): nothing outside
the steps changes their paths while they run; each step's declarations
describe what it does; and two spellings of one file are not two paths."""


@dataclass(frozen=True)
class Obligation:
    """What one atom a port requires relies on, under `ASSUMPTIONS`.

    ``status`` is ``"discharged"`` when an earlier step's passed check or
    confirmed promise (``by``) makes it true of the path on every run, and no
    step that may run in between may change it; ``"refuted"`` when such a fact
    makes it false: the check fails wherever both paths render; ``"at risk"``
    when ``by`` may refute it, or may have changed a path it was known of;
    and ``"external"`` when nothing in the pipeline establishes it, so the
    world must provide it."""

    port: Port
    atom: str
    status: ObligationStatus
    by: Port | None = None

    def __str__(self) -> str:
        what = f"{self.port} requires {self.atom} of {self.port.expr.pattern}"
        if self.status == "discharged":
            return f"{what}: discharged by {self.by}"
        if self.status == "refuted":
            return f"{what}: refuted by {self.by}, so the check fails"
        if self.status == "at risk":
            return f"{what}: at risk from {self.by}"
        return f"{what}: external, the world must provide it"


@dataclass(frozen=True)
class _Fact:
    atom: str
    port: Port  # whose path the fact is of, and whose check or promise made it


class EffectGraph:
    """What a set of named steps declare they do to their paths, related
    before any binding (see the module docstring).

    ``shared=True`` (the default) gives a parameter name one value across
    every step; ``shared=False`` relates every binding of one step to every
    binding of another, as when steps run with bindings of their own.
    ``builtin_values=True`` assumes bound values are of builtin types, which
    proves more paths apart (`wend.relate`).

    ``existing`` names paths (expressions or strings) that exist before the
    pipeline runs and that no step deletes: no step makes them, or a
    directory above them, as a missing parent. Without it, any directory
    above a created path may be missing, except the anchor (``/`` or the
    working directory). A step that may delete one of them, or a directory
    above it, raises ValueError.
    """

    def __init__(
        self,
        steps: Mapping[str, Step],
        *,
        shared: bool = True,
        builtin_values: bool = False,
        existing: Iterable[PathExpr | str] = (),
    ) -> None:
        self.steps: dict[str, Step] = dict(steps)
        self.shared = shared
        self.builtin_values = builtin_values
        self.existing: list[PathExpr] = [
            e if isinstance(e, PathExpr) else P(e) for e in existing
        ]
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
        inputs = [p for p in self.ports if p.is_input or p.observes]
        for e in self.existing:
            for d in deleters:
                a = self._analysis(d.expr, e)
                if a("same") != "never" or a("contains") != "never":
                    raise ValueError(
                        f"{d} may delete {e.pattern} or a directory above it, so"
                        " it cannot be given as existing"
                    )

        # A declared path covers what lies below it (it may be a directory),
        # so two ports touch when their paths are one, or one is inside the
        # other: every link asks all three.
        self.edges: list[Dependency] = []
        for c in inputs:
            vias = [v for v in ("read", "list") if v in c.verbs]
            for p in suppliers:
                for via in vias:
                    pair = (c, p) if via == "read" else (p, c)
                    self._link(Dependency, pair, producer=p, consumer=c, via=via)
                if not vias and p.step != c.step:
                    # An existence requirement follows the creation of its
                    # path, or of a path below it: making that path may make
                    # this one, as a missing parent. Whether it does depends
                    # on whether it was missing, so that link is "unknown",
                    # and none when the path is known to exist.
                    self._link(
                        Dependency,
                        (c, p),
                        parent="contains",
                        producer=p,
                        consumer=c,
                        via="exists",
                    )

        self.hazards: list[Hazard] = []
        for c in inputs:
            for d in deleters:
                if d.step == c.step:
                    continue  # a step that reads its own input, then deletes it
                self._link(Hazard, (c, d), reader=c, deleter=d)

        # Two ports of two steps conflict when either may change what the
        # other touches: two writers, a writer and a deleter, two deleters
        # (one may find the path gone), or a port whose effect is unknown
        # (no verbs, and no existence it requires) and any other.
        self.conflicts: list[Conflict] = []
        joined: set[tuple[int, int]] = set()
        unknown = [p for p in self.unassigned if not p.observes]
        changers = [p for p in self.ports if p.supplies or p.deletes] + unknown
        for n, x in enumerate(changers):
            for y in changers[n + 1 :]:
                if x.step == y.step:
                    continue
                if self._link(Conflict, (x, y), first=x, second=y):
                    joined.add((id(x), id(y)))
        for u in unknown:
            for r in inputs:
                if r.step != u.step and not (r.supplies or r.deletes):
                    self._link(Conflict, (u, r), first=u, second=r)

        # Parents a creation may make. A step that creates a path may make
        # the missing directories above it, which is assumed to be done
        # idempotently (as os.makedirs(..., exist_ok=True) does): two such
        # creations do not conflict. But a check that a path may be created
        # or written (Creatable, Writable) finds a different answer once a
        # directory above it is made, so a creation below a directory that
        # may be missing conflicts with such a check below the same one.
        checking = {id(p) for p in suppliers if p.checks_creation}
        for n, x in enumerate(suppliers):
            for y in suppliers[n + 1 :]:
                if id(x) not in checking and id(y) not in checking:
                    continue
                if x.step == y.step or (id(x), id(y)) in joined:
                    continue
                missing, parent = self._shared_parent(x.expr, y.expr)
                if missing:
                    a = self._analysis(x.expr, y.expr)
                    self.conflicts.append(
                        Conflict(
                            "unknown",
                            a,
                            (),
                            first=x,
                            second=y,
                            via="parent",
                            parent=parent,
                        )
                    )

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

    def _analysis(self, a: Any, b: Any) -> Analysis:
        key = (id(a), id(b))
        if key not in self._analyses:
            self._analyses[key] = Analysis(
                a,
                b,
                shared=self.shared,
                builtin_values=self.builtin_values,
                memo=self._memo,
            )
        return self._analyses[key]

    def _link(
        self,
        kind: type[Dependency] | type[Hazard] | type[Conflict],
        pair: tuple[Port, Port],
        *,
        parent: How | None = None,
        **ports: Any,
    ) -> Dependency | Hazard | Conflict | None:
        """Link ``pair`` by the relations of their paths. ``parent`` names a
        relation by which the first port's path holds a directory the
        second's step may make as a missing parent: it counts as "unknown"
        at most, and not at all when that path is known to exist."""
        if self._apart(*pair):
            return None
        a, b = pair
        analysis = self._analysis(a.expr, b.expr)
        answers: list[tuple[How, Certainty]] = []
        found: list[Certainty] = []
        for how in _TOUCH:
            c: Certainty = analysis(how)
            if how == parent and c != "never":
                c = "never" if self._exists(a.expr) else "unknown"
            answers.append((how, c))
            found.append(c)
            if c == "always":
                break
        certainty = either(*found)
        if certainty == "never":
            return None
        link = kind(certainty, analysis, tuple(answers), **ports)
        if isinstance(link, Dependency):
            self.edges.append(link)
        elif isinstance(link, Hazard):
            self.hazards.append(link)
        else:
            self.conflicts.append(link)
        return link

    def _exists(self, e: Any) -> bool:
        """Whether ``e`` exists throughout the pipeline: an anchor (``/`` or
        the working directory), or at or above a path given as existing."""
        if not isinstance(e, PathExpr):
            return False
        if not e.parts and isinstance(e.head, (Root, _Rel)):
            return True
        for x in self.existing:
            a = self._analysis(x, e)
            if a("same") == "always" or a("inside") == "always":
                return True
        return False

    def _shared_parent(self, a: Any, b: Any) -> tuple[bool, PathExpr | None]:
        """Whether a directory above both ``a`` and ``b`` (whose paths do not
        touch) may be missing; and the deepest such directory, when the
        structure says which one it is."""
        if not (isinstance(a, PathExpr) and isinstance(b, PathExpr)):
            return True, None
        # A changed name lies where its base's does (`wend.relate`'s view).
        a, b = _view(a, self._memo), _view(b, self._memo)
        k = _common(a, b, self.shared, self._memo)
        if k is None:
            return True, None
        ra, rb = a.parts[k:], b.parts[k:]
        if not ra or not rb:
            return True, None
        # The paths part at the first remaining part: two different literal
        # segments, or the last segment of each.
        diverge = _static(ra[0]) and _static(rb[0]) and ra[0].literal != rb[0].literal
        last = len(ra) == len(rb) == 1 and all(
            isinstance(x, Seg) for x in (ra[0], rb[0])
        )
        if not (diverge or last):
            return True, None
        parent = PathExpr(a.head, a.parts[:k])
        return not self._exists(parent), parent

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
        form a cycle (see `order`).

        That two steps share a stage means their *declared* effects cannot
        interfere, with parents not declared made idempotently
        (docs/SEMANTICS.md §15.4). It is no promise about what a step's code
        does beyond its declarations."""
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
        meet nor nest where either one writes, deletes, or has no known
        effect, and no creation check of one depends on a directory the
        other may make. Independent steps may run in either order, or at
        once, so far as their declarations go: a step's code may touch paths
        it does not declare, and two spellings of one file are two paths
        here."""
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

    def obligations(
        self, schedule: Sequence[str] | Sequence[Sequence[str]] | None = None
    ) -> list[Obligation]:
        """For every atom each port requires, what it relies on (`Obligation`),
        when the steps run by ``schedule``: an order of step names, or groups
        (as `stages` gives) whose steps may interleave in any way. The default
        is `stages`. Raises ValueError if the steps form a cycle and no
        schedule is given.

        A run knows an atom of a path from the moment a check of it passes
        (a step's precondition, or its postcondition once it completes) until
        a declared mutation that may touch the path. A fact is of the paths
        the relation proves the same on every run, or proves below a path
        known to exist (which then exists, as a directory), or above one known
        absent. Static identity is not freshness: a fact about one spelling
        holds of another only while no step that may run in between declares
        a change to either, and only under `ASSUMPTIONS`."""
        groups = self._schedule(schedule)
        known: list[_Fact] = []
        lost: list[tuple[_Fact, Port]] = []
        out: list[Obligation] = []
        ports = {s: [p for p in self.ports if p.step == s] for s in self.steps}
        changers = {
            s: [p for p in ps if p.supplies or p.deletes or not (p.verbs or p.observes)]
            for s, ps in ports.items()
        }
        for group in groups:
            for s in group:
                # Another step of the group may run first: what it may change
                # is not known here.
                others = [m for o in group if o != s for m in changers[o]]
                here, gone = self._forget(known, others)
                for p in ports[s]:
                    for atom in sorted(p.requires):
                        out.append(self._judge(p, atom, here, [*lost, *gone]))
            for s in group:
                for p in ports[s]:
                    known.extend(_Fact(a, p) for a in p.requires & _KEPT)
            for s in group:
                known, gone = self._forget(known, changers[s])
                lost.extend(gone)
            for s in group:
                others = [m for o in group if o != s for m in changers[o]]
                for p in ports[s]:
                    learned = [_Fact(a, p) for a in p.expr.declares.ensures & _KEPT]
                    kept, gone = self._forget(learned, others)
                    known.extend(kept)
                    lost.extend(gone)
        return out

    def _schedule(
        self, schedule: Sequence[str] | Sequence[Sequence[str]] | None
    ) -> list[list[str]]:
        if schedule is None:
            stages = self.stages()
            if stages is None:
                raise ValueError("the steps form a cycle: give a schedule")
            return stages
        groups = [[g] if isinstance(g, str) else list(g) for g in schedule]
        named = [s for g in groups for s in g]
        if sorted(named) != sorted(self.steps):
            raise ValueError("a schedule names every step once")
        return groups

    def _touches(self, a: Port, b: Port) -> bool:
        if self._apart(a, b):
            return False
        analysis = self._analysis(a.expr, b.expr)
        return any(analysis(how) != "never" for how in _TOUCH)

    def _forget(
        self, facts: list[_Fact], mutations: list[Port]
    ) -> tuple[list[_Fact], list[tuple[_Fact, Port]]]:
        """``facts`` split into those no mutation may change, and those one
        may, with the mutation."""
        kept, gone = [], []
        for f in facts:
            m = next((m for m in mutations if self._touches(f.port, m)), None)
            if m is None:
                kept.append(f)
            else:
                gone.append((f, m))
        return kept, gone

    def _holds(self, f: _Fact, p: Port, atom: str, *, certain: bool = True) -> bool:
        """Whether fact ``f`` makes ``atom`` true of ``p``'s path on every run
        under which both render; with ``certain=False``, on some run."""
        if self._apart(p, f.port):
            return False
        analysis = self._analysis(p.expr, f.port.expr)

        def proved(how: How) -> bool:
            answer = analysis(how)
            return answer == "always" if certain else answer != "never"

        if f.atom == atom and proved("same"):
            return True
        # A path below p's exists: p exists, as a directory.
        if atom in ("exists", "dir") and f.atom == "exists" and proved("contains"):
            return True
        # p's path is below an absent one: it is absent too.
        return atom == "absent" and f.atom == "absent" and proved("inside")

    def _judge(
        self,
        p: Port,
        atom: str,
        known: list[_Fact],
        lost: list[tuple[_Fact, Port]],
    ) -> Obligation:
        if atom not in _KEPT:
            return Obligation(p, atom, "external")
        for f in known:
            if self._holds(f, p, atom):
                return Obligation(p, atom, "discharged", f.port)
        excluded = [b if atom == a else a for a, b in _EXCLUSIVE if atom in (a, b)]
        if atom in ("file", "dir") and any(self._holds(f, p, "exists") for f in known):
            excluded.append("dir" if atom == "file" else "file")
        for other in excluded:
            for f in known:
                if self._holds(f, p, other):
                    return Obligation(p, atom, "refuted", f.port)
        for other in excluded:
            for f in known:
                if self._holds(f, p, other, certain=False):
                    return Obligation(p, atom, "at risk", f.port)
        for f, m in reversed(lost):
            if self._holds(f, p, atom):
                return Obligation(p, atom, "at risk", m)
        return Obligation(p, atom, "external")

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
        if link.via == "exists":
            if how == "contains":
                text = (
                    f"{c} requires {c.expr.pattern} to exist, which {p} may make as"
                    f" a missing directory above {p.expr.pattern}, {phrase}"
                )
            else:
                text = (
                    f"{c} requires {_WHAT[how]} {p} writes to exist, {phrase}:"
                    f" {_paths(c, p)}"
                )
        elif link.via == "list":
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
        if link.via == "parent":
            where = "a directory above both"
            if link.parent is not None:
                where = link.parent.pattern
            if x.checks_creation and y.checks_creation:
                return (
                    f"{x} and {y} each check they may create a path below {where},"
                    f" which either may make if it is missing: what each check"
                    f" finds depends on whether the other has, {phrase}:"
                    f" {_paths(x, y)}"
                )
            checker, other = (x, y) if x.checks_creation else (y, x)
            return (
                f"{other} may make {where} if it is missing, and {checker} checks"
                f" it may create {checker.expr.pattern}, which depends on whether"
                f" {where} exists, {phrase}: {_paths(x, y)}"
            )
        if not x.verbs or not y.verbs:
            u, o = (x, y) if not x.verbs else (y, x)
            text = (
                f"{u} declares no verbs nor that its path exists, so it is kept"
                f" apart from {o}, which may touch its path, {phrase}: {_paths(x, y)}"
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
        text += f" (e.g. {shown}: {rendered})" if shown else f" (e.g. {rendered})"
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
    "ASSUMPTIONS",
    "Certainty",
    "Conflict",
    "Dependency",
    "EffectGraph",
    "Example",
    "Hazard",
    "Obligation",
    "Port",
    "Relation",
    "relate",
]
