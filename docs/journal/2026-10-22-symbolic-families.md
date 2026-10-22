# 2026-10-22: Reasoning about path families before any binding (research)

This entry extends [the knowledge model](2026-10-22-knowledge-states.md) from rendered
paths to *families*, expressions with unbound parameters. A pipeline can then be
analysed before any filename exists:

- which checks every run will find already established;
- which checks every run will fail;
- which adjacent steps cannot interfere.

The prototype is `wend._experimental.families`, with tests in
`tests/families_test.py` and a worked pipeline in
`docs/journal/scripts/2026-10-22-families-demo.py`.

Labels: **[Fact]**, **[Measured]**, **[Proven]**, **[Interpretation]**,
**[Conjecture]**.

> **Audit, 2026-10-22.** The text below is kept as written. [The addendum](#addendum-audit-2026-10-22)
> records that three rules had no test that could fail and that no test asserted
> what the analysis knows (both now fixed), corrects §4's measurements, narrows
> §1.1's evidence, and records the development this entry left out.

---

## 1. Facts about families

**[Fact]** A family fact is an atom and an expression. It reads: *for the shared
bindings of a run (one value per parameter name, as one run of a pipeline uses), if
every earlier step completed and the expression renders, the atom held of the path
it renders.* The learn and forget rules are those of the knowledge model, with
three relations between expressions in place of string comparison.

### 1.1 Must-equal

**[Fact]** `must_equal(a, b)` holds when `a.pattern == b.pattern` and every parameter
default agrees in type and `repr`. It claims that wherever both render, they render
the same string.

**[Conjecture]** The claim rests on one observation. A parameter's declaration (type,
choices, kind) decides only which bindings it accepts, never what an accepted binding
renders. Rendering is a function of the normal form, and that function is what the
pattern prints. Even the two shapes where the pattern is ambiguous
([typed path families, §4.6](2026-10-21-typed-path-families.md)) differ only in
validation: a head parameter and a first segment render the same text wherever both
accept the value.

**[Measured]** A probe took 6,000 terms from the contract strategy. It re-declared
every parameter at random (untyped, `Segment`, `AnyPath`, `type=str`, defaults kept)
and rebuilt the term from its pattern. In the 2,325 cases where both renders
succeeded, they were equal every time; in the other 1,573, one render failed. This is
evidence, not a proof.

**[Fact]** `must_equal` sees through construction. `(P(root) / "raw").joinpath(T(t"{Param('day', type=str)}.csv"))`
must-equals `P(root) / "raw" / T(t"{day}.csv")`. Syntactic equality would not see
this: the two differ in how `day` is declared.

### 1.2 May-relate, with prefix cancellation

**[Fact]** `relation(a, b)` asks whether, for some shared binding, `a`'s path is `b`'s
or lies above or below it. It returns `"no"` (never), `"yes"` (for some binding) or
`"maybe"`. `coincide(a, b)` asks only for equality.

Both use `overlaps(·, shared=True)` from #89. `relation` takes "at or below" as
`b / SubPath`, the `_below` of the effect graph.

**[Measured]** Used directly, overlap called `{root}/raw/{day}.csv` and
`{root}/out/{day}.parquet` "maybe", although they never meet. A head parameter is
coarse in overlap's shapes: #89 found it in 75% of builtin-mode MAYBEs. Almost every
pipeline starts at a `{root}`, so this would make the analysis useless.

**[Proven] Prefix cancellation.**
- Let `a` and `b` share a head `h` that must-equals across them, followed by common
  parts that must-equal pairwise. Under shared bindings the common prefix renders one
  string `s`, wherever both render.
- Each side is `s` joined with its remainder. With `s` fixed, joining `s` with a
  relative remainder is injective on the remainder, and preserves the order of
  "lies above". So the two expressions coincide, or one lies above the other, exactly
  when their remainders do.
- If one remainder is empty, the other expression is at or below the common prefix
  for every binding.

`_split` implements this. With it, the two families above are `"no"`, and so are
`{root}/out/{day}.parquet` and `{root}/raw`.

### 1.3 Derived knowledge

**[Fact]** Two rules come from the algebra's structure (`_parents`, the structural
parents of an expression):
- if `exists` is known of a path, then its parent is known to exist and to be a
  directory;
- if `absent` is known of a path, then every path below it is known absent.

**[Proven]** Both are POSIX lookup facts:
- `stat` of `x/y` succeeds only if `x` resolves to a directory;
- if `lstat(x)` fails, `x/y` cannot be resolved.

They hold with symlinks too: `stat` follows a symlinked parent to its directory.

## 2. The analysis

**[Fact]** `analyse_families(steps)` runs the learn and forget rules over these
relations:
- a required atom is **known** where a fact's expression must-equals the input's,
  directly or derived;
- it is **refuted** where a known fact contradicts it through must-equal, so the
  check fails for every binding under which the earlier steps completed;
- it is **possibly refuted** where a contradicting fact only coincides with the input
  for some binding.

A mutation forgets every fact whose relation to it is not `"no"`. It also forgets
`create` and `write` facts about paths not known to exist, if they may lie below a
parent the mutation may make. Those parents are the ones nearer than the nearest
parent known to exist; if none is known to exist, the region is unbounded.

**[Fact]** The worked pipeline (scripts/2026-10-22-families-demo.py) has eight steps,
each a function of `{root}` and `{day}`. Analysed before any binding:

| step | port | the analysis says |
|---|---|---|
| validate | `{root}/raw/{day}.csv` | `exists` and `file` known, from ingest's postcondition |
| featurise | `{root}/raw/{day}.csv` | `exists`, `file`, `read` known (`read` from validate's check) |
| train | `{root}/features` | `exists` and `dir` known, derived because featurise made a path below it |
| report | `{root}/features/{day}.parquet` | `exists` and `file` known |
| cleanup | `{root}/raw/{day}.csv` | `exists` known |
| audit | `{root}/raw/{day}.csv` | `exists` and `read` **refuted**: cleanup deleted it, for every binding |

Adjacent pairs that commute: validate|featurise, train|report, report|cleanup.

Run for `day=mon` and `day=tue` with `elide=True`, every step completes until audit,
which fails with a missing-path error, and each run skips 8 checks.

## 3. Independence

**[Fact]** `independent(x, y, k)` holds when, in both directions:
- no mutating port of one step is related (`relation` ≠ `"no"`) to any port of the
  other;
- no port of the other that requires `create` or `write` may lie below a parent the
  mutation may make, given the knowledge `k` before the pair.

**[Interpretation]** Here is the argument for commuting, under the knowledge model's
closed world, with one more assumption: each body's effect is determined by the state
of its own declared paths.
- A step's checks read the state of its own paths. For a `create` or `write` of a
  missing path, they also read that path's nearest existing ancestor.
- Independence leaves all of those untouched by the other step.
- So each step sees the same state in either order, makes the same changes, and the
  changes are disjoint. The final trees are equal, and so is each step's outcome.

This is an argument, not a proof checked by a machine. The test below checks its
conclusion.

## 4. Measured

**[Measured]** `tests/families_test.py` generates pipelines over 14 families that are
chosen to collide under some binding:
- a second construction of the same family;
- `{root}/{name}`, which is the raw directory when `name=raw`;
- an empty SubPath, which is its parent;
- a second head, `{base}`;
- a deferred `with_suffix`;
- a deferred `parent` of a SubPath, which overlap can only call MAYBE;
- `day` defaulted two different ways.

Each pipeline is analysed once, then run under four shared bindings in a fresh
temporary directory, one of which leaves `day` unbound. At every step whose
predecessors completed, the tests assert that every symbolically known atom holds on
disk for that binding, and that a refuted atom makes the step fail. For every
adjacent pair the analysis calls independent, they run both orders and compare
outcomes and final trees. Each property runs 250 examples, half random and half
modelled on the tree under the first binding.

**[Measured]** Over 1,000 modelled pipelines:

| measure | count |
|---|---|
| step runs with every predecessor completed | 7,033 (4,437 completed) |
| required atoms at those entries | 12,299 |
| known by the concrete tracker, for that one binding | 1,534 |
| known by the family analysis, for every binding | 867 |
| adjacent pairs / judged independent | 1,926 / 234 |

**[Interpretation]** The family analysis knows 57% of what the concrete tracker knows
for one binding. That is the price of quantifying over all bindings when families can
collide: with `name` possibly equal to `day`, or `base` possibly the raw directory,
a mutation has to forget more.

On simpler families it can know more than the tracker. In an earlier run, before the
colliding families were added, it knew 809 atoms against 726, through the derived
parent rule, which the concrete tracker lacks.

**[Measured]** Mutants of the rules, and what rejected each:

| mutant | rejected by |
|---|---|
| cancel prefixes even under different heads | the generated soundness property |
| relation: coincidence only, not above or below | the generated soundness property |
| derive a child's existence from its parent's | the generated soundness property |
| must-equal: same head and length only | the generated soundness property |
| independence ignores the other step's reads | the generated commutation property |
| forget treats MAYBE as NO | only a targeted test |
| must-equal ignores defaults | only a targeted test |

**[Fact]** The last two survived the generated properties at 250 examples. They needed
a MAYBE that is a real overlap (`up` against `sub` when `name=raw`), and an unbound
`day` with two different defaults. The targeted tests that reject them are kept.

## 5. Limits

**[Fact]** Everything here inherits the knowledge model's assumptions: a closed world,
and identity as strings. Symlinks, hard links, case-insensitive filesystems, `..`
spellings and concurrent writers are the subject of the next entry, which tests them
on disk.

**[Fact]** Must-equal is a conjecture with evidence. Prefix cancellation and the
derived rules are proven. Commutation is argued and tested.

**[Fact]** A MAYBE from overlap (deferred operations, conversions, untyped formatted
fields) forgets. So a pipeline built from such expressions knows little, but what it
knows remains sound.

---

## Addendum: audit (2026-10-22)

The journals of the research stack were audited against the commits, the tests and the
session record, and the strongest findings were re-run. This entry was the least
complete about its own development. The owner had asked (2026-10-18) that the journal
tell what was attempted and what failed, and the corrections below do that.

### A.1 Tests that could not fail, and what replaced them

- **[Measured] Three rules could be removed without any test failing.** The audit broke
  each in turn:
  - `forget` ignoring the region of parents a mutation may make;
  - `made_parents` returning its list where it should return `None` (unbounded);
  - `independent` dropping its made-parents clause.

  Each passed all of `tests/families_test.py`. The last two also passed #112's
  `confined_test.py`; the third was re-run here, 24 passed. The reasons:
  - the tests run as root, so `access()` grants every permission and permission atoms
    fail only by kind;
  - the bodies make parents with `exist_ok`;
  - the commutation property compares only the shape of the tree (path and kind), and
    every body writes constant text, so the order of writes is invisible to it.

  The commit message (6ac4d38) said "Each rule's mutant is rejected, two only by
  targeted tests". For these three rules that was false, and §4's table omits them.
- **[Measured] No test asserted what the analysis knows.** The properties check
  soundness only: every known atom holds, every refuted atom fails.
  - An analysis that *learns nothing* passed all six tests. That was re-run here: the
    mutant `learn` that adds no fact, 6 passed.
  - So, per the audit, did one that forgets everything on any mutation, and one that
    finds no pair independent.
  - #112's `confined_test` was the first suite to notice "never learn", and only
    incidentally.
- **[Fact] Added now:**
  - `test_the_worked_pipeline_knows_refutes_and_commutes_what_its_table_shows` fixes the
    worked pipeline's table exactly: what each entry knows and refutes, and which
    adjacent pairs commute;
  - `test_making_a_path_forgets_creatability_below_the_parents_it_may_make` tests the
    rule against its own statement, as #108's sibling test does;
  - `test_independence_sees_the_parents_a_creation_may_make` tests the clause in both
    directions.

  The "learn nothing", "forget ignores made parents" and "independence ignores made
  parents" mutants each fail at least one of these.
- **[Fact] One mutant still survives:** `made_parents` bounded where it should be
  unbounded. No construction was found in which the two readings differ. Overlap
  answers coarsely for head parameters, which masks it. The first draft of the rule
  bounded the region at the head, and was replaced because it "missed the unbounded
  case". That was an argument, never a counterexample on disk. **[Conjecture]** The
  unbounded reading is needed only when a head can name a directory that the mutation
  makes. Not demonstrated.

### A.2 §4's measurements, corrected

- **[Refuted] The refutation count.** The final measurement script counted refuted
  predictions from `Tracker.entries`. `Tracker.run` records an entry only once all
  entry checks have passed, so it reported "0 refuted symbolically" by construction. An
  earlier script, which counted correctly, gave 164. §4's table therefore has no
  refutation row. The audit re-measured on the final code, 1,000 pipelines × 4
  bindings, with **[Measured]** results:

  | | refutation reached | step failed | possible refutation reached | of which failed |
  |---|---|---|---|---|
  | modelled | 122 | 122 | 2,130 | 929 |
  | random | 283 | 283 | 1,046 | 761 |

  Every refutation was followed by a failure, as the analysis claims. A *possible*
  refutation was followed by one less than half the time in modelled pipelines, as a
  MAYBE should be.
- **[Refuted] "The family analysis knows 57% of what the concrete tracker knows."** That
  is a ratio of counts (867 / 1,534), not a subset. In the audit's run of 1,000 modelled
  pipelines:
  - the family analysis knew 903 atoms and the tracker 1,395;
  - 720 were known by both: 52% of what the tracker knew;
  - 183, 20% of what the family analysis knew, were known *only* by it: `exists` 113,
    `dir` 51, `absent` 19. All came from the derived parent rules, which the concrete
    tracker lacks.

  So two effects pull in opposite directions:
  - quantifying over bindings makes the analysis forget more;
  - the parent rules make it know facts the tracker never learns.

  The interpretation above attributes the whole difference to the first. The earlier
  "809 against 726" was the second effect, as the entry guessed; the audit measured it.
- **[Fact]** Every precision number in §4 was made by scripts in the session's scratch
  space, not committed. The new table test above is the committed oracle.
- **[Fact] Development the table hides.**
  - The families `base_day`, `via_suffix`, `up`, `raw_dmon` and `raw_dtue` were added
    *because* mutants survived the first generator.
  - "Split ignores the heads" was at first not detected.
  - All five MAYBE pairs the first generated families produced were harmless.
  - The first measurement completed 1,368 of 6,552 step runs and knew only 229 atoms.
    That was too thin to trust, and it led to the modelled generator.

### A.3 §1.1's evidence, narrowed

**[Fact]** The must-equal probe was weaker than §1.1 says, in five ways:
- it ran in #106's worktree, because it needs `patterns.parse`, which this stack does
  not have;
- its `"int"` re-declaration was a no-op;
- Hypothesis found two failures in the probe itself, and the fix fell back to the
  original declaration, which lowered the real re-declaration rate;
- about 2,100 of the 6,000 terms never built;
- it compares `e` with `parse(e.pattern)` only. Two independently built expressions
  with equal patterns, which is how the analysis uses must-equal, are tested once
  (`raw_day` against `raw_day2`).

The premise is supported by the audit's check: `type=int` refuses `"01"` rather than
coerce it, and a segment refuses `"."`, `""` and `".."`. The status stays
**[Conjecture]**.

### A.4 What the entry did not discuss

- **The owner's challenge.** The owner wrote (2026-10-22): "I'd challenge the proposed
  rule of knowing facts only when expressions are equal. Different expressions can be
  proven to denote the same paths, disjoint paths, or overlapping sets under particular
  bindings. […] The analysis should distinguish must overlap, may overlap, and provably
  disjoint, with conservative behaviour where it cannot decide."
  - What was built: must-equal, plus prefix cancellation and parent rules.
  - What was dropped without a record: the knowledge entry's option "aligned by a lens".
  - Every rule tests `relation != "no"`. None distinguishes a YES from a MAYBE, so a
    must-overlap is treated as a may-overlap. That is sound, and it is precision the
    analysis does not use. **[Open]**
- **One binding per run.** A run fixes one value per parameter. Two things are not
  modelled:
  - runs of several days over one tree, sequential or concurrent. Under assumption 1 a
    concurrent run is "another writer";
  - steps that read across all days, like `train`'s listing.
- **A family can render to the root.** `up` renders `{root}` itself under one of the
  bindings, so a deletion in the harness could remove its own temporary root.
  `2026-10-22-confined-runs.md` §1 found the same and made both executors refuse to
  delete the root.
- **The soundness of `"no"` is inherited.** Prefix cancellation is proven relative to
  overlap's NO being sound under wend's rendering rules, and to deterministic rendering
  (`2026-10-20-overlap-research-89.md`). The limits above should have named that
  dependency.
- **Mixed spellings.** A relative and an absolute spelling of one file are judged
  unrelated: `relation(P("data") / "x.csv", P("/work/data") / "x.csv") == "no"`. This is
  the lexical identity assumption, which `2026-10-22-aliasing.md` breaks on disk and
  confined runs enforce.
- **Links that break in this stack.** Two links point to
  `2026-10-21-typed-path-families.md`, which exists only on #106's branch. They resolve
  once #106 is merged.

### A.5 Where this leads

- `2026-10-22-aliasing.md` (#110) tests the lexical identity this analysis assumes, on
  disk.
- `2026-10-22-confined-runs.md` (#112) runs the plan of families beneath a root and
  measures it under another writer.
- The research index, `2026-10-22-research-index.md` on the latest research branch,
  orders all of them.
