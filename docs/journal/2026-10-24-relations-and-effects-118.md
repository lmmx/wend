# 2026-10-24: Relations between families, and effects across a pipeline (#118)

The first development after 0.3.0. The research stack left a set of experimental
analyses; this entry records what each one does at 0.3.0, and then the one carried into
the public API: `wend.relate`, which says whether two families of paths name the same
path, one inside the other, or neither, for every binding, for some, or for none; and
`wend.effects.EffectGraph`, which relates a pipeline's steps by it. The contract is
`docs/SEMANTICS.md` §15.

*Revised before merging.* The owner's check of the graph's scheduling semantics (§8)
refuted two claims of §4 and narrowed one of §7. They are revised in place; the earlier
wording stays beside each, marked *Before*.

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
- nesting: a declared path covers what lies below it, since it may be a directory, so
  every link (dependency, hazard, conflict) holds when the two paths are one or one is
  inside the other. Two deletions conflict; a port that declares nothing of its path is
  kept apart from every port it touches; a port requiring `Exists` follows what may make
  its path; and a creation check is kept apart from a creation below a directory that may
  be missing (§8.5). The experimental graph compared the paths for equality only (§8);

  > *Before:* "deletion: a hazard also when the read path is *inside* the deleted one,
  > and for a listing when the deleted path is inside the listed directory; a conflict
  > also when a written path is inside a deleted one." Nesting was asked of deletions
  > only: a writer of `{root}/raw` and a reader of `{root}/raw/{day}.csv` were
  > independent (§8.1).
- queries: `stages()` (groups that may run at once, no two joined by any link),
  `independent(x, y)`, `links`, `explain` (one sentence per link, with an example), and
  `cycles(certain=...)` over the links `order()` follows, dependencies and hazards both;

  > *Before:* "`stages()` (groups that may run at once, no two conflicting)". It was so,
  > but `cycles()` followed dependencies alone, so it could find none where `order()`
  > found one (§8.2).
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
  `"unknown"` alike. With `relate`, a fact *established* of `b` names the string `a`
  renders whenever `same` is `"always"`. Whether the fact still holds is another
  question: knowledge is sound only under the knowledge model's closed world, with every
  mutation declared, and on alias-free runs (the aliasing entry, §5). Static identity of
  two strings says nothing of freshness. A reuse of facts across `same == "always"` has
  to be invalidated by every declared mutation of either spelling, and by nothing else
  only under those assumptions.

  > *Before:* "With `relate`, a fact known of `b` could be known of `a` whenever `same`
  > is `"always"`, not only when the patterns are equal." Narrowed by the owner: textual
  > equality does not make facts fresh.

## 8. The owner's check before merging

The owner approved merging on one condition: that the graph never take a possible
interference for independence. Concretely, that `"sometimes"` and `"unknown"` never become
independence, that `stages()` never groups steps that may interfere, that `order()`
tells an unavoidable cycle from a possible one, and that the documents say the relation is
of strings, not of files. Each was checked against the code; two defects were found, and
fixed before merging.

### 8.1 Nested paths were independent

**[Refuted]** "a link holds when the two paths are equal (or, for a deletion, when one is
inside the other)". A declared path may name a directory, and a step that writes, reads
or deletes a directory touches what is inside it. Under one `{root}`, each of these pairs
was independent and shared a stage:

| steps | a link now |
|---|---|
| writes `{root}/raw`; reads `{root}/raw/{day}.csv` | dependency, always |
| reads `{root}/raw`; writes `{root}/raw/{day}.csv` | dependency, always |
| writes `{root}/raw`; writes `{root}/raw/{day}.csv` | conflict, always |
| writes `{root}/raw`; deletes `{root}/raw/{day}.csv` | conflict, always |
| reads `{root}/raw`; deletes `{root}/raw/{day}.csv` | hazard, always |
| deletes `{root}/raw`; deletes `{root}/raw/x.csv` | conflict, always |
| declares nothing of `{root}/raw`; reads or writes `{root}/raw/x.csv` | conflict, always |
| requires `{root}/raw` to exist; writes `{root}/raw/x.csv` | dependency, unknown (§8.5) |

> *Before:* "checks `Exists` on `{root}/raw` (no verbs); reads or writes
> `{root}/raw/x.csv` | conflict, always". A port requiring `Exists` was an effect
> unknown. Since §8.5 it is an input of existence: it follows what may make its path,
> and a reader below it is no conflict.

**[Fact]** Every link now asks `same`, `inside` and `contains`, and its certainty is that
of the three together (§15.4). Two deletions conflict because the second may find its
path gone. A port that declares nothing of its path may write: it is kept apart from
every port it touches, and orders nothing, since nothing says which way.

**[Measured]** No precision lost where it was measured: the six-step pipeline keeps its 5
dependencies, 1 hazard, 1 conflict, order and stages (0.17 ms), and the chain benchmark
its links and orders (77 ms at N = 200).

### 8.2 `cycles()` and `order()` followed different relations

**[Refuted]** "`order()` is None if the steps form a cycle (`cycles`)". `order()` follows
dependencies and hazards; `cycles()` followed dependencies alone. Step `a` reads `x` and
`y`, and step `b` writes `y` and deletes `x`: `b` must come first (it writes what `a`
reads) and last (it deletes what `a` reads). `order()` was None, and `cycles()` was
empty. Both now follow one relation, and `cycles(certain=True)` keeps the links that hold
on every run: a cycle among them is unavoidable. A cycle found only without it rests on a
link that holds on some runs or is not ruled out, and may depend on the bindings
(`test_a_cycle_that_rests_on_a_possible_link_is_not_called_unavoidable`).

### 8.3 What held

**[Fact]** `_link` drops a pair only when its relation is `"never"`, and the literal
index (`_apart`) only when two literal segments diverge, which proves `"never"` for all
three relations. Every query but those given `certain=True` counts every other link.
`stages()` puts into one group only steps with no dependency or hazard between them (a
step is ready only once all it follows are done) and no conflict.

**[Fact]** One interaction was left outside the graph, as an assumption: the parents a
creation may make. The owner did not accept it (§8.5), and it is now part of the
graph.

> *Before:* "Two steps that create siblings in a missing directory both may create it,
> and do not touch. They may share a stage, which is safe when parents are made
> idempotently. [...] Counting every parent would join every two writers under a root
> that may not exist yet. [...] carrying that bound into the graph is open." The safety
> contract rested, unstated in the API, on how every step makes its parents.

**[Fact]** The relation's documents now say, in `relate`, `Relation`, `Relation.disjoint`,
`EffectGraph.independent` and SEMANTICS §15, that paths are compared as rendered strings,
not filesystem objects. `Relation.disjoint` had said "they cannot interact".

### 8.4 An oracle for the schedule

**[Measured]** `test_order_and_stages_hold_for_every_rendered_run` renders every port of
150 generated pipelines (2–5 steps, 1–3 ports each, every verb and none) under 300
bindings from the overlap tests' pool. It compares the rendered paths as strings, and
checks three things. A step reading or listing what another writes comes after it, in
`order()` and in `stages()`. A step reading what another deletes comes before it. Two
steps whose paths touch, where either changes its path or has no known effect, never
share a stage. It also checks that `order()`, `stages()` and `cycles()` agree on whether
there is a cycle. Since §8.5 it checks the parent rules too.

**[Measured]** Mutants of `effects.py`, run against the scheduling tests with one seed
and no example database:

| mutant | killed by |
|---|---|
| the graph as first pushed | the oracle, the nesting cases, the hazard cycle |
| a link asks only `same` | the oracle, the nesting cases |
| `cycles()` ignores hazards | the oracle, the hazard cycle |
| two deletions never conflict | the oracle, the nesting cases |
| a port without verbs conflicts with nothing | the oracle (seeds 0–4), the nesting case for a writer |
| `stages()` ignores unknown conflicts | `test_an_unknown_conflict_keeps_two_steps_apart` |
| `order()` follows certain links only | the oracle, the possible cycle |
| unknown links dropped | the oracle, `test_unknown_is_a_dependency_for_the_order_but_never_certain` |
| sometimes links dropped | the oracle, the possible cycle, `test_a_dependency_that_holds_on_some_runs_only` |
| hazards for a deletion inside a read path dropped | the oracle, the nesting cases |

**[Fact]** The oracle cannot catch the unknown-conflict mutant: an `"unknown"` link is
one no binding from the pool shows (`{n!r}.csv` against `q.csv` needs an object whose repr
is `q`). Only the contract, and a test of it, keeps such steps apart.

### 8.5 Parents a creation may make

The owner's second check: making a missing parent is part of a creation's effect, so the
graph must not assume, silently, that every step makes its parents with
`os.makedirs(..., exist_ok=True)`. Four kinds of step were to be told apart:
- one that requires its parent to exist;
- one that makes missing parents idempotently;
- one that makes a directory exclusively, or checks `Creatable`;
- one with effects it does not declare.

**[Fact]** wend's `Creatable` passes for a missing path when its *nearest existing
ancestor* is a writable, searchable directory (`conditions.py`, `_creatable`). So a
creation check's answer depends on which directories above the path exist. Another
step that makes one of them changes it, even when both make parents idempotently.

**[Fact]** The rules, all in terms of what a step declares (§15.4's table):
- **requires its parent to exist**: the parent is declared, `requires(Exists, Dir)`.
  A port requiring `Exists` is now an input of existence (`via="exists"`). It follows
  a step that creates its path (as sure as the paths' relation), and a step that creates
  a path below it (`"unknown"`, since that makes it only if it was missing). It precedes
  a step that may delete it. Before, such a port counted as an effect unknown, kept apart
  from every writer below it, and ordered nothing.
- **makes parents idempotently**: assumed for every parent not declared. Two creations
  below one missing directory share a stage.
- **makes a directory exclusively**: declared, `requires(Absent)` and
  `ensures(Exists, Dir)`, and nesting links it to everything below it (§8.1).
- **checks `Creatable` or `Writable`**: a conflict, `"unknown"` and `via="parent"`, with a
  creation in another step below a directory above both that may be missing.
- **undeclared effects**: outside the graph. `stages()`, `independent()` and the module
  documentation now say the guarantees hold for declared effects only.

**[Fact]** "May be missing" is bounded by `EffectGraph(..., existing=[...])`: paths that
exist before the run and that no step deletes. A step that may delete one of them, or a
directory above it, raises `ValueError`. The anchor (`/`, or the working directory for a
relative path) always exists. The deepest directory two paths share is read from their
structure:
- after their common prefix, two different literal segments, or one segment each, and
  it is that prefix;
- otherwise it is not known, and the conflict is kept.

**[Measured]** What the bound buys, on the pipelines of the tests and the example:

| pipeline | `existing` | parent conflicts | stages |
|---|---|---|---|
| six steps | none | 10, all through `{root}` | unchanged: every pair is already ordered |
| six steps | `[P(root)]` | 0 | unchanged |
| seven steps, with `stats` writing `features/summary.json` beside `features/{day}.npz` | `[P(root)]` | 1: `featurise`, `stats`, through `{root}/features` | `[featurise, purge] [stats]` |
| the same | `[P(root), P(root) / "features"]` | 0 | `[featurise, purge, stats]` |

So the graph no longer serialises every writer sharing a root, once the root is named as
existing. Only creation checks below a directory that may genuinely be missing are kept
apart from the creations that may make it.

**[Measured]** The oracle (§8.4) now also generates ports that check `Creatable`, ports that
require `Exists`, and ports with no conditions at all. It requires two things.
- **Apart:** two steps creating paths below a shared directory other than the anchor,
  either checking creation, are kept apart.
- **Ordered:** a step requiring a path to exist comes after a step creating that path or
  one below it.

  Its first run failed twice, on the oracle's side: it required a step requiring `.` to
  exist to wait for a step creating `data` below it. The anchor exists, so nothing makes
  it, and the graph was right. The oracle now exempts anchors.

  The full suite, under another seed, found the same case for stages. A port that only
  requires `.` to exist was required to stay apart from a step creating `a` below it.
  The graph links them only when the observed path may be missing, so it did not. The
  oracle now exempts that too, and passes under seeds 0 to 9. One property run under one
  seed is not evidence enough: this one needed ten.

**[Measured]** The harness of §8.4, run again on the parent rules: 18 mutants, one seed and no
example database, all killed. The ten of §8.4, adapted to the new code, still fall. The eight
new ones:

| mutant | killed by |
|---|---|
| no parent conflicts | the parent cases, the naming test, the seven-step pipeline, the `{root}` count |
| parent conflicts only when both steps check | the parent cases, the naming test, the `{root}` count |
| `existing` ignored for parents | the parent cases, the seven-step pipeline |
| nothing known to exist (not even `existing`) | the parent cases, the seven-step pipeline |
| existence requirements not inputs | the oracle, the parent cases, `test_an_existence_requirement_follows_what_may_make_it` |
| a missing parent made as surely as the path | `test_an_existence_requirement_follows_what_may_make_it` |
| `existing` never checked against deleters | `test_a_path_given_as_existing_must_not_be_deleted` |
| existence requirements kept apart as unknown | the parent cases |

**[Fact]** The oracle did not kill "no parent conflicts" under seed 0: a generated pipeline
rarely holds two creations below one shared, non-anchor directory, in one layer, with a
creation check. The deterministic cases kill it; the oracle is evidence for the rest.

**[Measured]** Cost: the parent rule pairs suppliers, and its first version recomputed each
port's declarations for every pair, which took the chain benchmark to 105 ms at N = 200
(77 ms before). With the creation checks computed once per port it is 47 ms, links and
orders unchanged: the chain's steps check no creation, so no pair is examined further.
