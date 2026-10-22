# wend.schema

Directory schemas: declare a project's layout once, then bind, validate and scaffold it.

A schema is a class whose attributes are entries, each a relative path (a string, t-string or expression) that names a file or a directory::

```text
from wend import Dir, File, Param, T
from wend.schema import Tree

index = Param("index", type=int)

class MLProject(Tree):
    data = Dir("data")
    raw = Dir(data / "raw")
    processed = Dir(data / "processed")
    models = Dir("models")
    checkpoints = File(models / T(t"model-{index:03d}.pt"), many=True)
    config = File("config.yaml")

project = MLProject("/srv/project")
project.config            # PathExpr('/srv/project/config.yaml', requires=(File, Exists))
project.validate()        # a Report: missing, extra, misfiled, wrong-kind ... paths
project.scaffold()        # creates the directories (an explicit effect)
```

An entry's *cardinality* says how many paths matching it each directory that matches its parent holds: exactly one by default, `optional=True` for at most one, `many=True` for any number, both for "zero or more". Entries are expressions, so one can be built from another (`data / "raw"`) and the relation is kept: a bound schema's `raw` has `data` as its base.

`from_inferred` turns an inferred `wend.infer.Schema` into a schema class, and `Tree.source` prints a schema as Python, so a layout can be inferred from a tree, reviewed, edited and kept as code. See docs/SEMANTICS.md §12.

## Cardinality

Bases: `Enum`

How many paths matching an entry each directory matching its parent holds, as UML multiplicities.

The lower bound is zero when `optional`, and the upper bound is more than one when `many`. A schema entry declares the two flags; an inferred layout (`wend.infer.Layout`) observes them, and reports its cardinality with this same type.

### ONE

```python
ONE = '1'
```

### OPTIONAL

```python
OPTIONAL = '0..1'
```

### AT\_LEAST\_ONE

```python
AT_LEAST_ONE = '1..*'
```

### MANY

```python
MANY = '0..*'
```

### of

```python
of(*, optional: bool, many: bool) -> Cardinality
```

The cardinality with these bounds.

## Entry

```python
Entry(
    path: Any,
    kind: str,
    *,
    optional: bool = False,
    many: bool = False,
    open: bool = False,
)
```

One declared path of a schema: made by `File(path, ...)` or `Dir(path, ...)`. On a bound schema instance, the attribute is the entry's expression under the instance's root.

### expr

```python
expr = expr
```

### kind

```python
kind = kind
```

### optional

```python
optional = optional
```

### many

```python
many = many
```

### open

```python
open = open
```

### name

```python
name = ''
```

### \_\_truediv\_\_

```python
__truediv__(other: Any) -> PathExpr
```

The entry's expression joined with `other`, for building one entry from another: `raw = Dir(data / "raw")`.

### cardinality

```python
cardinality: Cardinality
```

### condition

```python
condition: Any
```

## Problem

```python
Problem(kind: str, path: str, entry: str | None, detail: str = '')
```

One way a tree departs from its schema.

`kind` is one of: - `"missing"`: an entry has fewer paths than its cardinality allows (`path` is where one was expected); - `"too-many"`: a directory holds more than one path of a single-path entry; - `"wrong-kind"`: a path matches an entry but is a file where a directory is declared, or the reverse; - `"extra"`: a path no entry describes (the topmost one, not each path below it); - `"misfiled"`: an extra path whose name matches an entry, somewhere else.

`entry` names the entry concerned (for an extra path, the nearest directory entry above it, if any).

### kind

```python
kind: str
```

### path

```python
path: str
```

### entry

```python
entry: str | None
```

### detail

```python
detail: str = ''
```

## Report

```python
Report(
    root: str,
    problems: list[Problem],
    matches: dict[str, list[Any]],
    overlaps: dict[str, list[str]] | None = None,
)
```

The result of `Tree.validate`: every problem found, every entry's matches, and the paths more than one entry matches (`overlaps`, which a schema may intend: a literal exception beside a general pattern).

### root

```python
root = root
```

### problems

```python
problems = problems
```

### matches

```python
matches = matches
```

### overlaps

```python
overlaps = overlaps or {}
```

### ok

```python
ok: bool
```

### of

```python
of(kind: str) -> list[Problem]
```

## Tree

```python
Tree(root: Any, /, **bindings: Any)
```

Base class of directory schemas (see the module docstring).

Subclass it with `Entry` attributes (`File(...)`, `Dir(...)`). `ignore` lists patterns, relative to the root, whose paths (and everything below them) validation does not look at; with `hidden = False` it does not look at names starting with `.` either.

### entries

```python
entries: dict[str, Entry] = {}
```

### ignore

```python
ignore: tuple[Any, ...] = ()
```

### hidden

```python
hidden: bool = True
```

### root

```python
root = _coerce(root, at_head=True)
```

### bindings

```python
bindings = bindings
```

### paths

```python
paths() -> dict[str, PathExpr]
```

Every entry's expression under this root.

### validate

```python
validate() -> Report
```

Compare the tree on disk with the schema, now (an effect).

Every problem is reported, not just the first. The tree is observed as `infer` observes it: real directories are descended, a symlinked directory is neither descended nor reported as extra (an entry can still match it), and a symlink counts as a file or a directory by what it points to.

### scaffold

```python
scaffold(*, files: bool = False, dry_run: bool = False) -> list[Path]
```

Create the schema's directories under the root (an effect), and, with `files=True`, an empty file for each required file entry.

An entry with unbound parameters is created once per combination of their declared `choices`, and skipped if one has none. Existing paths are left alone; nothing is overwritten. Returns the paths created (or, with `dry_run`, that would be).

### source

```python
source(name: str | None = None) -> str
```

The schema as Python source: parameter declarations, then a class.

## from\_inferred

```python
from_inferred(
    schema: Schema, name: str = "Inferred", *, hidden: bool = False
) -> type[Tree]
```

A schema class with one entry per layout of an inferred schema.

Each entry keeps its layout's kind, pattern and cardinality (the layout's observed `optional` and `many`), so the class validates the tree it was inferred from. `hidden` should match the `include_hidden` the schema was inferred with.
