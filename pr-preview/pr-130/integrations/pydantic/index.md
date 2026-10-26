# Pydantic

`wend.pydantic` validates the path fields of a Pydantic model against an expression. A field accepts either a path, which must match the expression, or the bindings to render one. This page needs Python 3.14 and the `pydantic` extra:

```sh
pip install "wend[pydantic]"
```

The examples build on each other: run them in order, in an empty directory.

## A model with path fields

A job reads one day's raw file, writes one shard, and reads a configuration file. Create the files it reads:

```python
from pathlib import Path

Path("data/raw").mkdir(parents=True)
Path("data/raw/mon.csv").write_text("id,value\n1,3\n")
Path("job.toml").write_text("workers = 4\n")
```

Declare the layouts, then annotate each field with `PathOf` and the expression it must fit:

```python
from typing import Annotated

from pydantic import BaseModel

from wend import Exists, File, Match, P, Param, Segment, T, counter
from wend.pydantic import PathOf

root, day = Param("root"), Param("day")
split = Segment("split", choices={"train", "test"})

raw = P(root) / "raw" / T(t"{day}.csv")
shard = P(root) / split / counter("shard", width=3, suffix=".parquet")


class Job(BaseModel):
    src: Annotated[Path, PathOf(raw.requires(File, Exists))]
    dst: Annotated[Match, PathOf(shard)]
    config: Annotated[Path, File, Exists]
```

- `src` must match `raw`, and then be an existing file, because the expression requires `File` and `Exists`.
- `dst` must match `shard`. Its type is `Match`, so the validated value is the path together with its bindings.
- `config` has no layout. The conditions `File` and `Exists` are validators on their own.

## A path as input

```pycon
>>> job = Job(src="data/raw/mon.csv", dst="data/test/shard_007.parquet", config="job.toml")
>>> job.src
PosixPath('data/raw/mon.csv')
>>> job.dst
Match('data/test/shard_007.parquet', {'root': 'data', 'split': 'test', 'idx': 7})
>>> job.dst["idx"]
7
```

A path given as input must have exactly one reading by the expression. After it matches, the expression's preconditions (its `requires`) are checked against the filesystem with the bindings read from the path.

## Bindings as input

Anything that is not a path is taken as bindings: a mapping, or an object such as another model or a dataclass (`wend.bindings`). The path is rendered through the expression when the model is validated, and defaults apply as they do in `render`:

```pycon
>>> job = Job(
...     src={"root": "data", "day": "mon"},
...     dst={"root": "data", "split": "train", "idx": 3},
...     config="job.toml",
... )
>>> job.src
PosixPath('data/raw/mon.csv')
>>> job.dst
Match('data/train/shard_003.parquet', {'root': 'data', 'split': 'train', 'idx': 3})
```

## The field's type

The field's type decides the validated value: `Path` (or another `PurePath` class), `str`, or `Match`. In JSON every one of them is the path string, and the JSON schema records the expression's pattern:

```pycon
>>> job.model_dump_json()
'{"src":"data/raw/mon.csv","dst":"data/train/shard_003.parquet","config":"job.toml"}'
>>> Job.model_json_schema()["properties"]["dst"]
{'format': 'path', 'title': 'Dst', 'type': 'string', 'x-wend-pattern': '{root}/{split}/shard_{idx:03d}.parquet'}
```

## Conditions as validators

wend's conditions validate a path field without `PathOf`, and without importing `wend.pydantic`: `Annotated[Path, File, Exists]` accepts what Pydantic's `FilePath` accepts. `Under` works with a base that has no parameters:

```pycon
>>> from wend import Under
>>> class Export(BaseModel):
...     out: Annotated[Path, Under(P("/data/exports"))]
>>> Export(out="/data/exports/2026-10")
Export(out=PosixPath('/data/exports/2026-10'))
```

A base with parameters needs bindings, so it is declared on an expression, and the field is annotated with `PathOf(expr)`. Annotating the field with it directly raises `TypeError` when the class is defined:

```pycon
>>> class Upload(BaseModel):
...     path: Annotated[Path, Under(P(root))]
Traceback (most recent call last):
  ...
TypeError: Under('{root}') needs bindings for ['root']: declare it on an expression and annotate the field with PathOf(expr)
```

## Invalid input

Invalid input raises a Pydantic `ValidationError`, with one error for each field that fails. The error type says what failed: `wend_no_match`, `wend_ambiguous`, `wend_render` (bindings that do not render) or `wend_condition`.

```pycon
>>> from pydantic import ValidationError
>>> try:
...     Job(src="data/raw/tue.csv", dst="data/val/shard_001.parquet", config="data")
... except ValidationError as e:
...     print(e)
3 validation errors for Job
src
  'data/raw/tue.csv' does not exist (required: Exists) [type=wend_condition, input_value='data/raw/tue.csv', input_type=str]
dst
  data/val/shard_001.parquet does not match {root}/{split}/shard_{idx:03d}.parquet [type=wend_no_match, input_value='data/val/shard_001.parquet', input_type=str]
config
  'data' is not a regular file (required: File) [type=wend_condition, input_value='data', input_type=str]
```

Bindings that do not render report the same error as `render`:

```pycon
>>> try:
...     Job(
...         src="data/raw/mon.csv",
...         dst={"root": "data", "split": "train"},
...         config="job.toml",
...     )
... except ValidationError as e:
...     print(e.errors()[0]["type"], e.errors()[0]["msg"])
wend_render Missing bindings: ['idx']
```

A path that the expression reads in more than one way is rejected, and the message lists the readings:

```pycon
>>> stem, ext = Param("stem"), Param("ext")
>>> class Package(BaseModel):
...     file: Annotated[str, PathOf(P("dist") / T(t"{stem}.{ext}"))]
>>> try:
...     Package(file="dist/tool-1.0.tar.gz")
... except ValidationError as e:
...     print(e.errors()[0]["type"])
wend_ambiguous
```

Checking conditions reads the filesystem, so validating a model with conditions is an effect. The checks describe the filesystem at the moment of validation ([Effects](<https://lmmx.github.io/wend/pr-preview/pr-130/concepts/effects/#checks-are-point-in-time>)).

## See also

- [Settings and anchors](<https://lmmx.github.io/wend/pr-preview/pr-130/guides/settings/index.md>): a Pydantic model as a source of bindings.
- [Rendering and matching](<https://lmmx.github.io/wend/pr-preview/pr-130/concepts/matching/index.md>): what a reading is, and when a path has more than one.
- [Effects](<https://lmmx.github.io/wend/pr-preview/pr-130/concepts/effects/index.md>): the conditions.
- API reference: `wend.pydantic`, `PathOf`, `Match`.
