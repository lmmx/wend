# Pipeline steps

A pipeline step reads a day's raw readings, drops the rows with no value, and writes a clean copy. This guide declares what the step needs before it runs and what it promises afterwards, runs it as a `Step`, and shows what happens when it runs again or fails. It needs Python 3.14 and wend, with no extras. The examples build on each other: run them in order, in an empty directory.

## Declare the paths and their conditions

```python
from wend import Absent, Creatable, Exists, File, P, Param, Readable, Step, T

root, day = Param("root"), Param("day")

raw = (P(root) / "raw" / T(t"{day}.csv")).requires(File, Exists, Readable)
clean = (P(root) / "clean" / T(t"{day}.csv")).requires(Absent, Creatable)
clean = clean.ensures(File, Exists)

convert = Step(raw=raw, clean=clean)
```

- `requires` declares preconditions. The raw file must be an existing, readable file. Nothing may be at the clean path yet, and it must be possible to create it.
- `ensures` declares postconditions: after the step, the clean path is an existing file.
- `Step` groups the paths that one step uses, by name. Its bindings are shared, and each path takes the parameters it uses.

`effects` lists what each path is declared to be used for:

```pycon
>>> convert
Step(raw='{root}/raw/{day}.csv', clean='{root}/clean/{day}.csv')
>>> convert.effects()
[<raw: read {root}/raw/{day}.csv>, <clean: create {root}/clean/{day}.csv>]
```

`read` comes from `Readable`, and `create` from `Creatable`. A path that must exist afterwards and need not exist before is also listed as `create`. The list reports the declarations. It does not observe what the step's code does.

## Write the transform

The transform is ordinary code that takes two `pathlib.Path` values:

```python
import csv
from pathlib import Path


def drop_missing(src: Path, dst: Path) -> None:
    with src.open(newline="") as f:
        rows = [row for row in csv.DictReader(f) if row["temp_c"].strip()]
    dst.parent.mkdir(parents=True, exist_ok=True)
    with dst.open("w", newline="") as f:
        out = csv.DictWriter(f, fieldnames=["station", "temp_c"])
        out.writeheader()
        out.writerows(rows)


Path("data/raw").mkdir(parents=True)
Path("data/raw/2026-10-17.csv").write_text("station,temp_c\nA,11.5\nB,\nC,9.0\n")
```

## Run the step

Calling the step with bindings gives a context manager. Entering it checks every precondition and gives the rendered paths, as a dict keyed by the names given to `Step`. Leaving it without an exception checks every postcondition.

```pycon
>>> with convert(root="data", day="2026-10-17") as p:
...     print(p)
...     drop_missing(p["raw"], p["clean"])
{'raw': PosixPath('data/raw/2026-10-17.csv'), 'clean': PosixPath('data/clean/2026-10-17.csv')}
>>> print(Path("data/clean/2026-10-17.csv").read_text())
station,temp_c
A,11.5
C,9.0
<BLANKLINE>
```

## Run it a second time

The clean file now exists, and the step requires it to be absent. The second run raises before the body runs, so the output is not overwritten:

```pycon
>>> with convert(root="data", day="2026-10-17") as p:
...     drop_missing(p["raw"], p["clean"])
Traceback (most recent call last):
  ...
wend.errors.PathExistsError: 'data/clean/2026-10-17.csv' already exists (required: Absent)
```

`PathExistsError` is also a `FileExistsError`. A loop over every day with input can run the step for each one and skip the days already done. `glob` yields a `Match` for each raw file, and a `Match` is a mapping of bindings, so it can be passed to the step:

```python
Path("data/raw/2026-10-18.csv").write_text("station,temp_c\nA,12.0\nB,10.5\n")
```

```pycon
>>> for m in raw.glob(root="data"):
...     try:
...         with convert(m) as p:
...             drop_missing(p["raw"], p["clean"])
...     except FileExistsError:
...         print("skipped", m["day"])
...     else:
...         print("converted", m["day"])
skipped 2026-10-17
converted 2026-10-18
```

## A missing input

A day with no raw file fails on entry, with `MissingPathError`, a `FileNotFoundError`:

```pycon
>>> with convert(root="data", day="2026-10-19") as p:
...     drop_missing(p["raw"], p["clean"])
Traceback (most recent call last):
  ...
wend.errors.MissingPathError: 'data/raw/2026-10-19.csv' does not exist (required: Exists)
```

`check` runs the same checks without a body, and returns the rendered paths. Once the input exists, they pass:

```python
Path("data/raw/2026-10-19.csv").write_text("station,temp_c\n")
```

```pycon
>>> convert.check(root="data", day="2026-10-19")
{'raw': PosixPath('data/raw/2026-10-19.csv'), 'clean': PosixPath('data/clean/2026-10-19.csv')}
```

## A body that does not write its output

If the body finishes without creating the clean file, the postcondition fails when the block is left:

```pycon
>>> with convert(root="data", day="2026-10-19") as p:
...     pass
Traceback (most recent call last):
  ...
wend.errors.MissingPathError: 'data/clean/2026-10-19.csv' does not exist (required: Exists)
```

If the body raises, its exception propagates and the postconditions are not checked. `confirm` checks the postconditions on their own.

## A step that replaces its output

To let a step overwrite its output, declare `Writable` in place of `Absent` and `Creatable`. `Writable` holds for an existing path that can be written, or for one that can be created.

```pycon
>>> from wend import Writable
>>> output = (P(root) / "clean" / T(t"{day}.csv")).requires(Writable)
>>> rebuild = Step(raw=raw, clean=output.ensures(File, Exists))
>>> rebuild.effects()
[<raw: read {root}/raw/{day}.csv>, <clean: create, write {root}/clean/{day}.csv>]
>>> with rebuild(root="data", day="2026-10-17") as p:
...     drop_missing(p["raw"], p["clean"])
```

## What the checks guarantee

Each check describes the filesystem at the moment it runs. A file that exists when the step is entered can be removed before the body opens it, and the checks are not atomic with the body's reads and writes. The conditions state what the step expects and catch mistakes such as a missing input or an output that would be overwritten ([Effects](<https://lmmx.github.io/wend/pr-preview/pr-119/concepts/effects/#checks-are-point-in-time>)).

## See also

- [Effects](<https://lmmx.github.io/wend/pr-preview/pr-119/concepts/effects/index.md>): every condition, what it checks, and the error it raises.
- [Lineage and caching](<https://lmmx.github.io/wend/pr-preview/pr-119/guides/lineage/index.md>): record what each run of a step made from what, with `Ledger.run`.
- API reference: `Step`, `PathExpr.requires`, `PathExpr.ensures`, `wend.conditions`, `wend.errors`.
