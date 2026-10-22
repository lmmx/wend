# Parameters

```python
from wend import P, Param

asset = P("/srv/static") / Param("name")
```

```pycon
>>> asset.render(name="logo.png")
'/srv/static/logo.png'
>>> asset.render(name="../../etc/passwd")
Traceback (most recent call last):
  ...
wend.errors.InvalidBindingError: name='../../etc/passwd' is not a single path segment; declare 'name' with SubPath('name') to bind multi-segment paths
```

`name` comes after the head of the expression, so it binds exactly one path segment. `../../etc/passwd` is four segments, so the binding is rejected. pathlib joins the same value as written:

```pycon
>>> from pathlib import Path
>>> Path("/srv/static") / "../../etc/passwd"
PosixPath('/srv/static/../../etc/passwd')
```

## The four kinds

A parameter's kind says what it may bind to when it is used as a path operand:

| kind | constructor | accepts |
| --- | --- | --- |
| path (default at the head) | `Param("root")`, `AnyPath(...)` | any path; pathlib join semantics |
| absolute | `Absolute(...)` | an absolute path |
| segment (default after the head) | `Param(...)`, `Segment(...)` | exactly one segment: no `/`, not `""`, `.` or `..` |
| sub-path | `SubPath(...)` | a relative path of zero or more segments, without `..` |

A `Param` takes its kind from its position. At the head of an expression, with nothing before it, it is a path. Anywhere else it is a segment. The other constructors fix the kind wherever the parameter is used: `AnyPath`, `Absolute`, `Segment` and `SubPath`.

```python
from wend import Absolute, Segment, SubPath, T

root, rel, stem = Param("root"), SubPath("rel"), Param("stem")
module = root / "src" / rel / T(t"{stem}.py")
```

```pycon
>>> module
PathExpr('{root}/src/{rel...}/{stem}.py')
>>> module.render(root="/home/a/project", rel="pkg/sub", stem="io")
'/home/a/project/src/pkg/sub/io.py'
>>> module.render(root="project", rel="", stem="setup")
'project/src/setup.py'
>>> module.render(root="project", rel="../..", stem="setup")
Traceback (most recent call last):
  ...
wend.errors.InvalidBindingError: rel='../..' must not contain '..'
```

The pattern writes a sub-path as `{rel...}`. An empty sub-path contributes no segments. An absolute parameter rejects a relative value:

```pycon
>>> home = Absolute("home")
>>> (home / ".config").render(home="/home/a")
'/home/a/.config'
>>> (home / ".config").render(home="home/a")
Traceback (most recent call last):
  ...
wend.errors.InvalidBindingError: home='home/a' must be an absolute path
```

Kinds apply to path operands. A parameter inside a formatted field, such as `{stem}` in `t"{stem}.py"`, contributes formatted text to one segment, and that text cannot contain a `/` ([Expressions](<https://lmmx.github.io/wend/pr-preview/pr-108/concepts/expressions/#path-operands-and-formatted-fields>)).

## Type, choices and default

```python
split = Segment("split", choices={"train", "test"})
idx = Param("idx", type=int)
total = Param("total", type=int, default=100)

shard = P("data") / split / T(t"chunk_{idx:04d}-of-{total:04d}.parquet")
```

- `type=` is checked with `isinstance` when a value is bound. It also tells `match` how to read text back, so `idx` matches as an `int`. `Param` and `Segment` take `type=`. `SubPath`, `AnyPath` and `Absolute` bind paths, so they do not.
- `choices=` lists the accepted values. `match` reads only those values, which can make a path that would otherwise be ambiguous readable in one way ([Rendering and matching](<https://lmmx.github.io/wend/pr-preview/pr-108/concepts/matching/#ambiguity-is-an-error>)).
- `default=` is the value used when a path is rendered without a binding for the name.

```pycon
>>> shard.render(split="train", idx=7)
'data/train/chunk_0007-of-0100.parquet'
>>> shard.render(split="val", idx=7)
Traceback (most recent call last):
  ...
wend.errors.InvalidBindingError: split='val': not one of {'test', 'train'}
>>> shard.match("data/test/chunk_0003-of-0100.parquet")
Match('data/test/chunk_0003-of-0100.parquet', {'split': 'test', 'idx': 3, 'total': 100})
>>> sorted(shard.required_params())
['idx', 'split']
```

A default is part of the declaration, and is checked against the `type`, `choices` and kind when the parameter is declared. It is used when a path is rendered, and nowhere else:

- `bind` leaves a defaulted parameter free. `defaults` gives the defaults by name, and `shard.bind(shard.defaults)` applies them.
- `match` reads every part from the path, so a default never makes a part optional.
- `glob` finds a defaulted parameter's values on disk, and does not fix it to its default.

```pycon
>>> shard.bind(shard.defaults)
PathExpr('data/{split}/chunk_{idx:04d}-of-0100.parquet')
>>> print(shard.match("data/test/chunk_0003.parquet"))
None
```

Two different declarations under one name in one expression raise `ParamConflictError`.

## Why a segment cannot traverse

A segment parameter's value must be exactly one segment: it contains no `/`, and it is not `""`, `.` or `..`. Each of those would change the path's structure, so a value bound to a segment parameter always names one entry of the directory before it. A sub-path parameter has the same property: its value is relative and contains no `..`.

So untrusted input, such as a file name from a request, can be bound to a `Param` after the head, a `Segment` or a `SubPath`: no value bound to it takes the rendered path outside a literal base before it. [SEMANTICS.md §8](<https://github.com/lmmx/wend/blob/master/docs/SEMANTICS.md#8-what-is-guaranteed-by-construction-and-what-is-only-tested>) records that this is tested with random expressions and operations.

A `Param` at the head and an `AnyPath` accept any path, and an `Absolute` accepts any absolute path. A value bound to one of them can lead anywhere. To keep such a path below a base, declare `Under` on it ([Effects](<https://lmmx.github.io/wend/pr-preview/pr-108/concepts/effects/#conditions-that-need-no-filesystem>)).

## A joined `str` is a trusted literal

A `str` joined with `/` is part of the expression's literal text, with pathlib's rules. Its `..` segments are kept, and an absolute `str` replaces everything before it:

```pycon
>>> asset / "../../etc"
PathExpr('/srv/static/{name}/../../etc')
>>> asset / "/etc"
PathExpr('/etc')
```

Literal text is part of the program. Bind untrusted values to a parameter, and do not join them.

## Reference

- `Param`, `Segment`, `SubPath`, `AnyPath`, `Absolute`, `Kind`
- [SEMANTICS.md §2](<https://github.com/lmmx/wend/blob/master/docs/SEMANTICS.md#2-position-of-a-parameter-operand>) (position), [§3](<https://github.com/lmmx/wend/blob/master/docs/SEMANTICS.md#3-values-of-parameter-operands>) (values) and [§3.1](<https://github.com/lmmx/wend/blob/master/docs/SEMANTICS.md#31-defaults>) (defaults)
