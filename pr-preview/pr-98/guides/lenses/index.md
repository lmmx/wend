# Mapping between trees

A site generator turns each Markdown file under `src/` into an HTML file at the same place under `site/`. This guide declares that relation once as a `Lens`, maps paths in both directions, and finds the pages that need building again. It needs Python 3.14 and wend, with no extras. The examples build on each other: run them in order, in an empty directory.

## Declare the lens

```python
from wend import Lens, P, Param, SubPath, T

rel, stem = SubPath("rel"), Param("stem")
source = P("src") / rel / T(t"{stem}.md")
output = P("site") / rel / T(t"{stem}.html")

build = Lens(source, output)
```

The two expressions share the parameters `rel` and `stem`. `rel` is a `SubPath`: zero or more directory names. Calling the lens matches a path against the source and renders the bindings through the output:

```pycon
>>> build
Lens('src/{rel...}/{stem}.md' -> 'site/{rel...}/{stem}.html')
>>> build("src/guide/install.md")
PosixPath('site/guide/install.html')
>>> build("src/index.md")
PosixPath('site/index.html')
>>> build.backward("site/guide/install.html")
PosixPath('src/guide/install.md')
```

`backward` maps the other way, from an output to its source. `render` returns the output as a `str`. A path that the source does not describe raises `NoMatchError`, a `ValueError`:

```pycon
>>> from wend import NoMatchError
>>> try:
...     build("src/notes/todo.txt")
... except NoMatchError as e:
...     print(e)
'src/notes/todo.txt' does not match 'src/{rel...}/{stem}.md'
```

## Map many paths

Create a source tree with three pages and a file that is not a page:

```python
from pathlib import Path

for name in ["index.md", "guide/install.md", "guide/usage.md", "notes/todo.txt"]:
    path = Path("src", name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"# {path.stem}\n")
```

`map` yields a pair `(path, output)` for each path that the source describes, in the order given, and skips the others:

```pycon
>>> files = sorted(str(p) for p in Path("src").rglob("*") if p.is_file())
>>> for src, out in build.map(files):
...     print(src, "->", out)
src/guide/install.md -> site/guide/install.html
src/guide/usage.md -> site/guide/usage.html
src/index.md -> site/index.html
```

`source.glob()` finds the same pages directly, with their bindings:

```pycon
>>> [m.path for m in source.glob()]
['src/guide/install.md', 'src/guide/usage.md', 'src/index.md']
```

## Find stale outputs

An output is stale when it does not exist, or when its source was modified after it. Build two of the pages, then edit one of their sources. The example sets the modification times with `os.utime`, so its result does not depend on how fast it runs.

```python
import os

for src, out in build.map(["src/guide/install.md", "src/guide/usage.md"]):
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(f"<h1>{out.stem}</h1>\n")
    os.utime(src, (1_700_000_000, 1_700_000_000))
    os.utime(out, (1_700_000_060, 1_700_000_060))

os.utime("src/guide/usage.md", (1_700_000_120, 1_700_000_120))


def stale(src, out):
    return not out.exists() or out.stat().st_mtime < os.stat(src).st_mtime
```

```pycon
>>> [src for src, out in build.map(m.path for m in source.glob()) if stale(src, out)]
['src/guide/usage.md', 'src/index.md']
```

`index.md` has never been built, and `usage.md` changed after its page was built.

## Find outputs with no source

An output whose source was deleted is left behind. `inverse` is the lens in the other direction, so mapping every output through it gives each one's source:

```python
Path("site/old.html").write_text("<h1>old</h1>\n")
```

```pycon
>>> pages = [m.path for m in output.glob()]
>>> pages
['site/guide/install.html', 'site/guide/usage.html', 'site/old.html']
>>> [out for out, src in build.inverse().map(pages) if not src.exists()]
['site/old.html']
```

## Parameters only the output has

An output can have parameters that the source does not. They are bound in each call, by keyword or in a mapping after the path:

```pycon
>>> versioned = Lens(source, P("site") / Param("version") / rel / T(t"{stem}.html"))
>>> versioned("src/index.md", version="1.2")
PosixPath('site/1.2/index.html')
>>> versioned.backward("site/1.2/guide/install.html")
PosixPath('src/guide/install.md')
>>> versioned("src/index.md")
Traceback (most recent call last):
  ...
wend.errors.MissingBindingError: Missing bindings: ['version']
```

## Two sources for one target

A lens whose two sides have the same parameters is lossless (`lossless`): each side gives all the bindings the other needs. A lossless lens checks that each output it renders reads back in exactly one way, so that it maps back to a single source. This lens flattens each section into the file name:

```pycon
>>> section = Param("section")
>>> page = P("src") / section / T(t"{stem}.md")
>>> flat = P("flat") / T(t"{section}-{stem}.html")
>>> flatten = Lens(page, flat)
>>> flatten.lossless
True
>>> flatten("src/api/read.md")
PosixPath('flat/api-read.html')
>>> flatten("src/api/io-read.md")
Traceback (most recent call last):
  ...
wend.errors.AmbiguousMatchError: 'flat/api-io-read.html' matches ambiguously: {'section': 'api', 'stem': 'io-read'}, {'section': 'api-io', 'stem': 'read'}. ...
```

`src/api/io-read.md` and `src/api-io/read.md` would both map to `flat/api-io-read.html`, so the lens raises `AmbiguousMatchError` for either of them. It raises whether or not the other source exists, because the output path alone cannot say which source it came from.

Declaring the sections with `choices=` leaves one reading:

```pycon
>>> from wend import Segment
>>> section = Segment("section", choices={"api", "guide"})
>>> page = P("src") / section / T(t"{stem}.md")
>>> flat = P("flat") / T(t"{section}-{stem}.html")
>>> flatten = Lens(page, flat)
>>> flatten("src/api/io-read.md")
PosixPath('flat/api-io-read.html')
>>> flatten.backward("flat/api-io-read.html")
PosixPath('src/api/io-read.md')
```

`map` takes `ambiguous=` with the same values as `glob`: `"raise"` (the default), `"skip"`, or a callable that receives each error, such as `report.append`.

## See also

- [Rendering and matching](<https://lmmx.github.io/wend/pr-preview/pr-98/concepts/matching/index.md>): why a path that reads more than one way is an error.
- [Parameters](<https://lmmx.github.io/wend/pr-preview/pr-98/concepts/parameters/index.md>): `SubPath` and `choices=`.
- API reference: `Lens`, `Lens.map`, `NoMatchError`, `AmbiguousMatchError`.
