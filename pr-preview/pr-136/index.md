# wend

Symbolic, typed, invertible filesystem paths built from Python t‑strings (3.14+).

A wend expression records *how* a path is built — which parts are literal, which are parameters, how values are formatted — instead of collapsing it to a string. The same expression can be resolved, partially bound, transformed structurally, matched against concrete paths, used to discover files on disk, compiled for batch resolution, and inferred from an existing directory tree.

```python
from wend import Param, Segment, T

root = Param("root")
split = Segment("split", choices={"train", "test"})
idx = Param("idx", type=int)

shard = root / split / T(t"chunk_{idx:04d}.parquet")
```

```pycon
>>> shard
PathExpr('{root}/{split}/chunk_{idx:04d}.parquet')
>>> shard.render(root="data", split="train", idx=7)
'data/train/chunk_0007.parquet'
>>> shard.match("data/test/chunk_0042.parquet")
Match('data/test/chunk_0042.parquet', {'root': 'data', 'split': 'test', 'idx': 42})
>>> [(m["split"], m["idx"]) for m in shard.glob(root="data")]
[('test', 0), ('train', 0), ('train', 1), ('train', 3)]
```

- `render` substitutes the values and applies the formatting: `idx=7` becomes `0007`.
- `match` goes the other way and returns typed values: `idx` is the integer `42`. It returns `None` for a path the expression does not describe, such as `data/val/chunk_0001.parquet` (`val` is not a declared split) or `data/test/chunk_42.parquet` (not four digits).
- `glob` lists only the directories the expression can reach, and yields the same `Match` objects for the files it finds.

```pycon
>>> print(shard.match("data/val/chunk_0001.parquet"))
None
>>> print(shard.match("data/test/chunk_42.parquet"))
None
```

## Where to go

- [Quickstart](<https://lmmx.github.io/wend/pr-preview/pr-136/getting-started/quickstart/index.md>): build, render, match and glob one expression, in about ten minutes.
- [How wend works](<https://lmmx.github.io/wend/pr-preview/pr-136/concepts/index.md>): the idea behind the library, and a map of the concept pages.

## Install

wend needs Python 3.14 or later.

```sh
pip install wend
```

The optional integrations are extras: `wend[pydantic]` for path fields on Pydantic models, `wend[fsspec]` for object stores, and `wend[polars]` for resolving whole columns of a DataFrame.

## What an expression is for

| with one expression you can | using |
| --- | --- |
| render it with values | `render`, `resolve`, `bind` |
| read the values back out of a path | `match` |
| find the paths that exist | `glob`, unions, queries |
| keep its relation to other paths | `rebase`, `sibling`, `cousin` |
| say what must be true when it is used | conditions, `Step` |
| map one tree onto another | `Lens` |
| describe a whole project | `Tree` |
| recover it from an existing tree | `infer` |
| render it in bulk | `compile`, `compile_many` |
| record where a file came from | `wend.lineage` |

The [API reference](<https://lmmx.github.io/wend/pr-preview/pr-136/reference/index.md>) documents each of these.

wend grew out of the [Future Paths](<https://cog.spin.systems/future-paths>) essays, which set out what Python paths could keep track of beyond a concrete value.
