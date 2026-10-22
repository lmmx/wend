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
