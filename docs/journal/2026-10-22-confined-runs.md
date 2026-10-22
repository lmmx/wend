# 2026-10-22: Running the plan confined to its root (research)

[The analysis of path families](2026-10-22-symbolic-families.md) says, before any binding
exists, which checks of a pipeline every run will find already established. That holds
under two assumptions, a closed world and lexical identity.
[The aliasing entry](2026-10-22-aliasing.md) showed that lexical identity holds on
alias-free runs, and that `openat2` can enforce it at the moment of use.

This entry builds the executor that puts the two together:
- plan once, before any binding;
- run each binding with the plan's known checks elided;
- make every check and every access beneath the root.

It then asks whether pre-execution analysis is sound for *actual* runs, in a world that
is not closed.

The prototype is `wend._experimental.confined`, with tests in `tests/confined_test.py`
and two worked pipelines in `docs/journal/scripts/2026-10-22-confined-demo.py`.

[Confinement is not consistency](2026-10-22-confinement-is-not-consistency.md) draws the
conclusions together. It separates what this executor establishes (path resolution at
the moment of use) from what it does not (freshness, consistency, contents).

Labels: **[Fact]**, **[Measured]**, **[Proven]**, **[Interpretation]**,
**[Conjecture]**, **[Proposal]**.

---

## 1. The executor

**[Fact]** `run(steps, bodies, env, io, elide=plan, between=hook)` does the following
for each step:
1. renders each port's path;
2. checks its required atoms, less the plan's known ones;
3. runs its bodies on the path relative to the root;
4. checks what the step ensures.

A step that raises has failed. The plan is made assuming every earlier step completed,
so after a failure nothing is elided. `between(point, i)` is where another writer acts:
before a step's checks, and between its checks and its bodies.

**[Fact]** There are two `io` implementations with the same operations:

- **`Confined(root)`.** Every lookup and every operation goes through a descriptor
  opened by `openat2` beneath the root, without symlinks or mount points
  (`identity.Beneath`):
  - **checks** are made on an `O_PATH` descriptor;
  - **creation** walks the parents with `mkdirat` and an open beneath each directory,
    then creates with `O_CREAT | O_EXCL`;
  - **deletion** removes through descriptors, and opens each subdirectory beneath its
    parent under the same rules, so it never enters a mount point.

  A name that resolves through a symlink or a mount point is refused, with a
  `ContainmentError` for a check and `ELOOP` or `EXDEV` for an access.

  Each object opened is then judged on its descriptor:
  - a regular file must have exactly one name;
  - anything but a regular file or a directory is refused;
  - opens are non-blocking, and a write truncates only after the judgement.

  Path confinement is not object confinement: §3 has the counterexamples.
- **`Plain(root)`.** The same operations on ordinary paths, with checks by
  `wend.conditions`. Creation is exclusive unless `exclusive=False`, which opens as
  `open(p, "w")` does.

**[Fact]** Neither executor removes the root itself. A family can render to the root
(the parent of an empty `SubPath`), and the first generated case found it.

## 2. Claims, and what they rest on

**[Proven] A. Without another writer, confinement changes nothing.** On a tree with no
symlink or mount point below the root, a confined run of the plan completes the same
steps, reads the same data and leaves the same tree as a plain run that checks
everything. Three things give this:
- the analysis's soundness: a known atom holds whenever every earlier step completed
  ([families](2026-10-22-symbolic-families.md) §4, tested there);
- the confined checks agree with `wend.conditions` on such a tree;
- both executors create exclusively.

**[Proven] B. Every path a confined run resolves stays below the root, read as
written.** This rests on the kernel's guarantee for `RESOLVE_BENEATH`, `NO_SYMLINKS` and
`NO_XDEV`, as the [man page](https://man7.org/linux/man-pages/man2/openat2.2.html)
states it. Every operation of `Confined` is relative to a descriptor obtained that way,
and a descriptor cannot be redirected by later changes to names. B is a property of the
mechanism, not of the plan.

**[Fact]** B is about *paths*. The first version claimed more, that a confined run reads
and writes nothing outside the root, and two objects at inside names refuted it:
- **a hard link to an outside file:** the path is beneath the root, with no link and no
  mount, and the confined run read the file and overwrote it;
- **a FIFO at an input's name:** the open blocked indefinitely.

Judging each object on its descriptor (§1) refuses both. B′, that no object outside the
root is read or written, now holds for every move tested. It is not a guarantee against
names that another writer adds to an object later.

**[Interpretation] C. An elided check fails closed.** Suppose another writer makes a
known fact false. Then the access that relied on it either:
- fails (`ENOENT`, `EEXIST`, `ELOOP`, `EXDEV`, `EISDIR`, `ENOTDIR`), or
- reaches the file the string names, read as written.

The atoms say nothing about content, so another writer can still change what a file
holds.

## 3. What each flag buys

**[Measured]** Each part of the mechanism was mutated:

| mutant | rejected by |
|---|---|
| symlinks allowed (no `RESOLVE_NO_SYMLINKS`) | the alias-inside-the-root test; the aliasing entry's kernel-agreement and swap tests |
| mounts crossed (no `RESOLVE_NO_XDEV`) | the generated never-outside property, the moves table, the mount-below-a-deletion test |
| deletion enters subdirectories with a plain `open(O_NOFOLLOW)` | the mount-below-a-deletion test only |
| parents made with `os.makedirs` on the path string | the parents-through-a-link test |
| creation not exclusive | the generated agreement property (§2 A) |
| the plan kept after a step fails | the generated agreement property |
| hard-linked files allowed | the never-outside property, the moves table, the truncation test |
| objects of any kind allowed | the FIFO test |
| truncation at the open (`O_TRUNC`), before the judgement | the truncation test |
| blocking opens | the suite hangs on the planted FIFO |

**[Fact]** The first mutant survived every escape test. `RESOLVE_BENEATH` alone
already refuses an absolute link and a link that climbs out of the root. So
`RESOLVE_NO_SYMLINKS` does not guard against escape: it guards against an **alias
inside the root**. The test that rejects the mutant:
- after `copy`'s output is made, another writer replaces `out/` with a link to `raw/`;
- deleting `out/mon.csv` then deletes the source, `raw/mon.csv`, while the plan still
  knows that the source exists.

Nothing leaves the root, but the plan's lexical identity is false. So the two flags
protect the two assumptions separately: `BENEATH` the boundary, `NO_SYMLINKS` and
`NO_XDEV` the identity.

**[Fact]** An earlier version of that test overwrote the source by copying through the
link instead. Exclusive creation refused that on its own, so the mutant survived it too.
Each defence has to be tested where the others cannot reach.

## 4. The moves, one at a time

**[Measured]** The pipeline is `make raw/mon.csv; read it; copy it to out/mon.csv;
drop out/mon.csv; remake out/mon.csv`. Five moves of another writer, run under five
executors. ✗ means the run read, wrote or deleted something outside the root.

| move | checked | checked, `"w"` | plan | plan, `"w"` | confined |
|---|---|---|---|---|---|
| `raw/mon.csv` becomes a link out, before `read` | ✗ | ✗ | ✗ | ✗ | refused |
| `out/mon.csv` becomes a dangling link out, between `copy`'s checks and bodies | | ✗ | | ✗ | refused |
| `out/` becomes a link out, between `copy`'s checks and bodies | ✗ | ✗ | ✗ | ✗ | refused |
| a bind mount over `out/`, between `drop`'s checks and bodies | ✗ | ✗ | ✗ | ✗ | refused |
| `out/mon.csv` becomes a dangling link out, before `remake` (whose `Absent` the plan knows) | | | | ✗ | refused |

**[Interpretation]** Read by rows:

1. **Checks that follow links are no defence against a swapped link.** The checked run
   escapes as the plan does: `File`, `Exists` and `Readable` all hold of the link's
   target.
2. **Checking cannot win a race between check and use** (rows 3 and 4).
3. **Exclusive creation defends the name, not the way to it** (rows 2 and 3).
4. **The last row is the only one where elision is to blame.** A check would refuse the
   link, since `lstat` sees it; elided, the run writes through it. This is the aliasing
   entry's first counterexample, in a pipeline: the plan's knowledge was true of a name,
   until another writer changed what the name was.

In every row the confined run touches nothing outside the root and fails instead.

**[Fact]** `Under(root)` would not change the first column. Its physical half (the
`realpath` lies below the base) is a check of the moment.
`test_under_resolving_inside_the_root_is_a_fact_of_the_moment` shows that the check
passes, the name is swapped, and the read escapes.

This corrects [the knowledge entry](2026-10-22-knowledge-states.md), which says
containment is never forgotten. That is true of the lexical half only, the rendered
string lying below the base. `Tracker` checks atoms, not `Under`, so it makes neither
check. A confined run makes the physical half hold at every access.

## 5. Generated runs

**[Measured]** The families tests' pipelines are reused here: 14 families chosen to
collide under some binding, and 4 bindings. With them:

- **Agreement (claim A).** Over 200 examples, each under all four bindings, a confined
  run of the plan and a plain run with every check agreed every time: the same
  completed steps, final tree and data read.
- **Never outside (claims B and B′).** Over 300 examples with a random schedule of the
  writer, the confined run never reached outside the root. Each schedule has 1 to 4
  moves, drawn from: links out, dangling links, a directory replaced by a link,
  deletions, planted files, bind mounts, hard links to an outside file, and FIFOs. The
  last two were added after the hard-link counterexample (§2), and the property failed
  on them until objects were judged on their descriptors.
- **The writer never acts through its own mounts.** The first failure of this property
  was the harness's: the writer planted a link inside a bind mount it had made. That
  writes outside the root without any executor's help.

**[Measured]** 1,000 such pipelines (3,007 steps), each run under the same random
writer by five executors. This first measurement predates the hard-link and FIFO moves
and the judgement of objects (§2); it is kept as it was taken.

| executor | runs that reached outside the root | steps completed |
|---|---|---|
| plain, every check made | 74 | 1,045 |
| plain, every check made, creating as `"w"` | 83 | 1,072 |
| plain, the plan's checks elided | 74 | 1,045 |
| plain, elided, `"w"` | 83 | 1,072 |
| confined, elided | **0** | 944 |

Without the writer, the confined runs complete 1,186 steps.

**[Measured]** The same measurement repeated after hard links joined the writer's moves
and objects were judged on their descriptors. FIFOs are left out of this one, because a
plain read would block on them for ever. The schedules differ, so the counts are not
comparable row by row with the table above:

| executor | runs that reached outside the root | steps completed |
|---|---|---|
| plain, every check made | 60 | 1,073 |
| plain, every check made, `"w"` | 69 | 1,102 |
| plain, the plan's checks elided | 60 | 1,074 |
| plain, elided, `"w"` | 69 | 1,103 |
| confined, elided | **0** | 985 |

Over 1,000 pipelines and 2,997 steps:
- 238 confined steps failed under the writer that complete without it;
- the plan elided 623 of 9,634 required atoms.

**[Interpretation]** Three readings:
- **Checking everything did not prevent a single escape** here: the checked and elided
  plain runs reached outside in exactly the same runs. The writer's moves are swaps
  that checks follow, or races that come after the checks. Elision is not what makes a
  plain run unsafe; the elision-only escape of §4 needs a dangling link at a name whose
  absence is known, which random schedules rarely build.
- **Confinement costs completion, by design.** 258 steps that complete without the
  writer fail under it, where the plain runs went on through the writer's links.
- **The plan elided 623 of 9,769 required atoms.** That is fewer than in the modelled
  runs of the families entry, because half these pipelines are drawn at random and
  most of them fail early, after which nothing is elided.

## 6. Two pipelines of realistic shape

**[Measured]** The demo analyses two pipelines before any binding:
- the day pipeline of the families entry;
- a medallion layout, in which each `(table, date)` is landed into
  `bronze/{table}/{date}.json`, refined into `silver/`, listed by table, aggregated into
  `gold/{table}.parquet`, and expired from `bronze/`.

The plan elides 10 of 25 required checks in the first and 10 of 22 in the second, for
every binding. Both run to completion, confined, under every binding tried.

**[Measured]** Then another writer copies a stage directory outside the root, puts its
own data in every file, and replaces the stage with a link to the copy:

| pipeline (stage) | plain run of the plan | confined run of the plan |
|---|---|---|
| day (`raw/`, before `validate`) | reads the writer's data twice; `cleanup` deletes `raw/mon.csv` *outside the root*; every step "completes" | reads nothing of it; touches nothing outside; `validate` and every later step fail |
| medallion (`silver/`, before `check`) | reads the writer's data twice and aggregates it into `gold/`; every step "completes" | reads nothing of it; `check`, `partitions` and `aggregate` fail |

## 7. The answer, so far

**[Fact]** This section first answered "yes, for atoms of names". That overstated it,
and [the synthesis](2026-10-22-confinement-is-not-consistency.md#7-claims-narrowed)
narrows it. What the evidence supports is that confined execution:
- prevented the tested path-resolution attacks from escaping the workspace;
- with objects judged on their descriptors, prevented the tested object attacks too;
- preserved the behaviour of honest runs.

The plan's facts stay facts about the past. Confinement makes the names mean what the
strings say at each use; it does not keep the facts true.

**[Interpretation]** *Can symbolic overlap reasoning support sound pre-execution
analysis of actual pipelines?* It can be acted on safely where the runtime enforces the
analysis's weaker assumption and turns violations of the other into errors:
- **Lexical identity** becomes a property of the execution:
  - `Under(root)`, or the executor's own containment, puts every rendered path below
    the root without `..`;
  - `Confined` makes the kernel read every path as written.
- **The closed world** cannot be enforced, since other writers exist. A violation now
  shows as a failed access, never as a redirection to another file.
- **What remains outside** is content, which another writer can still change;
  [Held](2026-10-22-aliasing.md#7-what-this-means-for-check-events-and-capabilities)
  descriptors and content hashes are the tools there. Case folding also remains, and
  is untested.

**[Proposal]** For wend:
- a confined mode for `Step` or for pipeline runs, opt-in and Linux-first, with the
  root taken from the ports' `Under` bases;
- the plan as an artefact that can be inspected before the run: what will be elided,
  what is refuted, which steps commute. It is valid only for runs that are both
  confined and complete.

## 8. Limits

- **[Fact]** Linux 5.6+ only, and experimental. Elsewhere, or where `openat2` is
  missing or filtered, `Beneath` raises `UnsupportedPlatformError` at construction; there
  is no fallback to a weaker resolution.
- **[Fact]** Symlinks below the root are refused, including those that users put there
  on purpose; the root itself may be reached through symlinks. Multiply linked regular
  files are refused too, so hard-link farms (package stores, `cp -al` snapshots) cannot
  be read confined.
- **[Fact]** The writer acts only between steps and between a step's checks and its
  bodies. Between two system calls of one body, each call is relative to a descriptor
  already opened beneath, so a swap there fails or acts in the directory already
  reached; that case is argued, not tested.
- **[Fact]** Permissions are not exercised (the tests run as root), and fsspec stores
  are out of scope.
- **[Fact]** Claims A and B are argued from the analysis's tested soundness and the
  kernel's documented guarantee, then tested; neither proof is checked by a machine.
