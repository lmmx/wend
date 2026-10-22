# Datasets and shards

A dataset is stored as numbered shards, in one directory per split. This guide declares that layout once, renders the paths a writer produces, lists the shards that exist and finds the ones that are missing. It needs Python 3.14 and wend, with no extras. The examples build on each other: run them in order, in an empty directory.

## Declare the layout

```python
from wend import Param, Segment, counter

root = Param("root")
dataset = Segment("dataset")
split = Segment("split", choices={"train", "test"})
name = counter("shard", width=5, of_total=True, sep="-", suffix=".parquet")

shard = root / dataset / split / name
```

```pycon
>>> name
PathExpr('shard-{idx:05d}-of-{total:05d}.parquet')
>>> shard
PathExpr('{root}/{dataset}/{split}/shard-{idx:05d}-of-{total:05d}.parquet')
>>> shard.render(root="data", dataset="tiny", split="train", idx=0, total=4)
'data/tiny/train/shard-00000-of-00004.parquet'
```

- `counter` writes a counter filename. With `of_total=True` the name also holds the number of shards. Its parameters, `idx` and `total`, are integers formatted with `05d`, so matching reads them back as `int`.
- `dataset` and `split` are segments: each value is one directory name. `split` accepts only `train` and `test`.

`counter` returns an ordinary expression, equal to the same name written as a t-string:

```pycon
>>> from wend import T
>>> idx, total = Param("idx", type=int), Param("total", type=int)
>>> name == T(t"shard-{idx:05d}-of-{total:05d}.parquet")
True
```

## Render every expected path

A writer knows the root, the dataset and the number of shards before it starts. `bind` fixes them once:

```pycon
>>> layout = shard.bind(root="data", dataset="tiny", total=4)
>>> layout
PathExpr('data/tiny/{split}/shard-{idx:05d}-of-00004.parquet')
```

`compile` generates a Python function specialised to the expression, and caches it on the expression. Its `many` method renders one path for each mapping of bindings:

```pycon
>>> compiled = layout.compile()
>>> rows = [{"split": s, "idx": i} for s in ("train", "test") for i in range(4)]
>>> paths = compiled.many(rows)
>>> len(paths)
8
>>> for path in paths[:3]:
...     print(path)
data/tiny/train/shard-00000-of-00004.parquet
data/tiny/train/shard-00001-of-00004.parquet
data/tiny/train/shard-00002-of-00004.parquet
```

`columns` takes the same bindings column by column, and calling the compiled renderer returns one `pathlib.Path`, as `resolve` does:

```pycon
>>> for path in compiled.columns(split=["test", "test"], idx=range(2)):
...     print(path)
data/tiny/test/shard-00000-of-00004.parquet
data/tiny/test/shard-00001-of-00004.parquet
>>> compiled(split="test", idx=3)
PosixPath('data/tiny/test/shard-00003-of-00004.parquet')
```

A compiled renderer returns what `render` returns for the same bindings, and raises the same error for a value that `render` rejects:

```pycon
>>> compiled.many([{"split": "val", "idx": 0}])
Traceback (most recent call last):
  ...
wend.errors.InvalidBindingError: split='val': not one of {'test', 'train'}
```

## Render several paths per shard

Each shard has a JSON file of metadata next to it, with the same name and the suffix `.json`. `compile_many` compiles several expressions into one function. In each call, every parameter is looked up, checked and formatted once, however many of the expressions use it.

```pycon
>>> from wend import compile_many
>>> outputs = compile_many({"data": layout, "meta": layout.with_suffix(".json")})
>>> shard_0 = outputs.render(split="train", idx=0)
>>> shard_0["data"]
'data/tiny/train/shard-00000-of-00004.parquet'
>>> shard_0["meta"]
'data/tiny/train/shard-00000-of-00004.json'
>>> for data, meta in outputs.many(rows[:2]):
...     print(meta)
data/tiny/train/shard-00000-of-00004.json
data/tiny/train/shard-00001-of-00004.json
```

Given a dict, `render` returns a dict with the same keys. `many` returns one tuple per row, with the paths in the order the expressions were given.

## Write some shards

The next examples need shards on disk. This writes five of the eight shards, then two files that do not belong to `layout`: one named without the counter, and one left by an earlier write of three shards.

```python
from pathlib import Path

written = [("train", 0), ("train", 1), ("train", 3), ("test", 0), ("test", 1)]
for path in compiled.many({"split": s, "idx": i} for s, i in written):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).touch()

Path("data/tiny/train/shard-2.parquet").touch()
Path("data/tiny/test/shard-00002-of-00003.parquet").touch()
```

## List the shards that exist

`glob` walks the directories along the expression's structure and yields a `Match` for each existing path that the expression describes, in path order:

```pycon
>>> for m in layout.glob():
...     print(m["split"], m["idx"], m.path)
test 0 data/tiny/test/shard-00000-of-00004.parquet
test 1 data/tiny/test/shard-00001-of-00004.parquet
train 0 data/tiny/train/shard-00000-of-00004.parquet
train 1 data/tiny/train/shard-00001-of-00004.parquet
train 3 data/tiny/train/shard-00003-of-00004.parquet
```

`shard-2.parquet` does not have the counter's form, and `shard-00002-of-00003.parquet` has a total of 3 where `layout` requires 4, so neither is yielded. Each `idx` is an `int`, read from the filename and checked by rendering it again.

## Find the gaps

The set of shards that should exist, minus the set that glob found, is the set of missing shards. The same layout renders their paths:

```pycon
>>> expected = {(r["split"], r["idx"]) for r in rows}
>>> found = {(m["split"], m["idx"]) for m in layout.glob()}
>>> missing = sorted(expected - found)
>>> missing
[('test', 2), ('test', 3), ('train', 2)]
>>> for path in compiled.many({"split": s, "idx": i} for s, i in missing):
...     print(path)
data/tiny/test/shard-00002-of-00004.parquet
data/tiny/test/shard-00003-of-00004.parquet
data/tiny/train/shard-00002-of-00004.parquet
```

## Find shards from another write

`layout` fixes `total`. `shard` leaves it free, so glob reads the total from each filename, and shards written with a different total can be found:

```pycon
>>> for m in shard.glob(root="data", dataset="tiny"):
...     if m["total"] != 4:
...         print(m.path, m["total"])
data/tiny/test/shard-00002-of-00003.parquet 3
```

Bindings given to `glob` fix those parameters before the walk, so this call lists only `data/tiny`.

## Numbered files without a total

A log directory grows one file at a time, so its names have no total. Without `of_total`, `counter` writes the index alone:

```python
log = root / "logs" / counter("log", width=3, suffix=".jsonl")

Path("data/logs").mkdir()
for i in range(3):
    Path(log.render(root="data", idx=i)).touch()
```

```pycon
>>> log
PathExpr('{root}/logs/log_{idx:03d}.jsonl')
>>> last = max(m["idx"] for m in log.glob(root="data"))
>>> log.render(root="data", idx=last + 1)
'data/logs/log_003.jsonl'
```

Without `width`, the index is not padded. A match must render back to the same path, so a padded name does not match an unpadded counter:

```pycon
>>> part = counter("part", suffix=".csv")
>>> part
PathExpr('part_{idx:d}.csv')
>>> part.match("part_12.csv")
Match('part_12.csv', {'idx': 12})
>>> print(part.match("part_012.csv"))
None
```

## See also

- [Parameters](<https://lmmx.github.io/wend/pr-preview/pr-110/concepts/parameters/index.md>): segments, `choices=` and `type=`.
- [Rendering and matching](<https://lmmx.github.io/wend/pr-preview/pr-110/concepts/matching/index.md>): how `match` and `glob` verify each path they read.
- [Polars](<https://lmmx.github.io/wend/pr-preview/pr-110/integrations/polars/index.md>): render a path for every row of a DataFrame.
- API reference: `counter`, `PathExpr.compile`, `compile_many`, `CompiledSet`, `glob`.
