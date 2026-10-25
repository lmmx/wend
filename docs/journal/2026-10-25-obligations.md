# 2026-10-25: What a requirement relies on: obligations over the effect graph

The experimental families analysis (#109, research index row 4) answered a question the
public graph did not: of the conditions each step requires, which do the steps before it
settle, and which can never hold? It worked, and its disk oracle passed, but it read
`"sometimes"` and `"unknown"` alike, was written against one order of the steps, and lived
outside the wheel. This entry records how it was carried into `wend.effects` as
`EffectGraph.obligations()`, on `relate` and the graph's links, and the precision gap in
`relate` that the comparison exposed. The contract is `docs/SEMANTICS.md` §15.6.

## 1. The question, and the trap in it

The owner asked how a fact established of one expression can be reused for another
without confusing static identity with runtime freshness. The two are separate questions,
and the method answers them separately.
- **Identity.** `relate(a, b).same == "always"` says the two render one string under every
  shared binding. A check of one is then a check of the other, at the moment it ran.
- **Freshness.** Whether the check still holds depends on what ran since. The analysis
  keeps a fact only while no step that may run in between declares a change that may touch
  it, and only under three assumptions (`ASSUMPTIONS`): nothing outside the steps changes
  their paths; each step does what it declares; and no two spellings name one file.

Neither answer is borrowed from the other: two expressions proved the same still lose a
fact to a deletion between them, and a fact about a path with no intervening change says
nothing of a path only `"sometimes"` the same.

## 2. The rules

**[Fact]** A fact is an atom known of a port's path: `exists`, `absent`, `file`, `dir`,
`read` or `list`. A run learns it when a check passes: a step's precondition as it
starts, or its postcondition once it completes. `create` and `write` are never kept:
whether a path may be created depends on which directories above it exist, which every
creation may change (#118 §8.5).

**[Proven]**, under `ASSUMPTIONS` and on runs where every step of an earlier group
completed:
1. **A fact lasts until a change may reach it.** A fact of path `x` learned at time `t`
   holds at `t' > t` if no step that may run in `(t, t']` declares a change (supply,
   deletion, or a port with no known effect) to a path that touches `x`: the same, inside
   it, or containing it. Under the closed-world and declared-effects assumptions, only
   such a change can alter what `x` is: a change elsewhere leaves `x`'s entry and its
   ancestors as they were. "Touches" is decided by `relate`, and only a `"never"` on all
   three questions lets a fact survive a change, so a possible change always forgets.
2. **A fact is of the paths proved the same.** If `relate(p, f).same == "always"`, then
   on every run where both render they are one string, so one entry, and `f`'s fact is
   `p`'s.
3. **Existence goes up, absence goes down.** If `p` always contains `f` and `f` exists,
   then `p` exists and is a directory: an entry below a path exists only through it.
   If `p` is always inside `f` and `f` is absent, `p` is absent. Both are lexical, and
   rest on the third assumption.
4. **Refutation is the same rules on an excluded atom.** §10 forbids declaring together
   `exists` with `absent`, `absent` with `read` or `list`, and `file` with `list`, because
   no path satisfies both. `file` and `dir` exclude each other only where the path exists:
   both hold of a missing one. A fact that makes an excluded atom true makes the
   requirement false, so the step's check fails.
5. **A group may interleave.** For a step in a group, the analysis uses only what was
   known before the group, less anything another member may change: members may run in
   any order or at once. What members check or promise is known from the next group on,
   less what another member may change. Within `stages()` no two members interfere, so the
   second clause never applies there; a schedule given by hand may group steps that do.

**[Fact]** `"at risk"` and `"external"` promise nothing. `"at risk"` names the step that
may have broken the atom, or the known fact that may refute it, as a lead, not a verdict.

## 3. What the comparison found

**[Measured]** The method against the experimental `analyse_families`, atom by atom over
400 generated pipelines (seed 0), both run in order. First as the method was written,
then once `relate` cancelled a deferred head (below):

| families says | obligations says | first | after |
|---|---|---|---|
| known | discharged | 428 | 458 |
| known | at risk or external | 30 | 0 |
| refuted | refuted | 197 | 212 |
| refuted | at risk | 15 | 0 |
| neither | discharged | 66 | 66 |
| neither | refuted | 25 | 25 |

On the families tests' worked pipeline the two agree exactly
(`test_obligations_agree_with_the_experimental_analysis_on_its_pipeline`).

- **Where the method knew less** (45 atoms), every case involved one family,
  `up = parent({root}/{name}/{rel...})`: a `parent` that is deferred because the last part
  is a `SubPath`. `relate(up, up)` was `"sometimes"`, not `"always"`. The experimental
  `must_equal` compares construction, so it saw the two as one.
- **Where it knows more** (91 atoms, all checked by the disk oracle):
  - 60 through a sameness `must_equal` does not see. For example, `{root}/raw/{day}.csv` with `day`
    declared `str`, against the same path with `day` defaulting to `tue`: `must_equal`
    keeps them apart for the default, but wherever both render, `day` is bound, so they
    are one string. A step whose path cannot render does not complete, so no fact
    reaches past it;
  - 27 through a fact the families analysis forgot. It forgets on any possible overlap,
    and `relate` since #119 proves `"never"` where it could not: a step writing
    `{root}/tmp/{day}/x` no longer erases what was known of
    `with_suffix({root}/raw/{name}.tmp, ".csv")`;
  - 4 through the derived rules: `{root}/raw` exists, as a directory, once something
    below it was made.

**[Fact]** The missing 45 were a gap in `relate`, not in the method: an expression renders
one string for a binding, so an expression is always itself. `_common` refused to cancel
any deferred head, so the relation fell through to the overlap engine, whose shapes for a
deferred `parent` are coarse.

**[Proven]** A deferred head is a function of the binding, as a head parameter is: its
operation is pure string work (`PurePosixPath.parent`, `relative_to`, `with_*`) on what its
base renders. Two deferred heads with equal render keys (§15.3; the operation, its base
and its argument, parameters by name) therefore render one string under a shared binding,
unless a parameter inside them has a default on each side that differs: unbound, each
renders its own. That was the only missing case, since `_names`, which reports a part's
parameters for the defaults check, returned nothing for a deferred head. Both are fixed:
`_common` cancels alike deferred heads under shared bindings, and `_names` looks inside
them. Under independent bindings nothing changes: only a root or relative head cancels.

## 4. Counterexamples found while building it

- **A soundness defect on master: a changed name may be `..`.** The full suite's run of
  `test_every_always_and_never_holds_for_every_pooled_binding` found
  `relate(with_suffix({root}, "")/.., with_suffix({root}, ""), shared=False).same ==
  "never"`, though `root="a"` and `root="a/.."` render `a/..` on both sides. pathlib
  keeps the name `..` through `with_suffix("")` (a name of `..` has no suffix), and
  makes it from the stem `..`, or the stem `.` before the suffix `.`. Two places assumed
  a new name is never `..`, as a formatted segment never is:
  - the overlap engine's language for a renamed name (since #89), which gave the
    example above;
  - the view of a changed name (#119, §2 of its entry, corrected there in place): for
    `({root}/{d}).with_stem(".")` against `{root}/..`, "same" was `"never"`, though
    `d="x."` renders `q/..` on both sides, and likewise for the stem `..` with `d="x"`.

  `relate` is in no release yet (0.3.0 predates #118), so no released answer was wrong.
  **[Proven]** A new name is `..` only through a literal: a field never renders `.` or
  `..` (wend rejects them as text), so a stem or name with a field is neither; and a
  stem `t` before a suffix `x` makes `..` only if `t` is `.` (with `x = "."`) or `..`
  (with `x = ""`). `with_suffix(s)` makes `..` only from a base named `..` with `s =
  ""`, and a base renders that name only from a head, never from a field segment. So:
  - the engine allows `..` in the new name for `with_suffix("")`, and for `with_stem` of
    a literal `.` or `..`; `with_name("..")` was already exact (a literal);
  - `with_stem` of a literal `.` or `..` has no view; the `with_suffix` view's base ends in
    a field segment, which is never `..`, so it stands.

  The pool gained the value `x.`, and the property tests' operations the stems `.` and
  `..` and the name `..`. Against the code before the fix, the new deterministic test
  (`test_a_changed_name_may_be_dotdot`) fails under every seed, and the
  changed-names property test under one seed in two.

- **Exclusion read too broadly.** The method as first written flagged an atom as at risk
  whenever a fact of an excluded atom *touched* its path, where the prototype asked
  whether the fact may be *of* it. `ingest.src requires file of {root}/inbox/{day}.csv`
  was "at risk from survey.root", because the root is listable and a listable path is not
  a file, though the root is not the file. Sound (at risk promises nothing) but useless.
  It now asks the same three relations as a discharge, with "not never" for "always".
- **Lost facts of an excluded atom.** A fact that would have *refuted* the atom, once
  forgotten, was also reported as a risk. Its loss can only help. Only a lost fact that
  would have discharged the atom is a risk now.
- **The engine is not monotone.** Cancelling a deferred head lost one answer in 1,500
  pairs below one head: for `with_stem({f}/x.txt, {p})/{sc...}/{p}-{q}` against
  `with_stem({f}/x.txt, {p})/{p}-{q}/{n}.txt`, "same" went from `"never"` to `"unknown"`.
  The overlap engine says NO of the whole expressions and MAYBE of what follows their
  head, though the second question is the first with a common prefix removed. Where a
  deferred head was cancelled and the remainders leave an answer unknown, the engine is
  now asked of the whole expressions too, as before.
- **My expectations, twice.** In tests of hand-made groups I expected `drop`'s
  `exists` to be at risk when `drop` shares a group with `read`, and a later step's
  `exists` to be at risk after the group. The method said discharged, then refuted, and
  was right both times: `read` changes nothing, and once `drop` completes, the path is
  absent whatever order the group ran in.

## 5. Tests and measurements

**[Measured]** The disk oracle (`test_obligations_hold_on_disk_when_run_in_order` and
`..._by_stages`) reuses the families tests' generator, trees and four bindings, in which
families collide: `raw_name` is `raw_day` when `name` is `mon`, `up` is the root when
`rel` is `.`. Each pipeline runs in a real directory; by stages, each group's steps run
in both orders. Wherever every earlier group completed, every discharged atom holds on
disk as its step starts, and every step with a refuted atom fails. Both pass under seeds
0 to 9 before the changes to `relate` below, and under seeds 0 to 4 at the final head
(150 examples each, plus the root-replacing example #109's audit found).

**[Measured]** Mutants of the method, each against `tests/effects_test.py` under seeds 0
and 1:

| mutant | killed by |
|---|---|
| discharged on a `"sometimes"` relation | the spelling test, both disk oracles |
| a step's own changes not forgotten | six tests, both disk oracles among them |
| a group-mate's changes not forgotten | `test_a_group_given_by_hand_may_run_in_any_order` (survived until it was written: `stages()` never groups steps that interfere, so the oracles cannot see it) |
| a group-mate's promise kept | the hand-made groups test (likewise) |
| a group-mate's check known before the group ends | the oracle by stages, the worked pipeline |
| existence read from a path above, not below | the nesting test, the worked pipeline, both oracles |
| absence read from a path below, not above | the nesting test, the oracle in order |
| creating and writing kept | `test_creating_and_writing_are_never_discharged` |
| a port that declares nothing changes nothing | `test_a_port_that_declares_nothing_may_change_its_path` |
| refuted on a `"sometimes"` relation | the spelling test, both oracles |
| File and Dir exclusive of a missing path | `test_file_and_dir_exclude_each_other_only_for_a_path_that_exists` (survived its first version, whose `Dir`-only port declared nothing and so forgot its own fact) |
| no fact lost (at risk never from a lost fact) | the spelling test, the undeclared-port test (precision only) |
| any schedule accepted | `test_a_schedule_names_every_step_once` |

**[Measured]** Mutants of the deferred-head rule and of the `..` fix, against
`tests/relate_test.py` (and, for the first four, the fast part of
`tests/effects_test.py`; for the last three, `tests/overlap_test.py`):

| mutant | killed by |
|---|---|
| deferred heads never cancel | `test_one_deferred_head_cancels_as_a_prefix` (precision only) |
| a deferred head's defaults unseen | `test_one_deferred_head_cancels_as_a_prefix` (the property tests' pool binds every name, so no default is ever used) |
| deferred heads alike by operation alone | both new tests, the general and changed-names property tests |
| deferred heads cancel under independent bindings | both new tests, the changed-names property test |
| the engine: `with_suffix("")` never keeps `..` | `test_a_changed_name_may_be_dotdot` |
| the engine: a stem never makes `..` | the same, and the changed-names property test |
| a view of the stem `.` or `..` | the same, and the changed-names property test |

**[Measured]** The relation on the same derandomised samples as #119 §4, answered by master
(`b4a212f`) and by this branch, plus 1,500 pairs below one deferred head
(`under_one_head`). Each pair is asked `same`, `inside` and `contains`:

| sample | always | sometimes | never | unknown |
|---|---|---|---|---|
| 1,500 general pairs, master | 707 | 309 | 3,067 | 417 |
| the same, this branch | 711 | 305 | 3,075 | 409 |
| 1,500 changed names, master | 229 | 557 | 3,265 | 449 |
| the same, this branch | 235 | 551 | 3,273 | 441 |
| 1,500 pairs below one deferred head, master | 88 | 585 | 967 | 2,860 (63.6%) |
| the same, this branch | 576 | 193 | 2,247 | 1,484 (33.0%) |

Answer by answer, below one head: 1,280 `"unknown"` became `"never"`, 408 `"sometimes"`
became `"always"`, 80 `"unknown"` became `"always"` and 16 `"unknown"` became
`"sometimes"`. On the other two samples, 16 `"unknown"` became `"never"` and 10
`"sometimes"` became `"always"`. No answer moved the other way, once the engine was asked
of the whole expressions as well (§4).

## 6. What it does not do

- **[Fact]** Facts are only those the steps check or promise. A step that reads a file
  does not learn that its parent is listable; the method knows what was checked.
- **[Fact]** A fact of a path is not transferred to a path only `"sometimes"` the same, so
  a discharge needs the relation to prove identity. Unions are never `"always"` related,
  so a union's port discharges nothing.
- **[Fact]** The schedule is of whole steps. A step that checks its preconditions, then
  works for a long time, is judged at its start, and its postconditions count from its
  completion.
- **[Open]** `existing=[...]` bounds parent conflicts, but not obligations: a directory
  given as existing could discharge `exists` and `dir` of itself and its ancestors.
- **[Open]** Freshness in the stronger sense of #114 (a file changed in place with no
  observable trace) is outside the closed-world assumption: the method says what the
  declarations settle, not what another process may do.

## 7. Addendum (#121): what paths given as existing, reads and listings establish

**[Proven]**, under `ASSUMPTIONS`:
1. **A passed read or listing shows existence.** §10's table: `Readable` holds only of a
   path that exists, and `Listable` only of a directory. So a passed check of `read`
   makes `exists` known, and of `list` makes `exists` and `dir` known, for as long as the
   fact itself lasts (§2, 1). A read says nothing of the kind, since `Readable` holds of a
   directory too. Each also counts as evidence for the containment rule (§2, 3): a
   readable path below `p` shows that `p` exists, as a directory.
2. **A path given as existing exists throughout.** The constructor refuses a graph in
   which a step may delete such a path or a directory above it (§15.4), so under the
   declared-effects assumption nothing removes it, and nothing removes a directory above
   it. Its existence is a fact from the start that no change forgets, unlike a fact a
   step learns. It says the path exists, not that it is a directory; only the directories
   above it are, by the containment rule.

**[Fact]** The obligation that cites such a fact names a port of no step (`by.step ==
""`), which the obligation prints as "given as existing". The literal-prefix index
(`_apart`) looked ports up by identity, and the first version made these ports afresh
inside `obligations()`, so the extended oracle's first run raised `KeyError`. They are
now made once, in the constructor, and indexed with the rest.

**[Measured]** The disk oracle gained two roles, `Readable` alone and `Listable` alone,
so that the implications are tested apart from `Exists` and `Dir`, and three choices of
what the graph is told exists: nothing, the root, or the `raw` directory where the tree
has one. Over 600 derandomised cases, each judged in order and by stages, master
(`cc964ff`) against this branch:

| status | master | this branch |
|---|---|---|
| discharged | 1,353 | 1,738 |
| refuted | 564 | 566 |
| at risk | 1,334 | 1,367 |
| external | 8,209 | 7,789 |

Answer by answer:
- 372 `"external"` became `"discharged"`;
- 13 `"at risk"` became `"discharged"`;
- 2 `"external"` became `"refuted"`;
- 46 `"external"` became `"at risk"`: a fact now known that may refute them.

No discharged or refuted answer was lost.

**[Measured]** Mutants of the new rules, against `tests/effects_test.py` under seeds 0 and
1:

| mutant | killed by |
|---|---|
| a read shows a directory | `test_a_read_or_listing_says_the_path_exists` |
| a listing shows no directory | the same |
| a read or listing below is no evidence above | the same |
| a path given as existing forgotten like any fact | `test_a_path_given_as_existing_is_a_fact_throughout` |
| paths given as existing ignored | the same |
| a path given as existing taken for a directory | the same |
| a passed `Writable` check shows existence | survived: equivalent. A `Writable` port supplies its path (the verb `write`), so its own step forgets the fact as soon as it is learned, and no later step can use it. It would be unsound otherwise: a missing path may be `Writable` (§10) |

**[Measured]** The extended oracles pass under seeds 0 to 4, 150 cases each.
