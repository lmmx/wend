# Operations

```python
from wend import Param, SubPath, T

root, split, rel = Param("root"), Param("split"), SubPath("rel")
idx = Param("idx", type=int)

shard = root / split / T(t"chunk_{idx:04d}.parquet")
source = root / rel
```

```pycon
>>> shard.parent
PathExpr('{root}/{split}')
>>> shard.with_suffix(".json")
PathExpr('{root}/{split}/chunk_{idx:04d}.json')
>>> source.parent
PathExpr('parent({root}/{rel...})')
```

`shard`'s last segment is known from its structure, so its parent and its suffix are computed with no values bound. `source` ends in a sub-path of zero or more segments, so its parent depends on the value of `rel`, and the operation waits for it.

Every operation is one of three kinds: static, deferred or rejected.

## Static operations

A static operation is computed from the structure, without bindings:

- `parent`, `name` and `with_name` of an expression whose last part is a segment;
- `stem`, `suffix` and `with_suffix`, when the last dot of that segment is in literal text, no field after it can contain a dot (an integer field cannot), and a character other than a dot comes before it;
- `relative_to` a structural prefix;
- `bind`.

```pycon
>>> shard.name
Text('chunk_{idx:04d}.parquet')
>>> shard.stem
Text('chunk_{idx:04d}')
>>> shard.suffix
Text('.parquet')
>>> shard.with_name("index.json")
PathExpr('{root}/{split}/index.json')
>>> shard.relative_to(root)
PathExpr('{split}/chunk_{idx:04d}.parquet')
```

`name`, `stem` and `suffix` are strings, so they return a `Text`: a symbolic string with its own `render`.

A static operation can remove parameters. `shard.parent.parent` is `{root}`: the value of `split` does not change it, so the result has no `split` and needs no binding for it.

```pycon
>>> shard.parent.parent
PathExpr('{root}')
>>> shard.parent.parent.render(root="data")
'data'
```

## Deferred operations

A deferred operation depends on values that are not bound yet. It is recorded in the expression, shown in the pattern as a call, and evaluated with pathlib once its inputs are bound:

```pycon
>>> source.parent.render(root="/srv", rel="a/b")
'/srv/a'
>>> source.parent.render(root="/srv", rel="")
'/'
```

With `rel=""` the path is `/srv`, so its parent is `/`, as pathlib computes it.

The suffix of a free-form string field is deferred too, since the value can contain a dot:

```pycon
>>> name = Param("name")
>>> upload = root / "uploads" / name
>>> upload.suffix
Text('{suffix({root}/uploads/{name})}')
>>> upload.suffix.render(root="data", name="photo.tar.gz")
'.gz'
```

The suffix of `{name}.csv` is deferred for a similar reason. With `name=""` the segment is `.csv`, a hidden file whose suffix is `""`:

```pycon
>>> (root / T(t"{name}.csv")).suffix
Text('{suffix({root}/{name}.csv)}')
>>> (root / T(t"report_{name}.csv")).suffix
Text('.csv')
```

An expression that starts with a deferred operation cannot be matched against a path until its parameters are bound ([Rendering and matching](<https://lmmx.github.io/wend/pr-preview/pr-96/concepts/matching/#not-invertible>)).

## Rejected operations

An operation that is invalid for every binding raises `PathOperationError` when the expression is built. It is a `ValueError`, as pathlib's error for the same operation is.

```pycon
>>> from wend import P
>>> P("/").with_name("x")
Traceback (most recent call last):
  ...
wend.errors.PathOperationError: '/' has an empty name
>>> shard.with_suffix("json")
Traceback (most recent call last):
  ...
wend.errors.PathOperationError: Invalid suffix 'json'
```

## `bind` is partial evaluation

`bind` substitutes some parameters and folds what becomes static. The others stay free.

```pycon
>>> shard.bind(root="data")
PathExpr('data/{split}/chunk_{idx:04d}.parquet')
>>> shard.bind(root="data", split="train", idx=3).is_static
True
```

A value can also be an expression, which places the path under another one, or a `Param`, which renames:

```pycon
>>> shard.bind(root=P("/mnt") / Param("user"))
PathExpr('/mnt/{user}/{split}/chunk_{idx:04d}.parquet')
>>> shard.bind(split=Param("part"))
PathExpr('{root}/{part}/chunk_{idx:04d}.parquet')
```

`bind` does not apply defaults ([Parameters](<https://lmmx.github.io/wend/pr-preview/pr-96/concepts/parameters/#type-choices-and-default>)).

## `render` equals the pathlib computation

For every binding that an expression and its sub-expressions accept, `render` returns the path that the eager pathlib computation of the same operations returns, applied to the formatted strings:

```pycon
>>> from pathlib import PurePosixPath
>>> meta = shard.with_suffix(".json").relative_to(root)
>>> meta.render(root="data", split="train", idx=3)
'train/chunk_0003.json'
>>> eager = PurePosixPath("data") / "train" / f"chunk_{3:04d}.parquet"
>>> str(eager.with_suffix(".json").relative_to("data"))
'train/chunk_0003.json'
```

A binding that would make pathlib change the path's structure without an error is rejected with `InvalidBindingError`:

- a separator inside a segment;
- an empty segment, or a `.` segment;
- an escaping `..`;
- a value that violates a declared type or choices.

Evaluation is non-strict. A part of an expression that an operation discards, such as the segment `parent` drops or everything before an absolute join, need not be evaluated, so a value bound only to that part may go unchecked. This is the one case where `render` can return a path for a binding that the eager computation rejects.

## Reference

- `PathExpr`, `Text`, `PathOperationError`
- [SEMANTICS.md §5](<https://github.com/lmmx/wend/blob/master/docs/SEMANTICS.md#5-operations>) (operations) and [§6](<https://github.com/lmmx/wend/blob/master/docs/SEMANTICS.md#6-the-reference-value-and-wends-obligations>) (the reference value and wend's obligations)
