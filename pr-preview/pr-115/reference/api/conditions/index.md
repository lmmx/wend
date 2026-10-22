# wend.conditions

Conditions: what a path must be, and may be used for, when it is realised.

An expression can declare conditions about the filesystem (`Exists`, `Absent`), about the kind of thing it names (`File`, `Dir`), about how it will be used (`Readable`, `Writable`, `Creatable`, `Listable`) and about where it may lead (`Under(base)`)::

```text
src = (P(root) / "raw" / T(t"{name}.csv")).requires(File, Exists, Readable)
dst = (P(root) / "out" / T(t"{name}.parquet")).requires(Absent, Creatable)
dst = dst.ensures(File, Exists)
```

`PathExpr.render` stays pure: the only condition it enforces is the lexical part of `Under`, which needs no filesystem. Everything else is checked by an explicit step, `PathExpr.check` (preconditions) and `PathExpr.confirm` (postconditions), or by a `Step` that groups the paths of one pipeline step.

Checks are point in time. A path that exists when it is checked may be gone when it is opened, and a symlink may be swapped between the two: checks describe and catch mistakes, they are not a sandbox and do not prevent races. See docs/SEMANTICS.md §10.

## Absent

```python
Absent: Final[Condition[Literal['absent'], Literal['absent']]] = Condition('Absent')
```

Nothing occupies the path's name, not even a broken symlink.

## Condition

```python
Condition(name: str)
```

Bases: `Generic[Pre, Post]`

A property of a path, checked when the path is realised. For a type checker it adds its atom `Pre` to what an expression requires, and `Post` to what it ensures (the same atom, for every condition).

### name

```python
name = name
```

### \_\_call\_\_

```python
__call__(
    path: Any, /, *, optional: bool = False, many: bool = False, open: bool = False
) -> Entry
```

`File(path, ...)` and `Dir(path, ...)` declare a schema entry (see `wend.schema`): a relative path that names a file or directory, with its cardinality. Other conditions are not callable.

## Creatable

```python
Creatable: Final[Condition[Literal["create"], Literal["create"]]] = Condition(
    "Creatable"
)
```

The path exists, or could be created now: its nearest existing ancestor is a directory the process may write to and search.

## Declarations

Bases: `NamedTuple`

What an expression declares (docs/SEMANTICS.md §10.1): the atoms it requires before it is used, the atoms it ensures after it is produced, and the bases it is declared `Under`.

A declaration is an obligation, not a fact about the filesystem. Only containment holds of every path the expression renders (`render` checks it); every other atom holds when a check finds it, at that moment.

### requires

```python
requires: frozenset[str]
```

### ensures

```python
ensures: frozenset[str]
```

### under

```python
under: tuple[PathExpr, ...]
```

### verbs

```python
verbs: frozenset[str]
```

The effects declared (what `Step.effects` reports): each permission in either phase, `create` for `exists` ensured but not required, and `delete` for `absent` ensured but not required.

### \_\_and\_\_

```python
__and__(other: object) -> Declarations
```

What both declare: the atoms of each phase in both, and the bases both are declared under.

## Dir

```python
Dir: Final[Condition[Literal['dir'], Literal['dir']]] = Condition('Dir')
```

The path names a directory: if it exists it is one.

## Effect

Bases: `NamedTuple`

What a step may do to one of its paths, as declared.

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

## Exists

```python
Exists: Final[Condition[Literal['exists'], Literal['exists']]] = Condition('Exists')
```

Something exists at the path (symlinks are followed).

## File

```python
File: Final[FileCondition] = FileCondition('File')
```

The path names a regular file: if it exists it is one, and nothing can be joined below it. Add `Exists` to require that it exists.

## Listable

```python
Listable: Final[Condition[Literal['list'], Literal['list']]] = Condition('Listable')
```

The path is an existing directory the process may list.

## Readable

```python
Readable: Final[Condition[Literal['read'], Literal['read']]] = Condition('Readable')
```

The path exists and the process may read it.

## Step

```python
Step(paths: Mapping[str, Any] | None = None, /, **named: Any)
```

The paths one step of a pipeline uses, with their conditions.

A single declaration of what must hold before the step runs (each path's `requires`) and after it finishes (each path's `ensures`)::

```text
convert = Step(src=src, dst=dst)
with convert(root="/data", name="a") as p:
    write(transform(read(p["src"])), p["dst"])
```

Entering checks every precondition and yields the rendered paths; leaving without an exception checks every postcondition. The bindings are shared: each path takes the parameters it uses.

### paths

```python
paths: dict[str, PathExpr] = {k: _coerce(v, at_head=True) for k, v in {**paths or {}, **named}.items()}
```

### param\_names

```python
param_names: frozenset[str]
```

### pattern

```python
pattern: str
```

### check

```python
check(mapping: Any = None, /, *, fs: Any = None, **kw: Any) -> dict[str, Path]
```

Render every path and check its preconditions, in declaration order, on `fs` (a `wend.fs` filesystem; the local disk by default).

### confirm

```python
confirm(mapping: Any = None, /, *, fs: Any = None, **kw: Any) -> dict[str, Path]
```

Render every path and check its postconditions, in declaration order, on `fs`.

### \_\_call\_\_

```python
__call__(
    mapping: Any = None, /, *, fs: Any = None, **kw: Any
) -> Iterator[dict[str, Path]]
```

### effects

```python
effects() -> list[Effect]
```

The filesystem effects each path declares: `read`, `write`, `create`, `list` (capabilities), plus `create` for a path that must exist afterwards but need not before, and `delete` for one that must be absent afterwards but need not be before. Paths declaring none are listed with no verbs. This reports declarations, not behaviour.

## Under

```python
Under(base: L)
```

```python
Under(base: str | PathLike[str] | Param | PathExpr[Any, Any, Any])
```

Bases: `Condition['Under[B] | Under[str]', 'Under[B] | Under[str]']`, `Generic[B]`

The path stays under `base`: lexically when it is rendered, and after resolving symlinks when it is checked.

`base` is rendered with the same bindings as the path, so its parameters must be among the path's. Lexically, the path must start with the base's components and have no `..` after them.

For a type checker, a literal string base gives the atom its identity (`Under[Literal["/srv/static"]]`); every base, literal or not, also declares `Under[str]`, "under its own base".

### base

```python
base: PathExpr
```

### name

```python
name: str
```

## Writable

```python
Writable: Final[Condition[Literal['write'], Literal['write']]] = Condition('Writable')
```

The process may write the path: it exists and is writable, or it is `Creatable`.
