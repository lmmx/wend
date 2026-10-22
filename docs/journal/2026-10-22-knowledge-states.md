# 2026-10-22: What a program knows about a path (research)

This entry follows the decisions recorded in
[the typed path families entry](2026-10-21-typed-path-families.md#decisions-owner-2026-10-22).
It asks whether wend can describe what a program *knows* about a path before and
after each operation. It also designs the semantics that has to come before
postconditions become types: what is certified, when it is checked, and when that
knowledge ends.

The prototype is `wend._experimental.knowledge`. Its tests are in
`tests/knowledge_test.py`, and it builds on `PathExpr.declares` (#107,
SEMANTICS.md §10.1).

Labels: **[Fact]**, **[Measured]**, **[Proven]**, **[Interpretation]**,
**[Conjecture]**, **[Proposal]**.

> **Audit, 2026-10-22.** The text below is kept as written. [The addendum](#addendum-audit-2026-10-22)
> corrects §2 (containment is forgotten in its physical half), §3 (assumption 2's
> scope), §4 (what the properties can detect) and §6 (what a type certifies, and what
> `known()` means), and records how the model was developed.

---

## 1. Three things to keep apart

**[Fact]** §10.1 already separates two of them, and the prototype adds the third:

- **Declared.** `e.declares`: an obligation an expression states. It is a property
  of the expression, true forever, and says nothing about the filesystem.
- **Checked.** A fact `a(p)`: atom `a` found true of the rendered path `p` by a
  check that passed. It is true at the moment of the check.
- **Known.** A checked fact that no effect has invalidated since.

**[Interpretation]** The typed prototype of #106 certifies the first, `Checked[C]`
handles certify the second, and nothing certified the third. The third is the
missing link between the static types and the effects graph:
- the declaration fixes what is checked and what is mutated;
- the effects determine when a checked fact stops being known.

## 2. The model

**[Fact]** A `Knowledge` is a set of `Fact(atom, path)` over rendered path strings,
with two updates, as in a gen/kill dataflow analysis:

- **learn**: a check that passed adds its atoms for its path. For a step, every
  port's preconditions are learned once all of them have passed, and its
  postconditions are learned once its confirmation has passed.
- **forget**: a mutation of a path `m` (a port declaring `write`, `create` or
  `delete`, from `Declarations.verbs`) removes two kinds of fact:
  - every fact about `m`, about a path below `m`, or about a path above `m`;
  - every `create` or `write` fact about a path not known to exist that lies below
    a parent of `m` the mutation may make. Those are the parents below the deepest
    one known to exist, or all of them if none is.

**[Fact]** Containment is never forgotten: it is a property of the rendered string,
which `render` enforces (§10). `Tracker.run(name, step, env)` performs these updates
around a real step: checks, learn, body, forget, confirm, learn. Forgetting runs even
when the body raises.

**[Fact]** `analyse(steps, env)` computes the same updates before anything runs,
assuming every earlier step completed. It reports, for each port at each entry:
- which required atoms are already known (`known`);
- which a known fact contradicts (`refuted`). The contradiction pairs are
  `exists`/`absent`, `absent`/`read`, `absent`/`list` and `file`/`list`, and
  `file`/`dir` when the path is also known to exist.

The last one is conditional because a missing path satisfies both `File` and `Dir`
(§10: "p is missing, or is a regular file").

## 3. Soundness, and what it assumes

**[Proven]** *Under the closed world below, every known fact holds whenever a step
starts.* The proof is by induction on the operations, with the invariant that every
fact in the knowledge holds of the filesystem:

- **Base.** The knowledge starts empty.
- **Learn.** A fact is added only when a check found it true, at that moment.
- **A step's body.** By assumption it changes the filesystem only by its declared
  mutations of its own rendered paths. A mutation of `m` can change the truth of an
  atom about `p` in only three ways, and each removes the fact:
  - **Same, above or below.** If `p` is `m`, or `p` is above or below `m`, the fact
    is removed by the first forget rule.
  - **Nearest existing ancestor.** Otherwise, the node at `p` and at every path
    above and below `p` is unchanged, unless the mutation made a directory above
    `p`. That can happen only for directories it made as parents of `m`, so only
    below the deepest parent known to exist. And of the atoms, only `create` and
    `write` of a missing `p` depend on such a directory: they depend on `p`'s
    nearest existing ancestor (§10).
  - **Below the mutated path.** A deletion removes `m` and what is below it, never
    its parents.

  So every atom whose truth may have changed is forgotten.
- **Confirmation.** The postconditions are learned only after the confirmation
  passes, which is after the body's mutations.

**[Fact] The assumptions (the closed world):**
1. Between a step's entry check and the next step's, the filesystem changes only
   through the declared mutations of the steps' rendered paths. No other process
   acts, and no body writes a path it does not declare.
2. Identity is lexical. Two different rendered strings name different files: no
   symlink, hard link, case or `..` aliasing among the paths involved. This is the
   caveat `EffectGraph.lexical_caveats` already reports.
3. A mutation of `m` changes nothing outside `m`, the paths below it, and the
   parents it makes.

**[Interpretation]** Without assumption 1, a checked fact is only what §10.1 says,
true when checked. The model does not weaken that statement. It identifies the
condition under which a check need not be repeated.

## 4. Measured

**[Measured]** `tests/knowledge_test.py` generates trees and pipelines of 2 to 7
steps, each with 1 or 2 ports. Each port has one of six roles, with a body that does
exactly what the role declares:
- read a file; create a file (with parents);
- write a file; delete a path;
- list a directory; make a directory.

The tests run them in a fresh temporary directory, and assert:

- **soundness:** at every step's entry, every known fact holds on disk;
- **refutation:** a required atom that `analyse` reports refuted makes the step fail,
  whenever every earlier step completed;
- **agreement:** otherwise the atoms `analyse` reports known are exactly those
  `Tracker` found known;
- **elision:** running with `elide=True` gives the same completed steps and the same
  final tree as checking everything.

Each property runs 400 examples per test run. Half come from random pipelines, half
from pipelines that mostly fit the tree as earlier steps leave it, with one port in
five drawn at random.

**[Measured]** Over 2,000 modelled pipelines:

| measure | count |
|---|---|
| steps | 9,095 |
| steps completed | 7,288 |
| required atoms at entries | 21,391 |
| of which already known (an elidable check) | 5,067 (24%) |
| refuted predictions, with every earlier step completed | 257 |
| of which the step failed | 257 |

Over 2,000 random pipelines, 1,639 of 9,232 steps completed, and 538 of 4,216
required atoms were already known. All 255 refuted predictions failed, as predicted.

**[Measured]** Mutants of the rules, and the test that rejects each:

| mutant | rejected by |
|---|---|
| forget only the mutated path | soundness |
| forget below the mutated path, not above it | soundness |
| never forget | soundness |
| `file` and `dir` exclusive even for a missing path | a unit test, not the properties |
| learn a port's preconditions before every port's check has passed | not rejected |

- **The `file`/`dir` mutant.** No role requires `File` or `Dir` without `Exists`, so
  the generated pipelines never reach the case. The unit test covers it.
- **The undetected mutant is equivalent, and sound.** The facts it learns did pass
  their own checks, and a step that fails at entry mutates nothing. Adopting it would
  make the model slightly more precise.

**[Measured]** `test_an_undeclared_effect_breaks_the_closed_world` deletes, in a body,
a path the step does not declare. Afterwards `exists` is known for that path, and it
is false. That is assumption 1 made concrete.

## 5. A gap found by reasoning, and closed

**[Fact]** The first forget rule removed facts about the mutated path and the paths
above and below it, and nothing else. It missed facts about a path *beside* the
mutated one:
- `create` (and `write`) of a missing path depends on its nearest existing ancestor
  (§10);
- `mkdir -p` for `e/z` can make `e`, with permissions that make `e/w` uncreatable;
- `e/w` is neither above nor below `e/z`.

**[Fact]** The harness could not show this on disk, because the container runs as
root and `access()` grants root every permission. The unit test
`test_making_a_path_forgets_whether_its_missing_neighbours_are_creatable` checks
the rule itself, and §3's proof covers the case.

**[Interpretation]** This is the kind of case adversarial testing alone misses when
the environment cannot produce it. The proof is what found it.

## 6. What this means for postconditions as types

**[Interpretation]** Decision 2 asks three questions: what is certified, when it is
checked, and when that knowledge is invalidated. The model answers each:

- **Certified:** an event, *a check of these atoms passed for this path*, and nothing
  about the time after it. A static type can carry this faithfully. A
  `Checked[...]` handle produced at a step's entry certifies the preconditions. A
  handle produced at a step's exit (say `Confirmed[...]`) would certify the
  postconditions, with the same meaning.
- **Checked:** at entry for preconditions, at exit for postconditions, by
  `Tracker.run`, as by `wend.Step` today.
- **Invalidated:** by the forget rule. That depends on which mutations happen
  afterwards, so on the program's order and its bindings. Neither Pyright nor ty can
  track that: Python's types have no notion of a value going stale, no linear or
  affine types and no lifetimes.

**[Proposal]** Keep the two halves where they can be sound:

1. A handle's *type* certifies the check event (pre or post atoms), as `Checked`
   does now. That holds forever: the check did happen.
2. A handle's *validity* is the knowledge: computed at runtime by `Tracker` (an
   epoch per fact), and in advance by `analyse`. A typed step API can expose both:
   - `s.src`, typed `Checked[...]`;
   - `s.src.known()`, which returns whether its facts are still known;
   - and `analyse` before the run, for each check that will be redundant and each
     that will fail.

**[Conjecture]** A postcondition type parameter is safe to add under that reading,
the event and not its persistence. It would let a function demand "a path this
program created and confirmed as a file". It would not let one demand "a path that
is a file now". The second needs a checked fact plus knowledge that it still holds,
and that is a dataflow property, not a type.

## 7. Open

**[Conjecture]** `analyse` works on rendered paths, so it needs bindings. Over
families (unbound parameters) the natural extension is:
- forget wherever `overlaps` is not NO (MAYBE forgets, which is sound);
- know only where a fact's expression and the input's are equal normal forms, or
  aligned by a lens under shared bindings.

That extension, and its soundness, are untested.

**[Fact]** Not modelled:
- concurrency between steps;
- partial effects of a body that raises (the model forgets conservatively and learns
  nothing);
- fsspec stores, whose permissions are not bits.

**[Interpretation]** With knowledge in the model, the static capabilities, the effect
graph and the runtime checks no longer read as three adjacent APIs:
- a declaration says what will be checked and what may change;
- a check produces facts;
- effects end them;
- types certify the events;
- the analysis certifies, in advance, which facts survive to where they are needed.

---

## Addendum: audit (2026-10-22)

The journals of the research stack were audited against the commits, the tests and the
session record. Each later finding that bears on this entry is recorded here, with its
status, so that the text above still shows what was believed when it was written.

### A.1 Statements later shown wrong or narrowed

- **[Refuted] §2, "Containment is never forgotten: it is a property of the rendered
  string."**
  - Only the lexical half is. §10's `Under` also requires the realpath to stay below
    the base, and a symlink made later ends that.
  - Found in `2026-10-22-confined-runs.md` §4. SEMANTICS.md §10.1 now splits the two
    halves (`2026-10-22-declarations.md` §3).
- **[Refuted] §3, assumption 2, "the caveat `EffectGraph.lexical_caveats` already
  reports".**
  - That method reports relative paths and `..` only. Its own docstring says it cannot
    see case or symlinks, and neither analysis calls it.
  - Mixing a relative and an absolute spelling of one file is also outside both
    analyses: the audit measured
    `relation(P("data") / "x.csv", P("/work/data") / "x.csv") == "no"`.
- **[Interpretation] Assumption 2 is too strong about hard links.** Atoms are properties
  of names and of the objects they reach, so two names of one object do not make a
  string-keyed fact false. `2026-10-22-aliasing.md` §1 and §5 show which aliases break
  atoms: symlinks, `..`, mounts and case folding, not hard links. Hard links matter for
  *confinement*, not for knowledge (`2026-10-22-confined-runs.md` §2).
- **[Refuted] §4, "the undetected mutant is equivalent, and sound".** It is sound but not
  equivalent: it learns facts the rule does not, so it knows more. No property here can
  tell a sound refinement from the rule, for two reasons:
  - **soundness** checks that what is known is true, not that what is true is known;
  - **agreement** compares `analyse` with `Tracker`, which share `Knowledge`. That is
    self-consistency, not an oracle.

  No test asserts what the analysis *knows*. A model that knows nothing passes. The
  #109 addendum records the same gap there, measured.
- **[Refuted] §6, "A static type can carry this faithfully" and "A `Checked[...]` handle
  produced at a step's entry certifies the preconditions".** The typed core (#113)
  carries an event, but its addendum records two ways the type claims more than the
  check:
  - `Checked[C, K]` carries every atom the expression declares, post atoms included;
  - a path derived from an event (`c.parent`, `c / ".."`) is typed, and built, as the
    same event.
- **[Narrowed] §6, "`s.src.known()`, which returns whether its facts are still known".**
  `Run.known` (#113) is knowledge *conditional on the closed world*, not a statement
  about now (5672297, and the `2026-10-22-confinement-is-not-consistency.md` §3 table).
- **[Superseded] §7, "That extension, and its soundness, are untested".** #109 built it
  (`2026-10-22-symbolic-families.md`). Its answer to "know only where equal" is
  must-equal with prefix cancellation and parent rules.

### A.2 How the model was developed

These steps are missing above.

- **`file` and `dir` mutually exclusive.** The first draft made them exclusive outright.
  It was corrected from §10 ("p is missing, or is a regular file") before any test ran.
  §4 shows the case only as a mutant.
- **The docstring's first rationale.** The first draft justified forgetting above a
  mutated path with "making or removing a path can make or remove its parents". §3
  then argues that a deletion never removes its parents. Only the first half holds:
  making a path can make its parents, so a fact such as a parent's `absent` can end.
- **Creation facts outlive a step only as postconditions.** A port that requires
  `Creatable` declares `create`, a mutating verb, so the forget rule removes its own
  creation fact at exit. Only an ensured `Exists` carries forward. This was found by a
  surviving mutant in #110: the "creation keyed by the first missing entry" mutant died
  only once a test spanned two steps (`2026-10-22-aliasing.md` §8). It is a property of
  this model, not of #110.
- **The generator.** Random pipelines completed too few steps to say much: 1,639 of
  9,232 above. The *modelled* half of the generator, pipelines that mostly fit the tree
  as earlier steps leave it, was added for that reason.

### A.3 What the evidence covers

- **[Fact]** The counts in §4's table were made by a measurement script in the session's
  scratch space, not committed. The tests run the same generators and assert the
  properties, but they do not print the table.
- **[Fact]** The tests run as root, so `access()` grants every permission, and permission
  atoms fail only by kind or absence.
  - §5's rule therefore has no on-disk test.
  - `2026-10-22-aliasing.md` §3 later found the first way to make `access()` refuse as
    root: a read-only bind mount (`EROFS`). It has not been used to test §5's sibling
    case.
- **[Fact]** `test_an_undeclared_effect_breaks_the_closed_world` has a concrete
  counterpart from #110. A "write" role that does not declare `Writable` declares no
  mutation, so its write is invisible to the forget rule. That is assumption 1, made by a
  declaration rather than by another process.

### A.4 Where this leads

- `2026-10-22-symbolic-families.md` (#109) does the same for unbound families.
- `2026-10-22-aliasing.md` (#110) breaks assumption 2 on disk. String-keyed knowledge
  held a false fact in 189 of the 1,663 pipelines that had an alias, and in none of the
  337 alias-free ones. Identity keys restore it.
- `2026-10-22-confinement-is-not-consistency.md` separates the closed world into the
  five properties a run can and cannot establish.
- The research index, `2026-10-22-research-index.md` on the latest research branch,
  orders all of them.
