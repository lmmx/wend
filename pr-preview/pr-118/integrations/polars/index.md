# Polars

`wend.frame.resolve_frame` renders one expression for every row of a Polars DataFrame whose columns are named after the expression's parameters. It checks every row with the same rules as `render`, then builds the paths with Polars' own string operations. This page needs Python 3.14 and the `polars` extra:

```sh
pip install "wend[polars]"
```

`resolve_frame` is one way to render many paths. A compiled renderer's `many` method renders any expression from rows of bindings, without Polars ([Datasets and shards](<https://lmmx.github.io/wend/pr-preview/pr-118/guides/datasets/#render-every-expected-path>)). The examples build on each other: run them in order.

## Render a column of paths

```python
import polars as pl

from wend import Param, Segment, counter
from wend.frame import resolve_frame

root = Param("root")
split = Segment("split", choices={"train", "test"})
filename = counter("shard", width=5, of_total=True, sep="-", suffix=".parquet")
shard = root / split / filename

frame = pl.DataFrame(
    {
        "root": ["data", "data", "/mnt/data", "/mnt/data"],
        "split": ["train", "train", "test", "test"],
        "idx": [0, 1, 0, 1],
        "total": [2, 2, 2, 2],
    }
)
```

`resolve_frame` returns a String Series named `path`, with one path per row:

```pycon
>>> paths = resolve_frame(shard, frame)
>>> paths.name, paths.dtype
('path', String)
>>> for path in paths:
...     print(path)
data/train/shard-00000-of-00002.parquet
data/train/shard-00001-of-00002.parquet
/mnt/data/test/shard-00000-of-00002.parquet
/mnt/data/test/shard-00001-of-00002.parquet
```

Each path is the one `render` returns for that row:

```pycon
>>> paths.to_list() == [shard.render(row) for row in frame.iter_rows(named=True)]
True
>>> frame.with_columns(path=paths).columns
['root', 'split', 'idx', 'total', 'path']
```

A `LazyFrame` is accepted too. The result is collected.

## Path columns are normalised

A column at a path position, such as `root` here, is normalised as `render` normalises a path: `data/`, `./data` and `/mnt//data` become `data`, `data` and `/mnt/data`. A column whose values are all normalised already skips that work.

```pycon
>>> messy = frame.with_columns(
...     pl.Series("root", ["data/", "./data", "/mnt//data", "/mnt/./data"])
... )
>>> resolve_frame(shard, messy).to_list() == paths.to_list()
True
```

## Missing columns take defaults

A parameter with no column takes its default on every row, as `render` does for a missing binding:

```pycon
>>> total = Param("total", type=int, default=2)
>>> sized_filename = counter(
...     "shard", width=5, of_total=True, sep="-", suffix=".parquet", total=total
... )
>>> sized = root / split / sized_filename
>>> resolve_frame(sized, frame.drop("total")).to_list() == paths.to_list()
True
```

## Every row is checked

A value that `render` rejects raises the same exception class, with the number of the first row that fails. No paths are returned:

```pycon
>>> bad = frame.with_columns(pl.Series("split", ["train", "val", "test", "test"]))
>>> resolve_frame(shard, bad)
Traceback (most recent call last):
  ...
wend.errors.InvalidBindingError: Row 1: split not in choices
>>> shard.render(root="data", split="val", idx=1, total=2)
Traceback (most recent call last):
  ...
wend.errors.InvalidBindingError: split='val': not one of {'test', 'train'}
```

A null is always rejected, also where `render` would format `None` as text:

```pycon
>>> from wend import P, T
>>> name = Param("name")
>>> note = P("notes") / T(t"note_{name}.txt")
>>> note.render(name=None)
'notes/note_None.txt'
>>> resolve_frame(note, pl.DataFrame({"name": ["a", None]}))
Traceback (most recent call last):
  ...
wend.errors.InvalidBindingError: Row 1: name is null
```

## What it refuses

A lowering to Polars exists only where Polars reproduces `render` exactly. For anything else, `resolve_frame` raises `NotImplementedError`, which names the construct. Float columns are refused:

```pycon
>>> score = Param("score")
>>> checkpoint = root / T(t"model-{score:.3f}.pt")
>>> scores = pl.DataFrame({"root": ["runs", "runs"], "score": [0.91234, 0.8]})
>>> resolve_frame(checkpoint, scores)
Traceback (most recent call last):
  ...
NotImplementedError: Column 'score' of type Float64 cannot be lowered to Polars exactly; use expr.compile().many(rows)
```

So is `!r` on a string, which renders the value's repr:

```pycon
>>> quoted = root / T(t"{name!r}.txt")
>>> resolve_frame(quoted, pl.DataFrame({"root": ["out"], "name": ["a"]}))
Traceback (most recent call last):
  ...
NotImplementedError: {name!r} (!r on a string) cannot be lowered to Polars exactly; use expr.compile().many(rows)
```

The fallback renders the same rows with the compiled renderer. `iter_rows(named=True)` gives one mapping per row:

```pycon
>>> checkpoint.compile().many(scores.iter_rows(named=True))
['runs/model-0.912.pt', 'runs/model-0.800.pt']
```

The `wend.frame` docstring lists exactly what is lowered and what is refused. In outline:

- **Lowered:** String, integer and Boolean columns; integer format specs in bases `d`, `b`, `o`, `x` and `X`, with fill, alignment, sign, `#`, `0`, width and grouping; string specs with fill, alignment, width and precision; and `parent`, `with_name`, `with_stem`, `with_suffix` and joins applied to unbound paths.
- **Refused:** floats and other column types; `!r` and `!a` on strings; format specs that contain a parameter; `relative_to` on unbound paths; and a declared `type=` that a column's values are not instances of.

`to_polars` returns the Polars expression itself, for use inside a larger query. It does not validate: rows that `render` would reject get unspecified values.

## See also

- [Datasets and shards](<https://lmmx.github.io/wend/pr-preview/pr-118/guides/datasets/index.md>): `compile`, `many` and `compile_many`.
- [Parameters](<https://lmmx.github.io/wend/pr-preview/pr-118/concepts/parameters/index.md>): the checks every row goes through.
- API reference: `wend.frame`, `resolve_frame`, `to_polars`, `PathExpr.compile`.
