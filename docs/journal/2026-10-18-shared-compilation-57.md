# 2026-10-18: What optimisation still buys

This entry covers issue #36: what optimisation can still buy beyond the normal
form, and where the gain is measurable. It records:
- a measured gain from shared compilation, which this PR ships;
- an analysis of rewrites on deferred chains, which ships nothing;
- the cost model wend optimises for.

Labels: **[Fact]**, **[Measured]**, **[Interpretation]**, **[Decision]**.

---

## Shared compilation: measured, shipped

**[Fact]** `compile()` generates one straight-line function per expression.
Expressions used together repeat each other's work:
- the two sides of a lens split the same `SubPath` and format the same `stem`;
- a project's paths share a root;
- a shard's data, index and checksum files format the same counters.

Part 4 calls avoiding that repetition common-subexpression elimination across
roots.

**[Decision]** `compile_many(exprs)` generates one function for a set. The
generator now memoises by structure:
- a parameter lookup, by name;
- a head value, by parameter;
- a `SubPath` split, by parameter;
- a formatted field, by (parameter, conversion, spec, role), so two
  expressions declaring the same name differently do not share;
- a whole templated segment, by segment.

All shared work happens once per call. `compile_expr` uses the same generator,
and its output is unchanged.

**[Decision]** Results are exactly "render each expression in turn", errors
included, by the same construction as `compile()`. Any exception in the shared
fast path re-renders each expression with the interpreter, in order, so the
first failing expression's error is raised. A Hypothesis property checks this
on random sets of one to four contract terms. It runs 600 examples in the
suite and passed 10,000 locally.

**[Measured]** `bench/bench.py`, new *Rendering sets of expressions* workload,
median ns per set:

| set | one compiled call each | `compile_many` | gain |
|---|---:|---:|---:|
| a lens's two sides (`src/{rel}/{stem}.md`, `site/{rel}/{stem}.html`) | 2,286 | 1,427 | 1.6× |
| a project's 6 paths under one root | 4,985 | 2,296 | 2.2× |
| a shard's 3 files (`.parquet`, `.idx`, `.sha256`) | 5,118 | 2,512 | 2.0× |

The issue's first criterion ("at least one workload … shows a measured gain
from shared compilation") is met by all three.

**[Interpretation]** The gain comes from not repeating per-parameter validation
and formatting, plus one Python call instead of several. What remains per
expression is string concatenation. A further step would share each
expression's directory prefix (`head + "data/" + split + "/"`). For the shard
set, I estimate that at about 100 ns per extra expression; I left it out.

## Rewrites on deferred chains: analysed, nothing shipped

**[Fact]** After the rebuild, the normal form decides `parent`,
`name`/`stem`/`suffix` and `with_*` statically whenever the structure allows.
#41 added the one rewrite that mattered, `parent(with_*(x)) → parent(x)`, under
§6's structural-elimination rule. A deferred chain survives only in two cases:
- an operation on a path whose last segment is unknown, meaning a `PATH`- or
  `ABSOLUTE`-kind operand after the head, or a `SubPath` tail;
- `relative_to` with unknown prefixes.

**[Interpretation]** Candidate rules, checked against pathlib:

| rule | sound? |
|---|---|
| `with_suffix(with_suffix(x, a), b) → with_suffix(x, b)` | **no**: `a.tar` with `.gz` then `.zip` is `a.tar.zip`, not `a.zip` |
| `with_name(with_*(x, …), n) → with_name(x, n)` | yes under structural elimination: the replaced name is discarded, as in #41's parent rule |
| `with_stem(with_suffix(x, a), s) → with_name(x, s + a)` | only when `a` is non-empty and `x`'s name is non-empty; otherwise the errors differ |
| `relative_to(x / y, x) → y` | yes when `y` has no `..`, which #26's derivations make visible |

**[Decision]** None is implemented. No workload in `bench/bench.py`, the
examples, or the inferred layouts of the messy-trees script produces these
chains. A rewrite costs a SEMANTICS entry and a contract term, and would gain
nothing measurable.

So the issue's open question gets a direct answer. The normal form leaves almost
nothing for a rewrite engine: e-graphs and Datalog stay out of scope, as Part 4
expected, unless a backend (#37) gives the rules conflicting costs.

## Cost model

**[Decision]** What wend optimises for, recorded so later work can be judged
against it:

1. **Compiled render, per call.** Python bytecode executed and objects
   allocated in the generated function. This is the hot path for batch
   resolution, and the measure for `compile`/`compile_many`.
2. **Filesystem calls in discovery.** `glob` walks along the expression's
   structure:
   - one `lstat` per literal segment;
   - one `scandir` per directory a templated segment must list;
   - no recursion except under a `SubPath`.

   On an object store (#34) this becomes listing calls per prefix, which is the
   number to minimise there.
3. **Construction and `bind`, per call.** These matter for code that builds
   expressions in loops. #53 halved them.
4. **Match, per path.** Dominated by render verification (~1.9 µs; #44). It is
   not optimised away, because verification is what makes matching sound.

String allocation within one rendering is not a target. A rendering allocates
its result string once per concatenation chain, and that is all.
