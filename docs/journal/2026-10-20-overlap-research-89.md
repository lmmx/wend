# 2026-10-20: Symbolic overlap and declared effect graphs (research)

This entry covers PR #89, a research prototype stacked on #88. It asks
two questions:

- can two path expressions render the same path?
- what does a set of steps' *declared* effects (`Step.effects`) imply about
  their order, their conflicts and their inputs?

Both live in `wend._experimental`. Nothing there is exported from `wend`,
documented in the API reference or covered by the stability promise.

Labels: **[Fact]**, **[Measured]**, **[Interpretation]**, **[Proposal]**, **[Decision]**.

---

## What landed

**[Fact]** `overlaps(a, b, *, shared=False, builtin_values=False)` returns
an `Overlap(verdict, witness, reason, assumptions)`:

- **YES** carries a path and a binding of each side that renders it. Each
  binding came from `match_all`, which returns only bindings that render
  back (SEMANTICS.md §7), or is one the path was rendered from. A YES
  never rests on an assumption; `builtin_values` only strengthens NOs.
- **NO** is sound relative to three things:
  - wend's rendering rules (§3, §4: a segment is never `""`, `.` or `..`
    unless literal, a SubPath has no `..`, nothing contains `/` or NUL);
  - deterministic rendering (the same bindings give the same text, as
    `match` also assumes);
  - in `builtin_values` mode, that bound values are of builtin types. A NO
    that used this lists `"builtin_values"` in `assumptions`.
- **MAYBE** is everything else, with a reason. A failed witness search
  is never read as disjointness.

**[Fact]** `EffectGraph(steps, *, shared=False, builtin_values=False)`
relates the declared paths of a mapping of `Step`s (§10):

- `edges`: a supplier (`create`/`write`) to an input (`read`, or `list`
  of a directory). Each edge carries its overlap, `lens()`, `aligned()`
  and `readers()`.
- `hazards`: an input that a deleter may remove.
- `conflicts`: two writers that may name one path.
- Methods:
  - `external_inputs()`, `terminal_outputs()`;
  - `dependencies(definite_only=)`, `cycles()` (Tarjan), `self_loops()`;
  - `order()`, which honours hazards;
  - `compare(ledger.records())`, which checks observed lineage against
    the declarations;
  - `lexical_caveats()`.

## The overlap algorithm

**[Fact]** Each expression becomes a set of *shapes*: an anchor set (`""`,
`/`, `//`) and a sequence of items. An item is either one segment from a
regular language, or a *run* of zero or more segments from one. The rule
that builds each piece keeps every path the contract lets the expression
render. The full list is in the module docstring.

| Piece | Language |
|---|---|
| Literal segment (a literal `..` included) | Itself |
| Formatted segment | The concatenation of its pieces' languages, less `""`, `.` and `..` |
| Field with a finite domain (`bool`, `Enum`; `choices` only under `builtin_values`) | Exactly its renderings |
| Integer-presented field under `builtin_values` | Its presentation type's alphabet with the width as a minimum length, plus `format(False/True, spec)` |
| Any other field | Any string without `/` or NUL, narrowed only by the field's facts (dot-free, non-empty) |
| SubPath | A run of segments other than `.` and `..`; the exact set with `choices` |
| Head parameter | Any anchor and a run of any segments |
| `parent`, `with_name`, `with_stem`, `with_suffix` of a deferred head | Derived from the base's shapes |
| `join`, `relative_to` | Any path |

**[Fact]** Two shapes are compared in three steps:

1. **Align.** A DP aligns the two item sequences; a run absorbs zero or
   more segments of the other side.
2. **Intersect.** Each aligned slot intersects its languages by a product
   BFS over the NFAs. Each character class is represented by two
   characters (a dot and a non-dot), and the search tracks whether the
   text so far is `.` or `..`. The search is exact, with no length bound.
3. **Solve equalities.** A segment that is exactly one parameter's field
   with a static spec carries a variable. Per alignment, a union-find
   merges equal variables. The alignment is infeasible when a group is
   bound to two different texts, or when its slots' languages do not
   meet.

NO requires that no alignment of any pair of shapes is feasible **and**
that enumeration was complete (at most 64 alignments per pair, 256 shapes
per expression). Above those caps the answer is MAYBE.

**[Fact]** The witness search draws candidates from two places: the
shortest texts of the feasible alignments, and renderings of sample values
(each parameter's domain, typed samples including `True` and `False` for
`int`, and literal words of both sides). Each candidate is read back on
each side by trying, in order:

1. `match_all`;
2. a render index: every binding of a small finite domain (at most 4096),
   rendered once per expression and cached;
3. inversion through a deferred operation: for `.parent`, say, the
   candidate plus a child name.

With `shared=True`, a candidate counts only if both sides' readings agree
on the common names in value and type.

## Counterexamples found, and what changed

Each one is now a test.

1. **[Fact] Choices are not exhaustive.**
   - The case: `choices={1}` accepts `1.0` and `True`, because the check
     is `value in choices`, and they render as `1.0` and `True`. A `str`
     subclass equal to a choice may format as anything.
   - What went wrong: treating choices as a finite domain gave a wrong NO
     (`r/{c}.txt` vs `r/1.0.txt`).
   - The fix: choices are finite only under `builtin_values`, and then
     with their numeric twins added (`1.0`, `True`, `1+0j` for `1`).
2. **[Fact] An `int` subclass can format as letters.**
   - The case: `class Odd(int)` with a `__format__` that returns `abcd`
     is a valid binding for `type=int`.
   - The consequence: under the contract alone, `{n:04d}` guarantees only
     its facts. Digit alphabets need `builtin_values`.
3. **[Fact] `bool` is a builtin `int`.**
   - The case: under `builtin_values`, `x/{n}.txt` vs `x/True.txt` was
     NO, yet `render(n=True)` is exactly that path. `format(True, "")` is
     `True`; under any non-empty spec it formats as `1`.
   - How it was found: by hostile review, not by the fuzzer. The fuzzer's
     value pool had no `True` for `n`, and its grammar never put a
     constrained `True` segment opposite an int field. Its pool and its
     grammar shared the implementation's blind spot.
   - The fix: the field's language is now the integer alphabet *union*
     wend's own renderings of `False` and `True`. That needed a union
     operation (`_Builder.either`).
   - Hardening: the pools hold every builtin type a parameter accepts,
     and the grammar has `True`, `{f}` and `{n}.txt`.
   - Mutation check: with the bool branch removed, the targeted test fails
     and the fuzzer finds 2 refutations in 3000 pairs. The Hypothesis
     property test, at 300 examples, does not catch it.
4. **[Fact] A bounded intersection is unsound.** An early search capped
   the text length. `{n:070d}` against `{name}9` meets only at 70
   characters, so the cap produced a false NO. The intersection is now
   exact.
5. **[Fact] Spelling is not identity.**
   - The cases: `overlaps("/srv/data/x", "data/x")` and
     `overlaps("data/raw/../clean/x", "data/clean/x")` are both NO, and
     correctly so for strings. Yet each pair names one file under the
     right working directory or directory layout.
   - Why it matters: a graph built on these NOs can miss an edge
     silently.
   - The fix: see `lexical_caveats` below.
6. **[Fact] Deletion is not supply.** Treating `delete` as supplying
   the deleted path made the cleaning step depend on `compact` (which
   deletes `raw/`), producing a false cycle. A deleter now creates a
   *hazard*: the reader has to run before it.
7. **[Measured] A witness search took 1.35 s on one pair.**
   - The pair: `(P(rc)/T"{f}.txt"/T"v{ci:d}"/sc).parent` vs
     `/{n:d}.{p}/{p}/{ci}{ci}`.
   - The cause: each candidate re-rendered every binding of the finite
     side, and inversion through `.parent` repeated that per start path.
     That came to 35,376 renders.
   - The fix: the render index, built once per expression. The pair now
     takes 4.4 ms and about 600 renders. A test counts renders, not time,
     and it fails at 35,376 on the old code.

## A realistic effect graph

**[Fact]** The test pipeline (`tests/effects_graph_test.py`) has six steps:

| Step | Reads | Writes |
|---|---|---|
| `ingest` | `inbox/{day}.csv` | `raw/{day}.parquet` |
| `clean` | `raw/{day}.parquet` | `clean/{day}.parquet` |
| `features` | `clean/{day}.parquet` | `features/{day}/{name}.npy` |
| `report` | lists `features/{day}` | `reports/{day}.html` |
| `compact` | `clean/{day}.parquet` | deletes `raw/{day}.parquet` |
| `backfill` | — | writes `clean/{day}.parquet` |

`EffectGraph` gives:

```
edge     ingest.dst -> clean.src (read, yes): data/raw/data.parquet
edge     clean.dst -> features.src (read, yes): data/clean/data.parquet
edge     backfill.dst -> features.src (read, yes): data/clean/data.parquet
edge     features.dst -> report.src (list, yes): data/features/data/data.npy
edge     clean.dst -> compact.src (read, yes): data/clean/data.parquet
edge     backfill.dst -> compact.src (read, yes): data/clean/data.parquet
hazard   clean.src before compact.old: data/raw/data.parquet
conflict ingest.dst ~ compact.old (yes): data/raw/data.parquet
conflict clean.dst ~ backfill.dst (yes): data/clean/data.parquet
external [('ingest', 'src')]
terminal [('report', 'dst')]
order    ['backfill', 'ingest', 'clean', 'compact', 'features', 'report']
```

Every verdict there is YES, with a witness. Six facts come out of it:

- the only file needed from outside is `ingest`'s input;
- the report is the only output nothing reads;
- `compact` must run after `clean`;
- `backfill` and `clean` race for `clean/{day}.parquet`;
- the listing edge sees `features/{day}/{name}.npy` through a `_listed`
  SubPath;
- `Edge.readers({"day": "mon", "name": "x"})` returns
  `[{"day": "mon", "_listed": "x.npy"}]`.

**[Fact]** Other tests show four further behaviours:

- *Bindings matter.* Step `a` reads `data/{k}/in` and writes
  `data/{k}/mid`; step `b` reads `data/{k}/mid` and writes `data/a/{k}`.
  That is a cycle with independent bindings (`a` with `k="a"` reads what
  `b` with `k="in"` writes). With `shared=True` it is not a cycle, because
  one `k` cannot be both.
- *A real cycle stays a cycle.* `report` lists `features/{day}`, and
  `rollup` writes `features/{day}/summary.npy`, so the graph correctly
  shows a cycle.
- *Observed lineage is checked.* `compare` on Ledger records reports an
  observed dependency (a report that really read `clean/`) as
  `undeclared`.
- *Ambiguity is refused.* `compare` raises when two steps have one repr,
  since their records could not be told apart.

## Decisions and rejected alternatives

**[Decision]** The verdict has three values, with witnesses. A boolean
"may overlap" cannot tell "proved disjoint" from "gave up", and an effect
graph needs both: a NO removes an edge, a MAYBE keeps it.

**[Decision]** Languages are per segment, with runs for SubPaths and
heads. A single regular expression over the whole path was rejected:
segments are what wend validates (`.`, `..`, `/`), and per-segment
languages let equality variables attach to segments.

**[Decision]** Intersection is exact. A bounded search was rejected
because it is unsound (counterexample 4).

**[Decision]** Choices are non-exhaustive by default, and the builtin
assumption is opt-in and reported. Treating choices as exhaustive was
rejected because it is unsound (counterexample 1). Turning the
assumption on by default was rejected because it would hide the one place
NO stops being a theorem.

**[Decision]** Equality is tracked only on whole-segment single-field
segments. General string equations across segments are word equations:
decidable, but expensive (Makanin and Plandowski) and unbounded in
practice. Repeated whole-segment parameters cover the common layouts
(`{day}/.../{day}.csv`), and anything else widens soundly.

**[Decision]** A listing is modelled as `dir / SubPath("_listed")`. That
over-approximates a one-level `iterdir`, which can only add edges; it
never removes one.

**[Decision]** Path identity is lexical, and the graph reports where
that is at risk. Two alternatives were rejected:

- *Symbolic path resolution* needs the working directory, symlinks and
  case folding, none of which a declaration carries.
- *Demoting every NO between a relative and an absolute path to MAYBE*
  would turn mixed graphs into all-MAYBE and hide which ports carry the
  risk.

`lexical_caveats()` instead lists two kinds of port: relative paths
among absolute ones, and ports that may render `..`.

## Limits

**[Measured] How often each verdict comes up.** These are random
adversarial pairs from `docs/journal/scripts/2026-10-20-overlap-falsify.py`
(seeds 90–95, 18,000 pairs, each in both modes):

| Mode | YES | NO | MAYBE |
|---|---|---|---|
| strict | 16.7% | 60.7% | 22.6% |
| `builtin_values` | 16.9% | 76.6% | 6.5% |

**[Measured] Where MAYBE comes from.** In an audit of 3000 pairs (962
MAYBEs across both modes), brute force over the value pool found no
common path for any MAYBE. So MAYBEs come from coarse shapes, not from a
weak search. Of the 216 builtin-mode MAYBEs:

| Feature present | Share of MAYBEs |
|---|---|
| A head parameter | 75% |
| `!r`, a float or an untyped formatted field | 50% |
| A deferred operation | 36% |
| A SubPath | 26% |

(A pair can have more than one, so the shares overlap.)

The audit found two misses before the search pools were widened. Untyped
parameters are now also sampled with non-string values, and head
parameters with absolute ones.

**[Fact] A gap in wend's matcher, outside this PR.** The simpler oracle
grammar still has one missed witness in 3000 pairs: `{root}/True/a` vs
`/{n}/{q}`, which meet at `/True/a` with `n=True`. The cause is in core
wend:
- `(P("x") / n).render(n=True)` is `x/True` for `n = Param("n", type=int)`,
  because `bool` passes the `int` check;
- `.match("x/True")` is None, because `match` reads only integers back.

So `match(render(env))` does not contain `env` for a bool bound to an int
parameter. Either `type=int` should refuse `bool`, as strict validators
do, or `match` should read `True` and `False` back. That is a core
decision and is left alone here.

In strict mode most MAYBEs are honest. For example, a `choices={1, 2}`
field can be bound to values that format as anything, so a witness may
exist but needs a hostile value that no search can find.

**[Fact] What the analysis does not model:**

- `join` and `relative_to` are treated as any path.
- Dynamic specs, conversions and float presentation types fall back to
  their fields' facts.
- Equality is not tracked inside a segment (`{p}-{p}`) except when the
  segment's whole domain is finite and small.

**[Fact] What the graph does not model:**

- It describes declarations, not behaviour. A step's code can read or
  write anything, and the module says it does not analyse Python side
  effects.
- A cycle among patterns need not be a cycle among runs. A step that reads
  earlier days and writes later ones is a cycle under independent
  bindings.
- Conflicts do not constrain `order()`. Which of two writers should win
  is the caller's decision.
- `lexical_caveats` works per port, not per pair. It is noisy for
  pipelines with a head parameter (`P(root)/...`), and it cannot see case
  folding or symlinks.
- `compare` names steps by `repr`, which is what a Ledger record stores.

**[Measured] Cost.** Each figure is the median of 5 calls with cold
caches (`bench/experimental_overlap.py`, 4-core container):

| Case | Time |
|---|---|
| Alternating literal/parameter, 2 → 32 segments | 0.27 → 3.1 ms |
| 1 → 8 SubPaths on each side | 0.22 → 3.2 ms |
| `choices` with 4 → 256 values | 0.35 → 1.7 ms |
| `{n:0Wd}` vs text ending in `z`, width 4 → 64 | 0.11 → 0.83 ms |
| Repeated parameter ×32 | 1.1 ms (YES), 0.38 ms (NO) |
| Deferred pair over finite domains (counterexample 7) | 4.4 ms (was 1349 ms) |
| `EffectGraph`, 10 → 100 steps (200 → 20,000 supplier-input pairs) | 10 ms → 0.56 s |

A graph costs about 28 µs per pair, quadratic in the number of ports.
There is no index by literal prefix, and the shapes cache barely helps.
The slowest single call in the sweeps was about 100 ms, which proved to
be garbage-collection pauses: the worst call with GC disabled was 30 ms.

## Validation

**[Measured]** The suite now has 817 tests, which pass. That is
the 777 on #88 plus 40 new ones:

- `tests/overlap_test.py`: 29, including Hypothesis property tests that
  NO is never refuted, YES is always witnessed, and an expression always
  overlaps itself with a YES;
- `tests/effects_graph_test.py`: 11.

Ruff is clean, and pyright and ty are clean on `src/wend/_experimental`.

**[Measured]** The final adversarial sweep found no problems:

- 36,000 calls, after the pools were widened;
- 9,476 strict-mode NOs checked against hostile renderings;
- the self-overlap check: 5,948 expressions, all YES;
- the simpler oracle grammar with shared bindings: 3,000 pairs,
  0 refuted.

**[Measured]** Mutation checks. Each fix was reverted to confirm a test
fails without it:

| Mutation | Failing tests |
|---|---|
| Deletion counted as supply | 1 |
| Every overlap YES | 4 |
| No render index | The render-count test (35,376 renders) |
| No absolute-path samples | The self-overlap property (`{ab}/{n:02d}`) |
| No bool renderings | The bool test, and the fuzzer |

## Status

**[Interpretation]** What is proven, what is approximated, and what is
missing:

- *Sound, given the stated assumptions:* NO in both modes; every YES
  witness.
- *Approximated, and widening soundly:* deferred operations, head
  parameters, floats, conversions, dynamic specs, and equality across
  segments.
- *Unsupported:* identity of files as opposed to strings; behaviour
  beyond declarations; `join` and `relative_to`.

**[Interpretation]** Nothing here is production-worthy as an API yet.
`overlaps` is close: small, well tested, with an honest MAYBE.
`EffectGraph` is a demonstration that `Step.effects` carries enough to
build a useful graph, not a scheduler.

**[Proposal]** What promotion would need:

1. **A written contract.** A SEMANTICS.md section saying what NO means
   (lexical, deterministic rendering, the two modes), with tests that
   fail if `render`'s validation changes under it.
2. **Generated value pools.** Counterexample 3 shows that pools written by
   hand inherit their author's blind spots. A pool generated from each
   `Param`'s type, enumerating the builtin subclasses (`bool` for `int`)
   and the twins for choices, could run as a slow or nightly test.
3. **A real pipeline.** One real pipeline's steps, rather than synthetic
   ones, run through the graph to measure how often MAYBE and
   `lexical_caveats` get in the way.
4. **Graph-level decisions.** Whether conflicts order steps, caveats per
   pair, and an index by literal prefix before anything near a thousand
   steps.
5. **Naming.** A name and home in the public API, and whether
   `builtin_values` should be the default for typed parameters.
6. **The bool decision in core.** Whether `type=int` accepts `bool`
   (see Limits). Refusing it would make `{n}` exactly digits under
   `builtin_values`.
