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
```

## Requirements

- Python 3.14+ (t-strings, PEP 750)
- Optional: Polars for `wend.frame`

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

### Discovery and lenses

```py
for m in shard.glob(root="/mnt"):  # walks the tree along the expression's structure
    print(m["split"], m["idx"], m.path)  # typed bindings, verified

# below the expression's literal prefix, glob does not follow symlinks unless asked
shard.glob(
    root="/mnt", follow_symlinks=True
)  # pathlib-like; recurse_symlinks for SubPath

from wend import Lens

stem, rel = Param("stem"), SubPath("rel")
build = Lens(P("src") / rel / T(t"{stem}.md"), P("site") / rel / T(t"{stem}.html"))
build("src/guide/install.md")  # PosixPath('site/guide/install.html')
build.backward("site/guide/install.html")  # PosixPath('src/guide/install.md')
# a lossless lens raises AmbiguousMatchError where two sources would share a target
```

### Compilation and batch resolution

- **`compile()`:** generates a specialised Python function per expression, cached on the
  expression. Validation and formatting are inlined, and checks that the structure makes
  redundant are dropped. Any exception falls back to the reference interpreter, so errors
  are identical.
  - `compiled.many(rows)` and `compiled.columns(idx=range(n), ...)` render in bulk.
- **`wend.frame.resolve_frame(expr, df)`:** validates every row of a Polars DataFrame and
  renders natively.
  - Supported: string columns, integer `d`/`0Nd`/`Nd` specs, and `<N`/`>N` padding.
  - Anything Polars can't reproduce exactly raises `NotImplementedError`.
  - Path columns must already be canonical.

Measured with `bench/bench.py`: one 4-vCPU container and one expression shape, so compare
rows rather than absolute numbers.

| workload | wend | baseline |
|---|---|---|
| single resolve, compiled (validated) | ~2 µs to `str`, ~3 µs to `Path` | eager pathlib joins ~3.5–4.5 µs; `os.path.join` ~1.8 µs; unvalidated f-string ~0.9 µs |
| batch, `compiled.many` | ~2 µs/row | unvalidated f-string comprehension ~0.8 µs/row |
| batch, `resolve_frame` (validated) | ~0.3 µs/row | |
| match one path | ~10 µs | hand-written regex + `int()` ~1.5 µs (no round-trip check) |
| glob, 10k files | ~6 µs/file | `Path.glob` + regex ~6 µs/file; `os.walk` + regex ~2 µs/file |

### Layout inference

```py
from wend.infer import infer

schema = infer("path/to/tree")  # or an iterable of relative paths
print(schema)
# Schema(18 paths, 4 layouts)
#       10  file data/{data}/part-{part:03d}.parquet
#        6  file checkpoints/run_{run:d}/epoch_{epoch:02d}.pt
#        1  file README.md
#        1  file checkpoints/run_{run:d}/notes.txt  (optional)
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
- **Optional entries:** a layout is optional when some directory matching a prefix of it
  contains none of its paths.

Layouts are ordinary expressions (`rename`, `match`, `under(root).glob()`, ...), and
`schema.check(paths)` lists paths that don't fit.

### Examples

[`examples/`](examples/) has runnable scripts:
- dataset shard manifests and gap detection;
- source-to-build mapping with staleness checks;
- a project layout bound per environment;
- untrusted input;
- pipeline pre- and postconditions;
- layout inference.

### Limitations

- POSIX path semantics only (`/` separators, `PurePosixPath` rules).
- `match` and `glob` take a single-regex fast path when every segment parses
  unambiguously by construction. Otherwise they fall back to a general backtracking
  matcher, which is correct but slower.
- Polars resolution rejects non-canonical path columns that `render` would normalise.
- Patterns have no alternation or optional pieces: `app.log.{k}` and `app.log.{k}.gz` are
  two expressions.
- `glob` raises `AmbiguousMatchError` if any path it finds parses more than one way
  (`{stem}.{ext}` on `a.tar.gz`); constrain a field with `choices=` or `type=`.
- `glob`'s symlink policy decides what it traverses; it is not a sandbox.
- Conditions are checked at runtime, at the moment `check` runs; type checkers see a
  plain `PathExpr`. [The conditions journal entry](docs/journal/2026-10-18-conditions-49.md)
  records what static checking could add.
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
