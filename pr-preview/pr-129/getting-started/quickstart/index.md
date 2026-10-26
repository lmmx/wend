# Quickstart

This page builds one expression for a dataset stored as numbered chunks, and uses it in each direction. It needs Python 3.14 and wend, with no extras ([Installation](<https://lmmx.github.io/wend/pr-preview/pr-129/getting-started/installation/index.md>)). The examples build on each other: run them in order, in an empty directory.

## Build an expression

```python
from wend import Param, Segment, T

root = Param("root")
split = Segment("split", choices={"train", "test"})
idx = Param("idx", type=int)

shard = root / split / T(t"chunk_{idx:04d}.parquet")
```

- `Param` declares a parameter: a named part of the path that gets its value later. `type=int` says that `idx` holds integers.
- `Segment` declares a parameter that is exactly one path segment. `choices=` lists the values it accepts.
- `T` makes an expression from a t-string. `{idx:04d}` is a formatted field: its format spec is kept and applied when the path is rendered.
- `/` joins, as it does for `pathlib.Path`.

The result is a `PathExpr`. Its repr shows the structure it records:

```pycon
>>> shard
PathExpr('{root}/{split}/chunk_{idx:04d}.parquet')
```

## Render it

`render` substitutes values and returns a string. `resolve` returns a `pathlib.Path`.

```pycon
>>> shard.render(root="data", split="train", idx=7)
'data/train/chunk_0007.parquet'
>>> shard.resolve(root="data", split="train", idx=7)
PosixPath('data/train/chunk_0007.parquet')
```

Each value is checked against its declaration first:

```pycon
>>> shard.render(root="data", split="train", idx="7")
Traceback (most recent call last):
  ...
wend.errors.InvalidBindingError: idx='7': expected int
```

## Match a path back

`match` reads the values back out of a path. It returns a `Match`, a read-only mapping of names to typed values, or `None` when the expression does not describe the path.

```pycon
>>> m = shard.match("data/test/chunk_0042.parquet")
>>> m
Match('data/test/chunk_0042.parquet', {'root': 'data', 'split': 'test', 'idx': 42})
>>> m["idx"]
42
>>> print(shard.match("data/val/chunk_0042.parquet"))
None
```

`val` is not one of the declared splits, so the second path has no match.

## Find the files that exist

First create a small tree: four chunks, a `notes.txt` and a `val/` directory.

```python
from pathlib import Path

for name in [
    "train/chunk_0000.parquet",
    "train/chunk_0001.parquet",
    "train/chunk_0003.parquet",
    "train/notes.txt",
    "test/chunk_0000.parquet",
    "val/chunk_0000.parquet",
]:
    path = Path("data", name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()
```

`glob` walks the tree along the expression's structure and yields a `Match` for each path the expression describes:

```pycon
>>> for m in shard.glob(root="data"):
...     print(m["split"], m["idx"], m.path)
test 0 data/test/chunk_0000.parquet
train 0 data/train/chunk_0000.parquet
train 1 data/train/chunk_0001.parquet
train 3 data/train/chunk_0003.parquet
```

`notes.txt` and `val/chunk_0000.parquet` do not fit the expression, so they are not yielded. Bindings given to `glob` fix parameters before the walk, so the next call lists only `data/train`. Comparing what exists with what should exist finds a gap:

```pycon
>>> found = {m["idx"] for m in shard.glob(root="data", split="train")}
>>> sorted(set(range(4)) - found)
[2]
```

## Operate on it without values

Path operations work on the expression itself, with no values bound.

```pycon
>>> shard.parent
PathExpr('{root}/{split}')
>>> meta = shard.with_suffix(".json")
>>> meta
PathExpr('{root}/{split}/chunk_{idx:04d}.json')
```

A `Match` is a mapping, so the values read from one path render another:

```pycon
>>> meta.render(shard.match("data/train/chunk_0003.parquet"))
'data/train/chunk_0003.json'
```

## Check a condition

`render` never looks at the filesystem. An expression can declare what must be true of its path when the path is used, and `check` tests that against the filesystem.

```python
from wend import Exists, File

stored = shard.requires(File, Exists)
```

```pycon
>>> stored.check(root="data", split="train", idx=1)
PosixPath('data/train/chunk_0001.parquet')
>>> stored.check(root="data", split="train", idx=2)
Traceback (most recent call last):
  ...
wend.errors.MissingPathError: 'data/train/chunk_0002.parquet' does not exist (required: Exists)
```

`MissingPathError` is also a `FileNotFoundError`, so existing `except FileNotFoundError` handlers catch it.

## Next

- [How wend works](<https://lmmx.github.io/wend/pr-preview/pr-129/concepts/index.md>): the idea behind these operations, and what else an expression can do.
- [Parameters](<https://lmmx.github.io/wend/pr-preview/pr-129/concepts/parameters/index.md>): the four kinds of parameter, and why `split` cannot be bound to `../etc`.
- [Rendering and matching](<https://lmmx.github.io/wend/pr-preview/pr-129/concepts/matching/index.md>): what happens when a path can be read more than one way.
- [Effects](<https://lmmx.github.io/wend/pr-preview/pr-129/concepts/effects/index.md>): conditions, and which operations touch the filesystem.
- [API reference](<https://lmmx.github.io/wend/pr-preview/pr-129/reference/index.md>).
