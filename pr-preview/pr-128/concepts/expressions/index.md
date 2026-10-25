# Expressions

```python
from wend import P, Param, T

root, split = Param("root"), Param("split")
idx = Param("idx", type=int)

joined = root / "data" / split / T(t"chunk_{idx:04d}.parquet")
written = T(t"{root}/data/{split}/chunk_{idx:04d}.parquet")
```

```pycon
>>> joined
PathExpr('{root}/data/{split}/chunk_{idx:04d}.parquet')
>>> joined == written
True
>>> joined.params
{'root': Param('root'), 'split': Param('split'), 'idx': Param('idx', type=int)}
```

The two expressions are built differently and describe the same path, so they are equal. Each one records the structure of the path, and `params` lists its parameters with their declarations.

## Describing and realising a path

pathlib composes paths well. Its result is a concrete value:

```pycon
>>> from pathlib import Path
>>> Path("data") / "train" / f"chunk_{7:04d}.parquet"
PosixPath('data/train/chunk_0007.parquet')
```

The f-string is formatted before the join, so the value holds the text `chunk_0007`. It records neither the `04d` format nor which part of the name was a number.

A wend expression is a description of the path. It is realised as a concrete path by `render` (a `str`) or `resolve` (a `pathlib.Path`), which apply the same pathlib rules to the values given:

```pycon
>>> joined.resolve(root=".", split="train", idx=7)
PosixPath('data/train/chunk_0007.parquet')
```

The description itself can also be matched against paths, used to find files, transformed, or bound in part.

## What an expression records

- **Literal parts**: text that is the same in every rendering, such as `data`, `chunk_` and `.parquet`.
- **Parameters**: named parts whose values are given later. Each keeps its declaration: its kind, `type`, `choices` and `default` ([Parameters](<https://lmmx.github.io/wend/pr-preview/pr-128/concepts/parameters/index.md>)).
- **Formatted fields**: interpolations such as `{idx:04d}`, with their conversion and format spec, applied when the path is rendered.
- **Operations**: `parent`, `with_suffix`, `relative_to` and the others, applied to the structure where possible and recorded where not ([Operations](<https://lmmx.github.io/wend/pr-preview/pr-128/concepts/operations/index.md>)).

The `pattern` property, which the repr shows, writes this structure out in t-string syntax.

## Building an expression

- `P(x)` makes an expression from a `str`, an `os.PathLike`, a `Param`, a t-string or another expression.
- `T(t"...")` makes an expression from a t-string.
- `/` and `joinpath` join. The right-hand side can be any of the values `P` takes, and a t-string on the right needs no `T`:

```pycon
>>> name = Param("name")
>>> P("data") / t"{name}.csv"
PathExpr('data/{name}.csv')
```

A `str` joined with `/` is a literal path, with pathlib's rules. Its separators make segments, and an absolute path replaces what came before it:

```pycon
>>> P("data") / "raw/2026"
PathExpr('data/raw/2026')
>>> P("data") / "/srv"
PathExpr('/srv')
```

An f-string formats a `Param` into text before wend receives it. wend detects this and raises `TypeError`:

```pycon
>>> P(f"{root}/data")
Traceback (most recent call last):
  ...
TypeError: A Param was formatted into a plain string (an f-string or str.format); use a t-string instead, e.g. T(t'chunk_{idx:04d}')
```

## How a t-string is split

A t-string's literal text is split at every `/`, so the number of segments and their positions are known before any value is bound. This is why operations on the structure need no values:

```pycon
>>> T(t"reports/{split}/{name}.csv").parent
PathExpr('reports/{split}')
```

A value bound later adds segments only through a parameter whose kind accepts a path of several segments, such as the parameter at the head or a `SubPath`. Anywhere else, a `/` in a value is rejected ([Parameters](<https://lmmx.github.io/wend/pr-preview/pr-128/concepts/parameters/index.md>)).

## Path operands and formatted fields

An interpolation is one of two things, depending on where it stands:

- **A path operand** is an interpolation that forms a whole segment, with no conversion and no format spec, such as `{root}` and `{split}` in `t"{root}/data/{split}"`. It is joined exactly as `/` joins it, so `T(t"{root}/data")` equals `root / "data"`.
- **A formatted field** is any other interpolation, such as `{idx:04d}` in `t"chunk_{idx:04d}"`, `{name}` in `t"{name}.csv"` or `{name!r}`. Its value is formatted as an f-string formats it, and the text becomes part of one segment.

A template renders as formatting the t-string as an f-string and parsing the result would, except where that would change the path's structure. A path operand is joined, so an empty value at the head is the empty path and does not make the path absolute:

```pycon
>>> value = ""
>>> T(t"{root}/data").render(root=value)
'data'
>>> Path(f"{value}/data")
PosixPath('/data')
```

The text of a formatted field cannot contain `/`, since it is part of one segment:

```pycon
>>> T(t"{name}.csv").render(name="a/b")
Traceback (most recent call last):
  ...
wend.errors.InvalidBindingError: {name} formats 'a/b' to 'a/b', which contains a separator
```

[SEMANTICS.md §4.1](<https://github.com/lmmx/wend/blob/master/docs/SEMANTICS.md#41-differences-from-formatting-the-t-string-as-an-f-string>) lists every case where a template differs from formatting the t-string as an f-string.

## Dynamic format specs

A format spec can contain parameters of its own:

```python
width = Param("width", type=int)
chunk = T(t"chunk_{idx:0{width}d}.parquet")
```

```pycon
>>> chunk
PathExpr('chunk_{idx:0{width}d}.parquet')
>>> chunk.render(idx=7, width=6)
'chunk_000007.parquet'
```

`width` is a parameter like any other, and is checked against its declaration. A path can be matched once the spec is fixed, by binding `width` first:

```pycon
>>> chunk.bind(width=6).match("chunk_000007.parquet")
Match('chunk_000007.parquet', {'idx': 7})
```

## Reference

- `P`, `T`, `PathExpr`, `Text`
- [SEMANTICS.md §1, terms](<https://github.com/lmmx/wend/blob/master/docs/SEMANTICS.md#1-terms>) and [§4, templates](<https://github.com/lmmx/wend/blob/master/docs/SEMANTICS.md#4-templates>)
