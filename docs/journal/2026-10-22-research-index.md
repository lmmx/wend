# 2026-10-22: Research index: from path algebra to typed knowledge of program state

The research programme, from #105 to the synthesis, asked one question in stages: what
can a program that names files by templates *know* about those files, before it runs,
while it runs, and after? This index orders its journal entries by concept, not by date.
For each entry it says:
- what the entry established;
- what refuted or narrowed it later;
- where the evidence is.

**Two kinds of document, kept apart.** The journals keep the development: the
hypotheses, the counterexamples that refuted them, and the corrections. Corrections are
recorded in two ways:
- **Addenda.** The audit of #106–#114 added a dated addendum at the end of each entry it
  corrected, with a note under the entry's title.
- **Revisions in place.** Since the owner's review, a refuted or narrowed claim is
  revised where it stands. The corrected statement replaces it, and the earlier wording
  is kept beside it, marked *Before*, with the counterexample and a pointer to the entry
  that found it. The synthesis's lease claims were the first so revised. Every claim
  the audit's addenda refute or narrow, in every entry from #108 to #114, is now revised
  in place too, and each entry's note under its title says so. The addenda stay, as the
  record of how each correction was found.

Nothing is deleted. The earlier wording stays in the text, and in the history.

`docs/SEMANTICS.md` keeps the current theory, stated cleanly:
- §10.1's corrections (#107);
- §10.2, evidence (#113);
- §14, the run model (#115): events, holds, seals, drafts, versions and leases.

Each guarantee in §14 is classed as holding by construction, holding under named
assumptions, or only detected, with the test that pins it. §14 is not part of the
contract; it is what `wend._experimental` would have to keep before any of it leaves
there.

## Status vocabulary

The entries label each statement. The labels map onto four statuses:

| status | labels in the entries | meaning |
|---|---|---|
| proven under explicit assumptions | **[Proven]** | an argument written out; its assumptions named in the entry; not machine-checked |
| empirically observed | **[Measured]**, **[Fact]** for documented interface behaviour | a test, probe or measurement, on Linux 6.18 and ext4 as root unless stated |
| plausible but unproven | **[Conjecture]**, **[Interpretation]** | argued, or evidence short of proof |
| refuted | **[Refuted]**, **[Narrowed]** in addenda | a counterexample, named, and what replaced the claim |

## The entries, in conceptual order

Each row lists the PR, the entry, the commits that carry its research and its audit
addendum, and its tests. Every PR has landed on master as one squash commit, titled with
its number, in the order #105, #107, #106, #108, #109, #110, #112, #113, #114, #115,
#111. The commits named here are on the PR branches, which are kept.

> *Before:* "All branches are unmerged." Revised when the stack landed.

| # | entry | PR | commits | tests and scripts |
|---|---|---|---|---|
| 0 | [Future Paths, taken stock](2026-10-21-future-paths-stock.md) | #105 | b7d2345 | `scripts/2026-10-21-capability-probe.py` |
| 0 | [Symbolic overlap](2026-10-20-overlap-research-89.md), [choices](2026-10-21-choices-semantics-89.md) | merged | | `tests/overlap_test.py`, `tests/choices_semantics_test.py` |
| 1 | [Typed path families](2026-10-21-typed-path-families.md) | #106 | 2b3f392, addendum 520f21e | `experiments/typed/`, `tests/{typed,patterns,obligations}_test.py` |
| 2 | [Declarations are obligations](2026-10-22-declarations.md), and SEMANTICS.md §10.1 | #107 | 04fa23f, 1643cd1 | `tests/contract_test.py`, `conditions_test.py` |
| 3 | [What a program knows](2026-10-22-knowledge-states.md) | #108 | 70db979, addendum 8c6de83 | `tests/knowledge_test.py` |
| 4 | [Families before binding](2026-10-22-symbolic-families.md) | #109 | 6ac4d38, tests and addendum ea44af0 | `tests/families_test.py`, `scripts/2026-10-22-families-demo.py` |
| 5 | [When two strings name one file](2026-10-22-aliasing.md) | #110 | f55be8e, addendum 4dfa278 | `tests/aliasing_test.py` |
| 5′ | `Creatable` through a dangling link (no entry; aliasing addendum A.2) | #111 | 355ea00 | `tests/conditions_test.py`, and the last row of `confined_test`'s moves |
| 6 | [Running the plan confined](2026-10-22-confined-runs.md) | #112 | 5619102, bc845dc, d73b5fb, addendum 4aa656a | `tests/confined_test.py`, `scripts/2026-10-22-confined-demo.py` |
| 7 | [Confinement is not consistency](2026-10-22-confinement-is-not-consistency.md) | #112 | d73b5fb, addendum 4aa656a | `tests/held_test.py` |
| 8 | [The typed core](2026-10-22-typed-core.md) | #113 | df1ca7c, 5672297, addendum 95ab9ee; §6 revised in place, 653f457 | `experiments/typed_core/`, `tests/events_test.py` |
| 8′ | [Evidence is not a path](2026-10-22-evidence.md): the addendum's two holes closed | #113 | 01c8c27, 03f1852 | `tests/evidence_test.py`, `experiments/typed_core/soundness.py`, `check.py` |
| 9 | [Freshness, publication and consistency](2026-10-22-publication-and-consistency.md) | #114 | 9bc511c, addendum 51cc4a0 | `tests/{fresh,publish,consistency,lifecycle,durability}_test.py` |
| 10 | [Synthesis](2026-10-22-synthesis.md) | #115 | 164eac2, 4f1bf41, and the leases commit (revisions in place); §3's immutability revised, 1a230d1 | `experiments/synthesis/`, `tests/synthesis_test.py` |
| 11 | [Leases](2026-10-22-leases.md) | #115 | 8b2caa0; §3.4 revised for Linux 7.0, 43c675d | `tests/leases_test.py`, `experiments/mutation/mutants.py` |
| 12 | [Drafts](2026-10-22-drafts.md) | #115 | aa38be1; Yama answered, a60bb7e | `tests/drafts_test.py`, `experiments/mutation/mutants.py` |
| 13 | [Consolidation: a plan](2026-10-22-consolidation.md) (a proposal) | #115 | a60bb7e | none: nothing in it is done |
| 14 | [Relations between families, and effects across a pipeline](2026-10-24-relations-and-effects-118.md), and SEMANTICS.md §15 (after 0.3.0) | #118 | d5b2779 | `tests/{relate,effects}_test.py` (the schedule's oracle), `bench/effects.py`, `examples/pipeline_effects.py` |
| 15 | [A more precise relation](2026-10-25-relation-precision-119.md): anchors, depth, names changed by binding | #119 | b4a212f; corrected by #120 and #124 | `tests/relate_test.py` (two property tests), `tests/overlap_test.py`'s pool |
| 16 | [What a requirement relies on](2026-10-25-obligations.md): obligations over the effect graph, and a deferred head is itself; addendum §7 on paths given as existing, reads and listings | #120, #121 | 23ecda4; addendum 2dcfbfe | `tests/effects_test.py` (the disk oracle, in order and by stages), `tests/relate_test.py` (paths below one deferred head) |
| 17 | [Fewer unknowns on realistic pipelines](2026-10-25-realistic-precision.md): segments that differ, names written out by their split, parent conflicts a precondition rules out | #122 | 809cfc1 | `bench/effects_corpus.py`, `tests/effects_test.py` (stages commute on disk), `tests/relate_test.py` |
| 18 | [Deferred operations with known anchors, and parents written out](2026-10-25-deferred-operations.md): what pathlib guarantees of `parent`, `relative_to` and joins | #123 | 7266a22; corrected by #124 | `tests/relate_test.py` (anchors, the cases of a parent) |
| 19 | [A name defaulted differently on each side is two texts](2026-10-25-defaults-in-views.md): a soundness fix to the names of views and of a parent's SubPath (0.4.0 affected) | #124 | 2c287b4 | `tests/relate_test.py` (both sides' defaults, bound and unbound), `tests/effects_test.py` |
| 20 | [A field in either role, for builtin values](2026-10-25-builtin-roles.md): segment-valued and formatted fields cancel under `builtin_values=True` | #125 | on the PR's branch | `tests/relate_test.py` (both modes of `builtin_values`), `tests/effects_test.py` (the disk oracles with it), `bench/effects_corpus.py --builtin` |

## How the discoveries build on one another

1. **A path template is a set of paths.** Symbolic overlap (#89) decides, without
   binding, whether two templates can name one path: yes, no or maybe. It is sound for
   NO relative to wend's rendering rules. Everything later that says two families
   "cannot interfere" inherits that.
2. **A declaration is an obligation (#106, #107).**
   - #106 read one declaration three ways: as a type, as an effect, as an obligation.
   - Its type reading started from capabilities. The owner's qualification ("must not
     silently mean 'this path exists'") made it an obligation instead: three things,
     *declared*, *checked* and *known*, are kept apart.
   - Effects (`verbs`) are a function of the declaration, and not a monotone one. That
     limits what any inclusion-ordered type can certify.
3. **Knowledge is a dataflow (#108).**
   - A check *learns* atoms, and a declared mutation *forgets* those it may end: the
     path, above it, below it, and creatability beside it.
   - It is sound, by induction, under a closed world and lexical identity.
   - The proof found a gap the tests could not: the sibling's creatability.
4. **Over families, before binding (#109).**
   - Must-equal (a conjecture with evidence) and prefix cancellation (proven) carry
     the dataflow to unbound templates.
   - Independence of adjacent steps follows from no-overlap.
   - The audit found the tests checked only soundness, never precision. Fixed in the
     addendum's commit.
5. **Identity breaks lexical identity (#110).**
   - On disk, two strings name one file through symlinks, `..`, mounts and case folding.
     String-keyed knowledge held a false fact in 189 of 1,663 aliased pipelines.
   - Keying each atom by what its check reads (its read set) repairs it.
   - Alias-free runs make strings sound again, and `openat2` can enforce alias-freedom
     at the moment of use.
6. **Confinement is of paths, not objects, nor of time (#112).**
   - A confined executor runs the plan beneath its root. The tested path attacks never
     escaped.
   - Two objects at confined names did: a hard link to an outside file, and a FIFO. The
     fix was to judge objects on their descriptors.
   - The five properties separated: resolution, identity, freshness, consistency, and
     durable facts of held objects. Confinement gives only the first.
7. **Three guarantees, three types (#113).**
   - It was true: `Checked` and `Confirmed`, events. Which object: `Held`. It stays true:
     `Sealed`.
   - The encoding moved into the core cheaply at runtime.
   - The audit found the types claim more than the checks in two ways: events carry
     declared atoms, and derived paths stay events. ty 0.0.90 loses multi-condition
     declarations.
   - Both holes were closed on the same PR (evidence entry). `Checked[C, K]` and
     `Confirmed[Q, K]` are records of one phase's check, not paths, and nothing derived
     from the path inherits them. ty's loss is scoped to inline declarations.
   - A third hole was found when SEMANTICS.md §14 was checked against the code: a
     `Held` typed as a file could be a directory swapped in between the check and the
     hold. The hold now judges the kind on its descriptor (typed-core §6).
8. **Freshness is detection, publication is a capability, consistency needs help
   (#114).**
   - No observer sees a writer through dirty mapped pages, until writeback.
   - A draft is invisible until published, and survives a crash only with both syncs.
   - A held generation is coherent only if nothing writes into it.
9. **The synthesis.**
   - Exchange-and-validate fails for three writers: consensus number 2.
   - A store of versions claimed by `RENAME_NOREPLACE` is a universal construction over
     sticky registers.
   - Pinned reads verified against a manifest read only committed bytes.
   - Immutable members refuse every writer tried.
   - Read leases *exclude* the writer no observer can see, so a coherent snapshot of
     several inputs needs either cooperation or exclusion, not cooperation alone.
   - Every guarantee is classed: by construction, under named assumptions, or
     impossible without cooperation or exclusion (synthesis §6).
10. **What a lease excludes (leases entry).**
    - A truncation by `O_RDONLY | O_TRUNC` does not break a read lease. Under an unbroken
      lease the size can only fall, so a recorded size detects it.
    - `/proc` files are leased and change anyway. Only tested filesystems are allowed.
    - A lease taken in-process makes the host the owner of its break signal. A helper
      that takes the leases and exits leaves them owned by no living process.
    - Proposition L: a leased copy is one version, under five named assumptions.
11. **Who can reach an unpublished output (drafts entry).**
    - A draft is nameless, not private. The processes that may inspect the writer can
      read, write and name it: its uid while it is dumpable, and root. Taking its
      descriptor needs attach as well, which Yama narrows to ancestors (and root).
    - A store's hidden version has a name, so dumpability does not guard it. The kernel
      makes each version name hold one directory; that it is the writer's is detected
      at the claim, never prevented.
    - What ordinary users have, and what needs privilege, in one table (drafts §4).
12. **From one answer to three (#118).**
    - Overlap answered one question: can two families meet? `relate` answers three,
      same, inside and contains, and each always, sometimes, never or unknown, so a
      dependency can be certain and not only possible.
    - Prefix cancellation (#109) is what makes "always" provable under one root, and the
      public `wend.effects` graph is built on it.
    - Two answers the engine gives are not yet proofs: a NO for "strictly below" when the
      inner side may render `..`, and a witness of two remainders that binds no prefix
      parameter.
13. **Identity is not freshness (#120).**
    - A fact of one spelling is a fact of another when `relate` proves them the same
      string on every run; whether it still holds is a separate question, answered by
      what may run in between.
    - `EffectGraph.obligations()` keeps a fact until a step that may run in between
      declares a change that may touch it, under three named assumptions, and a disk
      oracle checks what it discharges and refutes, in order and by stages.
    - Comparing it with the experimental analysis found a gap in `relate`: an expression
      under a deferred head was not always itself.

## Discoveries not to lose

| discovery | status | where |
|---|---|---|
| A writer through an already dirty page of a shared mapping changes a file with no change of time, size or event; change-and-change-back leaves no trace at all | observed; bounded by writeback (the first write after it moves `ctime`) | #114 §1, addendum A.1; synthesis §4 |
| No observer can establish a snapshot of files others write in place | proven, for observers (indistinguishability) | #114 §3 |
| A read lease is refused while any writer exists, the dirty-mapping writer included; leases give the snapshot by exclusion | observed; proven under L1–L5 with a size check (proposition L) | synthesis §4.2; leases §4; `test_a_read_lease_excludes_the_writer_no_observer_sees`, `tests/leases_test.py` |
| `open(O_RDONLY \| O_TRUNC)` empties a leased file without breaking the lease | observed on ext4 and tmpfs; explained by the source (`handle_truncate`) | leases §3.1 |
| `F_SETLEASE` makes the caller's process the owner of its break signal; no in-process order of calls avoids it | proven from the source; observed | leases §3.2 |
| Leases taken by a helper that exits survive it, and their breaks signal no one | observed | leases §3.3 |
| The kernel leases `/proc` files, which change under the lease | observed on 6.17 and 6.18; from 7.0 the kernel refuses them (leases are opt-in per filesystem), read in the source | leases §3.4 |
| Path confinement (`openat2`) is not object confinement: hard links and FIFOs pass every path check | observed | confined runs §2; aliasing addendum A.1 |
| `RESOLVE_NO_XDEV` guards the boundary as well as identity | observed (mutant escapes) | confined-runs addendum A.1 |
| String-keyed knowledge is sound exactly on alias-free runs | proven, tested | aliasing §5 |
| Exchange-and-validate is not compare-and-swap: two writers end right but show the loser; three lose updates in 126 of 420 schedules | proven by exhaustive enumeration; observed on the kernel | synthesis §2 |
| A claim by `RENAME_NOREPLACE` is a sticky register; a store of versions is a universal construction, lock-free | proven (cited theory), observed | synthesis §2.2–§3 |
| A pinned directory pins names, not contents | observed | synthesis §3 |
| `FS_IMMUTABLE_FL` refuses every write tried, including through a mapping made before the flag (`SIGBUS`) | observed and tested; the mechanism read in ext4's source | synthesis §3 |
| A `Sealed` copy cannot change, but can be torn: a state the file never had | observed (244 of 300) | synthesis §4.3 |
| An unpublished `O_TMPFILE` draft can be read, written, named and taken by another process through `/proc/<pid>/fd` | observed (same uid unless non-dumpable; root always; never another unprivileged uid; under Yama scope 1, the same uid takes it only as an ancestor) | synthesis §5; drafts §2, §7 |
| A process that changed its uid is non-dumpable by default | observed (`fs.suid_dumpable` 0) | drafts §2 |
| A store's hidden version can be claimed, or replaced, by any process that may rename in the store's directory, even at mode 0700; a sticky directory stops other uids | observed | drafts §3 |
| Event types carried every declared atom, and paths derived from events stayed events | observed in both checkers and at runtime; both closed | typed-core addendum A.1–A.2; evidence §1–§2 |
| A held object's kind must be judged on its descriptor: a directory is confined, so judging confinement there does not judge the kind | observed; closed | typed-core §6 (revised) |
| A union's verbs are not those of its alternatives | observed | SEMANTICS.md §10.1; declarations §3 |
| Containment holds for every rendered path only lexically | refutes the earlier statement | declarations §3; SEMANTICS.md §10.1 |
| A declared path may name a directory: a graph that links only equal paths calls a writer of `{root}/raw` independent of a reader of `{root}/raw/{day}.csv`, and schedules them together | observed; fixed before merging; pinned by an oracle over rendered paths | relations §8.1; `test_order_and_stages_hold_for_every_rendered_run` |
| A creation's missing parents are part of its effect: `Creatable` judges the nearest existing ancestor, so another step's `mkdir -p` changes what the check finds | read in `_creatable`; ruled on by the owner; modelled before merging | relations §8.5; `test_parents_a_creation_may_make` |
| A NO for "strictly below" does not rule out lexical nesting: `/x/..` is inside `/x`, and no segment parameter renders `..` | found by reading the construction; pinned | relations §5; `test_dotdot_makes_a_path_lexically_inside_and_is_never_ruled_out_by_shape` |
| Durability needs the file's sync *and* the directory's | observed, in one crash model (ext4, loop device) | #114 §2 and addendum A.3 |

| An absent sync permits loss and does not promise it: a crash test may require only the guaranteed outcome, the permitted set, or that a loss is possible | argued; measured stable under writeback load on this machine, which is no guarantee | publication §2 (revised); `durability_test` |
| A test's cleanup must not share state with the run it checks: a plain run may delete its own root | observed (a rare generated case) | families A.1′; this index, "An intermittent failure, isolated" |
| Runs of a mutation harness must not share a property-testing database, and a kill by a property under one seed can be luck | observed (three kills held under 1–2 of 5 seeds) | this index, "The harness checked against itself" |
| Checking the specification against the code, claim by claim, finds what the tests do not: a judgement the text claims and nothing makes, a cited test that does not exist, a measured row that rests on a probe | observed | this index, "The specification checked against the code" |

## Hypotheses that were refuted, and what replaced them

| believed | refuted by | replaced by | where |
|---|---|---|---|
| a declared atom is a capability the path has | the owner's qualification | declarations are obligations; declared, checked, known | declarations §1 |
| a string names a file | 189 aliased pipelines with false knowledge | facts keyed by read set; alias-free runs | aliasing §1–§5 |
| one key per path suffices | three counterexamples (final symlink, below a file, creation) | per-atom read sets | aliasing §3 |
| a confined run reads and writes nothing outside | a hard link, a FIFO | object judgement on the descriptor | confined runs §2 |
| "the failure is closed" under confinement | the same two | the same | aliasing addendum A.1 |
| `known()` is a fact about now | the owner's review | knowledge conditional on the closed world | typed-core §5 and addendum A.6 |
| a checked event's type is the atoms checked | `out.check()` typed with post atoms | `Checked[C, K]` and `Confirmed[Q, K]`, one phase each, records not paths | typed-core addendum A.1; evidence §1–§2 |
| a `Held` typed `IsFile` is a regular file while it is open | a directory swapped in between the check and the hold | the kind judged on the descriptor | typed-core §6 |
| writes through a mapping made before the immutable flag are tested | the test mapped only after the flag | the test maps before it too, clean and dirty | synthesis §3 |
| a mutant killed by a property in one run is killed by it | three kills that held under 1–2 of 5 seeds | killers that held under every seed; one seed and an empty database per run | this index, "The harness checked against itself" |
| ty agrees with Pyright except one corner | `requires(Exists, Readable)` is `Never` in ty | recorded; precision gap | typed-core addendum A.3 |
| exchange with `expect` prevents lost updates | three writers | `Store` (claims) | synthesis §2 |
| holding a generation's directory reads one generation | in-place rewrite through the held directory | manifests, immutability, leases on reclaim | synthesis §3 |
| `Sealed` is a snapshot of the input | torn copies | leased copies; committed digests | synthesis §4.3 |
| a coherent multi-file snapshot needs the writers' cooperation | read leases | cooperation *or* exclusion with ownership or `CAP_LEASE` | synthesis §4.2 |
| any truncation breaks a read lease (synthesis L1) | `O_RDONLY \| O_TRUNC` | a size recorded with the leases | leases §3.1 |
| a filesystem that grants leases excludes every change | `/proc/uptime` | `LEASABLE`: tested filesystems only | leases §3.4 |
| `F_SETSIG` to `SIGURG`, then `F_SETOWN` 0, keeps break signals from the host | a writer between `F_SETLEASE` and `F_SETOWN` | a helper process takes the leases | leases §3.2–§3.3 |
| leases need privilege | `nobody` leases its own file | ownership or `CAP_LEASE` | leases §5 |
| a draft is unnameable until published | `linkat` through `/proc/<pid>/fd` | other uids only, or a non-dumpable run; and the same processes can read and write it | synthesis §5; drafts §2 |
| nothing of an unclaimed store version is ever visible | the hidden directory, listed and readable (mode 0755) | private while filled (0700); nothing visible under a version's name | drafts §3 |
| the store's claim is the writer's, given the protocol | another process claims or replaces the hidden draft | identity checked at the claim: detected, not prevented | drafts §3 |
| a derivation records what the step used | a read after the entry observation | reads recorded and checked at exit | synthesis §5 |
| the families tests show the analysis knows what it should | a "learn nothing" mutant passed | an oracle of the worked pipeline | families addendum A.1 |

| a link holds when two declared paths are equal | a writer of a directory and a reader inside it, staged together | every link asks same, inside and contains: a declared path covers what lies below it | relations §8.1 |
| `order()` is None exactly when `cycles()` finds one | a cycle through a hazard | one relation for both; `cycles(certain=True)` for the unavoidable ones | relations §8.2 |
| every step makes missing parents idempotently, so siblings in a new directory never interfere | the owner: a `Creatable` check, an exclusive `mkdir`, or a step requiring the parent | each declared and modelled; idempotence assumed only for parents not declared; `existing=` bounds what may be missing | relations §8.5 |
| `with_suffix` on `{day}.csv` names the same path as `{day}.parquet` | `day = ""`: `.csv` has no suffix, so it renders `.csv.parquet` | `"sometimes"`, as wend's deferral of the operation implies | relation precision §3 |
| an overlap witness of two remainders is a witness of the two paths | a value for a parameter shared with the prefix that does not render there | a full binding that renders both and shows the relation | relations §5 |
| each crash row's observed outcome can be asserted | an absent sync permits loss, never promises it | guaranteed, permitted and demonstrated outcomes | publication §2 |
| a failure that passes on rerun is no defect | a rare generated case, found again in a third full run | the harness fixed and the case pinned | families A.1′ |

## Gaps in the record

These are the gaps that remain after the audit.

- **Mutation harnesses and measurement scripts are not committed.**
  - The kill tables of #108–#114 come from scripts in the session's scratch space.
  - The tests that kill each mutant are committed; the harnesses that made the mutants
    are not.
  - *Addressed:* `experiments/mutation/mutants.py` is committed, with 65 mutants, every
    one an entry recorded:
    - the leases and drafts entries';
    - the run's kind judgement (typed-core §6), and the typed core's three event
      mutants;
    - the confined runs' ten;
    - the knowledge model's four;
    - the families entry's eleven, one expected to survive (the bounded made-parents
      reading, families addendum A.1);
    - the aliasing entry's ten rows, as eleven mutants (one row names two);
    - the publication entry's seven, and the `collect` defect's.

    It guards against the defects the audit found in the earlier harnesses, and
    against two more it found itself:
    - a mutant's stale bytecode, run by every later import (drafts §5);
    - a Hypothesis example database shared across runs, and a fresh seed each run
      (below, "The harness checked against itself").

    It runs in a worktree of its own, since it edits sources in place. At 86e6141 all
    65 met their expectation, in 32 minutes.
  - The precision measurements of #108 and #109 can be rerun only through the tests'
    generators.
- **Privileged evidence was not run in CI.** *Addressed on #115.* These skipped
  without root, loop devices, mounts or `CAP_LINUX_IMMUTABLE`:
  - the crash model;
  - mount aliasing;
  - the confined mount moves;
  - the immutable tests;
  - now also the drafts and leases tests that act as other users.

  Several mutant kills depend on them. Each is now marked `privileged`
  (`tests/conftest.py`): 29 when the marker was added, 31 now that the crash model has
  two demonstrations. An unprivileged run lists every one that did not
  run, under "privileged evidence", instead of a bare count of skips. A `privileged` job
  in `.github/workflows/test.yml` runs them as root with `WEND_REQUIRE_PRIVILEGED=1`,
  under which a privileged test that skips fails.
- **The run model's specification.** *Addressed:* SEMANTICS.md §14. Derivations and
  `invalidated()` are described only in the publication entry and docstrings.
- **Untested here, for want of kernel support:**
  - case folding (no `CONFIG_UNICODE`);
  - fs-verity (no `CONFIG_FS_VERITY`);
  - reflinks (ext4).
- **Open questions, gathered:**
  - names under leases (synthesis §8);
  - a persistent lease helper; xfs and btrfs; whether L3 is complete; reporting the
    `O_TRUNC` gap (leases §8);
  - a warning for shared stores; a draft written by a helper; same-uid manifest
    integrity (drafts §7);
  - exchange between shared names (§2.2);
  - the unbounded made-parents case (families addendum A.1);
  - must/may/disjoint as distinct rules (families addendum A.4);
  - whether some operation on evidence could keep it (evidence §9);
  - runs across bindings over one tree (families addendum A.4);
  - an unprivileged writer's hard-link attack (confined-runs addendum A.4).

## An intermittent failure, isolated

A full-suite run at #115's head reported "1 failed, 1181 passed". A rerun passed. The
owner asked for it to be isolated, not dismissed: a rerun shows a failure is not always
reproducible, not that nothing is wrong. That matters most in a programme about
concurrency.

1. **The first failure's record was lost.** The background script kept only the summary
   line, so the test name, traceback and Hypothesis example were never saved. Every run
   since then keeps its full log and pytest's `-rf` report.
2. **Isolation.** Each worktree's environment imports its own sources (checked for all
   seven), so no run executes another worktree's code. Two hazards were found, and runs
   were sequenced so they cannot meet:
   - the mutation harness edits sources in place, so it runs only in a worktree of its
     own;
   - kernel-global state is shared by any concurrent runs: writeback, CPU, loop devices,
     the mount table.
3. **Hypotheses, each tested.**
   - **The crash model's exact assertions.** They were semantically wrong (an absent
     sync permits loss, and does not promise it) and are redesigned (publication
     entry §2). Measured under a writer pushing writeback throughout, every outcome was
     unchanged: they were not the cause.
   - **Hypothesis's default 200 ms deadline.** It remains on 8 property tests of
     `frame_gaps_test.py`, from master: a latent risk under load. Not observed failing.
4. **Found in the third of three further full runs:**
   `families_test::test_what_the_analysis_knows_holds_and_what_it_refutes_fails`.
   - Once drawn, the case replayed from Hypothesis's database and failed every time.
   - Root cause: the family `up` can render to the run's root. A plain run then deletes
     the root and creates a file in its place, and the test's own temporary-directory
     cleanup failed on that file.
   - The property's assertions held. Not timing, and not the system under test: a rare
     generated case, and a harness that shared its cleanup with the run.
   - Fixed on #109, where the test lives. The case is pinned with `@example`; it fails on
     the earlier harness and passes now. Families entry, A.1′.

## The specification checked against the code

SEMANTICS.md §14 names a mechanism and a test for each guarantee. Before it was
committed, each statement was checked against the code it describes and the test it
cites. The tests had passed throughout. What this found, they could not.

1. **A soundness hole (#113).**
   - **The claim.** §14.1 said a held input is judged on its descriptor: a regular file
     with one name.
   - **The code.** The hold judged confinement there, and a directory is confined. So
     the kind rested on the earlier check of `File`, made through another open.
   - **The counterexample.** A directory swapped in between the check and the hold was
     held, and handed to the body typed as a file. On #114 and #115 the step failed
     anyway, by accident: reading the directory at entry raised `EISDIR`, or, with a
     lease, the lease was refused as `Unleasable`.
   - **The fix,** on #113: the hold judges the kind on its descriptor. The test is
     deterministic: the swap is made inside the check, so the interleaving that matters
     runs every time. It fails on the earlier code. A mutant that removes the judgement
     is killed by it alone. Typed-core §6 is revised in place.
2. **A cited test that did not exist.** §14.2 cited `input_rewritten_after`. The test is
   `events_test::test_known_is_blind_to_another_writer`.
3. **A measured row that rested on a probe.**
   - Synthesis §3's table gave a write through a mapping made before the immutable flag
     as `SIGBUS`, under "[Measured]" and the name of a test. The test mapped only after
     the flag; the row came from a probe in the session.
   - The test now maps before the flag too, with the page clean and dirty.
   - The mechanism, a conjecture, was read in Linux 6.18's ext4 source, and is now a fact
     about ext4.
4. **An overstatement, measured elsewhere.** The draft matrix's "takes" was measured
   without Yama. CI's kernel (Yama scope 1) refuses the same uid's `pidfd_getfd` unless
   it comes from an ancestor. The drafts entry recorded it; §14.4, the synthesis and
   this index did not. All three now do.
5. **The draft of §14 was itself wrong once.** It said `Run` does not refuse a `..` in a
   spelling. Lexical containment refuses it; what remains is case folding. Running it
   found this.
6. **Imprecisions, now stated in §14:**
   - a `Makes` output's directories are made at entry, and stay if the step fails;
   - outputs are published one after another, not together, and a failed
     postcondition leaves them published;
   - `Held.used` records reads through `read()`, not through the descriptor;
   - `replace` and `exchange` first link the draft under a hidden name, which a listing
     shows;
   - confinement's cited test runs #112's executor, which shares `Confined` with `Run`;
     the pipeline test runs `Run` itself.
7. **Found on the way, in #114's entry** (publication §2):
   - its in-place revision had been inserted inside the crash table, stranding the full
     protocol's row after it;
   - the interpretation under the table said publication was "old or new, never torn",
     while two of its rows show a name leading to the new object with 0 bytes. The
     atomicity is of the name, not the contents, and the statement is narrowed so;
   - two cited test names were stale. Every test name the journals cite now exists, on
     every branch of the stack, checked by a search, but one: the audit's record of a
     test since renamed, which now names what it became.

## The harness checked against itself

The first full run of the 65 mutants, at 267d496, met 62 expectations. The three
misses were killed, but not by the tests their entries recorded:

| mutant | recorded killer | it rejected the mutant under | a test that rejected it under every seed tried |
|---|---|---|---|
| families: prefixes cancelled under different heads | the soundness property | 1 of 5 seeds | the commutation property (5 of 5) |
| families: relation is coincidence only | the soundness property | 2 of 5 | the commutation property (5 of 5), and two unit tests |
| aliasing: a final symlink not followed | the known-atoms property | 2 of 5 | kernel agreement (5 of 5) |

Each seed was run alone, with an empty example database. The mutants are the harness's
own versions; the entries' scripts were not kept, so their mutants may have differed.

1. **A kill by a property in one run can be luck.** The entries recorded each kill from
   one run. The families and aliasing tables are revised in place.
2. **The runs shared state.** Hypothesis keeps the failing examples it finds in
   `.hypothesis/` in the worktree, and replays them in later runs. So a failure found
   under one mutant was replayed under the next. A verdict could depend on the order
   of the mutants, and the first run's 62 kills may have had that help. The first seed
   experiment had the same defect (a failure in 0.5 s was a replay); it was redone with
   a database of its own per run.
3. **The fix.** Each run of the tests now uses a `mutation` Hypothesis profile
   (`tests/conftest.py`): no example database, and no shrinking or explaining of a
   failure, which only a person reads. With seed 0, verdicts are reproducible and
   independent. The three mutants name the tests that rejected them under every seed.
4. **A hang the shared database had hidden.** The first rerun stopped at "creation not
   exclusive": its run of `confined_test.py` passed the harness's 900-second timeout,
   with shrinking and explaining off too. The test process was in the kernel's
   `wait_for_partner`. The writer's `fifo` move plants a FIFO at a name a step will
   create, and without `O_EXCL` the open waits for ever for a reader. Under the shared
   database another property's failure had been replayed first, and this schedule was
   never drawn. The never-outside property now runs each pipeline under a deadline, on
   #112 (confined-runs A.5), and a run that hangs is reported as that mutant's failure
   instead of ending the harness.

The final run, at 86e6141: all 65 mutants met their expectation, in 32 minutes. Two
survive, as expected, and one ends the test run by `SIGIO`, as expected.

Since #111 landed, a third survives, as expected: the aliasing creation key, which
aliasing addendum A.2 argues is equivalent under #111's `Creatable`. On the landed tree
all 65 mutants meet their expectation.

## Reproducing the evidence

The evidence is of four kinds, and each runs in a different place:

| kind | marked | where it runs |
|---|---|---|
| portable tests | none | every CI job, any platform |
| Linux tests | `linux` | the CI test jobs (Linux); skipped elsewhere |
| privileged tests | `privileged` | the CI `privileged` job, as root; listed as not run elsewhere |
| measurements by script | none (not tests) | by hand, with the commands below; their figures are dated in the entries that cite them |

The scripts are:
- the benchmarks and probes of each entry;
- `experiments/typed_core/check.py` (both checkers against the markers);
- the mutation harness.

None of them runs in CI. A figure from one is **[Measured]** on the machine and date its
entry names, not continuously checked.

**Kernels.** The tests have run on three: Linux 6.18 here, 6.17 on CI, and 7.0 on CI's
newer runner image. Mechanisms were read in the 6.18, 6.19 and 7.0 sources. GitHub moves
its image without notice, so two jobs of one run can meet different kernels. That
happened at 92800a2: `test (3.15)` ran on 6.17 and passed; `test (3.14)` ran on 7.0,
where a test that had asserted the kernel leases `/proc` files failed, because 7.0 does
not. The outcome is fixed by the kernel, so it is not a flake. Each run's summary names
its kernel and Yama scope ("privileged evidence"), and the test now accepts either
kernel's answer, but no other (leases §3.4).

```sh
uv run pytest                                      # everything; privileged tests skip without root
uv run python experiments/typed_core/check.py      # both checkers against the E markers
uv run python experiments/synthesis/pipeline.py    # the pipeline and its scenarios
uv run python experiments/mutation/mutants.py      # each mutant against its named tests,
                                                   # seed 0, a fresh example database each:
                                                   # run it in a worktree nothing else uses
uv run python docs/journal/scripts/2026-10-22-families-demo.py
uv run python docs/journal/scripts/2026-10-22-confined-demo.py
```
