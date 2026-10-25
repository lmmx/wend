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
400 generated pipelines (seed 0), both run in order:

| families says | obligations says | count |
|---|---|---|
| known | discharged | 428 |
| refuted | refuted | 197 |
| neither | discharged | 66 |
| neither | refuted | 25 |
| known | at risk or external | 30 |
| refuted | at risk | 15 |

On the families tests' worked pipeline the two agree exactly
(`test_obligations_agree_with_the_experimental_analysis_on_its_pipeline`).

- **Where the method knows more** (91 atoms), it is through the derived rules (existence
  of a parent, absence below) and `relate`'s precision since #119: for example
  `with_suffix({root}/raw/{name}.tmp, ".csv")` listed, then required as a directory.
- **Where it knew less** (45 atoms), every case involved one family,
  `up = parent({root}/{name}/{rel...})`: a `parent` that is deferred because the last part
  is a `SubPath`. `relate(up, up)` was `"sometimes"`, not `"always"`. The experimental
  `must_equal` compares construction, so it saw the two as one.

**[Fact]** That is a gap in `relate`, not in the method: an expression renders one string
for a binding, so an expression is always itself. `_common` refused to cancel any deferred
head, so the relation fell through to the overlap engine, whose shapes for a deferred
`parent` are coarse.

**[Proven]** A deferred head is a function of the binding, as a head parameter is: its
operation is pure string work (`PurePosixPath.parent`, `relative_to`, `with_*`) on what its
base renders. Two deferred heads with equal render keys (§15.3; the operation, its base
and its argument, parameters by name) therefore render one string under a shared binding,
unless a parameter inside them has a default on each side that differs: unbound, each
renders its own. That was the only missing case, since `_names`, which reports a part's
parameters for the defaults check, returned nothing for a deferred head. Both are fixed:
`_common` cancels alike deferred heads under shared bindings, and `_names` looks inside
them. Under independent bindings nothing changes: only a root or relative head cancels.

After the change, the 45 atoms the families analysis knew and the method did not are
OPEN_AFTER.

## 4. Counterexamples found while building it

- **Exclusion read too broadly.** The method as first written flagged an atom as at risk
  whenever a fact of an excluded atom *touched* its path, where the prototype asked
  whether the fact may be *of* it. `ingest.src requires file of {root}/inbox/{day}.csv`
  was "at risk from survey.root", because the root is listable and a listable path is not
  a file, though the root is not the file. Sound (at risk promises nothing) but useless.
  It now asks the same three relations as a discharge, with "not never" for "always".
- **Lost facts of an excluded atom.** A fact that would have *refuted* the atom, once
  forgotten, was also reported as a risk. Its loss can only help. Only a lost fact that
  would have discharged the atom is a risk now.
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
0 to 9 (150 examples each, plus the root-replacing example #109's audit found).

**[Measured]** Mutants of the method, each against `tests/effects_test.py` under seeds 0
and 1:

MUTANTS_TABLE

**[Measured]** Mutants of the deferred-head rule, against `tests/relate_test.py` and the
fast part of `tests/effects_test.py`:

RELATE_MUTANTS

**[Measured]** RELATE_COMPARISON

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
