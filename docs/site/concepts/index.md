---
description: "The idea behind wend: an expression describes a path, and every feature is something done with that description."
---

# How wend works

pathlib composes a path from its parts, and the result is a concrete value:

```pycon
>>> from pathlib import Path
>>> split, i = "train", 7
>>> Path("data") / split / f"chunk_{i:04d}.parquet"
PosixPath('data/train/chunk_0007.parquet')
```

`split` and `i` have been substituted and the `04d` format has been applied, and the
value records neither the parameters nor the format. Code that needs the layout again, to
read `split` and `i` back out of a filename, to list the chunks that exist or to check
that one is present, has to state it again, for example as a regular expression or a glob
pattern.

A wend expression is the description of the path:

```python
from wend import Param, T

root, split, idx = Param("root"), Param("split"), Param("idx", type=int)
shard = root / split / T(t"chunk_{idx:04d}.parquet")
```

```pycon
>>> shard
PathExpr('{root}/{split}/chunk_{idx:04d}.parquet')
>>> shard.render(root="data", split="train", idx=7)
'data/train/chunk_0007.parquet'
>>> shard.match("data/train/chunk_0007.parquet")
Match('data/train/chunk_0007.parquet', {'root': 'data', 'split': 'train', 'idx': 7})
```

It keeps its parameters (with their kinds, types and choices), its literal parts, its
formatting and the operations applied to it. It becomes a concrete path only when it is
rendered. For every set of values it accepts, the rendered path is the path pathlib
computes from the same values. Everything else wend does is done with the description.

## With one expression you can

| with one expression you can | using | concepts |
|---|---|---|
| render it with values | [`render`][wend.PathExpr.render], [`resolve`][wend.PathExpr.resolve], [`bind`][wend.PathExpr.bind], defaults, [bindings from objects][wend.bindings] | [Rendering and matching](matching.md), [Parameters](parameters.md) |
| read values back out of a path | [`match`][wend.PathExpr.match], [`match_all`][wend.PathExpr.match_all] | [Rendering and matching](matching.md) |
| transform it before any value is known | [`parent`][wend.PathExpr.parent], [`with_suffix`][wend.PathExpr.with_suffix], [`relative_to`][wend.PathExpr.relative_to] | [Operations](operations.md) |
| find the existing paths it describes | [`glob`][wend.PathExpr.glob], [unions][wend.PathUnion], [queries][wend.Query] | [Effects](effects.md) |
| keep its relations to other paths | [`base`][wend.PathExpr.base], [`rebase`][wend.PathExpr.rebase], [`sibling`][wend.PathExpr.sibling], [`cousin`][wend.PathExpr.cousin], [`under`][wend.PathExpr.under] | [Relations](relations.md) |
| say what must be true when it is used | [conditions][wend.conditions], [`Step`][wend.Step] | [Effects](effects.md) |
| map one tree onto another | [`Lens`][wend.Lens] | |
| describe a whole project | [`Tree`][wend.schema.Tree], [`validate`][wend.schema.Tree.validate], [`scaffold`][wend.schema.Tree.scaffold] | |
| recover it from an existing tree | [`infer`][wend.infer.infer], [`from_inferred`][wend.schema.from_inferred] | |
| render it fast and in bulk | [`compile`][wend.PathExpr.compile], [`compile_many`][wend.compile_many], [`resolve_frame`][wend.frame.resolve_frame] | |
| record where a file came from | [`explain`][wend.lineage.explain], [`tags`][wend.lineage.tags], [`Ledger`][wend.lineage.Ledger], [`content_key`][wend.lineage.content_key] | |

The rows without a concept page are documented in the [API reference](../reference/index.md).

## The concept pages

Together with the [Quickstart](../getting-started/quickstart.md), this page is enough to
use the library. The other pages explain one part each, and can be read in any order.

- [Expressions](expressions.md): what an expression records, and how `P`, `T` and `/`
  build one from text, parameters and t-strings.
- [Parameters](parameters.md): the four kinds of parameter, `type=`, `choices=` and
  `default=`, and why a value bound to a segment parameter cannot leave its directory.
- [Operations](operations.md): which path operations are computed from structure, which
  wait for values, and which are rejected.
- [Rendering and matching](matching.md): the two directions, how matches are verified,
  and why an ambiguous path is an error.
- [Relations](relations.md): how an expression remembers the paths it was built from,
  and how rebasing one path moves the paths derived from it.
- [Effects](effects.md): which operations touch the filesystem, and how conditions
  declare what a path must be.

The precise rules are in [SEMANTICS.md](https://github.com/lmmx/wend/blob/master/docs/SEMANTICS.md),
the contract that the tests check wend against.
