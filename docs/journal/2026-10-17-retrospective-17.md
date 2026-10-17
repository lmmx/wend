# 2026-10-17: Retrospective — ideation, t-string regression, soundness, performance

First journal entry for wend. The package was written in January–February 2026 without a
journal; this entry reconstructs the design history from the
[Future Paths](https://cog.spin.systems/future-paths) blog series, the two gists linked from it,
and the repository, then records what was found when the code was probed on Python 3.14.6.

The free-form sections come first. The giacometti-format tail is at the end
([docs/JOURNAL.md](../JOURNAL.md)).

**Evidence labels** used in the free-form sections:

- **[Fact]** checked against a primary source: repository, PyPI artefacts, blog text, gist text,
  PEP text, PyO3 source
- **[Measured]** produced by a script in `scripts/` in this session; reproducible with the
  command in the script's docstring
- **[Interpretation]** a reading of the facts and measurements; reasonable people could read
  them differently
- **[Proposal]** a design option recorded for later decision; nothing here is decided

Reproduction scripts:

- [`scripts/2026-10-17-soundness-probe.py`](scripts/2026-10-17-soundness-probe.py): wend vs
  wend's own un-rewritten nodes vs eager pathlib
- [`scripts/2026-10-17-resolve-bench.py`](scripts/2026-10-17-resolve-bench.py): per-resolve timings
- [`scripts/2026-10-17-rust-path-semantics.rs`](scripts/2026-10-17-rust-path-semantics.rs): `std::path` vs pathlib

---

## Provenance

**[Fact]**

| Date | Artefact | Content |
|---|---|---|
| 2026-01-18 | [Part 1: Semantic Types](https://cog.spin.systems/future-paths-types) | Phantom-typed paths, effects/capabilities, lenses, lineage, content-addressing, directory schemas (with filesystem schema inference à la polars-genson), path algebra, `PathVar` late binding |
| 2026-01-18 | [Part 2: Connectivity](https://cog.spin.systems/future-paths-connectivity) | Relations as values: `base`/`base_rel`, `rebase`, `sibling`, `cousin`; five requirements (relation type, base tracking, rebasing, composition rules, type integration) |
| 2026-01-18 23:34 | [PoC gist `deferred_path_exprs.py`](https://gist.github.com/lmmx/f5d1b07d266f160f9a431c1f6bdc8a17) | `Param` placeholders inside t-strings; `JoinExpr`/`ParentExpr`/`SiblingExpr`/`WithSuffixExpr`/`TemplateExpr`; rewrites applied at resolve time |
| 2026-01-18 | [Part 3: Deferred Path-ification](https://cog.spin.systems/future-paths-template-strings) | Walkthrough of the PoC gist |
| 2026-01-19 12:59 | [Design report gist](https://gist.github.com/lmmx/bb2ad52a9efee015c3cd2a083ef3d63d) | "Lazy Path Execution: Polars Analogues". The gist's `0_prompt.md` is a request to an agent to write the report, so the report is agent-written. Proposes a Rust crate named `pathforge` |
| 2026-01-20 | [Part 4: Compilation Theory](https://cog.spin.systems/future-paths-compilation-theory) | Term rewriting (termination, confluence, completeness), e-graphs, Datalog, "do we need a parser?", stack vs register machines, SSA, slot allocation |
| 2026-01-20 | [Part 5: Lazy Execution](https://cog.spin.systems/future-paths-lazy-execution) | Rust arena + `PathExpr` enum + fixed-point optimiser + slot instruction executor + pyo3; Python API `compile_path(expr)` |
| 2026-02-03 16:45 | `da961f9 feat: initial commit` | `src/wend/__init__.py`, 290 lines, pure Python |
| 2026-02-03 17:44 / 17:55 | PyPI `wend` 0.1.0, 0.1.1 | 0.1.1 differs from 0.1.0 by the version bump and one removed README line, "Git (with sparse-checkout support)" (`f62e20c`) |
| 2026-02 → 2026-09-01 | `#2`–`#15` | pre-commit autoupdates only |

**[Fact]** What shipped is the Part 3 PoC plus the Part 4 rewrite rules. I downloaded both PyPI
releases: each wheel contains only `wend/__init__.py` (8,767 bytes) plus dist-info, and each
sdist contains only `README.md`, `pyproject.toml` and `src/wend/__init__.py`. None of Part 5's
Rust (arena, `compile_path`, `CompiledPath`, `num_instructions`, `num_slots`) is in the
repository or in either release. Part 5's error type is `PathForgeError`, matching the report's
`pathforge` crate name.

**[Interpretation]** If Rust code was written, the name match suggests it was called
`pathforge`. No such repository was located in this session; the repository listing used was
incomplete, so this is not evidence that none exists.

## The idea, compressed

**[Interpretation]** (summary of the series)

**A path should be a plan, not a value.** `pathlib` composition gives you a concrete value
immediately and throws away intent (what kind of path this is), relation (what it is relative
to) and parameterisation (which parts vary). The series goes after each of these:

- **Types** (Part 1) carry intent: file/dir, must-exist/must-not, `Under[ROOT]`, capabilities.
- **Relations** (Part 2) carry connectivity: a path keeps its base and can be rebased.
- **Placeholders** (Part 3) carry parameterisation. A t-string evaluates its interpolations
  eagerly, but when the evaluated value is a `Param` sentinel the `Template` keeps the slot's
  name, conversion and format spec (`:04d`) for later. This is laziness without thunks.
- **Compilation** (Parts 4–5): once a path is a tree, it can be rewritten (simplified) and
  lowered to straight-line code.

**[Fact]** [PEP 750](https://peps.python.org/pep-0750/) evaluates interpolations eagerly and
rejects implicit lazy evaluation ("Delayed Evaluation of Interpolations" under Rejected Ideas).
Its documented route to laziness is an explicit `lambda` interpolation, e.g.
`t"Hello {(lambda: name)}"`, which "assumes … that template processing code anticipates and
handles callable interpolation values" ("Approaches to Lazy Evaluation").

**[Interpretation]** `Param` is an alternative to that `lambda` route: an eagerly-evaluated
sentinel that, unlike `lambda: x`, carries a name the processor can inspect (`required_params()`).

## What shipped vs. the PoC gist

**[Fact]** (diff of the gist against `src/wend/__init__.py`)

- Rewrites moved from resolve time (PoC `ParentExpr.resolve` checked `isinstance(child, JoinExpr)`)
  to construction time (`JoinExpr.create`, `ParentExpr.create`, `WithSuffixExpr.create`). A
  construction-time rewrite can't see bindings (see Soundness).
- Dropped: PoC `TemplateExpr.parent`, which cut a template at its last `/` by string surgery.
- Changed: `SiblingExpr` (PoC: `base.parent / name`) became `WithNameExpr` (pathlib `with_name`).
- Changed: `P()` means a literal in wend (it was the `Param` shorthand in the PoC).
- Added: `required_params()`, missing-binding check, an `id()`-keyed memo cache, `RelativePath`
  with `rebase`.

## The t-string regression between the design report and Part 5

### Three snapshots of the template node

**[Fact]**

**Part 3 / wend (Python).** The template node *is* the `string.templatelib.Template`: strings
and interpolations already separated by CPython's parser, each interpolation carrying
`value` (a `Param`), `expression`, `conversion`, `format_spec`. Resolution calls
`format(bound_value, spec)` (`src/wend/__init__.py:133-149`), so `idx=7` with `:04d` gives `0007`.

**Design report, 2026-01-19.** The template is still represented structurally:

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
slots: **the slot machine has a single type, `PathBuf`.** By the time a template is formatted,
`idx` is already the path `"7"`, and `:04d` has nothing to apply to. The report's API and its
executor contradict each other, and the report doesn't mention this.

**Part 5, 2026-01-20.** The API changes; the executor's binding type stays path-only:

```rust
Template { format: SmolStr, params: Vec<SmolStr> },
```
```python
template = T("chunk_{idx}.parquet", ["idx"])
compiled.resolve({"root": "/data", "dataset": "train", "idx": f"{i:04d}"})
```

with `execute(&self, bindings: &HashMap<SmolStr, PathBuf>)`.

### What was mistaken at that juncture

1. **[Fact]** **A parsed template was turned back into source text at the FFI boundary.** A
   t-string arrives already parsed: `Template.strings` / `Template.interpolations` are the
   parse. `T("chunk_{idx}.parquet", ["idx"])` hands Rust a string to re-parse instead. Part 4,
   dated the same day, concludes that "Python is our parser", and that a text-based pattern
   syntax "defeats the point of the current design (where Python t-strings handle the parsing)".
2. **[Fact]** **Parameter names are stated twice** (`{idx}` in the string, `["idx"]` in the list).
   In the Part 3 design, names come from the `Param` objects in the interpolations, so
   `required_params()` is derived rather than declared.
3. **[Fact]** **Formatting moved to the call site.** `"idx": f"{i:04d}"` means the caller writes an
   f-string on every iteration. The README's sharded-dataset example
   (`chunk_{idx:04d}-of-{total:04d}`) can't be expressed in the Part 5 API without the caller
   doing the padding.
4. **[Interpretation]** **The value domain was conflated with the path domain.** A path template
   has two stages: *values* (int, str, date — formatted by `__format__` with a spec) become
   *segments* (strings), and segments become *paths*. The register machine models only the last
   domain. Part 5's "Where This Leads" mentions the loss ("they could support format specs like
   the Python proof-of-concept's t-string integration") as future work.
5. **[Interpretation]** **The Polars analogy doesn't carry over at this node.** Polars expressions
   lower cleanly because every `Expr` already has a Rust meaning. A t-string interpolation's
   meaning is `type(value).__format__(spec)`, i.e. arbitrary Python code. The template leaf is
   the node whose meaning lives in Python, and the report treats it as plain data.

### A lowering that keeps both

**[Proposal]**

- Keep `TemplatePart::Interpolation { param, conversion, spec }` (as in the design report).
- Give slots a value type (`enum Value { Int(i64), Str(SmolStr), Path(PathBuf), … }`), or
  format at load time (`LoadParamFormatted { slot, param, spec }`).
- Parse the format-spec mini-language
  (`[[fill]align][sign][z][#][0][width][grouping][.precision][type]`) for int and str. That subset
  covers the shard-numbering patterns; fall back to a Python callback (or refuse at compile time)
  for other types and specs.
- Test Rust path ops against whichever specification wend adopts (see the open question under
  Soundness), not against `std::path`'s behaviour.

**[Measured]** `scripts/2026-10-17-rust-path-semantics.rs`: `std::path` and pathlib disagree on
these operations:

| Operation | Rust `std::path` | pathlib |
|---|---|---|
| `set_extension(".json")` / `with_suffix(".json")` on `/x/a.txt` | `/x/a..json` | `/x/a.json` |
| parent of `/` | `None` | `/` |
| parent of `a` | `Some("")` | `.` |
| `/x` joined with `.` | `/x/.` | `/x` |

**[Interpretation]** If the report's executor (`path.set_extension(suffix)`) receives the
pathlib-style `".json"` argument that `PathExpr.with_suffix` takes, it produces the double dot.

## Soundness of the construction-time rewrites

**[Measured]** `scripts/2026-10-17-soundness-probe.py` resolves each expression three ways:
- through wend as constructed (rewrites applied);
- through the same node tree built directly with the dataclass constructors, which bypasses the
  `.create` rewrites so each node resolves via its own `_resolve` (which calls pathlib);
- eagerly in pathlib.

| Expression (`root="/x"`) | wend (rewritten) | wend (un-rewritten) | pathlib |
|---|---|---|---|
| `(root / "a/b").parent` | `/x` | `/x/a` | `/x/a` |
| `(root / ds).parent`, `ds="train/v2"` | `/x` | `/x/train` | `/x/train` |
| `(root / T(t"{ds}/c_{idx}")).parent` | `/x` | `/x/tr` | `/x/tr` |
| `(root / ".").parent` | `/x` | `/` | `/` |
| `(root / "/abs/f").parent` | `/x` | `/abs` | `/abs` |
| `(root/"a.tar.gz").with_suffix("").with_suffix(".json")` | `/x/a.tar.json` | `/x/a.json` | `/x/a.json` |
| `(root/"a.txt").with_suffix(".tar.gz").with_suffix(".json")` | `/x/a.json` | `/x/a.tar.json` | `/x/a.tar.json` |
| `T(t"f_{ds!r}")`, `ds="a"` (not a rewrite) | `f_a` | — | `f_'a'` |

Controls that agree on all three: `(root/"f.txt").with_suffix(".json").parent`, and literal
folding. `(root / ds).parent.required_params()` returns `{'root'}`.

**[Fact]** In all seven rewrite rows, the rewrite changes the result wend itself computes for
the node it replaces. So these are inconsistencies inside the current implementation, whichever
external specification is chosen. The eighth row is a different kind of issue: the
`Interpolation.conversion` field is ignored at resolve time (`src/wend/__init__.py:141-144`).

**[Fact]** Parts 4 and 5 *assert* termination and confluence ("our rules only shrink or simplify
terms", "Our path rules are confluent"). Neither part states a soundness condition — that a rule
preserves the value of the term it rewrites. The rows above show that condition failing.

**[Fact]** Conditions the rules need under the current resolve-time behaviour:
- `Parent(Join(a, b)) → a` needs `b` to resolve to exactly one non-`.`, non-empty, relative
  component. Part 5 and the inline comment at `src/wend/__init__.py:187` both state the
  single-component condition, but `ParentExpr.create` (`src/wend/__init__.py:185-195`) checks the
  *node type* (`LiteralExpr | ParamExpr | TemplateExpr`, line 190). For `ParamExpr` and
  `TemplateExpr` the condition depends on values bound later, so it can't be decided when the node
  is built.
- The parent rewrite also changes `required_params()`, which Part 3 presents as a feature ("we
  don't have to specify the idx"). The two agree only when `idx` is known to fill a single segment.
- `WithSuffix(WithSuffix(a, s1), s2) → WithSuffix(a, s2)` needs `s1` to be non-empty and contain
  exactly one dot. `with_suffix` replaces the *last* dot-suffix, so `""` (strip) and `".tar.gz"`
  (two dots) both break it (`src/wend/__init__.py:234-242`).

**Open question: what wend's semantics are.** **[Interpretation]** The repairs depend on which of
two readings wend adopts. This entry does not choose between them.

- **(A) pathlib-compatible symbolic API.** A resolved expression must equal the eager pathlib
  computation. The rows above are then defects. The repairs are guarded rewrites (skip the rule
  unless the condition holds) or no construction-time rewrite for value-dependent nodes, and
  pathlib serves as a free differential-testing oracle: Hypothesis can generate random trees and
  bindings and compare.
- **(B) Independently specified typed path algebra.** Operations are defined by wend's own spec,
  with pathlib compatibility only at the resolve boundary. Some rows could become *rejections*
  rather than repairs: binding `"train/v2"` to a `Segment`-kind param, `"."` as a segment, or an
  absolute right operand to `/` could be errors, which would make the current rewrites sound for
  all accepted inputs. Differential testing then compares against the spec, not pathlib.

**[Proposal]** Under either reading, parameter kinds (`Segment`: one relative component, no
separator, not absolute, not `.`/`..`/empty; `SubPath`; `Absolute`) connect Part 1's semantic types
to Part 4's rewrites:
- `Parent(Join(a, b)) → a  if  kind(b) = Segment` becomes a guarded rule;
- checking kinds at resolve time costs one string scan per param;
- the same `Segment` guarantee decides whether the concatenation lowering in the next section
  matches join semantics.

## Performance

**[Measured]** `scripts/2026-10-17-resolve-bench.py` on the README's chunk-file expression
(`root / "data" / dataset / T(t"chunk_{idx:04d}-of-{total:04d}.parquet")`).

Environment: Python 3.14.6, polars 2.0.0, Linux 6.18 cloud container, Intel Xeon @ 2.80GHz, 4
vCPUs, other load unknown.

Qualifications:
- one expression shape, one machine;
- each value is the minimum over 5 repeats (3 for the batch rows);
- "recorded" is the first full run; "range" spans that run plus three later reruns.

Absolute values are machine-specific; compare rows within a run.

| Lowering | ns / resolve (recorded) | range over 4 runs |
|---|---|---|
| wend `expr.resolve(b)` | 8,863 | 8,863–9,999 |
| wend `expr._resolve(b, {})` (skips the `required_params` check) | 7,289 | 7,289–8,010 |
| wend `expr.required_params()` alone | 805 | 805–1,048 |
| eager pathlib joins + f-string leaf | 3,547 | 3,383–3,693 |
| `Path(fmt.format_map(b))` | 1,677 | 1,652–1,778 |
| hand-written f-string function → `Path` | 1,403 | 1,403–1,422 |
| hand-written f-string function → `str` | 802 | 802–824 |
| `Path(s)` alone | 553 | 553–600 |
| `str(Path(s))` (construct + parse + render) | 3,449 | 3,216–3,478 |
| batch, hand-written f-string → `str`, per item (100k) | 933 | 839–960 |
| batch, polars `pl.format` + `str.zfill`, per item (100k) | 155.5 | 145.9–306.7 |

The "hand-written f-string function" rows time a function written by hand in the shape a code
generator would emit. No code generator exists in wend. The polars row varies most (about 2×
across runs), consistent with a multi-threaded kernel on a shared 4-vCPU container.

Observations:

- **[Fact]** The design report estimated "Current Python ~1µs, estimated Rust ~100ns" per
  resolution. **[Measured]** wend resolve measured 8.9–10.0µs.
- **[Measured]** pathlib parses lazily: a `Path` stores its raw segments (`_raw_paths`) and
  parses on first use. `Path(s)` costs 553–600ns; `str(Path(s))` costs 3.2–3.5µs.
- **[Fact]** PyO3 ≥ 0.25 converts `PathBuf` by calling `pathlib.Path(...)`
  ([changelog](https://pyo3.rs/v0.25.0/changelog),
  [source](https://pyo3.rs/main/doc/src/pyo3/conversions/std/path.rs.html)).
- **[Interpretation]** A per-item Rust resolve that *returns `pathlib.Path`* therefore costs at
  least the `Path(s)` row on top of its own work. That bound covers that return type only. No
  Rust implementation was measured: not per-item returning `str`, not batch returning Arrow or a
  list, not filesystem effects (stat/glob) run in Rust. The Rust direction stays open.
- **[Measured]** Within these runs, the hand-written f-string function is 6–7× faster than
  wend when returning `Path` and 11–12× faster returning `str`. The polars batch is about
  30–70× faster per item than a single wend resolve. The outputs differ in type
  (`Path` / `str` / Arrow column), as the row labels say.
- **[Proposal]** Compiling a wend expression to a Polars expression (as in the polars row)
  resolves a column of bindings without creating per-item Python objects. **Hypothesis
  (unmeasured):** a Rust polars plugin could serve the operations `pl.format` can't express
  (parent, with_suffix, pathlib normalisation, existence/glob checks in parallel).
- **[Fact]** `Path(f"/x/{'/abs'}")` is `/x/abs`, while `Path("/x") / "/abs"` is `/abs`.
  **[Interpretation]** Concatenation-based lowerings equal pathlib joins only when every param is
  a single relative segment, so the parameter-kind question above also decides when the fast
  lowering applies.

## Blog and code comments vs. code

**[Fact]** Documented claims outside the README that the code doesn't match (the README makes
no such claims; see Divergence below):

- Part 5 states parent-join cancellation applies "assuming b is a single path component"; the
  inline comment at `src/wend/__init__.py:187` states the same condition. `ParentExpr.create`
  checks node type only (`src/wend/__init__.py:190`), so `(root / "a/b").parent` and
  `(root / ds).parent` with `ds="train/v2"` both resolve to `/x`.
- Parts 4 and 5 present suffix chain collapse as equivalent to the uncollapsed chain;
  `WithSuffixExpr.create` (`src/wend/__init__.py:237-238`) changes the result for `""` and
  `".tar.gz"` inner suffixes.
- Part 5 says "For the implementation details so far, see the wend repository"; the repository
  contains no Rust source, no `Cargo.toml` and no pyo3 build configuration (`pyproject.toml`
  uses `uv_build`).
- Part 5 shows `from wend import Param, P, T, compile_path` and `T("chunk_{idx}.parquet", ["idx"])`;
  `wend` exports no `compile_path`, and `T()` takes a single `Template` argument
  (`src/wend/__init__.py:263-265`).

## Open threads

**[Proposal]** Blog promises with no code yet, plus directions that came out of this review.
None of these is decided.

- **Semantics choice** (A) pathlib-compatible vs (B) independent typed algebra, as set out under
  Soundness. Most threads below depend on it.
- **Reverse direction: parsing.** A `Template` holds literal strings and format specs, from which
  a regex can be derived (`:04d` → `(\d{4})`, plain `{x}` → `([^/]+)` for a `Segment`). That
  points towards `expr.match(path) -> bindings` and `expr.glob(partial_bindings)` (enumerate which
  bindings exist on disk), i.e. Snakemake-style wildcards, typed and composable. It would also
  realise Part 1's lens (`forward`/`backward`) for the case where the backward map is parsing.
  - Inversion isn't automatic. Formatting can lose information (`{x!s}` of distinct objects;
    format specs that truncate). Several bindings can produce the same path. Adjacent dynamic
    fields (`{a}{b}`) are ambiguous without separators or fixed widths.
  - When `match()` is well-defined is itself an open question, and parameter kinds bear on it.
- **Filesystem schema inference à la polars-genson** (Part 1). Observe directory trees, infer node
  kind, name fixity vs parameterisation (`model-{index:03}.pt`), cardinality. Inference could emit
  wend templates that `match` then checks. The genson-core analogue of Record → Map unification
  is literal-names → parameterised-name unification.
- **Substitution as the single primitive.** Allow bindings to map to `PathExpr`, not only values.
  - `Param` becomes a hole, and `RelativePath.rebase` becomes substitution of the base hole.
  - Partial binding (`expr.bind(root=...)` followed by folding) becomes staged compilation.
  - `required_params()` becomes the set of free variables.
- **Param kinds** (`Segment`, `SubPath`, `Absolute`) as the bridge from Part 1 types to Part 4
  rewrite guards, to the concatenation lowering, and to unambiguous matching.
- **t-string preservation across any backend.** Keep the `Template` structure (strings,
  interpolations, conversions, specs) intact through lowering, so the Part 3 API survives any
  compiled backend.
- **Compile targets.** Generated f-string function, Polars expression, Rust slot machine with a
  value-typed slot domain. Each needs workloads to measure against beyond the single
  microbenchmark here: per-item vs batch, `Path` vs `str` vs Arrow output, with and without
  filesystem effects.
- **Part 1/2 surface:** `Annotated` existence/kind checks (`FilePath`, `NewPath` equivalents) at
  resolve time; `Under[ROOT]` traversal guard; `sibling`/`cousin`; `stem`/`name`/`suffix` as
  expressions; lineage tags; a readable repr (`$root/data/$dataset/chunk_{idx:04d}…`).

---

## Current State

- `Param` (`src/wend/__init__.py:19-33`) stores a name in a frozen dataclass; `/` with a `Param` operand wraps the `Param` in `ParamExpr` and returns a `PathExpr`
- `PathExpr.__truediv__` and `__rtruediv__` normalise `str`, `Param` and `PathExpr` operands and build nodes through `JoinExpr.create` (`src/wend/__init__.py:42-52`)
- `JoinExpr.create` folds `LiteralExpr / LiteralExpr` into a single `LiteralExpr` at construction time (`src/wend/__init__.py:157-163`)
- `ParentExpr.create` returns `child.left` for any `JoinExpr` child whose right node has type `LiteralExpr`, `ParamExpr` or `TemplateExpr`, and folds the parent of a `LiteralExpr` (`src/wend/__init__.py:184-195`)
- `WithSuffixExpr.create` replaces a nested `WithSuffixExpr` with the outer suffix and folds `with_suffix` on a `LiteralExpr` (`src/wend/__init__.py:233-242`)
- `WithNameExpr` applies pathlib `with_name` at resolve time with no construction-time rewrite (`src/wend/__init__.py:209-224`)
- `TemplateExpr` stores a `string.templatelib.Template`, collects `Param` interpolation names into `_params` in `__post_init__`, and calls `format(value, item.format_spec)` per interpolation at resolve time (`src/wend/__init__.py:117-149`)
- `PathExpr.resolve` computes `required_params()` recursively, raises `ValueError("Missing bindings: ...")` for unbound names, then walks the tree with an `id()`-keyed cache local to the call (`src/wend/__init__.py:68-75`)
- The `id()`-keyed cache in `_resolve` returns a hit only when the same node object appears more than once in a single expression tree — the README and test expressions contain no repeated node objects, so the cache returns no hits for them (`src/wend/__init__.py:74`, `tests/cache_test.py`)
- `RelativePath` holds `base` and `relative` expressions, joins them on `expr` access, and `rebase` returns a new `RelativePath` with the base replaced (`src/wend/__init__.py:271-291`)
- `P()` wraps a `str | Path` in `LiteralExpr` and `T()` wraps a t-string `Template` in `TemplateExpr` (`src/wend/__init__.py:258-265`)
- 11 tests in `tests/` pass on Python 3.14.6, one per behaviour: literal folding, parent simplification, suffix collapse, `with_name`, template resolution, template `required_params`, param resolution, missing-binding error, `required_params`, rebase, repeated-resolve stability
- `demo.py` output matches the README Usage section on Python 3.14.6
- PyPI wheels 0.1.0 and 0.1.1 (2026-02-03) contain only `wend/__init__.py` (8,767 bytes) and dist-info, with no compiled extension
- `ParentExpr.create` and `WithSuffixExpr.create` return a different resolved path than the un-rewritten node for seven probe expressions, including `(root / "a/b").parent` resolving to `/x` against `/x/a` for the un-rewritten `ParentExpr(JoinExpr(...))` (`docs/journal/scripts/2026-10-17-soundness-probe.py`)
- `TemplateExpr._resolve` passes the bound value to `format()` without applying the interpolation's `!r`/`!s`/`!a` conversion — `T(t"f_{ds!r}")` with `ds="a"` resolves to `f_a` (`src/wend/__init__.py:141-144`, `docs/journal/scripts/2026-10-17-soundness-probe.py`)
- `expr.resolve(b)` on the README chunk-file expression measured 8,863–9,999 ns per call across four runs on Python 3.14.6 in a 4-vCPU container, with `required_params()` alone measuring 805–1,048 ns (`docs/journal/scripts/2026-10-17-resolve-bench.py`)

## Stubbed

- No placeholder implementations — every concrete node class overrides the base-class `PathExpr.required_params` and `PathExpr._resolve`, which raise `NotImplementedError` only as interface definitions (`src/wend/__init__.py:64-80`)

## Missing

- Rust backend described in Future Paths part 5 (arena, `PathExpr` enum, optimiser loop, slot instructions, pyo3 bindings) has no code in the repository
- `compile_path` and `CompiledPath` (`required_params`, `num_instructions`, `num_slots`) have no code in `src/wend/__init__.py`
- Parameter kinds (single segment vs multi-segment vs absolute) have no representation — `Param` holds only a name (`src/wend/__init__.py:19-22`)
- Inverse resolution (matching a concrete path to bindings) and globbing over bindings have no code
- `stem`, `name`, `suffix`, `with_stem`, `relative_to`, `sibling`, `cousin` have no expression node classes
- Partial binding and substitution of `PathExpr` values for `Param` holes have no code — `resolve` accepts only a complete `dict[str, Any]` of values
- `RelativePath` defines no `/` operator and does not subclass `PathExpr` — a `RelativePath` cannot appear as a child in a `JoinExpr` (`src/wend/__init__.py:271-291`)
- Typed path annotations (file/dir, exists/not-exists, `Under[ROOT]`, capabilities) from Future Paths part 1 have no code
- Filesystem schema inference from Future Paths part 1 has no code
- No test in `tests/` compares rewritten expressions against un-rewritten nodes or against eager pathlib — each test file checks one hand-picked case

## Divergence

- README Usage examples (`required_params`, resolve, literal folding, parent simplification, suffix chain collapse, `RelativePath.rebase`) produce the outputs shown in their comments when run as `demo.py` on Python 3.14.6 — `src/wend/__init__.py` implements every README-documented behaviour; blog-documented claims that differ from the code are listed under "Blog and code comments vs. code" above
