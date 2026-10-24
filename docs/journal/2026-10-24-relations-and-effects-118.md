# 2026-10-24: Relations between families, and effects across a pipeline (#118)

The first development after 0.3.0. The research stack left a set of experimental
analyses; this entry records what each one does at 0.3.0, and then the one carried into
the public API: `wend.relate`, which says whether two families of paths name the same
path, one inside the other, or neither, for every binding, for some, or for none; and
`wend.effects.EffectGraph`, which relates a pipeline's steps by it. The contract is
`docs/SEMANTICS.md` §15.

## 1. The experimental modules at 0.3.0

**[Fact]** `wend._experimental` held 16 files and 6,066 lines at 0.3.0 (`c07b42a`), none
in the wheel (`pyproject.toml`, `wheel-exclude`).

| module | from | what it does at 0.3.0 | why it is experimental | carried forward |
|---|---|---|---|---|
| `overlap` | #89 | whether two expressions can render one path: YES with a witness, NO by disjoint shapes, else MAYBE | an engine without a contract or public name | moved into the wheel as private `wend._overlap`, behind `relate` (§3) |
| `effects` | #89 | a graph of `Step.effects`, edges from `overlaps` | imprecise under one root (§2) | superseded by `wend.effects` (§4); kept for its tests |
| `families` | #109 | `must_equal`, `relation` (YES/NO/MAYBE) with prefix cancellation; knowledge over families | every rule reads YES and MAYBE alike (its addendum A.4) | `relate` generalises `relation`; the knowledge analysis stays research |
| `knowledge` | #108 | gen/kill knowledge over rendered paths, a `Tracker` executor | a model and test oracle | no |
| `obligations` | #106 | verbs from atoms (now core `declares.verbs`); obligations over an `EffectGraph` | built on the experimental graph | no |
| `patterns` | #106 | `parse(pattern)`; `{root}/raw/{day}_{n:03d}.csv` round-trips | two printings parse back wrongly: `a/{x}` (a head parameter or a segment) and a segment or value field | no: the printing is not injective |
| `typed` | #106 | a typed facade; `StepSpec`, `declared_by` | core typing (#113) carries `PathExpr[C, K, Q]` and evidence since 0.3.0 | no |
| `choices` | #89 | `match_all`, `faithful` for `choices=` | core `match` reads a declared member back since 0.2.0 (#97): `Param("c", choices={1})` matches `x/1.txt` as `{'c': 1}` | no |
| `identity`, `confined` | #110, #112 | aliasing, `openat2` beneath a root | Linux only | no |
| `events`, `publish`, `fresh` | #113–#115 | runs, holds, seals, drafts, versions, leases (§14) | Linux only, some privileged | no |

**[Fact]** The test files of these modules hold 177 tests (`patterns_test` 10, `typed_test`
11, `obligations_test` 7, `choices_semantics_test` 12, `knowledge_test` 9,
`families_test` 9, `aliasing_test` 24, `confined_test` 10, `events_test` 10,
`publish_test` 14, `fresh_test` 3, `leases_test` 30, `drafts_test` 12, `synthesis_test`
11, `held_test` 5), all of which still pass.

## 2. Why this one

**[Measured]** A six-step pipeline under one `{root}`, run through the experimental graph
with shared bindings (`ingest` writes `raw/{day}.csv`, `clean` reads it and writes
`clean/{day}.parquet`, `featurise` writes `features/{day}.npz`, `train` lists `features`
and writes `models/{model}.pkl`, `report` reads `clean` and `models`, `purge` deletes
`raw/{day}.csv`):
- 9 edges, 4 of them MAYBE: `ingest`, `clean` and `report` into `train`'s listing, and
  `train` into itself;
- `order()` is None, from the cycle `train`/`report` the MAYBEs make;
- 26.8 ms (median of 7; 39.9 ms in a second run on the final head).

**[Fact]** Overlap answered MAYBE because a head parameter is coarse in its shapes, and the
graph never cancelled the shared `{root}`. `families.relation` cancels it, and
`relation(raw, clean)` was already `"no"` (`families.py`, `_split`), but the graph did
not use it.

**[Fact]** The owner's challenge to the families entry ("distinguish must overlap, may
overlap, and provably disjoint") was left **[Open]** there: every rule tested
`relation != "no"`.

## 3. The relation

**[Fact]** `relate(a, b)` (`src/wend/_relate.py`) answers three questions, `same`,
`inside` and `contains`, each `"always"`, `"sometimes"` (with an `Example`), `"never"` or
`"unknown"`, under shared bindings by default. `Relation.kind` gives one word.

**[Proven]** relative to §15.3 (1), that rendering is a function of structure with
parameters by name:
- prefix cancellation: under shared bindings an equal prefix renders one string `s`, and
  `s` joined with a relative remainder is injective and keeps "inside";
- empty remainders are the same path, and an empty remainder against one holding a
  segment is a proper ancestor, for every binding under which both render;
- remainders whose first parts are different literal segments never meet nor nest.

**[Conjecture], with evidence**: §15.3 (1) itself. The families entry's probe (its §1.1,
narrowed in its addendum A.3) and the property test below support it; it is not proved
from `render`'s code.

**[Fact]** Structural equality compares a memoised *render key* (`_key`): structure,
with parameters by name, values by type, equality and repr (`0.0` and `-0.0` differ), and
an unhashable value only as itself.

## 4. The graph

**[Fact]** `wend.effects.EffectGraph` (`src/wend/effects.py`) differs from the experimental
graph in:
- relations: every link has the certainty of a `relate` answer, and a pair the relation
  proves apart has no link;
- deletion: a hazard also when the read path is *inside* the deleted one, and for a
  listing when the deleted path is inside the listed directory; a conflict also when a
  written path is inside a deleted one. The experimental graph compared the paths for
  equality only;
- queries: `stages()` (groups that may run at once, no two conflicting),
  `independent(x, y)`, `links`, `explain` (one sentence per link, with an example);
- shared bindings by default;
- `dependencies(certain=True)` keeps the links that hold on every run. The experimental
  `definite_only` kept those with a witness, which hold on *some* run.

**[Measured]** The six-step pipeline of §2: 5 dependencies, all `"always"`; 1 hazard
(`clean` before `purge`); 1 conflict (`ingest`, `purge`); order `ingest, clean,
featurise, purge, train, report`; stages `[ingest] [clean] [featurise, purge] [train]
[report]`; 0.21 ms (median of 7; 0.23 ms on the final head).

## 5. Counterexamples found while building it

- **`..` escapes "strictly below".** `inside` asks overlap whether `a` renders a path in
  `b/{segment}/{subpath}`, and neither parameter renders `..`. `/x/..` is inside `/x`
  lexically, so overlap's NO for `Absolute("ab") / ".."` against `/x` did not prove
  `"never"`. A NO for `inside` or `contains` is now `"unknown"` when the inner side may
  render `..`: a literal `..`, a head parameter or a deferred head (`_may_render_dotdot`).
  Found by reading the construction; pinned by
  `test_dotdot_makes_a_path_lexically_inside_and_is_never_ruled_out_by_shape`.
- **A remainder's witness is not a witness.** Overlap's YES for two remainders binds no
  prefix parameter, and a value it picks for a parameter shared with the prefix may not
  render there. A YES becomes `"sometimes"` only when a full binding renders both and
  shows the relation (`_search`); otherwise `"unknown"`.
- **Examples ignored defaults.** `root` defaulting to `p` and `y` against `root`
  defaulting to `p/y` and `z` nest only unbound (`p/y`, `p/y/z`). The example search bound
  every parameter and found nothing, so the answer was `"unknown"`. It now tries the
  defaulted parameters unbound first, and the answer is `"sometimes"`.
- **The index needs defaults too.** The graph's literal-prefix index (§6) compares heads
  by render key. That pair's tails, `y` and `z`, differ, so without the default in the
  head's key the index called them apart. The default is part of the key;
  `test_different_defaults_of_one_head_are_not_indexed_apart` pins it.

## 6. Measured

**[Measured]** `tests/relate_test.py::test_every_always_and_never_holds_for_every_pooled_binding`:
300 pairs from the overlap tests' adversarial grammar, half sharing a prefix, each checked
in both modes against every pooled binding (up to 800 shared, 120 × 120 independent).
In the shared mode, over one run of 300 pairs: `same` always 86, sometimes 22, never
173, unknown 14; `inside` always 30, sometimes 8, never 235, unknown 22; `contains`
always 43, sometimes 18, never 198, unknown 36. 16 of the 900 answers had no binding
that rendered both.

**[Measured]** Mutations of `_relate.py`, each run against `tests/relate_test.py` with
seed 0:

| mutation | caught by |
|---|---|
| `inside` and `contains` swapped in the structural rule | `test_a_file_is_always_inside_its_directory_and_the_directory_contains_it` |
| the `..` guard removed | `test_dotdot_makes_a_path_lexically_inside_and_is_never_ruled_out_by_shape` |
| conflicting defaults ignored | `test_different_defaults_break_always` |
| parameters alike whatever their names | `test_a_parameter_in_place_of_a_literal_overlaps_with_an_example` |
| independent bindings cancel parameters | the pooled-binding property |
| divergence on any two literal segments | survives: equivalent, since equal literal segments are already cancelled |

**[Measured]** Mutations of the graph's index, against `tests/effects_test.py`: pruning
whenever literal tails differ, and heads compared without their defaults, are caught
(the first by `test_the_index_never_changes_a_link`, which compares every link with the
index disabled over generated pipelines); indexing deferred heads survives, and is sound:
two deferred heads with one render key render one string under shared bindings.

**[Measured]** `bench/effects.py`, a chain of N steps under one `{root}` (each reads the
stage before it, every fifth lists a stage five back, the last deletes the first),
shared bindings, 4-core container, on the final head (an earlier run gave 0.9, 5.3, 17.7
and 67.3 ms for the public graph, and 74 ms to 28.8 s for the experimental one):

| N | ports | `wend.effects` | links (always) | order | experimental | links | order |
|---|---|---|---|---|---|---|---|
| 10 | 19 | 0.4 ms | 12 (9) | yes | 51 ms | 20 | none |
| 50 | 107 | 4.7 ms | 60 (57) | yes | 2.1 s | 500 | none |
| 100 | 217 | 17.3 ms | 120 (117) | yes | 7.5 s | 2,000 | none |
| 200 | 437 | 64.2 ms | 240 (237) | yes | 31.3 s | 8,000 | none |

The index is what makes the public graph near linear here: without it, 717 ms at
N = 200. `relate` on single pairs: 0.03 ms (disjoint stages) to 2.2 ms (`{root}/x`
against `/data/x`, through overlap).

## 7. What it does not do

- **[Fact]** Identity is lexical (§15.4): a symlink, a relative and an absolute spelling
  of one file, `..` and case folding are invisible to the relation.
- **[Fact]** The graph describes declarations, not behaviour.
- **[Fact]** A union is never `"always"` related; its alternatives are related pair by
  pair.
- **[Fact]** With `shared=False`, a free head parameter on each side relates everything
  `"sometimes"`: the six-step pipeline has no order.
- **[Fact]** Conversions (`!r`), float and untyped formatted fields, and deferred
  operations give `"unknown"` where overlap's shapes are coarse.
- **[Open]** `families.analyse_families` and `knowledge` still read `"sometimes"` and
  `"unknown"` alike. With `relate`, a fact known of `b` could be known of `a` whenever
  `same` is `"always"`, not only when the patterns are equal.
