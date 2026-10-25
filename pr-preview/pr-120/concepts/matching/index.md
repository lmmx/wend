# Rendering and matching

```python
from wend import P, Param, T

idx = Param("idx", type=int)
chunk = P("data") / T(t"chunk_{idx:04d}.parquet")
```

```pycon
>>> chunk.render(idx=7)
'data/chunk_0007.parquet'
>>> chunk.match("data/chunk_0007.parquet")
Match('data/chunk_0007.parquet', {'idx': 7})
>>> print(chunk.match("data/chunk_007.parquet"))
None
```

An expression goes in two directions. `render` takes bindings and returns a path. `match` takes a path and returns the bindings that render to it, or `None` when there are none. `chunk_007` has no match: `{idx:04d}` renders 7 as `0007`, and renders no integer as `007`.

## Rendering

- `render` returns the canonical path as a `str`.
- `resolve` returns the same path as a `pathlib.Path`, or as the class given with `cls=`.

Bindings can be keywords, a mapping keyed by name or by `Param`, or an object whose fields are named after the parameters, such as a dataclass or a Pydantic model (`bindings` shows what an object binds). Keywords take precedence.

```pycon
>>> from pathlib import PurePosixPath
>>> chunk.render({idx: 7})
'data/chunk_0007.parquet'
>>> chunk.resolve(idx=7, cls=PurePosixPath)
PurePosixPath('data/chunk_0007.parquet')
>>> chunk.render()
Traceback (most recent call last):
  ...
wend.errors.MissingBindingError: Missing bindings: ['idx']
```

A parameter with no binding takes its default if it declares one. Otherwise rendering raises `MissingBindingError`. A value that its declaration or its position does not accept raises `InvalidBindingError` ([Parameters](<https://lmmx.github.io/wend/pr-preview/pr-120/concepts/parameters/index.md>)).

## Matching

`match` returns a `Match`: a read-only mapping of parameter names to values, with the matched path as `.path`. The path is normalised as pathlib normalises it before it is matched, so `data//chunk_0007.parquet` and `data/./chunk_0007.parquet` match too.

Values are typed. A parameter declared with `type=` is read as that type. An undeclared one is read as the type its format spec implies: `{n:d}` and `{n:x}` read integers, and a field with no spec reads a `str`.

```pycon
>>> n, label = Param("n"), Param("label")
>>> T(t"run_{n:x}").match("run_1f")
Match('run_1f', {'n': 31})
>>> T(t"run_{label}").match("run_1f")
Match('run_1f', {'label': '1f'})
```

## Matches are verified

Every candidate reading is rendered again and compared with the path before it is returned, so a match always renders to exactly the path it came from. A format spec's width is a minimum, so a longer number is a valid rendering:

```pycon
>>> chunk.match("data/chunk_12345.parquet")
Match('data/chunk_12345.parquet', {'idx': 12345})
>>> chunk.render(idx=12345)
'data/chunk_12345.parquet'
```

`glob` verifies the paths it finds in the same way.

## Ambiguity is an error

Some paths can be read in more than one way. `match` raises `AmbiguousMatchError` for them. It does not choose one of the readings.

```python
stem, ext = Param("stem"), Param("ext")
dist = P("dist") / T(t"{stem}.{ext}")
```

```pycon
>>> dist.match("dist/tool.whl")
Match('dist/tool.whl', {'stem': 'tool', 'ext': 'whl'})
>>> dist.match("dist/tool-1.0.tar.gz")
Traceback (most recent call last):
  ...
wend.errors.AmbiguousMatchError: 'dist/tool-1.0.tar.gz' matches ambiguously: ...
>>> dist.match_all("dist/tool-1.0.tar.gz")
[{'stem': 'tool-1', 'ext': '0.tar.gz'}, {'stem': 'tool-1.0', 'ext': 'tar.gz'}, {'stem': 'tool-1.0.tar', 'ext': 'gz'}]
```

`match_all` lists every verified reading. Each reading renders to the path, so any choice among them would be a guess about which one was meant. The error's `candidates` attribute holds the same list.

Declaring what a field can hold, or binding a parameter, leaves one reading:

```pycon
>>> known = Param("ext", choices={"whl", "tar.gz"})
>>> package = P("dist") / T(t"{stem}.{known}")
>>> package.match("dist/tool-1.0.tar.gz")
Match('dist/tool-1.0.tar.gz', {'stem': 'tool-1.0', 'ext': 'tar.gz'})
>>> dist.bind(ext="gz").match("dist/tool-1.0.tar.gz")
Match('dist/tool-1.0.tar.gz', {'stem': 'tool-1.0.tar'})
```

Other ambiguous shapes are adjacent string fields such as `{a}{b}`, and a free head parameter followed by a `SubPath`, where the split between the two is not fixed. By default `glob` raises `AmbiguousMatchError` for the first ambiguous path it finds. `ambiguous="skip"` leaves such paths out, and a callable receives each error (`wend.glob`).

## Not invertible

An expression that starts with a deferred operation, or a field whose text is derived from another path, cannot be read back from a path. `match` raises `NotInvertibleError` and names the construct. Binding its parameters first makes the expression invertible:

```pycon
>>> from wend import SubPath
>>> root, rel = Param("root"), SubPath("rel")
>>> up = (root / rel).parent
>>> up.match("/srv/a")
Traceback (most recent call last):
  ...
wend.errors.NotInvertibleError: 'parent({root}/{rel...})' starts with a deferred 'parent'; bind its parameters before matching
>>> up.bind(root="/srv", rel="a/b").match("/srv/a")
Match('/srv/a', {})
```

A format spec that depends on an unbound parameter, such as `{idx:0{width}d}`, raises it too ([Expressions](<https://lmmx.github.io/wend/pr-preview/pr-120/concepts/expressions/#dynamic-format-specs>)).

## Reference

- `PathExpr.render`, `PathExpr.resolve`, `PathExpr.match`, `PathExpr.match_all`, `Match`, `bindings`
- [SEMANTICS.md §7](<https://github.com/lmmx/wend/blob/master/docs/SEMANTICS.md#7-matching>) (matching) and [§3.2](<https://github.com/lmmx/wend/blob/master/docs/SEMANTICS.md#32-environments>) (environments)
