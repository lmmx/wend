# Effects

```python
from wend import Absent, Creatable, Exists, File, P, Param, Readable, T

root, day = Param("root"), Param("day")

src = (P(root) / "raw" / T(t"{day}.csv")).requires(File, Exists, Readable)
dst = (P(root) / "clean" / T(t"{day}.csv")).requires(Absent, Creatable)
dst = dst.ensures(File, Exists)
```

The directory `data/raw/` holds one file, `mon.csv`:

```pycon
>>> src.render(root="data", day="tue")
'data/raw/tue.csv'
>>> src.check(root="data", day="tue")
Traceback (most recent call last):
  ...
wend.errors.MissingPathError: 'data/raw/tue.csv' does not exist (required: Exists)
>>> src.check(root="data", day="mon")
PosixPath('data/raw/mon.csv')
```

`src` declares that its path must be an existing, readable file when it is used. `render` returns the path for `tue` although no such file exists, because it reads nothing from the filesystem. `check` renders the path, tests each condition against the filesystem, and raises for the first one that fails.

## Pure operations and effects

Building an expression, every path operation, `bind`, `render`, `resolve`, `match`, `match_all`, the [relations](<https://lmmx.github.io/wend/pr-preview/pr-129/concepts/relations/index.md>) and `compile` are pure. Their results depend only on the expression and the bindings.

These operations touch the filesystem:

- `glob` lists directories to find the paths an expression describes.
- `check` and `confirm` test an expression's conditions, and a `Step` tests those of several paths.
- `PathUnion.first` returns the first alternative of a union whose path exists and meets its own conditions.
- `Tree.validate` reads a directory tree and reports where it differs from a schema. `Tree.scaffold` creates the schema's directories, and empty files with `files=True`. It never overwrites a path.
- `Ledger` records which files were made from which, with digests of their contents, and reads the files again to say what is stale.

```python
from wend import Dir
from wend.schema import Tree


class Project(Tree):
    data = Dir("data")
    config = File("config.yaml")
```

```pycon
>>> project = Project("project")
>>> project.scaffold()
[PosixPath('project'), PosixPath('project/data')]
>>> project.validate()
Report('project': 1 missing)
  <missing 'project/config.yaml' [config]>
```

## Conditions

`requires` declares preconditions, which must hold before a path is used. `ensures` declares postconditions, which must hold after it has been produced. `check` tests the first and `confirm` the second.

| condition | holds when |
| --- | --- |
| `Exists` | the path exists (symlinks followed) |
| `Absent` | nothing is at the path, not even a broken symlink |
| `File` / `Dir` | the path is missing, or is a regular file / a directory |
| `Readable` | the path exists and can be read |
| `Listable` | the path is a directory that can be listed |
| `Writable` | the path exists and can be written, or is `Creatable` |
| `Creatable` | the path exists, or its nearest existing ancestor is a directory that entries can be created in |
| `Under(base)` | the path is lexically inside `base`, and resolving symlinks keeps it there |

Conditions are not part of the path. An expression with conditions equals the same expression without them:

```pycon
>>> src == P(root) / "raw" / T(t"{day}.csv")
True
>>> dst
PathExpr('{root}/clean/{day}.csv', requires=(Absent, Creatable), ensures=(File, Exists))
```

Conditions that cannot hold together in one phase, such as `Exists` and `Absent`, raise `PathOperationError` when they are declared.

### Conditions that need no filesystem

Two conditions are enforced from the expression and its bindings alone.

`render` checks `Under(base)` lexically: a binding cannot lead outside the base through `..` or an absolute value. `check` also resolves symlinks.

```pycon
>>> from wend import AnyPath, Under
>>> upload = (P(root) / AnyPath("rel")).requires(Under(P(root)))
>>> upload.render(root="/srv", rel="a/b.txt")
'/srv/a/b.txt'
>>> upload.render(root="/srv", rel="../etc/passwd")
Traceback (most recent call last):
  ...
wend.errors.ContainmentError: '/srv/../etc/passwd' is not under '/srv' (required: Under('{root}'))
```

`File` is a fact about the structure: nothing can be joined below a path declared to be a file, so the join raises when the expression is built.

```pycon
>>> src / "x"
Traceback (most recent call last):
  ...
wend.errors.PathOperationError: '{root}/raw/{day}.csv' is declared a File: nothing can be joined below it
```

## Steps

A `Step` groups the paths that one step of a pipeline uses. Its bindings are shared, and each path takes the parameters it uses.

```pycon
>>> from wend import Step
>>> convert = Step(src=src, dst=dst)
>>> convert.effects()
[<src: read {root}/raw/{day}.csv>, <dst: create {root}/clean/{day}.csv>]
>>> with convert(root="data", day="mon") as p:
...     p["dst"].parent.mkdir()
...     _ = p["dst"].write_text(p["src"].read_text().upper())
>>> Path("data/clean/mon.csv").read_text()
'A,B\n1,2\n'
```

Entering the `with` block checks every precondition and gives the rendered paths. Leaving it without an exception checks every postcondition, here that `dst` now exists as a file. A second run fails before its body runs, because `dst` must be absent:

```pycon
>>> with convert(root="data", day="mon") as p:
...     print("not reached")
Traceback (most recent call last):
  ...
wend.errors.PathExistsError: 'data/clean/mon.csv' already exists (required: Absent)
```

`effects` lists what each path declares it is used for: `read`, `write`, `create`, `list` or `delete`. It reports the declarations, and does not observe what the step does.

## Across a pipeline

Because a step declares its paths as expressions, what several steps do to each other can be worked out before any of them runs, and before any value is bound. `relate` says how two families of paths relate: whether they name the same path, one inside the other, or neither, for every binding (`"always"`), for some (`"sometimes"`, with an example), for none (`"never"`), or `"unknown"`:

```pycon
>>> from wend import relate
>>> relate(src, dst).kind
'disjoint'
>>> relate(src, P(root) / "raw").inside
'always'
>>> relate(src, P(root) / "raw" / T(t"{Param('other')}.csv")).same
'sometimes'
```

A name changed with `with_suffix`, `with_stem` or `with_name` stays in its directory and keeps what the change fixes, even while the name itself is unknown. `{day}.csv` with the suffix `.parquet` is never the CSV. It is `{day}.parquet` only when `day` is not empty: an empty `day` renders `.csv`, which has no suffix, so the change gives `.csv.parquet`.

```pycon
>>> parquet = src.with_suffix(".parquet")
>>> relate(parquet, src).kind
'disjoint'
>>> relate(parquet, P(root) / "raw" / T(t"{day}.parquet")).same
'sometimes'
>>> parquet.render(root="data", day="")
'data/raw/.csv.parquet'
```

By default a parameter name means one value on both sides, as in one run of a pipeline: `{root}/raw/{day}.csv` and `{root}/clean/{day}.csv` never meet, whatever `root` and `day` are. An `EffectGraph` relates every path of a set of steps: which step reads what another writes, which deletes what another reads, and which two write one path. From that it gives an order, the steps that may run at once, and why:

```pycon
>>> from wend.effects import EffectGraph
>>> clean = P(root) / "clean" / T(t"{day}.csv")
>>> report = Step(
...     src=clean.requires(Readable),
...     out=(P(root) / "reports" / T(t"{day}.html")).ensures(Exists),
... )
>>> purge = Step(old=(P(root) / "raw" / T(t"{day}.csv")).ensures(Absent))
>>> graph = EffectGraph({"convert": convert, "report": report, "purge": purge})
>>> graph.order()
['convert', 'report', 'purge']
>>> graph.stages()
[['convert'], ['report', 'purge']]
>>> graph.independent("report", "purge")
True
>>> for line in graph.explain("purge"):
...     print(line)
purge.old deletes what convert.src reads, on every run, so convert runs first: {root}/raw/{day}.csv (e.g. day='data', root='out': out/raw/data.csv)
```

Every link carries how sure it is, and every query counts every link, whatever its certainty. A dependency, hazard or conflict that is only `"sometimes"` or `"unknown"` still orders the steps and keeps them out of one stage: treating it as absent could run two interfering steps at once. `dependencies(certain=True)` keeps the dependencies that hold on every run, and `cycles(certain=True)` the cycles no binding avoids.

A declared path covers what lies below it, since it may be a directory: a step that writes `{root}/raw` and one that reads `{root}/raw/{day}.csv` are linked, and so are two steps that delete a directory and a file in it. A path declared with no conditions at all is kept apart from every path it touches, since its effect is unknown.

A step that creates a file may also make its missing parent directories. The graph assumes it does so idempotently, as `os.makedirs(..., exist_ok=True)` does, unless the step declares the directory as a path of its own: - a path that must exist first is declared with `requires(Exists, Dir)`, and the step then runs after any step that may make it; - a directory made exclusively is declared with `requires(Absent)` and `ensures(Exists, Dir)`.

A `Creatable` or `Writable` check is kept apart from a creation in another step below a directory that may be missing, because making the directory changes what the check finds. Name the directories that exist before the pipeline runs with `existing`, and nothing is made there:

```pycon
>>> stats = Step(out=(P(root) / "out" / "summary.json").requires(Creatable).ensures(File))
>>> export = Step(out=(P(root) / "out" / T(t"{day}.csv")).requires(Creatable).ensures(File))
>>> EffectGraph({"export": export, "stats": stats}).stages()
[['export'], ['stats']]
>>> EffectGraph({"export": export, "stats": stats}, existing=[P(root) / "out"]).stages()
[['export', 'stats']]
```

A step that requires a path inside that directory to exist makes nothing there while it is missing, since its check fails first: `convert` reads a file below `{root}`, so it and `stats` may run at once even without `existing`.

```pycon
>>> EffectGraph({"convert": convert, "stats": stats}).stages()
[['convert', 'stats']]
```

`obligations` says, for each condition a step requires, whether the steps before it settle it. A check that passed, or a postcondition a step confirmed, is known of its path however the path is spelt, until a step that may run in between declares a change that may touch it. A *discharged* condition holds whenever the steps before it completed, and a *refuted* one makes the step fail. Anything else is *at risk* or *external*: for the world to provide. A passed `Readable` or `Listable` check shows that its path exists, and a path given as `existing` exists throughout, as does every directory above it.

```pycon
>>> audit = Step(out=(P(root) / "clean").joinpath(T(t"{day}.csv")).requires(File, Exists))
>>> late = Step(src=src)
>>> graph = EffectGraph({"convert": convert, "audit": audit, "purge": purge, "late": late})
>>> for o in graph.obligations(["convert", "audit", "purge", "late"]):
...     if o.status in ("discharged", "refuted"):
...         print(o)
audit.out requires exists of {root}/clean/{day}.csv: discharged by convert.dst
audit.out requires file of {root}/clean/{day}.csv: discharged by convert.dst
late.src requires exists of {root}/raw/{day}.csv: refuted by purge.old, so the check fails
late.src requires read of {root}/raw/{day}.csv: refuted by purge.old, so the check fails
```

That a path was checked is not that it is still true: the answer rests on nothing outside the steps changing their paths, and on each step doing what it declares (`ASSUMPTIONS`).

The graph promises only what the declarations say. Two steps in one stage cannot interfere through the effects they declare, but a step whose code touches a path it does not declare is outside the graph.

Paths are compared as rendered strings, not as files: a symlink, a `..`, or a relative and an absolute spelling of one file are two paths to the graph ([SEMANTICS.md §15](<https://github.com/lmmx/wend/blob/master/docs/SEMANTICS.md#15-relations-between-families>)).

## Errors

Each failed condition raises a `ConditionError`. Its `path` is the rendered path and its `condition` is the condition that failed. Each subclass also derives from the builtin exception for the same failure, so existing handlers keep working. `InvalidBindingError` is a `ValueError`.

| error | also a | raised when |
| --- | --- | --- |
| `MissingPathError` | `FileNotFoundError` | a path that must exist does not |
| `PathExistsError` | `FileExistsError` | a path that must be absent exists |
| `CapabilityError` | `PermissionError` | a path cannot be read, written, created or listed |
| `WrongKindError` |  | a path is not the declared kind: a file, or a directory |
| `ContainmentError` | `InvalidBindingError` | a path is not under its declared base |
| `NoAlternativeError` | `FileNotFoundError` | no alternative of a union qualifies for `first` |

```pycon
>>> try:
...     src.check(root="data", day="tue")
... except FileNotFoundError as e:
...     print(type(e).__name__, e.path)
MissingPathError data/raw/tue.csv
```

## Checks are point-in-time

A check describes the filesystem at the moment it runs. A path that exists when it is checked may be gone when it is opened, and a symlink may be replaced between the two. Checks are not atomic with any later use of the path, and `Readable`, `Writable` and the other capabilities report the permissions of the real user. Conditions state what a program expects and catch mistakes. They are not a sandbox, and neither is `glob`'s symlink policy.

Conditions are checked when the program runs. A type checker sees a `PathExpr`, with no conditions in its type.

## Other filesystems

`glob` and `infer` read a tree through a `wend.fs.FileSystem`: the local disk by default, or the filesystem given with `fs=`. With the `fsspec` extra, `url_to_fs` gives an `FsspecFS` for an object store and the path within it. `check`, `confirm`, `Step`, `first`, `Tree.validate`, `Tree.scaffold` and `Ledger` use the local filesystem.

## Reference

- `wend.conditions`, `Step`, `PathExpr.check`, `PathExpr.confirm`, `wend.errors`, `relate`, `wend.effects`
- [SEMANTICS.md §10](<https://github.com/lmmx/wend/blob/master/docs/SEMANTICS.md#10-conditions>) (conditions), [§11](<https://github.com/lmmx/wend/blob/master/docs/SEMANTICS.md#11-unions-and-queries>) (unions and `first`) and [§12](<https://github.com/lmmx/wend/blob/master/docs/SEMANTICS.md#12-schemas>) (schemas)
