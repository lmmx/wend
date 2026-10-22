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
  that found it. The synthesis's lease claims are the first so revised.

Nothing is deleted. The earlier wording stays in the text, and in the history.

`docs/SEMANTICS.md` keeps the current theory, stated cleanly. So far one result has
moved from the journals into it, §10.1's corrections (#107). The rest of the theory
(events, holds, seals, drafts, versions, leases) is still research. It would need its
own specification before any of it leaves `wend._experimental`.

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
addendum, and its tests. All branches are unmerged.

| # | entry | PR | commits | tests and scripts |
|---|---|---|---|---|
| 0 | [Future Paths, taken stock](2026-10-21-future-paths-stock.md) (on #105's branch) | #105 | b7d2345 | `scripts/2026-10-21-capability-probe.py` |
| 0 | [Symbolic overlap](2026-10-20-overlap-research-89.md), [choices](2026-10-21-choices-semantics-89.md) | merged | | `tests/overlap_test.py`, `tests/choices_semantics_test.py` |
| 1 | [Typed path families](2026-10-21-typed-path-families.md) (on #106's branch) | #106 | 2b3f392, addendum 520f21e | `experiments/typed/`, `tests/{typed,patterns,obligations}_test.py` |
| 2 | [Declarations are obligations](2026-10-22-declarations.md), and SEMANTICS.md §10.1 | #107 | 04fa23f, 1643cd1 | `tests/contract_test.py`, `conditions_test.py` |
| 3 | [What a program knows](2026-10-22-knowledge-states.md) | #108 | 70db979, addendum 8c6de83 | `tests/knowledge_test.py` |
| 4 | [Families before binding](2026-10-22-symbolic-families.md) | #109 | 6ac4d38, tests and addendum ea44af0 | `tests/families_test.py`, `scripts/2026-10-22-families-demo.py` |
| 5 | [When two strings name one file](2026-10-22-aliasing.md) | #110 | f55be8e, addendum 4dfa278 | `tests/aliasing_test.py` |
| 5′ | `Creatable` through a dangling link (no entry; aliasing addendum A.2) | #111 | 355ea00 | `tests/conditions_test.py` on its branch |
| 6 | [Running the plan confined](2026-10-22-confined-runs.md) | #112 | 5619102, bc845dc, d73b5fb, addendum 4aa656a | `tests/confined_test.py`, `scripts/2026-10-22-confined-demo.py` |
| 7 | [Confinement is not consistency](2026-10-22-confinement-is-not-consistency.md) | #112 | d73b5fb, addendum 4aa656a | `tests/held_test.py` |
| 8 | [The typed core](2026-10-22-typed-core.md) | #113 | df1ca7c, 5672297, addendum 95ab9ee | `experiments/typed_core/`, `tests/events_test.py` |
| 9 | [Freshness, publication and consistency](2026-10-22-publication-and-consistency.md) | #114 | 9bc511c, addendum 51cc4a0 | `tests/{fresh,publish,consistency,lifecycle,durability}_test.py` |
| 10 | [Synthesis](2026-10-22-synthesis.md) | #115 | 164eac2, 4f1bf41, and the leases commit (revisions in place) | `experiments/synthesis/`, `tests/synthesis_test.py` |
| 11 | [Leases](2026-10-22-leases.md) | #115 | this commit | `tests/leases_test.py`, `experiments/mutation/mutants.py` |

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
10. **What a lease excludes (leases entry).**
    - A truncation by `O_RDONLY | O_TRUNC` does not break a read lease. Under an unbroken
      lease the size can only fall, so a recorded size detects it.
    - `/proc` files are leased and change anyway. Only tested filesystems are allowed.
    - A lease taken in-process makes the host the owner of its break signal. A helper
      that takes the leases and exits leaves them owned by no living process.
    - Proposition L: a leased copy is one version, under five named assumptions.
   - Every guarantee is classed: by construction, under named assumptions, or
     impossible without cooperation or exclusion (synthesis §6).

## Discoveries not to lose

| discovery | status | where |
|---|---|---|
| A writer through an already dirty page of a shared mapping changes a file with no change of time, size or event; change-and-change-back leaves no trace at all | observed; bounded by writeback (the first write after it moves `ctime`) | #114 §1, addendum A.1; synthesis §4 |
| No observer can establish a snapshot of files others write in place | proven, for observers (indistinguishability) | #114 §3 |
| A read lease is refused while any writer exists, the dirty-mapping writer included; leases give the snapshot by exclusion | observed; proven under L1–L5 with a size check (proposition L) | synthesis §4.2; leases §4; `test_a_read_lease_excludes_the_writer_no_observer_sees`, `tests/leases_test.py` |
| `open(O_RDONLY \| O_TRUNC)` empties a leased file without breaking the lease | observed on ext4 and tmpfs; explained by the source (`handle_truncate`) | leases §3.1 |
| `F_SETLEASE` makes the caller's process the owner of its break signal; no in-process order of calls avoids it | proven from the source; observed | leases §3.2 |
| Leases taken by a helper that exits survive it, and their breaks signal no one | observed | leases §3.3 |
| The kernel leases `/proc` files, which change under the lease | observed | leases §3.4 |
| Path confinement (`openat2`) is not object confinement: hard links and FIFOs pass every path check | observed | confined runs §2; aliasing addendum A.1 |
| `RESOLVE_NO_XDEV` guards the boundary as well as identity | observed (mutant escapes) | confined-runs addendum A.1 |
| String-keyed knowledge is sound exactly on alias-free runs | proven, tested | aliasing §5 |
| Exchange-and-validate is not compare-and-swap: two writers end right but show the loser; three lose updates in 126 of 420 schedules | proven by exhaustive enumeration; observed on the kernel | synthesis §2 |
| A claim by `RENAME_NOREPLACE` is a sticky register; a store of versions is a universal construction, lock-free | proven (cited theory), observed | synthesis §2.2–§3 |
| A pinned directory pins names, not contents | observed | synthesis §3 |
| `FS_IMMUTABLE_FL` refuses every write tried, including through a mapping made before the flag (`SIGBUS`) | observed; mechanism conjectured | synthesis §3 |
| A `Sealed` copy cannot change, but can be torn: a state the file never had | observed (244 of 300) | synthesis §4.3 |
| An unpublished `O_TMPFILE` draft can be named by another process through `/proc/<pid>/fd` | observed (same uid unless non-dumpable; root always) | synthesis §5 |
| Event types carry every declared atom, and paths derived from events stay events | observed in both checkers and at runtime | typed-core addendum A.1–A.2 |
| A union's verbs are not those of its alternatives | observed | SEMANTICS.md §10.1; declarations §3 |
| Containment holds for every rendered path only lexically | refutes the earlier statement | declarations §3; SEMANTICS.md §10.1 |
| Durability needs the file's sync *and* the directory's | observed, in one crash model (ext4, loop device) | #114 §2 and addendum A.3 |

## Hypotheses that were refuted, and what replaced them

| believed | refuted by | replaced by | where |
|---|---|---|---|
| a declared atom is a capability the path has | the owner's qualification | declarations are obligations; declared, checked, known | declarations §1 |
| a string names a file | 189 aliased pipelines with false knowledge | facts keyed by read set; alias-free runs | aliasing §1–§5 |
| one key per path suffices | three counterexamples (final symlink, below a file, creation) | per-atom read sets | aliasing §3 |
| a confined run reads and writes nothing outside | a hard link, a FIFO | object judgement on the descriptor | confined runs §2 |
| "the failure is closed" under confinement | the same two | the same | aliasing addendum A.1 |
| `known()` is a fact about now | the owner's review | knowledge conditional on the closed world | typed-core §5 and addendum A.6 |
| a checked event's type is the atoms checked | `out.check()` typed with post atoms | none yet; proposal: split `Pre` and `Post` | typed-core addendum A.1 |
| ty agrees with Pyright except one corner | `requires(Exists, Readable)` is `Never` in ty | recorded; precision gap | typed-core addendum A.3 |
| exchange with `expect` prevents lost updates | three writers | `Store` (claims) | synthesis §2 |
| holding a generation's directory reads one generation | in-place rewrite through the held directory | manifests, immutability, leases on reclaim | synthesis §3 |
| `Sealed` is a snapshot of the input | torn copies | leased copies; committed digests | synthesis §4.3 |
| a coherent multi-file snapshot needs the writers' cooperation | read leases | cooperation *or* exclusion with ownership or `CAP_LEASE` | synthesis §4.2 |
| any truncation breaks a read lease (synthesis L1) | `O_RDONLY \| O_TRUNC` | a size recorded with the leases | leases §3.1 |
| a filesystem that grants leases excludes every change | `/proc/uptime` | `LEASABLE`: tested filesystems only | leases §3.4 |
| `F_SETSIG` to `SIGURG`, then `F_SETOWN` 0, keeps break signals from the host | a writer between `F_SETLEASE` and `F_SETOWN` | a helper process takes the leases | leases §3.2–§3.3 |
| leases need privilege | `nobody` leases its own file | ownership or `CAP_LEASE` | leases §5 |
| a draft is unnameable until published | `linkat` through `/proc/<pid>/fd` | other uids only, or a non-dumpable run | synthesis §5 |
| a derivation records what the step used | a read after the entry observation | reads recorded and checked at exit | synthesis §5 |
| the families tests show the analysis knows what it should | a "learn nothing" mutant passed | an oracle of the worked pipeline | families addendum A.1 |

## Gaps in the record

These are the gaps that remain after the audit.

- **Mutation harnesses and measurement scripts are not committed.**
  - The kill tables of #108–#114 come from scripts in the session's scratch space.
  - The tests that kill each mutant are committed; the harnesses that made the mutants
    are not.
  - Begun: `experiments/mutation/mutants.py` is committed, with the leases entry's ten
    mutants. It guards against the defects the audit found in the earlier harnesses. The
    earlier entries' mutants are to be moved into it.
  - The precision measurements of #108 and #109 can be rerun only through the tests'
    generators.
- **Privileged evidence is not run in CI.** These skip without root, loop devices,
  mounts or `CAP_LINUX_IMMUTABLE`:
  - the crash model;
  - mount aliasing;
  - the confined mount moves;
  - the immutable tests.

  Several mutant kills depend on them. They need a marker and one privileged job.
- **No specification of the run model.** Events, holds, seals, drafts, versions, leases
  and derivations are defined only in the journals and docstrings. SEMANTICS.md has
  none of them.
- **Untested here, for want of kernel support:**
  - case folding (no `CONFIG_UNICODE`);
  - fs-verity (no `CONFIG_FS_VERITY`);
  - reflinks (ext4).
- **Open questions, gathered:**
  - names under leases (synthesis §8);
  - a persistent lease helper; xfs and btrfs; whether L3 is complete; reporting the
    `O_TRUNC` gap (leases §8);
  - exchange between shared names (§2.2);
  - the unbounded made-parents case (families addendum A.1);
  - must/may/disjoint as distinct rules (families addendum A.4);
  - events that are not paths (typed-core addendum A.2);
  - `Pre`/`Post` split (A.1);
  - runs across bindings over one tree (families addendum A.4);
  - an unprivileged writer's hard-link attack (confined-runs addendum A.4).

## Reproducing the evidence

```sh
uv run pytest                                      # everything; privileged tests skip without root
uv run python experiments/typed_core/check.py      # both checkers against the E markers
uv run python experiments/synthesis/pipeline.py    # the pipeline and its scenarios
uv run python experiments/mutation/mutants.py      # each mutant against its named tests
uv run python docs/journal/scripts/2026-10-22-families-demo.py
uv run python docs/journal/scripts/2026-10-22-confined-demo.py
```
