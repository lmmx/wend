# wend.effects

Effects across a pipeline, before any binding (docs/SEMANTICS.md §15).

`EffectGraph` takes named steps (`wend.Step`) and relates what each declares it reads, lists, writes and deletes (`Step.effects`), with `wend.relate`:

- a *dependency* runs from a step that writes a path to one that reads it, or lists the directory it is in;
- a *hazard* runs from a step that reads a path to one that deletes it, or a directory above it: the reader has to run first;
- a *conflict* is two steps that write one path, or one that writes a path another deletes.

Each carries a certainty: `"always"` (on every run), `"sometimes"` (on some runs, with an example), or `"unknown"` (not ruled out). Pairs the analysis proves apart are not links at all. By default a parameter name means one value across every step, as when the pipeline runs with one set of bindings (`shared=True`)::

```text
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
```

What the graph knows is what the steps declare: a step's code can read or write anything, and a path read without `Readable` declared is not an input here. Paths are compared as strings, so two spellings of one file (a symlink, a relative and an absolute path, a `..`) are two paths.

## Certainty

```python
Certainty = Literal['always', 'sometimes', 'never', 'unknown']
```

## Conflict

```python
Conflict(
    certainty: Certainty,
    _analysis: Analysis,
    _hows: tuple[How, ...],
    *,
    first: Port,
    second: Port,
)
```

Bases: `_Link`

Two ports that write one path, or a write and a deletion of it (or of a directory above it): the steps must not run at once, and which one wins depends on their order.

### first

```python
first: Port = field(kw_only=True)
```

### second

```python
second: Port = field(kw_only=True)
```

## Dependency

```python
Dependency(
    certainty: Certainty,
    _analysis: Analysis,
    _hows: tuple[How, ...],
    *,
    producer: Port,
    consumer: Port,
    via: Via,
)
```

Bases: `_Link`

`consumer` reads the path `producer` writes (`via="read"`), or lists the directory it is in (`via="list"`).

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
    steps: Mapping[str, Step], *, shared: bool = True, builtin_values: bool = False
)
```

What a set of named steps declare they do to their paths, related before any binding (see the module docstring).

`shared=True` (the default) gives a parameter name one value across every step; `shared=False` relates every binding of one step to every binding of another, as when steps run with bindings of their own. `builtin_values=True` assumes bound values are of builtin types, which proves more paths apart (`wend.relate`).

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

For each step, the steps whose writes it may read.

`certain=True` keeps the dependencies that hold on every run (under which both steps' paths render). Use the default, which also counts those that hold on some runs or are not ruled out, to decide what may run independently.

### order

```python
order() -> list[str] | None
```

The steps in an order where each follows every step it may depend on, and every deleter follows the readers of what it deletes; ties keep the order the steps were given in. None if they form a cycle (`cycles`). Conflicts do not order steps: which writer wins is the caller's choice.

### stages

```python
stages() -> list[list[str]] | None
```

The steps in groups that may run at the same time: each group follows every step it may depend on, and no two steps in a group conflict. None if the steps form a cycle.

### independent

```python
independent(x: str, y: str) -> bool
```

Whether steps `x` and `y` cannot interact: neither may read what the other writes, nor delete what it reads, nor write what it writes or deletes. Independent steps may run in either order, or at once.

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

Groups of two or more steps that each depend, through the others, on themselves. A cycle among declarations need not be a cycle on a run: with `shared=False`, a step that reads `{day}` and writes `{day}` of another is one.

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
    _hows: tuple[How, ...],
    *,
    reader: Port,
    deleter: Port,
)
```

Bases: `_Link`

`deleter` deletes the path `reader` reads or lists, or a directory above it: `reader` has to run first.

### reader

```python
reader: Port = field(kw_only=True)
```

### deleter

```python
deleter: Port = field(kw_only=True)
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

`same`, `inside` and `contains` are each `"always"` (for every binding under which both render), `"sometimes"` (for one at least: see `examples`), `"never"`, or `"unknown"` (neither was proved). `inside` is `a` strictly below `b`; `contains`, strictly above.

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

Whether the two paths never meet nor nest: they cannot interact.

## relate

```python
relate(
    a: Any, b: Any, *, shared: bool = True, builtin_values: bool = False
) -> Relation
```

How the paths `a` and `b` render relate, before any binding.

`a` and `b` are expressions, unions or path strings. With `shared=True` (the default) a parameter name common to both takes one value, as the paths of one run of a pipeline do; `shared=False` relates every binding of `a` to every binding of `b`. `builtin_values=True` assumes bound values are of builtin types, which proves more paths apart (docs/SEMANTICS.md §15).

> > > from wend import P, Param, T root, day = Param("root"), Param("day") raw = P(root) / "raw" / T(t"{day}.csv") relate(raw, P(root) / "clean" / T(t"{day}.csv")).kind 'disjoint' relate(raw, P(root) / "raw").inside 'always'
