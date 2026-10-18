# wend

[![PyPI version](https://img.shields.io/pypi/v/wend.svg)](https://pypi.org/project/wend/)
[![Python versions](https://img.shields.io/pypi/pyversions/wend.svg)](https://pypi.org/project/wend/)
[![License](https://img.shields.io/pypi/l/wend.svg)](https://github.com/lmmx/wend/blob/master/LICENSE)
[![pre-commit.ci status](https://results.pre-commit.ci/badge/github/lmmx/wend/master.svg)](https://results.pre-commit.ci/latest/github/lmmx/wend/master)

Symbolic, typed, invertible filesystem paths built from Python t-strings (3.14+).

A wend expression records *how* a path is built — which parts are literal, which are
parameters, how values are formatted — instead of collapsing it to a string. The same
expression can be resolved, partially bound, transformed structurally, matched against
concrete paths, used to discover files on disk, compiled for batch resolution, and
inferred from an existing directory tree.

## Installation

```sh
uv pip install wend          # or: uv pip install "wend[polars]" for vectorised resolution
uv pip install "wend[pydantic]"  # path fields for Pydantic models
uv pip install "wend[fsspec]"  # discovery and inference on object stores
```

## Requirements

- Python 3.14+ (t-strings, PEP 750)
- Optional: Polars for `wend.frame`, Pydantic for `wend.pydantic`
- Optional: fsspec (and its S3, GCS or Azure backend) for `wend.fs.FsspecFS`

## About

For the backstory read the blog series [cog.spin.systems/future-paths][blog], and the
project journal in [`docs/journal/`](docs/journal/).

[blog]: https://cog.spin.systems/future-paths

## Usage

```py
from wend import P, Param, Segment, SubPath, T

root = Param("root")
split = Segment("split", choices={"train", "test"})
idx, total = Param("idx", type=int), Param("total", type=int)

shard = root / "data" / split / T(t"chunk_{idx:04d}-of-{total:04d}.parquet")
shard  # PathExpr('{root}/data/{split}/chunk_{idx:04d}-of-{total:04d}.parquet')

shard.resolve(root="/mnt", split="train", idx=7, total=100)
# PosixPath('/mnt/data/train/chunk_0007-of-0100.parquet')

shard.match("/mnt/data/train/chunk_0007-of-0100.parquet")
# Match(..., {'root': '/mnt', 'split': 'train', 'idx': 7, 'total': 100})

shard.parent  # PathExpr('{root}/data/{split}')  -- no bindings needed
shard.suffix  # Text('.parquet')
shard.with_suffix(
    ".json"
)  # PathExpr('{root}/data/{split}/chunk_{idx:04d}-of-{total:04d}.json')
shard.relative_to(
    root
)  # PathExpr('data/{split}/chunk_{idx:04d}-of-{total:04d}.parquet')
shard.bind(
    root="/mnt", total=4
)  # PathExpr('/mnt/data/{split}/chunk_{idx:04d}-of-0004.parquet')
```

### Building expressions

- `P(x)` makes an expression from a `str`, `os.PathLike`, `Param`, t-string, or expression;
  `T(t"...")` from a t-string. `/` and `joinpath` join.
- A t-string's literal text is split at `/`, so its segment structure is known statically.
- An interpolation that forms a **whole segment** with no format spec or conversion
  (`t"{root}/data/{split}"`) is a *path operand*, joined exactly as `/` would join it.
- Any other interpolation (`t"chunk_{idx:04d}"`) is a **formatted field**: its conversion
  (`!r`, `!s`, `!a`) and format spec are kept and applied at resolution, and specs may be
  dynamic (`t"{idx:0{width}d}"`).
- Formatting a `Param` into a plain f-string is detected and reported.

### Parameter kinds

How a parameter used as a path operand may bind:

| kind | constructor | accepts |
|---|---|---|
| path (default at the head) | `Param("root")`, `AnyPath(...)` | any path; pathlib join semantics |
| absolute | `Absolute(...)` | an absolute path |
| segment (default after the head) | `Param(...)`, `Segment(...)` | exactly one segment: no `/`, not `""`, `.` or `..` |
| sub-path | `SubPath(...)` | a relative path of zero or more segments, without `..` |

`type=` and `choices=` constrain values; `type=` also tells `match` how to parse text back
into a value. Because parameters after the head default to single segments, untrusted
input bound *to a parameter* cannot traverse:

```py
asset = P("/srv/static") / Param("name")
asset.resolve(name="logo.png")  # /srv/static/logo.png
asset.resolve(name="../../etc")  # InvalidBindingError
```

A `str` joined directly (`asset / user_input`) is a trusted literal path with pathlib
semantics, so untrusted values must be bound, never joined.

### Semantics

For every binding accepted by an expression and its sub-expressions, `render` (and
`resolve`) equals the eager pathlib computation of the same operations on the formatted
strings. Bindings that would make pathlib silently change the path's structure are rejected
with `InvalidBindingError` instead:
- a separator inside a segment;
- an empty segment, or a `.` segment;
- an escaping `..`;
- a declared type or choice violation.

Every operation is one of three kinds:

- **static**: computed from structure without bindings: `parent` of a segment,
  `name`/`stem`/`suffix` when the deciding dot is in literal text or an integer field,
  `with_suffix`, `with_name`, `relative_to` a structural prefix, `bind`;
- **deferred**: evaluated with pathlib once its inputs are bound (e.g. `parent` of a
  `SubPath`, or `suffix` of a free-form string field). It is shown in the pattern as
  `parent({root}/{rel...})`;
- **rejected**: invalid for every binding (`P("/").with_name("x")`), raised when the
  expression is built.

A structural operation may eliminate parameters: `(root / split).parent` is `{root}`, whose
value is the same for every valid `split`. Evaluation is non-strict: a sub-expression
discarded by an operation (everything before an absolute join) is never evaluated.

The precise contract is [docs/SEMANTICS.md](docs/SEMANTICS.md). Hypothesis checks it against
a reference evaluator written from that document alone (`tests/contract_test.py`), and
against an eager-pathlib oracle (`tests/oracle_test.py`). The document also says which
guarantees hold by construction and which are only tested.

### Binding and relations

`bind` performs partial evaluation and substitution. Values may be concrete, another
expression (rebasing), or a `Param` (renaming):

```py
config = root / "config" / "settings.yaml"
config.relative_to(root)  # PathExpr('config/settings.yaml')
config.bind(root=P("/tmp/test")).render()  # '/tmp/test/config/settings.yaml'
config.rebase(root, "/elsewhere").render()  # '/elsewhere/config/settings.yaml'
```

### Defaults and bindings from objects

A parameter can declare a default. Rendering uses it when no binding is given
for the name:

```py
total = Param("total", type=int, default=100)
shard = root / "data" / split / T(t"chunk_{idx:04d}-of-{total:04d}.parquet")
shard.required_params()  # {'root', 'split', 'idx'}
shard.render(root="/mnt", split="train", idx=7)
# '/mnt/data/train/chunk_0007-of-0100.parquet'
```

The default is part of the parameter's declaration, and is checked against its
`type`, `choices` and kind when the parameter is declared. It stands in for a
missing binding *when a path is rendered*, and nowhere else:
- `bind` leaves a defaulted parameter free, and `e.bind(e.defaults)` applies the defaults;
- `match` reads every part from the path, so a default never makes a part optional;
- `glob` discovers a defaulted parameter's values rather than fixing it.

Bindings can come from an object instead of a mapping. A dataclass, attrs or
Pydantic instance, a named tuple, or any object's instance attributes bind by
field name. This is Future Paths [part 1](https://cog.spin.systems/future-paths-types)'s
`PathVar`:

```py
ROOT = Param("root")
CONFIG, DATA = ROOT / "config.yaml", ROOT / "data"


@dataclass
class Settings:
    root: Path


CONFIG.resolve(Settings(Path("/actual/root")))  # PosixPath('/actual/root/config.yaml')
```

`wend.bindings(obj)` shows what an object binds. Properties, methods and
Pydantic computed fields don't bind, so a computed field can render a path
from its own model (`CONFIG.resolve(self)`). Keyword bindings override an
object's fields. The rules are in
[SEMANTICS.md §3.1–3.2](docs/SEMANTICS.md#31-defaults).

### Counters and anchors

`counter` writes the sized and unsized counter filenames of Future Paths
[part 3](https://cog.spin.systems/future-paths-template-strings):

```py
from wend import counter

chunk = root / "chunks" / counter("chunk", width=3, of_total=True, suffix=".parquet")
chunk.resolve(root="/data", idx=1, total=10)
# PosixPath('/data/chunks/chunk_001-of-010.parquet')

# {root}/logs/log_{idx:05d}.parquet
log = root / "logs" / counter("log", width=5, suffix=".parquet")
```

Anchors are the standard places a path starts from: `HOME`, `CWD` and the XDG
base directories. Each is a parameter named after its environment variable,
so an expression stays symbolic until you ask for the environment:

```py
from wend import anchors
from wend.anchors import XDG

models = (P("models") / Param("name")).under(XDG.CACHE_HOME / "myapp")
models  # PathExpr('{XDG_CACHE_HOME}/myapp/models/{name}')
models.render(
    anchors.bindings(), name="bert"
)  # reads $XDG_CACHE_HOME (or ~/.cache) now
```

### Pydantic

`wend.pydantic` (the `pydantic` extra) validates path fields against a layout:

```py
from typing import Annotated

from pydantic import BaseModel

from wend import Exists, File, Match
from wend.pydantic import PathOf

raw = P(root) / "raw" / T(t"{Param('name')}.csv")


class Job(BaseModel):
    src: Annotated[Path, PathOf(raw.requires(File, Exists))]  # must match, then exist
    out: Annotated[Match, PathOf(chunk)]  # the path and its typed bindings
    config: Annotated[
        Path, File, Exists
    ]  # conditions are validators: Pydantic's FilePath


job = Job(
    src="/data/raw/a.csv",
    out={"root": "/data", "idx": 1, "total": 10},
    config="app.toml",
)
job.out  # Match('/data/chunks/chunk_001-of-010.parquet', {'root': '/data', 'idx': 1, 'total': 10})
```

A path given as input must have exactly one reading. Bindings given as input
(a mapping, or another model) are rendered through the layout when the model
is validated, as Pydantic's `ImportString` imports. Either way, the layout's
preconditions are then checked against the filesystem.

### Matching

`match(path)` returns the typed bindings that render to `path`, or `None`:
- **Verified:** every candidate is checked by re-rendering it, so a result is always exact
  (`chunk_007` does not match `{idx:04d}`).
- **Ambiguity:** when several bindings fit, it raises `AmbiguousMatchError` rather than
  guessing. Examples are adjacent string fields `{a}{b}`, or a free head next to a
  `SubPath`. `match_all` lists them; binding some parameters first usually resolves it.
- **Not invertible:** deferred operations and fields derived from other paths raise
  `NotInvertibleError`.

### Connectivity

Paths remember how they were built, so relations survive composition (Future Paths
[part 2](https://cog.spin.systems/future-paths-connectivity)):

```py
root = Param("root")
config = P(root).child("config.yaml")
config.base, config.base_rel  # PathExpr('{root}'), PathExpr('config.yaml')
config.rebase(P("/tmp/test"))  # PathExpr('/tmp/test/config.yaml')

data = P(root) / "data" / T(t"{Param('name')}.csv")
schema = data.sibling("schema.json")  # defined by data, not by root
report = data.cousin("../reports", "summary.md")  # {root}/reports/summary.md

# rebasing a path moves everything derived from it
moved = data.rebase(P(root) / "data", P("/archive"))
schema.rebase(data, moved)  # PathExpr('/archive/schema.json')

frag = P("cache") / "models"
[frag.under(b) for b in ("/home/a/.app", "/home/b/.app")]  # one fragment, many bases
```

The rules are in [SEMANTICS.md §9](docs/SEMANTICS.md#9-connectivity).

### Conditions

A path can declare what it must be when it is used, and what a step promises
about it afterwards (Future Paths [part 1](https://cog.spin.systems/future-paths-types)):

```py
from wend import Absent, Creatable, Exists, File, Readable, Step, Under

name = Param("name")
src = (P(root) / "raw" / T(t"{name}.csv")).requires(File, Exists, Readable)
dst = (P(root) / "out" / T(t"{name}.parquet")).requires(Absent, Creatable)
dst = dst.ensures(File, Exists)

convert = Step(src=src, dst=dst)
with convert(root="/data", name="a") as p:  # checks every precondition first
    write(transform(read(p["src"])), p["dst"])
# leaving the block checks the postconditions: dst now exists, as a file

convert.effects()  # [<src: read {root}/raw/{name}.csv>, <dst: create {root}/out/{name}.parquet>]
```

Each failure is a typed `ConditionError`, and each subclass also derives from
the matching builtin error:
- `MissingPathError` is a `FileNotFoundError`;
- `PathExistsError` is a `FileExistsError`;
- `CapabilityError` is a `PermissionError`;
- `WrongKindError` covers paths of the wrong kind.

`e.check(...)` and `e.confirm(...)` check a single path.

`render` stays pure. The one condition it enforces is `Under(base)`, lexically:
a binding can't lead outside the base, through `..` or an absolute value.
`check` also resolves symlinks:

```py
upload = (P(root) / AnyPath("rel")).requires(Under(P(root)))
upload.render(root="/srv", rel="../etc/passwd")  # ContainmentError
```

`File` is a structural fact too: nothing can be joined below a path declared to
be a file. Checks are point-in-time, not a sandbox: a path can change between
`check` and `open`. The rules are in [SEMANTICS.md §10](docs/SEMANTICS.md#10-conditions).

### Unions and queries

Layouts have variants. A union is an ordered set of expressions (`a | b`, or
`U(...)`). `Alt` offers alternatives inside a t-string without any pattern
syntax, so log rotation is one pattern:

```py
from wend import Alt, U

d, k = Param("d"), Param("k", type=int)
logs = U(t"{d}/app.log{Alt('', t'.{k}')}{Alt('', '.gz')}")
for m in logs.glob(d="/var/log"):  # app.log, app.log.1, app.log.2.gz ...
    print(m.path, m.alternative, m.get("k"))
```

`match` and `glob` take every alternative's readings. A path two alternatives
read is ambiguous, as everywhere in wend.

`render` needs a single alternative. `renderings` gives all of them. `first`
is the explicit, effectful fallback, which picks the first alternative that
exists and meets its own conditions:

```py
config = P(home) / ".config/app.toml" | P("/etc/app.toml") | P(pkg) / "default.toml"
config.first(home="/home/a", pkg="/opt/app")  # NoAlternativeError if none exists
```

A query filters what a pattern finds, lazily, as `glob` streams it (Future Paths
[part 1](https://cog.spin.systems/future-paths-types)'s `PathQ`):

```py
from wend.query import modified_after

src = P("src") / SubPath("rel") / T(t"{stem}.py")
tests = P("src") / SubPath("rel") / T(t"{stem}_test.py")
for m in (src - tests).where(File, modified_after(yesterday)).glob():
    ...
```

The rules are in [SEMANTICS.md §11](docs/SEMANTICS.md#11-unions-and-queries).

### Lineage

A path has two pasts (Future Paths [part 1](https://cog.spin.systems/future-paths-types)).

As a plan, an expression records how it was built:

```py
from wend.lineage import Ledger, content_key, explain, tags

raw = (P(root) / "raw" / T(t"{day}.csv")).tag(source="upload")
report = raw.with_suffix(".parquet").cousin("../reports", T(t"{day}.md"))
print(explain(report))  # each operation, sources first
tags(report)  # {'source': 'upload'}: tags are found along the derivation
```

As an artefact, a `Ledger` records which files were made from which, with content
digests:

```py
ledger = Ledger("data/.lineage.jsonl")
with ledger.run(convert, root="data", day="mon") as p:  # a Step; outputs are recorded
    ...
ledger.upstream(out)  # what out was made from
ledger.downstream(raw_file)  # what to rebuild when raw_file changes
ledger.stale(out)  # inputs whose contents changed since out was made
```

Content addressing names a path after what it holds. The key is bound like any value,
so `render` stays pure and `match` reads it back:
`cache.render(root=..., key=content_key(raw_file))`.
The rules are in [SEMANTICS.md §13](docs/SEMANTICS.md#13-lineage).

### Discovery and lenses

```py
for m in shard.glob(root="/mnt"):  # walks the tree along the expression's structure
    print(m["split"], m["idx"], m.path)  # typed bindings, verified

# below the expression's literal prefix, glob does not follow symlinks unless asked
shard.glob(
    root="/mnt", follow_symlinks=True
)  # pathlib-like; recurse_symlinks for SubPath

# a path that parses more than one way is never yielded as a match; by default it
# raises AmbiguousMatchError, ambiguous="skip" drops it, and a callable receives it
stem, ext = Param("stem"), Param("ext")
report = []
found = list((P("/mnt/dist") / T(t"{stem}.{ext}")).glob(ambiguous=report.append))
report[0].path  # '/mnt/dist/tool-1.0.tar.gz'
report[0].candidates  # every verified reading
# [{'stem': 'tool-1', 'ext': '0.tar.gz'}, {'stem': 'tool-1.0', 'ext': 'tar.gz'},
#  {'stem': 'tool-1.0.tar', 'ext': 'gz'}]

from wend import Lens

stem, rel = Param("stem"), SubPath("rel")
build = Lens(P("src") / rel / T(t"{stem}.md"), P("site") / rel / T(t"{stem}.html"))
build("src/guide/install.md")  # PosixPath('site/guide/install.html')
build.backward("site/guide/install.html")  # PosixPath('src/guide/install.md')
# a lossless lens raises AmbiguousMatchError where two sources would share a target;
# build.map(paths, ambiguous=...) takes the same modes as glob
```

Options are keyword-only: `kind=`, `follow_symlinks=`, `recurse_symlinks=`, `ambiguous=`
and `fs=` for `glob`, `ambiguous=` for `Lens.map`, and `cls=` for `resolve`. Bindings can
be keywords too, so:
- a parameter that shares an option's name is bound through the positional mapping, which
  accepts any name: `layout.glob({"kind": "raw"}, kind="file")`;
- for such an expression, a `kind=` keyword without `"kind"` in the mapping could mean
  either, so it raises `TypeError`;
- `render`, `bind` and `compile()` take no options, and a `Lens` takes its path
  positionally, so these accept every parameter name as a keyword.

### Object stores and other filesystems

`glob` and `infer` read a tree through `wend.fs.FileSystem`, a small protocol: list a
directory, say what a path is, walk a tree. The local disk (`LocalFS`) is the default.
`FsspecFS` adapts an [fsspec](https://filesystem-spec.readthedocs.io) filesystem, so the
same expressions run on S3, GCS, Azure or memory, with the same results as on an
identical local tree:

```py
from wend.fs import url_to_fs
from wend.infer import infer

# fs is an FsspecFS around s3fs's S3FileSystem; path is 'bucket/datasets'
fs, path = url_to_fs("s3://bucket/datasets")
for m in shard.glob(root=path, split="train", fs=fs):  # one listing, of .../data/train
    print(m["idx"], m.path)  # 7 bucket/datasets/data/train/chunk_0007-of-0100.parquet
schema = infer(path, fs=fs)
```

- **Paths are the filesystem's own.** fsspec strips the protocol (`bucket/datasets`;
  `/x` on the memory filesystem), and that path is bound like any root. A URL cannot be a
  head, since pathlib reads `s3://bucket` as `s3:/bucket`; `glob` refuses one and points
  to `url_to_fs`.
- **One listing per walk.** By default (`listing="flat"`) a walk lists everything below the
  expression's literal prefix with a single `find` and matches the keys in memory, where a
  directory-by-directory walk makes a request per directory. `FsspecFS(fs,
  listing="tree")` lists directory by directory: use it for filesystems with real
  directories (SFTP, HDFS), or for a prefix holding many keys that the expression never
  reaches.
- **Store semantics.** Stores have no symlinks, so the symlink options change nothing. A
  directory is a key prefix or an explicit marker (a key ending in `/`). An empty
  directory therefore exists only as a marker, and a key that is also a prefix of other
  keys is a directory.

### Compilation and batch resolution

- **`compile()`:** generates a specialised Python function per expression, cached on the
  expression. Validation and formatting are inlined, and checks that the structure makes
  redundant are dropped. Any exception falls back to the reference interpreter, so errors
  are identical.
  - `compiled.many(rows)` and `compiled.columns(idx=range(n), ...)` render in bulk.
- **`wend.frame.resolve_frame(expr, df)`:** validates every row of a Polars DataFrame and
  renders natively, with the same result or error as `render` row by row.
  - Path columns are normalised exactly as `render` normalises them (`a/`, `./a`, `a//b`,
    `/a/./b`; `//x` keeps its two-slash root). Columns that are already canonical skip
    the work.
  - Supported: String, integer and Boolean columns; integer specs in bases `d`, `b`, `o`,
    `x`, `X` with any fill, alignment, sign, `#`, `0`, width and `,`/`_` grouping; string
    specs with fill, `<`/`>`/`^`, width and precision; `!s`/`!r`/`!a` on integers and
    Booleans, `!s` on strings; and `parent`, `with_name`, `with_stem`, `with_suffix` and
    joins applied to unbound paths. The `wend.frame` docstring has the exact list.
  - Anything Polars can't reproduce exactly raises `NotImplementedError` (floats, `!r` on
    strings, `relative_to` on unbound paths...): use `compile().many(rows)` for those.

Measured with `bench/bench.py`: one 4-vCPU container and one expression shape, so compare
rows rather than absolute numbers.

| workload | wend | baseline |
|---|---|---|
| single resolve, compiled (validated) | ~2 µs to `str`, ~3 µs to `Path` | eager pathlib joins ~3.5–4.5 µs; `os.path.join` ~1.8 µs; unvalidated f-string ~0.9 µs |
| batch, `compiled.many` | ~2 µs/row | unvalidated f-string comprehension ~0.8 µs/row |
| batch, `resolve_frame` (validated) | ~0.3 µs/row; ~0.6 µs/row if a path column needs normalising | |
| match one path | ~10 µs | hand-written regex + `int()` ~1.5 µs (no round-trip check) |
| glob, 10k files | ~6 µs/file | `Path.glob` + regex ~6 µs/file; `os.walk` + regex ~2 µs/file |

### Directory schemas

Declare a project's layout once, then bind, validate and scaffold it (Future Paths
[part 1](https://cog.spin.systems/future-paths-types)'s `MLProject`):

```py
from wend import Dir, File
from wend.schema import Tree

index = Param("index", type=int)


class MLProject(Tree):
    data = Dir("data")
    raw = Dir(data / "raw")  # built from another entry: the relation is kept
    models = Dir("models")
    checkpoints = File(models / T(t"model-{index:03d}.pt"), many=True)
    config = File("config.yaml")


project = MLProject("/srv/project")
project.config  # PathExpr('/srv/project/config.yaml', requires=(File, Exists))
project.scaffold()  # creates the directories (an effect; nothing is overwritten)
project.validate()  # Report: missing, extra, misfiled, wrong-kind, too-many, all at once
```

Cardinality is per directory: exactly one by default, `optional=True` for at most one,
and `many=True` for any number. An inferred layout becomes a declaration with
`from_inferred(infer(root))`. `.source()` writes it out as Python to review and keep.
The rules are in [SEMANTICS.md §12](docs/SEMANTICS.md#12-schemas).

### Layout inference

```py
from wend.infer import infer

schema = infer("path/to/tree")  # or an iterable of relative paths
print(schema)
# Schema(18 paths, 4 layouts)
#       10  file 1..*  data/{data}/part-{part:03d}.parquet
#        6  file 1..*  checkpoints/run_{run:d}/epoch_{epoch:02d}.pt
#        1  file 1     README.md
#        1  file 0..1  checkpoints/run_{run:d}/notes.txt
```

Inference works like JSON schema inference (genson, polars-genson), applied to trees:
- **Digit runs:** names sharing a skeleton of digit runs merge. A run that varies becomes an
  `int` field with a spec that round-trips every observed value; a run that stays constant
  stays literal. Names needing different padding are split, so a stray `epoch_7.pt` among
  `epoch_001.pt`... is reported as its own layout.
- **Directories:** sibling directories with similar contents become a segment field.
- **Files:** files sharing an extension become `{stem}.ext`.
- **Repeated fields:** a field that always equals an earlier one becomes the same parameter
  (`train/n{n:08d}/n{n:08d}_{i:d}.JPEG`), so `check` catches misfiled paths.
- **Variable depth:** a tail that recurs at three or more depths below a directory whose
  subdirectories form a family becomes a `SubPath` layout (`src/pkg/{rel...}/{stem}.py`).
  A deep tree of literal directories stays literal.
- **Opaque families:** eight or more sibling directories holding only files, with names
  that share no skeleton (terminfo's `a/att4410`, `b/bvt100`), collapse into one map.
- **Names:** dates become `{year}`, `{month}`, `{day}`; UUIDs and long hex tokens become
  `{uuid}` and `{hex}` string fields.
- **Kinds:** empty directories (or, in an iterable, entries ending in `/`) are observed
  paths too. Each layout is `file` or `dir` and covers paths of its kind only: an empty
  `examples/` in some package directories becomes a `dir` layout `{dir}/examples`, even
  where a `file` layout `{dir}/{name}` has a matching pattern.
- **Cardinality:** each layout reports how many of its paths a directory matching its
  parent holds: `1`, `0..1`, `1..*` or `0..*`. The lower bound is `optional`: some
  directory matching a prefix of the layout contains none of its paths.

Layouts are ordinary expressions (`rename`, `match`, `under(root).glob()`, ...), and
`schema.check(paths)` lists paths that don't fit. Both take kinds as `infer` does:

```py
schema.match("apt/examples", kind="dir")  # only dir layouts; kind="file" for files
schema.match("apt/examples/")  # a trailing "/" is a directory
schema.check(["a/README", "apt/examples/", ("bc/examples", True)])  # (path, is_dir)
```

A path given without a kind (no trailing `/`, not a pair) matches layouts of either kind.

### Examples

[`examples/`](examples/) has runnable scripts:
- dataset shard manifests and gap detection;
- source-to-build mapping with staleness checks;
- a project layout bound per environment;
- untrusted input;
- pipeline pre- and postconditions;
- log rotation and config fallbacks with unions;
- a declared project schema, inferred, validated and scaffolded;
- lineage, invalidation and a content-addressed cache;
- layout inference;
- defaults, settings objects, counters, anchors and Pydantic fields.
- a partitioned dataset in an object store (fsspec's memory filesystem, no network).

### Limitations

- POSIX path semantics only (`/` separators, `PurePosixPath` rules).
- `match` and `glob` take a single-regex fast path when every segment parses
  unambiguously by construction. Otherwise they fall back to a general backtracking
  matcher, which is correct but slower.
- Polars resolution lowers only what Polars reproduces exactly: float columns, `!r` on
  strings and `relative_to` on unbound paths raise `NotImplementedError`, and null values
  are rejected even where `render` would format `None`.
- Alternation expands to a union of plain expressions, so `n` binary `Alt`s make `2ⁿ`
  alternatives (capped at 4096); matching tries each.
- By default `glob` raises `AmbiguousMatchError` if any path it finds parses more than one
  way (`{stem}.{ext}` on `a.tar.gz`). `ambiguous="skip"` or a callback keeps the other
  matches, but the ambiguous paths still have no match: constrain a field with `choices=`
  or `type=` to read them.
- `glob`'s symlink policy decides what it traverses; it is not a sandbox.
- The XDG anchors follow the XDG specification on every POSIX platform, macOS
  included. For `~/Library/...` conventions, bind the anchor to a value from a
  library such as platformdirs.
- Conditions are checked at runtime, at the moment `check` runs; type checkers see a
  plain `PathExpr`. [The conditions journal entry](docs/journal/2026-10-18-conditions-49.md)
  records what static checking could add.
- An expression's head is never a URL: bind the path that `wend.fs.url_to_fs` gives.
- The Rust backend sketched in the blog series is not implemented; see the journal for
  what the measurements say a native backend would need to beat.

Changes from 0.1 (removed names and changed behaviour) are listed in
[docs/MIGRATING.md](docs/MIGRATING.md).

## Contributing

Contributions are welcome! Please:

1.  Open an issue to discuss bugs or feature requests
2.  Fork the repo and submit a PR for changes
3.  Install dev dependencies with `uv sync` and run `pre-commit install`
4.  Keep the semantic contract and its tests together: a change to
    [docs/SEMANTICS.md](docs/SEMANTICS.md) comes with the matching change to the
    reference evaluator in `tests/contract_test.py`, and the reverse

## License

MIT License - see [LICENSE](LICENSE) for details.
