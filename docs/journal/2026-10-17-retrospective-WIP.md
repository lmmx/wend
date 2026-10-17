# 2026-10-17: Retrospective — ideation, t-string regression, soundness, performance

First journal entry for wend. The package was written in January–February 2026 without a
journal; this entry reconstructs the design history from the
[Future Paths](https://cog.spin.systems/future-paths) blog series, the two gists linked from it,
and the repository, then records what was found when the code was probed against pathlib on
Python 3.14.6.

The free-form sections come first. The giacometti-format tail is at the end
([docs/JOURNAL.md](../JOURNAL.md)).

Reproduction scripts for every number below:

- [`scripts/2026-10-17-soundness-probe.py`](scripts/2026-10-17-soundness-probe.py): wend vs eager pathlib
- [`scripts/2026-10-17-resolve-bench.py`](scripts/2026-10-17-resolve-bench.py): per-resolve timings
- [`scripts/2026-10-17-rust-path-semantics.rs`](scripts/2026-10-17-rust-path-semantics.rs): `std::path` vs pathlib

---

## Provenance

| Date | Artefact | Content |
|---|---|---|
| 2026-01-18 | [Part 1: Semantic Types](https://cog.spin.systems/future-paths-types) | Phantom-typed paths, effects/capabilities, lenses, lineage, content-addressing, directory schemas (with filesystem schema inference à la polars-genson), path algebra, `PathVar` late binding |
| 2026-01-18 | [Part 2: Connectivity](https://cog.spin.systems/future-paths-connectivity) | Relations as values: `base`/`base_rel`, `rebase`, `sibling`, `cousin`; five requirements (relation type, base tracking, rebasing, composition rules, type integration) |
| 2026-01-18 23:34 | [PoC gist `deferred_path_exprs.py`](https://gist.github.com/lmmx/f5d1b07d266f160f9a431c1f6bdc8a17) | `Param` placeholders inside t-strings; `JoinExpr`/`ParentExpr`/`SiblingExpr`/`WithSuffixExpr`/`TemplateExpr`; rewrites applied at resolve time |
| 2026-01-18 | [Part 3: Deferred Path-ification](https://cog.spin.systems/future-paths-template-strings) | Walkthrough of the PoC gist |
| 2026-01-19 12:59 | [Design report gist](https://gist.github.com/lmmx/bb2ad52a9efee015c3cd2a083ef3d63d) | Agent-written report, "Lazy Path Execution: Polars Analogues"; proposes a Rust crate named `pathforge` |
| 2026-01-20 | [Part 4: Compilation Theory](https://cog.spin.systems/future-paths-compilation-theory) | Term rewriting (termination, confluence, completeness), e-graphs, Datalog, "do we need a parser?", stack vs register machines, SSA, slot allocation |
| 2026-01-20 | [Part 5: Lazy Execution](https://cog.spin.systems/future-paths-lazy-execution) | Rust arena + `PathExpr` enum + fixed-point optimiser + slot instruction executor + pyo3; Python API `compile_path(expr)` |
| 2026-02-03 16:45 | `da961f9 feat: initial commit` | `src/wend/__init__.py`, 290 lines, pure Python |
| 2026-02-03 17:44 / 17:55 | PyPI `wend` 0.1.0, 0.1.1 | 0.1.1 differs by a one-line README fix (`f62e20c`) |
| 2026-02 → 2026-09-01 | `#2`–`#15` | pre-commit autoupdates only |

What shipped is the Part 3 PoC plus the Part 4 rewrite rules. None of Part 5's Rust (arena,
`compile_path`, `CompiledPath`, `num_instructions`, `num_slots`) is in the repository or in either
PyPI wheel (4.6 kB, pure Python). Part 5's error type is named `PathForgeError`, matching the
report's `pathforge` crate name. If Rust code was written, it lives under that name somewhere
outside this repository.

## The idea, compressed

**A path should be a plan, not a value.** `pathlib` composition gives you a concrete value
immediately and throws away intent (what kind of path this is), relation (what it is relative
to) and parameterisation (which parts vary). The series goes after each of these:

- **Types** (Part 1) carry intent: file/dir, must-exist/must-not, `Under[ROOT]`, capabilities.
- **Relations** (Part 2) carry connectivity: a path keeps its base and can be rebased.
- **Placeholders** (Part 3) carry parameterisation. A t-string evaluates its interpolations
  eagerly, but when the evaluated value is a `Param` sentinel the `Template` keeps the slot's
  name, conversion and format spec (`:04d`) for later. This is laziness without thunks. PEP 750
  left deferral to wrapper objects after the lambda opt-in was dropped
  ([LWN](https://lwn.net/Articles/1005000),
  [DPO](https://discuss.python.org/t/deferred-evaluation-for-template-strings/91481)), and
  `Param` is such a wrapper — one that, unlike `lambda: x`, can be inspected
  (`required_params()`).
- **Compilation** (Parts 4–5): once a path is a tree, it can be rewritten (simplified) and
  lowered to straight-line code.

## What shipped vs. the PoC gist

- Rewrites moved from resolve time (PoC `ParentExpr.resolve` checked `isinstance(child, JoinExpr)`)
  to construction time (`JoinExpr.create`, `ParentExpr.create`, `WithSuffixExpr.create`). As a
  result a rewrite can no longer see bindings, so it becomes an unconditional structural claim
  (see Soundness).
- Dropped: PoC `TemplateExpr.parent`, which cut a template at its last `/` by string surgery.
- Changed: `SiblingExpr` (PoC: `base.parent / name`) became `WithNameExpr` (pathlib `with_name`).
- Changed: `P()` means a literal in wend (it was the `Param` shorthand in the PoC).
- Added: `required_params()`, missing-binding check, an `id()`-keyed memo cache, `RelativePath`
  with `rebase`.

## The t-string regression between the design report and Part 5

### Three snapshots of the template node

**Part 3 / wend (Python).** The template node *is* the `string.templatelib.Template`: strings
and interpolations already separated by CPython's parser, each interpolation carrying
`value` (a `Param`), `expression`, `conversion`, `format_spec`. Resolution calls
`format(bound_value, spec)` (`src/wend/__init__.py:133-149`), so `idx=7` with `:04d` gives `0007`.

**Design report, 2026-01-19.** Still structurally faithful:

```rust
pub enum TemplatePart {
    Literal(SmolStr),
    Interpolation { param: SmolStr, format_spec: Option<SmolStr> },
}
```

and the proposed Python API keeps the t-string and passes an int:

```python
expr = root / "datasets" / dataset / t"chunk_{idx:04d}.parquet"
compiled.resolve(root="/data", dataset="train", idx=i)
```

But its executor is `execute(&self, bindings: &HashMap<SmolStr, &Path>)`. Every `LoadParam`
writes a `PathBuf` into a slot, and `FormatTemplate { args: Vec<SlotId> }` reads `PathBuf`
slots. **The slot machine has a single type, `PathBuf`.** By the time a template is formatted,
`idx` is already the path `"7"`, and `:04d` has nothing to apply to. The report's API and its
executor contradict each other, and nothing in the report points this out.

**Part 5, 2026-01-20.** The contradiction is resolved by changing the API, not the executor:

```rust
Template { format: SmolStr, params: Vec<SmolStr> },
```
```python
template = T("chunk_{idx}.parquet", ["idx"])
compiled.resolve({"root": "/data", "dataset": "train", "idx": f"{i:04d}"})
```

with `execute(&self, bindings: &HashMap<SmolStr, PathBuf>)`.

### What was mistaken at that juncture

1. **A parsed AST was turned back into source text at the FFI boundary.** A t-string *is* a
   parse: `Template.strings` / `Template.interpolations` are the AST. `T("chunk_{idx}.parquet",
   ["idx"])` throws that away and hands Rust a string to re-parse. This reverses Part 4's own
   conclusion, written the same day: "Python is our parser", and a text-based pattern syntax
   "defeats the point of the current design (where Python t-strings handle the parsing)".
2. **Parameter names are now stated twice** (`{idx}` in the string, `["idx"]` in the list). That
   duplication is exactly what the `Param` sentinel existed to avoid. The names now come from
   strings, not from Python objects, so the link is gone that let `required_params()` be derived
   rather than declared.
3. **Formatting moved back to the call site.** `"idx": f"{i:04d}"` means the caller writes an
   f-string on every iteration. That was the eager, scattered formatting the project set out to
   get rid of. The README's sharded-dataset example (`chunk_{idx:04d}-of-{total:04d}`) can't be
   expressed in the Part 5 API without the caller doing the padding.
4. **Root cause: the value domain was conflated with the path domain.** A path template has two
   stages: *values* (int, str, date — formatted by `__format__` with a spec) become *segments*
   (strings), and segments become *paths*. The register machine was given only the last domain.
   Part 5's "Where This Leads" acknowledges the loss ("they could support format specs like the
   Python proof-of-concept's t-string integration") but presents it as future work rather than
   as a regression.
5. **Polars was the wrong analogy at this one node.** Polars expressions lower cleanly because
   every `Expr` already means something in Rust. A t-string interpolation's meaning is
   `type(value).__format__(spec)`, i.e. arbitrary Python code. The template leaf is the one
   node whose meaning lives in Python, and the analogy treated it as plain data.

### A lowering that keeps both

- Keep `TemplatePart::Interpolation { param, conversion, spec }` (the report had this right).
- Give slots a value type (`enum Value { Int(i64), Str(SmolStr), Path(PathBuf), … }`), or
  format at load time (`LoadParamFormatted { slot, param, spec }`).
- Parse the format-spec mini-language
  (`[[fill]align][sign][z][#][0][width][grouping][.precision][type]`) for int and str. That subset
  covers the shard-numbering patterns; fall back to a Python callback (or refuse at compile time)
  for other types and specs.
- Use pathlib as the oracle for Rust path ops, not `std::path`. Running
  `scripts/2026-10-17-rust-path-semantics.rs` shows they differ:

| Operation | Rust `std::path` | pathlib |
|---|---|---|
| `set_extension(".json")` / `with_suffix(".json")` on `/x/a.txt` | `/x/a..json` | `/x/a.json` |
| parent of `/` | `None` | `/` |
| parent of `a` | `Some("")` | `.` |
| `/x` joined with `.` | `/x/.` | `/x` |

  If the report's executor (`path.set_extension(suffix)`) receives the pathlib-style `".json"`
  argument that `PathExpr.with_suffix` takes, it produces the double dot.

## Soundness of the construction-time rewrites

`scripts/2026-10-17-soundness-probe.py` compares wend with eager pathlib:

| Expression (`root="/x"`) | wend | pathlib |
|---|---|---|
| `(root / "a/b").parent` | `/x` | `/x/a` |
| `(root / ds).parent`, `ds="train/v2"` | `/x` | `/x/train` |
| `(root / T(t"{ds}/c_{idx}")).parent` | `/x` | `/x/tr` |
| `(root / ".").parent` | `/x` | `/` |
| `(root / "/abs/f").parent` | `/x` | `/abs` |
| `(root/"a.tar.gz").with_suffix("").with_suffix(".json")` | `/x/a.tar.json` | `/x/a.json` |
| `(root/"a.txt").with_suffix(".tar.gz").with_suffix(".json")` | `/x/a.json` | `/x/a.tar.json` |
| `T(t"f_{ds!r}")`, `ds="a"` | `f_a` | `f_'a'` |

Controls that hold: `(root/"f.txt").with_suffix(".json").parent`, and literal folding.

**Diagnosis.** Part 4 checked *termination* and *confluence*. It did not check *soundness*:
whether each rule's two sides are equal in the model, here pathlib. A rewrite system can be
terminating and confluent and still wrong.

- `Parent(Join(a, b)) → a` holds only when `b` is exactly one non-`.`, non-empty, relative
  component. Part 5 states this ("assuming b is a single path component"), but
  `ParentExpr.create` (`src/wend/__init__.py:185-195`) checks the *node type*
  (`LiteralExpr | ParamExpr | TemplateExpr`, line 190) instead. For `ParamExpr` and
  `TemplateExpr` the condition depends on values bound later, so it can't be decided when the
  node is built.
- The parent rewrite also changes `required_params()`: `(root / ds).parent.required_params()`
  is `{'root'}`. Part 3 sold this as a feature ("we don't have to specify the idx"). It is only
  correct when `idx` is known to fill a single segment.
- `WithSuffix(WithSuffix(a, s1), s2) → WithSuffix(a, s2)` holds only when `s1` is non-empty and
  contains exactly one dot. `with_suffix` replaces the *last* dot-suffix, so `""` (strip) and
  `".tar.gz"` (two dots) both break it (`src/wend/__init__.py:234-242`).
- `!r`/`!s`/`!a` conversions are not applied before `format()` (`src/wend/__init__.py:141-144`).

**The link between the parts.** The semantic types from Part 1 are what make the rewrites in
Part 4 *legal*. Declaring a `Param` as `Segment` (one relative component: no separator, not
absolute, not `.`/`..`/empty) makes `Parent(Join(a, Segment)) → a` an equation. A `SubPath`
param gets no parent rewrite. Rules become guarded rewrites
(`Parent(Join(a, b)) → a  if  kind(b) = Segment`), and checking kinds at resolve time costs one
string scan per param. The same `Segment` guarantee is what makes the string-concatenation
lowering in the next section sound.

**Differential testing has a free oracle.** Hypothesis can generate random expression trees and
bindings, then compare `expr.resolve(b)` with the same operations done eagerly in pathlib. Every
row in the table above falls out of that, and so would any future Rust backend's divergences
from pathlib.

## Performance

`scripts/2026-10-17-resolve-bench.py`, Python 3.14.6, the README's chunk-file expression
(`root / "data" / dataset / T(t"chunk_{idx:04d}-of-{total:04d}.parquet")`):

| Lowering | ns / resolve |
|---|---|
| wend `expr.resolve(b)` | 8,863 |
| wend `expr._resolve(b, {})` (skips the `required_params` check) | 7,289 |
| wend `expr.required_params()` alone | 805 |
| eager pathlib joins + f-string leaf | 3,547 |
| `Path(fmt.format_map(b))` | 1,677 |
| generated f-string function → `Path` | 1,403 |
| generated f-string function → `str` | 802 |
| `Path(s)` alone | 553 |
| `str(Path(s))` (construct + parse + render) | 3,449 |
| batch, generated f-string → `str`, per item (100k) | 933 |
| **batch, polars `pl.format` + `str.zfill`, per item (100k)** | **155.5** |

Observations:

- The design report estimated "Current Python ~1µs, estimated Rust ~100ns" per resolution. The
  measured wend figure is 8.9µs.
- pathlib parses lazily (a `Path` stores its raw segments and parses on first use).
  `Path(s)` costs 553ns, but the first `str()`/`fspath` costs another ~2.9µs. Any route that hands the caller a `pathlib.Path` they then `open()` pays
  that ~3.4µs, whatever produced the string.
- PyO3 ≥ 0.25 converts `PathBuf` by calling `pathlib.Path(...)`
  ([changelog](https://pyo3.rs/v0.25.0/changelog),
  [source](https://pyo3.rs/main/doc/src/pyo3/conversions/std/path.rs.html)). So a per-item Rust
  resolve that returns `Path` can't get below the `Path(s)` row, and in practice pays the render
  cost too. This is the ceiling on Part 5's "No Python object allocation" claim.
- Code generation in pure Python (emit an f-string function per compiled expression) reaches
  1.4µs to `Path` and 0.8µs to `str`: 6–11× faster than wend today, with no Rust.
- The real Polars analogue is to *compile to a Polars expression* and resolve a column of
  bindings: 155ns/item, 57× faster than wend, with output as Arrow strings that never become
  Python objects. In this setting Rust (via a polars plugin) pays off for operations `pl.format`
  can't express (parent, with_suffix, pathlib normalisation, existence/glob effects run in
  parallel).
- Concatenation-based lowerings are only equal to pathlib joins when every param is a `Segment`:
  `Path(f"/x/{'/abs'}")` is `/x/abs`, while `Path("/x") / "/abs"` is `/abs`. The same
  `Segment`/`SubPath` declaration decides both rewrite soundness and whether the fast lowering
  can be used.

## Open threads

Blog promises with no code yet, plus directions that came out of this review:

- **Reverse direction: parsing.** A `Template` holds literal strings and format specs, which is
  enough to derive a regex (`:04d` → `(\d{4})`, plain `{x}` → `([^/]+)` for a `Segment`). That
  gives `expr.match(path) -> bindings` and `expr.glob(partial_bindings)` (enumerate which bindings
  exist on disk), i.e. Snakemake-style wildcards, typed and composable. It is also Part 1's lens
  (`forward`/`backward`) for the case where the backward map is parsing.
- **Filesystem schema inference à la polars-genson** (Part 1). Observe directory trees, infer node
  kind, name fixity vs parameterisation (`model-{index:03}.pt`), cardinality. The output is a set
  of wend expressions, so inference produces templates and `match` checks them. The genson-core
  analogue of Record → Map unification is literal-names → parameterised-name unification.
- **Substitution as the single primitive.** Allow bindings to map to `PathExpr`, not only values.
  Then `Param` is a hole, `RelativePath.rebase` is substitution of the base hole, partial
  binding (`expr.bind(root=...)` followed by folding) is staged compilation, and
  `required_params()` is the set of free variables.
- **Param kinds** (`Segment`, `SubPath`, `Absolute`) as the bridge from Part 1 types to Part 4
  rewrite guards and to the concatenation lowering.
- **Compile targets**, in order of cost: generated f-string function, Polars expression, Rust
  slot machine with a value-typed slot domain and pathlib-oracle tests.
- **Part 1/2 surface:** `Annotated` existence/kind checks (`FilePath`, `NewPath` equivalents) at
  resolve time; `Under[ROOT]` traversal guard; `sibling`/`cousin`; `stem`/`name`/`suffix` as
  expressions; lineage tags; a readable repr (`$root/data/$dataset/chunk_{idx:04d}…`).

---

## Current State

- `Param` (`src/wend/__init__.py:19-33`) is a frozen dataclass holding a name; `/` with a `Param` operand wraps it in `ParamExpr` and returns a `PathExpr`
- `PathExpr.__truediv__` and `__rtruediv__` normalise `str`, `Param` and `PathExpr` operands and build nodes through `JoinExpr.create` (`src/wend/__init__.py:42-52`)
- `JoinExpr.create` folds `LiteralExpr / LiteralExpr` into a single `LiteralExpr` at construction time (`src/wend/__init__.py:158-163`)
- `ParentExpr.create` returns `child.left` when `child` is a `JoinExpr` whose right node is a `LiteralExpr`, `ParamExpr` or `TemplateExpr`, and folds the parent of a `LiteralExpr` (`src/wend/__init__.py:185-195`)
- `WithSuffixExpr.create` replaces a nested `WithSuffixExpr` with the outer suffix and folds `with_suffix` on a `LiteralExpr` (`src/wend/__init__.py:234-242`)
- `WithNameExpr` applies pathlib `with_name` at resolve time with no construction-time rewrite (`src/wend/__init__.py:209-224`)
- `TemplateExpr` stores a `string.templatelib.Template`, collects `Param` interpolation names into `_params` in `__post_init__`, and calls `format(value, item.format_spec)` per interpolation at resolve time (`src/wend/__init__.py:117-149`)
- `PathExpr.resolve` computes `required_params()` recursively, raises `ValueError("Missing bindings: ...")` for unbound names, then walks the tree with an `id()`-keyed cache local to the call (`src/wend/__init__.py:68-75`)
- The `id()`-keyed cache in `_resolve` returns a hit only when the same node object appears more than once in a single expression tree — the README and test expressions contain no repeated node objects, so the cache returns no hits for them (`src/wend/__init__.py:74`, `tests/cache_test.py`)
- `RelativePath` holds `base` and `relative` expressions, joins them on `expr` access, and `rebase` returns a new `RelativePath` with the base replaced (`src/wend/__init__.py:271-291`)
- `P()` wraps a `str | Path` in `LiteralExpr` and `T()` wraps a t-string `Template` in `TemplateExpr` (`src/wend/__init__.py:258-265`)
- 11 tests in `tests/` pass on Python 3.14.6, one per behaviour: literal folding, parent simplification, suffix collapse, `with_name`, template resolution, template `required_params`, param resolution, missing-binding error, `required_params`, rebase, repeated-resolve stability
- `demo.py` output matches the README Usage section on Python 3.14.6
- PyPI wheels 0.1.0 and 0.1.1 (2026-02-03) contain only `wend/__init__.py`, with no compiled extension
- `wend` `expr.resolve(b)` on the README chunk-file expression takes 8,863 ns per call on Python 3.14.6, of which `required_params()` accounts for 805 ns (`docs/journal/scripts/2026-10-17-resolve-bench.py`)

## Stubbed

- `PathExpr.required_params` and `PathExpr._resolve` raise `NotImplementedError` on the base class and are overridden by every concrete node class (`src/wend/__init__.py:64-80`)

## Missing

- Rust backend described in Future Paths part 5 (arena, `PathExpr` enum, optimiser loop, slot instructions, pyo3 bindings) has no code in the repository
- `compile_path` and `CompiledPath` (`required_params`, `num_instructions`, `num_slots`) have no code in `src/wend/__init__.py`
- `!r`, `!s`, `!a` conversions on t-string interpolations are not applied — `TemplateExpr._resolve` passes the raw value to `format()` (`src/wend/__init__.py:141-144`)
- Parameter kinds (single segment vs multi-segment vs absolute) have no representation — `Param` holds only a name (`src/wend/__init__.py:19-22`)
- Inverse resolution (matching a concrete path to bindings) and globbing over bindings have no code
- `stem`, `name`, `suffix`, `with_stem`, `relative_to`, `sibling`, `cousin` have no expression node classes
- Partial binding and substitution of `PathExpr` values for `Param` holes have no code — `resolve` accepts only a complete `dict[str, Any]` of values
- `RelativePath` defines no `/` operator and is not a `PathExpr` subclass — a `RelativePath` cannot appear as a child in a `JoinExpr` (`src/wend/__init__.py:271-291`)
- Typed path annotations (file/dir, exists/not-exists, `Under[ROOT]`, capabilities) from Future Paths part 1 have no code
- Filesystem schema inference from Future Paths part 1 has no code
- No test compares wend resolution against eager pathlib for the same operations — `tests/` contains one hand-picked case per behaviour

## Divergence

- Future Paths part 5 states parent-join cancellation applies "assuming b is a single path component", but `ParentExpr.create` checks the node type only — `(root / "a/b").parent` resolves to `/x` where pathlib gives `/x/a` (`src/wend/__init__.py:190`, `docs/journal/scripts/2026-10-17-soundness-probe.py`)
- The inline comment in `ParentExpr.create` reads "parent(a / b) = a (when b is single component)", but the rewrite also fires for `ParamExpr` and `TemplateExpr` right operands whose bound values can span several components — `(root / ds).parent` with `ds="train/v2"` resolves to `/x` where pathlib gives `/x/train`, and `ds` is absent from its `required_params()` (`src/wend/__init__.py:187-191`)
- Future Paths parts 4 and 5 present suffix chain collapse as equivalent to the uncollapsed chain, but `WithSuffixExpr.create` gives `/x/a.tar.json` for `.with_suffix("").with_suffix(".json")` on `a.tar.gz` where pathlib gives `/x/a.json` (`src/wend/__init__.py:237-238`)
- Future Paths part 5 says "For the implementation details so far, see the wend repository", but the repository contains no Rust source, no `Cargo.toml` and no pyo3 build configuration (`pyproject.toml` uses `uv_build`)
- Future Paths part 5 shows `from wend import Param, P, T, compile_path` and `T("chunk_{idx}.parquet", ["idx"])`, but `wend` exports no `compile_path` and `T()` accepts a single `Template` argument (`src/wend/__init__.py:263-265`)
