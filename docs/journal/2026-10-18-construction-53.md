# 2026-10-18: Construction and bind, twice as fast

This entry covers the remaining criterion of issue #35: `bench/bench.py` should
show construction and `bind` at least 2× faster, with no regression elsewhere.
The other criteria, the matching fast paths, are #44.

Labels: **[Fact]**, **[Measured]**, **[Interpretation]**, **[Decision]**.

---

## Where the time went

**[Measured]** Profiles of the bench's shard expression showed three costs.

**Construction** (`root / "data" / split / T(t"chunk_{idx:04d}-of-{total:04d}.parquet")`, about 30 µs):
- pathlib parsed every literal;
- `_from_template` rebuilt a t-string's structure every time;
- each join re-read its operands' parameter tables through `cached_property`, walking any table not yet computed.

**`bind`** (about 25 µs) joined part by part. Every join merged and re-validated
the parameter tables, and the result was copied once more to take its
derivation.

**Operations:** `suffix` and `with_suffix` re-split the last segment on every
call.

## What changed

**[Decision]** Five changes, each preserving results exactly:

1. **A fast constructor.** `_new` skips the frozen dataclass `__init__`. It
   takes the parameter table when the caller already knows it: `{}` for a
   literal, `{p.name: p}` for a parameter operand.
2. **Cached literal parsing.** A literal path's anchor and segments are cached
   by string. Segments are immutable and their cached properties are pure,
   so expressions can share them. Each call still builds a fresh `PathExpr`,
   because `_derived` annotates fresh results in place, and a shared one would
   leak a derivation.
3. **Cached template structure.** The cache key is the t-string's strings plus,
   for each interpolation, its type, value, conversion and spec. Caching only
   applies when every value is a `Param`, `str` or `int` (exact types), so
   equal keys always format alike: `True` vs `1` and `0.0` vs `-0.0` never
   share an entry. Specs that refer to a `Param` by marker are not cached,
   because a marker names an object id, and ids are reused after collection.
   Results with a deferred head are not cached.
4. **`bind` builds once.** Every bound part is relative, so joining it is
   concatenation. `bind` collects the parts and builds one expression. When
   every value is concrete *and* the expression is direct (no deferred head,
   no field whose text derives from a path), the parameter table is the old
   one without the bound names. Otherwise a single walk computes it.
5. **The suffix split is cached on the segment.** Segments are shared across
   constructions through the caches above, so the split is computed once per
   segment, not once per call.

**[Fact]** The "direct" restriction in (4) came from a property that failed.
The first version assumed binding `x` removes `x` and nothing else. But
`name(root / sub)` becomes the static `"b"` once `sub="a/b"` is bound, so
`root` drops out too. `test_bound_and_joined_parameter_tables_equal_a_fresh_walk`
now checks that every constructed and bound table equals a fresh walk, on the
contract's random terms and environments. It runs 400 examples in the suite
and passed 5,000 locally.

**[Fact]** `_derived` no longer copies `bind`'s result. The copy existed
because the old `bind` could return a value the caller passed in (binding a
head to a `PathExpr` with no parts). The new `bind` always builds a fresh
expression.

## Measurements

**[Measured]** `bench/bench.py`, symbolic workload, median ns per item,
interleaved runs of master and this branch:

| case | master | this branch | speedup |
|---|---:|---:|---:|
| construct shard expression | 30,345 / 30,826 | 13,989 / 13,610 | 2.2× |
| `bind(root=..., total=...)` | 24,302 / 25,148 | 11,448 / 11,931 | 2.1× |
| construct + render nested SubPath | 25,263 / 25,605 | 13,231 / 13,039 | 1.95× |
| interpreted render | 7,684 / 7,404 | 7,464 / 7,143 | = |
| compiled render | 1,796 / 2,052 | 1,804 / 1,861 | = |

The single operations, minimum of 7×10,000:

| op | master | before this change | after |
|---|---:|---:|---:|
| `parent` | 0.61 µs | 1.05 µs | 0.93 µs |
| `suffix` | 2.73 µs | 2.75 µs | 0.46 µs |
| `with_suffix` | 4.22 µs | 4.70 µs | 2.17 µs |

**[Interpretation]** "Before this change" is the stack this PR sits on: #43's
derivations cost about 0.45 µs per derived operation. This change pays that
back on every row except `parent`, which stays +0.3 µs over master. A parent is
already the cheapest operation; what remains is the cost of recording where the
path came from (§9).

## What is left

**[Interpretation]** Per call, the remaining construction cost is spread across:
- `__truediv__`'s checks for alternation and conditions;
- `_derived`;
- the parameter-table merge in `_join`.

None of these dominates. Further gains would mean changing representation, such
as interning whole expressions. That is #36's territory (shared work across
expression sets) rather than #35's.
