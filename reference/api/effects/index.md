# wend.effects

Effects across a pipeline, before any binding (docs/SEMANTICS.md §15).

`EffectGraph` takes named steps (`wend.Step`) and relates what each declares it reads, lists, writes and deletes (`Step.effects`), with `wend.relate`:

- a *dependency* runs from a step that writes a path to one that reads or lists it;
- a *hazard* runs from a step that reads or lists a path to one that deletes it: the reader has to run first;
- a *conflict* is two steps that write one path, or delete it, or one that writes and one that deletes it, or a path declared with no verbs (whose effect is unknown) and another: they must not run at once.

A declared path covers what lies below it, since it may be a directory: each link holds when the two paths are one, or one is inside the other.

Each carries a certainty: `"always"` (on every run), `"sometimes"` (on some runs, with an example), or `"unknown"` (not ruled out). Pairs the analysis proves apart are not links at all, and every query but those given `certain=True` counts every other link, so a possible conflict is never taken for independence. By default a parameter name means one value across every step, as when the pipeline runs with one set of bindings (`shared=True`)::

```text
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
```

A step that creates a path may make its missing parents. The graph assumes it does so idempotently (as `os.makedirs(..., exist_ok=True)` does) unless it declares the directory as a port of its own. A check that a path may be created or written (`Creatable`, `Writable`) then conflicts with a creation below a directory above both that may be missing. A port requiring a directory to exist follows the steps that may make it. `existing` names the paths known to exist, which bounds both (docs/SEMANTICS.md §15.4).

What the graph knows is what the steps declare, and its guarantees hold only as far as the declarations describe what each step's code does: a step's code can read or write anything, and a path read without `Readable` declared is not an input here. Two steps in one stage cannot interfere through their declared effects; that is no promise about effects a step has and does not declare. Paths are compared as rendered strings, not as filesystem objects, so two spellings of one file (a symlink, a relative and an absolute path, a `..`, a hard link) are two paths.

## ASSUMPTIONS

```python
ASSUMPTIONS = frozenset({'closed world', 'declared effects', 'lexical identity'})
```

What every `Obligation` rests on (docs/SEMANTICS.md §15.6): nothing outside the steps changes their paths while they run; each step's declarations describe what it does; and two spellings of one file are not two paths.

## Certainty

```python
Certainty = Literal['always', 'sometimes', 'never', 'unknown']
```

## Conflict

```python
Conflict(
    certainty: Certainty,
    _analysis: Analysis,
    _answers: tuple[tuple[How, Certainty], ...],
    *,
    first: Port,
    second: Port,
    via: Literal["path", "parent"] = "path",
    parent: PathExpr | None = None,
)
```

Bases: `_Link`

Two ports that may change what the other touches: two writes, a write and a deletion, or two deletions of one path or of paths one inside the other, or a port that declares no verbs (so its effect is unknown) and any port it touches (`via="path"`). Or two creations below a directory that may be missing, where one checks whether it may create its path: making the directory changes what that check finds (`via="parent"`; `parent` is the directory, when it is known). The steps must not run at once; for writes, which one wins depends on their order, which the graph does not choose.

### first

```python
first: Port = field(kw_only=True)
```

### second

```python
second: Port = field(kw_only=True)
```

### via

```python
via: Literal['path', 'parent'] = field(default='path', kw_only=True)
```

### parent

```python
parent: PathExpr | None = field(default=None, kw_only=True, compare=False)
```

## Dependency

```python
Dependency(
    certainty: Certainty,
    _analysis: Analysis,
    _answers: tuple[tuple[How, Certainty], ...],
    *,
    producer: Port,
    consumer: Port,
    via: Via,
)
```

Bases: `_Link`

`consumer` reads (`via="read"`) or lists (`via="list"`) a path that is, holds, or lies inside one `producer` writes; or requires a path to exist (`via="exists"`) that `producer` may create, as that path or as a directory above one it creates.

### producer

```python
producer: Port = field(kw_only=True)
```

### consumer

```python
consumer: Port = field(kw_only=True)
```

### via

```python
via: Via = field(kw_only=True)
```

## EffectGraph

```python
EffectGraph(
    steps: Mapping[str, Step],
    *,
    shared: bool = True,
    builtin_values: bool = False,
    existing: Iterable[PathExpr | str] = (),
)
```

What a set of named steps declare they do to their paths, related before any binding (see the module docstring).

`shared=True` (the default) gives a parameter name one value across every step; `shared=False` relates every binding of one step to every binding of another, as when steps run with bindings of their own. `builtin_values=True` assumes bound values are of builtin types, which proves more paths apart (`wend.relate`).

`existing` names paths (expressions or strings) that exist before the pipeline runs and that no step deletes: no step makes them, or a directory above them, as a missing parent. Without it, any directory above a created path may be missing, except the anchor (`/` or the working directory). A step that may delete one of them, or a directory above it, raises ValueError.

### steps

```python
steps: dict[str, Step] = dict(steps)
```

### shared

```python
shared = shared
```

### builtin\_values

```python
builtin_values = builtin_values
```

### existing

```python
existing: list[PathExpr] = [
    e if isinstance(e, PathExpr) else P(e) for e in existing
]
```

### ports

```python
ports: list[Port] = [
    Port(name, e.name, e.expr, e.verbs)
    for name, step in self.steps.items()
    for e in step.effects()
]
```

### unassigned

```python
unassigned: list[Port] = [p for p in self.ports if not p.verbs]
```

### edges

```python
edges: list[Dependency] = []
```

### hazards

```python
hazards: list[Hazard] = []
```

### conflicts

```python
conflicts: list[Conflict] = []
```

### dependencies

```python
dependencies(*, certain: bool = False) -> dict[str, set[str]]
```

For each step, the steps whose writes it may read or list.

`certain=True` keeps the dependencies that hold on every run (under which both steps' paths render). Use the default, which also counts those that hold on some runs or are not ruled out, to decide what may run independently.

### order

```python
order() -> list[str] | None
```

The steps in an order where each follows every step it may depend on, and every deleter follows the readers of what it deletes; ties keep the order the steps were given in.

Every link counts, whatever its certainty: a dependency that holds on some runs, or that is only not ruled out, orders the steps as one that holds on every run does. None if these links form a cycle: `cycles` lists the cycles, and `cycles(certain=True)` those made of links that hold on every run, which no binding avoids. Conflicts do not order steps: which writer wins is the caller's choice, and a port that declares no verbs is kept apart from others (`stages`) but not ordered.

### stages

```python
stages() -> list[list[str]] | None
```

The steps in groups that may run at the same time: each group follows every step it may depend on, and no two steps in a group are joined by any link, whatever its certainty. None if the steps form a cycle (see `order`).

That two steps share a stage means their *declared* effects cannot interfere, with parents not declared made idempotently (docs/SEMANTICS.md §15.4). It is no promise about what a step's code does beyond its declarations.

### independent

```python
independent(x: str, y: str) -> bool
```

Whether no link joins steps `x` and `y`: no dependency, hazard or conflict between them holds always, sometimes, or is even not ruled out. Their declared paths, compared as strings, then never meet nor nest where either one writes, deletes, or has no known effect, and no creation check of one depends on a directory the other may make. Independent steps may run in either order, or at once, so far as their declarations go: a step's code may touch paths it does not declare, and two spellings of one file are two paths here.

### links

```python
links(x: str, y: str | None = None) -> list[Dependency | Hazard | Conflict]
```

The dependencies, hazards and conflicts between `x` and `y`, in either direction; with `y` omitted, every one involving `x`.

### explain

```python
explain(x: str, y: str | None = None) -> list[str]
```

One sentence per link between `x` and `y` (or involving `x`): which port relates to which, how surely, and an example when one is known.

### cycles

```python
cycles(*, certain: bool = False) -> list[list[str]]
```

Groups of two or more steps that must each run, through the others, before themselves, by the dependencies and hazards `order` follows. When there is one, `order` and `stages` are None.

`certain=True` keeps the links that hold on every run (under which their paths render): a cycle among them is unavoidable. A cycle found only without it is possible, not proved: it rests on a link that holds on some runs, or is only not ruled out, so it may depend on the bindings, as with `shared=False`, where a step that reads `{day}` and writes `{day}` of another run is one.

### self\_loops

```python
self_loops() -> list[Dependency]
```

Dependencies from a step to itself: it may read what it writes.

### external\_inputs

```python
external_inputs() -> list[Port]
```

Inputs no step writes: the paths the pipeline needs from outside.

### terminal\_outputs

```python
terminal_outputs() -> list[Port]
```

Paths written that no step reads: the pipeline's results.

### obligations

```python
obligations(
    schedule: Sequence[str] | Sequence[Sequence[str]] | None = None,
) -> list[Obligation]
```

For every atom each port requires, what it relies on (`Obligation`), when the steps run by `schedule`: an order of step names, or groups (as `stages` gives) whose steps may interleave in any way. The default is `stages`. Raises ValueError if the steps form a cycle and no schedule is given.

A run knows an atom of a path from the moment a check of it passes (a step's precondition, or its postcondition once it completes) until a declared mutation that may touch the path. A fact is of the paths the relation proves the same on every run, or proves below a path known to exist (which then exists, as a directory), or above one known absent. Static identity is not freshness: a fact about one spelling holds of another only while no step that may run in between declares a change to either, and only under `ASSUMPTIONS`.

### compare

```python
compare(records: Iterable[Any]) -> dict[str, list[tuple[str, str]]]
```

Observed lineage (the `wend.lineage.Record` objects a `Ledger` writes) against the declarations. A record names its step by `operation` (`repr(step)`, as `Ledger.run` records it).

Returns `undeclared`: observed dependencies (a record's input was a record's output) between steps the graph proves apart, which means a declaration is wrong or incomplete; and `unobserved`: dependencies declared to hold on every run that no record shows (informational: a run need not exercise them). Raises ValueError if two steps have one repr, since their records would be indistinguishable.

## Example

```python
Example(
    how: How,
    a_path: str,
    b_path: str,
    a_bindings: dict[str, Any],
    b_bindings: dict[str, Any],
)
```

Bindings under which a relation shows, and the paths each side renders with them. Under shared bindings the two bindings agree on every common name.

### how

```python
how: How
```

### a\_path

```python
a_path: str
```

### b\_path

```python
b_path: str
```

### a\_bindings

```python
a_bindings: dict[str, Any]
```

### b\_bindings

```python
b_bindings: dict[str, Any]
```

## Hazard

```python
Hazard(
    certainty: Certainty,
    _analysis: Analysis,
    _answers: tuple[tuple[How, Certainty], ...],
    *,
    reader: Port,
    deleter: Port,
)
```

Bases: `_Link`

`deleter` deletes the path `reader` reads or lists, a directory above it, or a path inside it: `reader` has to run first.

### reader

```python
reader: Port = field(kw_only=True)
```

### deleter

```python
deleter: Port = field(kw_only=True)
```

## Obligation

```python
Obligation(port: Port, atom: str, status: ObligationStatus, by: Port | None = None)
```

What one atom a port requires relies on, under `ASSUMPTIONS`.

`status` is `"discharged"` when an earlier step's passed check or confirmed promise (`by`) makes it true of the path on every run, and no step that may run in between may change it; `"refuted"` when such a fact makes it false: the check fails wherever both paths render; `"at risk"` when `by` may refute it, or may have changed a path it was known of; and `"external"` when nothing in the pipeline establishes it, so the world must provide it. A path given to the graph as `existing` is a fact too: `by` is then a port of no step (`by.step == ""`).

### port

```python
port: Port
```

### atom

```python
atom: str
```

### status

```python
status: ObligationStatus
```

### by

```python
by: Port | None = None
```

## Port

```python
Port(step: str, name: str, expr: PathExpr, verbs: frozenset[str])
```

One declared path of one step, with the verbs it declares.

### step

```python
step: str
```

### name

```python
name: str
```

### expr

```python
expr: PathExpr
```

### verbs

```python
verbs: frozenset[str]
```

### supplies

```python
supplies: bool
```

Whether the step writes or creates this path.

### deletes

```python
deletes: bool
```

Whether the step deletes this path.

### is\_input

```python
is_input: bool
```

Whether the step reads this path or lists it.

### requires

```python
requires: frozenset[str]
```

The atoms the step requires of this path before it runs.

### observes

```python
observes: bool
```

Whether the step requires this path to exist (`Exists`): it follows any step that may create it, as a path or as a directory above one, and precedes any step that may delete it.

### checks\_creation

```python
checks_creation: bool
```

Whether the step checks that it may create or write this path (`Creatable` or `Writable`). For a missing path the answer depends on which directories above it exist.

## Relation

```python
Relation(
    same: Certainty,
    inside: Certainty,
    contains: Certainty,
    shared: bool = True,
    examples: tuple[Example, ...] = (),
    assumptions: frozenset[str] = frozenset(),
)
```

How two path families relate (docs/SEMANTICS.md §15).

`same`, `inside` and `contains` are each `"always"` (for every binding under which both render), `"sometimes"` (for one at least: see `examples`), `"never"`, or `"unknown"` (neither was proved). `inside` is `a` strictly below `b`; `contains`, strictly above. Each compares the rendered strings, not the files they may name.

### same

```python
same: Certainty
```

### inside

```python
inside: Certainty
```

### contains

```python
contains: Certainty
```

### shared

```python
shared: bool = True
```

### examples

```python
examples: tuple[Example, ...] = ()
```

### assumptions

```python
assumptions: frozenset[str] = frozenset()
```

### \_\_getitem\_\_

```python
__getitem__(how: How) -> Certainty
```

### kind

```python
kind: Summary
```

The relation in one word: `"same"`, `"inside"` or `"contains"` when that holds always; `"disjoint"` when the paths never meet nor nest; `"overlapping"` when some binding shows one of the three; else `"unknown"`.

### disjoint

```python
disjoint: bool
```

Whether the two rendered paths never meet nor nest, as strings: no path is both, nor one inside the other. Two spellings of one file (a symlink, `..`, a relative and an absolute path) are not seen.

## relate

```python
relate(
    a: Any, b: Any, *, shared: bool = True, builtin_values: bool = False
) -> Relation
```

How the paths `a` and `b` render relate, before any binding.

The paths are compared as strings (lexically), not as filesystem objects: `"never"` means never the same string, and a symlink or a `..` can still make two strings name one file.

`a` and `b` are expressions, unions or path strings. With `shared=True` (the default) a parameter name common to both takes one value, as the paths of one run of a pipeline do; `shared=False` relates every binding of `a` to every binding of `b`. `builtin_values=True` assumes bound values are of builtin types, which proves more paths apart (docs/SEMANTICS.md §15).

> > > from wend import P, Param, T root, day = Param("root"), Param("day") raw = P(root) / "raw" / T(t"{day}.csv") relate(raw, P(root) / "clean" / T(t"{day}.csv")).kind 'disjoint' relate(raw, P(root) / "raw").inside 'always'
