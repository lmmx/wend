# 2026-10-17: Rebuild — segment normal form, matching, discovery, compilation, inference

Second entry. The [retrospective](2026-10-17-retrospective-17.md) found that wend 0.1.1's
construction-time rewrites contradicted its own resolve-time results. It also found that
the Rust design in Future Paths part 5 had dropped t-string format semantics. This entry
records the rebuild that followed on a fresh branch from `master`: what was built, which
decisions were taken and why, the evidence for them, and what is still open.

The free-form sections come first. The giacometti-format tail is at the end
([docs/JOURNAL.md](../JOURNAL.md)).

Labels as in the retrospective, plus **[Decision]** for choices taken in this work that
the owner should confirm:

- **[Fact]** checked against code, tests or a primary source
- **[Measured]** produced by `bench/bench.py` or a test in this session
- **[Interpretation]** a reading of the evidence
- **[Proposal]** an option recorded for later; not decided
- **[Decision]** a choice made during the rebuild; open to review

---

## The architectural diagnosis

**[Interpretation]** The eight counterexamples were symptoms of one design gap. The 0.1
expression tree had no notion of *how many segments a node produces*:
- every structural rewrite (parent of a join, suffix of a chain) silently assumed one
  segment per node;
- nothing enforced that assumption: the node type was checked, never the value.

**[Decision]** The rebuild makes segment structure the central invariant instead of an
assumption:

- **Normal form.** `PathExpr(head, parts)`:
  - `head` is one of `REL`, `Root("/" | "//")`, `HeadParam(param)`, or `Deferred(op, …)`;
  - each part is a `Seg` (exactly one segment, built from literal text and formatted
    fields) or a `Splice` (a declared sub-path parameter of zero or more segments).

  (`src/wend/_expr.py:283-360`)
- **Static structure from t-strings.** A t-string's literal text is split at `/` when the
  expression is built, so the segment count of `t"data/{split}/chunk_{idx:04d}.parquet"` is
  known from the source, with Python as the parser (Part 4's conclusion, kept)
  (`_from_template`, `src/wend/_expr.py:858`).
- **Validation makes the structure true.** Every `Seg` must render to exactly one
  canonical segment: no `/`, not `""`, not `.`, and not a computed `..`. A rendering that
  would change the segment count is rejected rather than allowed to shift the structure
  (`seg_value`, `format_field`, `check_seg`, `src/wend/_expr.py:940-1015`).
- **Three outcomes per operation.** An operation is *static* when the structure decides
  it, *deferred* (pathlib after binding) when only values can decide it, and *rejected*
  when it is invalid for every binding. No rule picks a static answer that values could
  contradict.

**[Fact]** All eight retrospective counterexamples now agree with pathlib:
- `(root / "a/b").parent` is `{root}/a`;
- `(root / ".").parent` is `parent({root})`;
- the suffix chains match pathlib;
- `!r` is applied;
- `(root / SubPath("ds")).parent` is deferred.

The smoke run and `tests/algebra_test.py` cover these cases.

## Semantics, and what the oracle forced

**[Decision]** The retrospective's open question was (A) pathlib-compatible vs (B) an
independently specified typed algebra. It is resolved as a hybrid:
- for every binding accepted by an expression and its sub-expressions, `render` equals the
  eager pathlib computation of the same operations;
- bindings that would make pathlib silently change the structure are rejected
  (`InvalidBindingError`).

This keeps (A) on every input wend accepts and takes (B)'s ability to refuse. **This
choice affects the project's original ambition and is the main item for owner review.**

**[Fact]** `tests/oracle_test.py` builds random expression programs twice: once with wend,
once as an independent eager pathlib function on the formatted strings. The committed suite
runs 600 examples per property; during development each property was also run at 4,000 to
6,000 examples. It asserts that:
- results are equal on nice values;
- there is never a disagreement on wild values, only a rejection;
- partial binding commutes;
- `match` recovers the original bindings;
- static `name`/`stem`/`suffix` equal pathlib;
- the compiled function equals the interpreter;
- the canonical-string fast path equals pathlib.

The oracle found three semantic questions that the original design never stated. Each one
is now part of the definition:

1. **[Decision] Structural elimination.** `(root / seg).parent` is `{root}`, so it no
   longer mentions `seg`. For an invalid `seg=""`, which wend rejects for `root / seg`,
   eager pathlib drops the empty segment and returns a different answer. The parent is
   defined as the value pathlib gives for every *valid* binding of the eliminated
   parameters, which is well defined because it is constant across them. This keeps
   Part 3's "the parent doesn't need `idx`" as a guarantee. The alternative, that parent
   keeps validating dropped parameters, was considered and rejected: it would remove that
   feature.
2. **[Decision] Non-strict evaluation.** `root.with_stem("") / "/abs"` is `/abs`. Eager
   pathlib raises inside `with_stem` first. A sub-expression that a structural operation
   discards (everything before an absolute join) is never evaluated.
3. **[Decision] A whole-segment interpolation is a path operand.** The test oracle first
   modelled `t"{seg}/{w}.txt"` as "format an f-string, then parse". With `seg=""` that
   produces the *absolute* path `/.txt`: the classic f-string path bug. wend joins
   `seg / f"{w}.txt"` instead. The rule (`_from_template`): an interpolation that fills a
   whole segment, with no conversion or format spec, is joined exactly as `/` would join
   it. Any other interpolation is a formatted field.

**[Decision]** A parameter after the head defaults to a single segment, not to any path:
- it gives every common expression a static segment count;
- `root / user_input` cannot traverse: `../x`, `/etc/passwd` and `a/b` are rejected
  (`examples/untrusted_names.py`);
- multi-segment values need `SubPath`, and the error message says so.

This is a behaviour change from 0.1, where any value was joined.

## What was built

**[Fact]** Modules and their roles:

| module | role |
|---|---|
| `_params.py` | `Param` with `kind` (path, absolute, segment, subpath), `type`, `choices`; `Segment`/`SubPath`/`AnyPath`/`Absolute`; markers that detect a Param in an f-string and support dynamic specs (`t"{idx:0{width}d}"`) |
| `_spec.py` | format-spec facts (dot-free and non-empty guarantees for integer formatting, enforced at resolution) and inversion with round-trip verification |
| `_expr.py` | normal form, construction, structural operations, the reference interpreter, `bind` (partial evaluation: concrete values, expressions for rebasing, Params for renaming), `rebase`, `relative_to` |
| `_match.py` | structural backtracking matcher; typed extraction; every candidate verified by re-rendering; `AmbiguousMatchError` rather than guessing |
| `_fs.py` | `glob`: walks along the expression's structure with the same segment matcher; SubPath recursion without following symlinked dirs by default |
| `_lens.py` | `Lens(src, dst)`: bidirectional mapping by shared parameters (Part 1's lenses) |
| `_compile.py` | code generator: one specialised function per expression, falling back to the interpreter on any exception |
| `frame.py` | Polars lowering with whole-frame validation; refuses formatting Polars can't reproduce exactly |
| `infer.py` | layout inference (below) |

**[Decision]** Compilation strategy. The generated fast path only has to be correct *when
it succeeds*. Any exception — a missing key, a format error, a failed inline check — falls
back to the reference interpreter. Errors and messages are therefore identical by
construction, and the differential test only needs to check successes.

**[Decision]** `wend.polars` was renamed to `wend.frame`. A module called `polars` inside
the package shadowed the real polars for pyright and for scripts run from the package
directory.

## Layout inference

**[Fact]** `wend.infer.infer` generalises a tree bottom-up (`src/wend/infer.py:112-150`):
- **Skeletons:** names tokenise into digit runs plus the text between them. Siblings with
  the same skeleton pool their run values.
- **Numeric fields:** a run that varies becomes an `int` field. Its spec (`0Nd` or `d`) is
  chosen so every observed string round-trips (`_int_spec`); otherwise it becomes a string
  field. A constant run stays literal.
- **Directory fields:** sibling directories whose children's skeletons have Jaccard
  similarity ≥ 0.5, with at least 2 of them, collapse into a segment field.
- **File fields:** at least 3 files sharing an extension collapse into `{stem}.ext`.
- **Optional entries:** merging directories re-unifies their children. Each child tracks
  which original directories contained it, and is flagged optional if some didn't.

**[Fact]** Field statistics come from matching each layout's own observed paths. That
also verifies that every observed path round-trips through its layout, and a Hypothesis
test (3,000 random trees) checks full coverage. Two bugs were found and fixed during
development:
- a lone `chunk_0001` became a literal too early and stopped generalising;
- statistics were taken from all merged parents instead of the leaf's own paths.

## Measurements

**[Measured]** `bench/bench.py`, final run: Python 3.14.6, polars 2.0.0, Linux 6.18
container, Intel Xeon @ 2.80GHz, 4 vCPUs. One expression shape (the README shard
expression). Median of 7 repeats; machine-to-machine and run-to-run variation is large
(the eager-pathlib baseline moved between 3.4 and 4.9 µs across runs), so compare rows
within a run.

| workload | wend | baseline |
|---|---|---|
| single, interpreter `render` | 8.1 µs | |
| single, compiled `render` → str (validated) | 2.1 µs | eager pathlib joins 4.4 µs; `os.path.join` 1.8 µs; f-string 0.9 µs (neither validated) |
| single, compiled → `Path` | 3.1 µs | |
| batch 100k, `compiled.many` | 2.1 µs/row | f-string comprehension 0.8 µs/row (unvalidated) |
| batch 100k, `resolve_frame` (validated) | 0.29 µs/row | |
| match one path (general matcher) | 27.6–28.8 µs | hand-written regex + `int()` 1.5 µs (no round-trip check) |
| match one path (deterministic fast path, below) | 9.5–10.8 µs | |
| glob, 10,000 files (general → fast path) | 17.2 → 6.2 µs/file | `Path.glob` + regex 5.8–6.5 µs; `os.walk` + regex 2.0–2.5 µs |
| infer, 20,030 paths (general → fast path) | 40.5 → 24.0 µs/path | |
| construct the shard expression | 32.8 µs | |

**[Interpretation]** Resolution is no longer the bottleneck. Compiled single resolution
validates every value and still beats eager pathlib, and the Polars path renders a
validated row in about 0.3 µs. With the general backtracking matcher, **matching** cost
about 19× a hand-written regex and **discovery** about 9× `os.walk`.

**[Decision]** Deterministic matching fast path (`seg_plan`, `_fast_candidate` in
`src/wend/_match.py`). The fast path applies when every segment is deterministic by
construction:
- integer `d`/`0Nd` fields are followed by a literal that does not start with a digit;
- a segment has at most one free string field, and only as its last field;
- the head's extent is fixed (no `SubPath`).

Under those conditions one regex `fullmatch` per segment is the only possible parse, so no
search is needed to prove uniqueness. The result is still verified by rendering, and
anything else falls back to the general matcher. A Hypothesis property asserts that the
fast path and the full search return identical results (6,000 examples during
development). Matching dropped from about 28 µs to about 10 µs, and discovery is now on
par with `Path.glob` plus a hand-written regex while returning typed, verified bindings.

**[Proposal]** The remaining gap to `os.walk` + regex (about 3×) is per-entry Python
overhead (bindings dictionaries, verification). A native backend is worth revisiting for
batch matching or filesystem walks that return Arrow arrays without creating Python
objects per path. That would keep Part 5's direction, but at a boundary where the
measurements say it can pay.

## Open questions for the owner

- **[Decision → review]** The hybrid semantics and the single-segment default after the
  head (above).
- **[Proposal]** Release: the public API changed incompatibly (0.1's class-per-operation
  names and `RelativePath` are gone). A version bump such as 0.2.0, and any release, is
  yours to approve.
- **[Proposal]** Windows path semantics: currently POSIX only.
- **[Proposal]** Part 1 capabilities beyond kinds: existence (`FilePath`/`NewPath`), file
  vs directory, `Under[ROOT]` at the type level, lineage tags. Kinds already give
  traversal safety; existence checks would fit naturally as glob/resolve options.

---

## Current State

- `PathExpr` holds a head (`REL`, `Root`, `HeadParam` or `Deferred`) and a tuple of `Seg` and `Splice` parts, and every `Seg` renders to exactly one canonical segment or raises `InvalidBindingError` (`src/wend/_expr.py:283-360`, `src/wend/_expr.py:940-1015`)
- `_from_template` splits t-string literal text at `/`, joins whole-segment interpolations without a spec or conversion as path operands, and stores other interpolations as `Field`s with their conversion and format spec (`src/wend/_expr.py:833-905`)
- `Param` carries a `Kind` (`AUTO`, `PATH`, `ABSOLUTE`, `SEGMENT`, `SUBPATH`), an optional `type` and optional `choices`, and an `AUTO` parameter after the head of an expression binds a single segment (`src/wend/_params.py:18-104`, `src/wend/_expr.py:756-816`)
- `parent`, `name`, `stem`, `suffix`, `with_name`, `with_suffix`, `with_stem` and `relative_to` return static results when the last segment's structure decides them and `Deferred` heads evaluated with pathlib otherwise (`src/wend/_expr.py:497-662`)
- `bind` substitutes concrete values, expressions (rebasing) and parameters (renaming) by rebuilding through the join and operation constructors, which folds deferred operations whose inputs become static (`src/wend/_expr.py:1134-1304`)
- `match` and `match_all` take a single-regex path for expressions whose segments parse deterministically, otherwise enumerate candidate bindings structurally and parse field text with `_spec.invert`, verify each candidate by rendering it, and raise `AmbiguousMatchError` for more than one distinct verified binding (`src/wend/_match.py`)
- `glob` walks a directory tree along the expression's parts, filters entries with the segment matcher, verifies each result by rendering, and does not follow symlinked directories inside a `SubPath` unless `recurse_symlinks` is set (`src/wend/_fs.py:52-149`)
- `Lens` maps a path matching one expression to the corresponding path of another expression with shared parameters, in both directions (`src/wend/_lens.py:22-72`)
- `compile` generates one Python function per expression, caches it on the expression, and falls back to the interpreter on any exception in the generated fast path (`src/wend/_compile.py:24-244`)
- `PathExpr`, `Seg`, `Field` and `Text` leave cached derived state (compiled function, match plans, parameter tables) out of their pickled and copied state, so expressions pickle after use (`_Cached` in `src/wend/_expr.py`)
- `wend.frame.resolve_frame` validates every row of a Polars frame and renders with native Polars expressions for string columns, integer `d`/`0Nd`/`Nd` specs and `<N`/`>N` string padding (`src/wend/frame.py:30-256`)
- `wend.infer.infer` produces `Layout`s whose expressions, field statistics and optional flags come from bottom-up skeleton merging, Jaccard clustering of directories and suffix grouping of files (`src/wend/infer.py:112-423`)
- 76 test functions in `tests/` pass on Python 3.14.6, including 8 Hypothesis properties in `tests/oracle_test.py`, 1 in `tests/infer_test.py` and 1 in `tests/frame_test.py`, and `tests/examples_test.py` runs every script in `examples/` and `demo.py`
- pyright 1.1.408 reports 0 errors on `src/wend` (`uvx pyright src/wend --pythonpath .venv/bin/python`)
- `bench/bench.py` measures single and batch resolution, matching, discovery, inference and symbolic operations against pathlib, f-string, `os.path`, regex and `os.walk` baselines, and prints its environment

## Stubbed

- No placeholder implementations — no function in `src/wend/` raises `NotImplementedError` except `wend.frame`'s lowering, which raises for format specs and column types that Polars does not reproduce exactly and names `compile().many()` as the alternative (`src/wend/frame.py:48-200`)

## Missing

- A Rust or other native backend has no code in the repository
- Expressions with adjacent free fields, non-terminal string fields, non-`d` integer specs or `SubPath` parts have no fast matching path — `match` and `glob` use the backtracking matcher for them (`src/wend/_match.py`)
- Windows path semantics have no code — rendering and matching follow `PurePosixPath` rules only
- Existence, file-versus-directory and capability constraints from Future Paths part 1 have no code beyond the `kind` filter of `glob`
- `wend.frame.resolve_frame` has no normalisation for non-canonical path columns — rows that `render` would canonicalise raise `InvalidBindingError` instead
- Layout inference has no detection of variable-depth structure — inferred layouts contain `Seg` parts only, never `SubPath`

## Divergence

- `pyproject.toml` declares version 0.1.1 while the public API differs from the 0.1.1 release on PyPI — `LiteralExpr`, `JoinExpr`, `WithSuffixExpr` and `RelativePath` are removed, and README.md describes the new API under "Changes from 0.1"
