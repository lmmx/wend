# 2026-10-22: Synthesis: one pipeline, and what each guarantee rests on (research)

> **Revised in place, 2026-10-22,** after the owner's review. Where a claim here was
> refuted or narrowed, the corrected statement replaces it and the earlier wording is kept
> beside it, marked *Before*:
> - the lease claims of §4.2, §6 and §8: see
>   [Leases](2026-10-22-leases.md).

The stack #107–#114 built its mechanisms one problem at a time:
- declarations as obligations;
- knowledge before and after each step;
- families of paths;
- identity and confinement;
- three guarantees as three types;
- freshness, drafts and publication.

The owner asked for them to be put together in one pipeline and tested end to end
against controlled interference. Each guarantee is then classed as one of three:
- it holds **by construction**;
- it holds **under an assumption**, which is named;
- it is **impossible without the cooperation** of the other writers.

Two details were to be examined closely:
- exchange-and-validate is not a compare-and-swap;
- a pinned directory is not a snapshot.

Building the pipeline produced results of its own, and so did auditing the earlier entries
while building it. Three changed the classification:
- read leases, which exclude a writer where no observer can see one (§4), on conditions
  the [leases entry](2026-10-22-leases.md) narrowed;
- copies torn by a concurrent writer (§4.3);
- drafts that another process can name (§5).

The development is recorded with the results, as in the other entries.

Code:
- `experiments/synthesis/pipeline.py`, the example, run with
  `uv run python experiments/synthesis/pipeline.py`;
- `experiments/synthesis/misuse.py`, the type-level rejections;
- `tests/synthesis_test.py`;
- the new parts of `wend._experimental.publish` (`Store`, `VersionDraft`, `Version`,
  `Pinned`), `fresh` (`Leases`) and `events` (`Commits`, `Run(lease=True)`).

Labels, as in the other entries:
- **[Proven]**, under the assumptions named;
- **[Measured]**, observed on Linux 6.18 and ext4, as root unless stated;
- **[Fact]**, documented behaviour of an interface;
- **[Conjecture]**, plausible and unproven;
- **[Refuted]**;
- **[Interpretation]**;
- **[Proposal]**.

[The research index](2026-10-22-research-index.md) places this entry among the others. The audit of
the earlier entries, made alongside this one, is in an addendum at the end of each.

---

## 1. The pipeline

A day's sales land as two files under `landing/{day}/`:
- `orders.csv` (order, SKU, quantity);
- `prices.csv` (SKU, price).

There are two steps:
- `Validate` holds both inputs and makes `staging/{day}.csv`, the orders joined to their
  prices;
- `Report` holds the staged file and commits one version of a store at `reports/{day}`,
  with two members: `summary.csv` (count, total) and `by_sku.csv` (amount per SKU).

A consumer pins the version and checks that the total equals the sum by SKU. A reader
that mixed two versions would see the two disagree.

```python
class Validate(Spec):
    orders = Holds(orders)  # File, Exists, Readable
    prices = Holds(prices)
    staged = Makes(staged_new)  # Absent, Creatable -> File, Exists


class Report(Spec):
    staged = Holds(staged)
    report = Commits(reports)  # Dir -> Dir, Exists
```

Each mechanism appears once, in the order a value meets it.

1. **Declaration, analysed before anything runs.**
   - `analyse_families` (#109) over the two steps finds that `report.staged`'s `File`
     and `Exists` are known from `Validate`'s postconditions for every day, and that only
     `Readable` must be checked.
   - A pipeline that validates twice is refuted before running: the second `Makes`
     requires `Absent`, which the first ensures false. The check would fail, and the plan
     says so.
2. **Check (an event).**
   - At entry, each port's preconditions are checked beneath the root (`Confined`,
     #112), giving a `Checked` event: it was true.
3. **Hold (which object).**
   - Each input is opened and judged on its descriptor: a regular file, one name, not a
     FIFO.
   - It is fingerprinted with its contents.
4. **Seal (the bytes used).**
   - The body reads through `seal`, a copy in a sealed memfd that no one can change.
5. **Draft (a write capability nobody can see).**
   - `Makes` gives an `O_TMPFILE` in the output's directory.
   - `Commits` gives a `VersionDraft`, a hidden directory of drafts.
6. **Publish or claim.**
   - At exit, the staged file is published with `create`: it never replaces another
     writer's file.
   - The version is claimed with `RENAME_NOREPLACE` (§3).
7. **Derivation.**
   - Each publication records the fingerprints of what it was made from.
   - `invalidated` follows the records downstream.
8. **Pin.**
   - The consumer pins the version.
   - It reads every member through the held directory, and verifies each against the
     manifest digest the commit returned.

`SCENARIOS` in the example run the pipeline honestly, then against one move of another
writer at a time, each scheduled at a named point of the run. `tests/synthesis_test.py`
runs each one as a test. The classification of the results is §6.

## 2. Exchange-and-validate is not a compare-and-swap

**[Fact]** `Draft.publish(policy="exchange", expect=ident)` works in four moves:
1. link the draft under a temporary name;
2. `renameat2(RENAME_EXCHANGE)` it with the name;
3. look at what came out;
4. if that is not `expect`, exchange back and raise `Conflict`.

Either way the temporary name is then unlinked.

The second exchange is as unconditional as the first. The flags of `renameat2(2)` are:
- `RENAME_NOREPLACE`, which conditions on the target's *absence*;
- `RENAME_EXCHANGE`, which needs only its *presence*;
- `RENAME_WHITEOUT`.

None conditions on *which* object the target is. No system call replaces a name only if
it still names a given object.

### 2.1 Every schedule, checked

**[Proven]** `test_exchange_and_validate_over_every_schedule` enumerates every
interleaving of the protocol's system calls for two and for three writers. All writers
expect the original object. Assumptions:
- each call is atomic;
- only writer *i* touches its temporary name, so looking at what came out is part of its
  exchange.

| writers | schedules | end wrong | a "published" version lost | the name holds a version whose writer was told "conflict" | a reader can meet a version that is not kept |
|---|---|---|---|---|---|
| 2 | 8 | 0 | 0 | 0 | 8 |
| 3 | 420 | 126 | 126 | 126 | 420 |

With two writers the final state is always right, but a reader can always meet the
loser's version: it is the file between the two exchanges.

With three writers, 30% of schedules end wrong, and wrong in the same way each time:
- a writer told "published" has lost its version;
- a writer told "conflict" has its version at the name.

**[Measured]** The kernel agrees on the shortest such schedule:
`test_exchange_and_validate_loses_an_update_with_three_writers` drives three real writers
through it with a deterministic scheduler around `renameat2`.

| step | call | name holds | temporaries | consequence |
|---|---|---|---|---|
| A1 | A exchanges in | A | tA: X0 | A sees X0 = expected: publishes, unlinks X0 |
| B1 | B exchanges in | B | tB: A | B sees A ≠ X0 |
| C1 | C exchanges in | C | tC: B | C sees B ≠ X0 |
| B2 | B exchanges back | A | tB: **C** | B raises `Conflict`, unlinks tB: **C is destroyed** |
| C2 | C exchanges back | **B** | tC: **A** | C raises `Conflict`, unlinks tC: **A is destroyed** |

The mechanism: an undo puts back whatever the temporary holds *now*, and takes out
whatever the name holds *now*. Each undo after the first moves a third writer's version
into a temporary name, and the cleanup then unlinks it.

**[Refuted]** These two statements of #114 are withdrawn:
- "A lost update is prevented, at the price of a withdrawn version being visible";
- the docstring's "a compare-and-swap after the fact".

They hold for two writers only. The docstring now names the protocol as optimistic and
not a compare-and-swap, and points here.

### 2.2 Why two writers work and three do not: consensus numbers

**[Interpretation]** Herlihy's hierarchy (1991) ranks a shared object by the largest
number of processes for which it solves wait-free consensus:
- read/write registers: 1;
- swap and test-and-set: 2;
- compare-and-swap: ∞.

Exchanging a temporary name, which only its writer uses, with the shared name is a
*swap* of a private value with a shared register: rank 2. The protocol is correct for two
writers and fails for three, as an object of rank 2 would be expected to.

The analogy is not a proof about this protocol. The theorem does say that compare-and-swap
for three or more processes cannot be built, wait-free, from swaps and registers alone.

**[Interpretation]** The filesystem offers more than swaps:
- `linkat`, which fails with `EEXIST`;
- `renameat2(RENAME_NOREPLACE)` into a fresh name.

Each is a **sticky register**: written once, every later write fails, and everyone reads
the winner's value. Sticky registers have consensus number ∞ (Plotkin, 1989).

A sequence of fresh names claimed this way is Herlihy's *universal construction*: a log
of one-shot consensus decisions, whose head is the current state. `Store` (§3) is that
construction. It is lock-free, not wait-free:
- some writer's claim always succeeds;
- a particular writer can lose every time;
- Herlihy's helping would be needed for wait-freedom, and is not built.

**[Conjecture]** Open question: whether `RENAME_EXCHANGE` between two *shared* names
gives a correct conditional replace without fresh names. That is a memory-to-memory swap,
which Herlihy ranks at ∞. Nothing here needs it.

**[Proven]** What no construction gives: protection against a writer that does not use
it. Any of these objects is linearizable only for the processes that act through it. A
writer that renames over the name, or writes into a version, is outside the construction.
That is the precise sense of "impossible without cooperating writers" for conditional
publication.

## 3. A versioned generation: what pins it, and what keeps it unchanged

**[Refuted]** "A reader holding a generation's directory reads one generation" (#114 §3)
held only under a protocol that nothing enforced.

`test_a_pinned_directory_is_not_a_snapshot`:
- a reader holds a `Generation`'s directory;
- another writer opens a member by name and rewrites it in place;
- the next read through the held directory returns the new bytes.

Holding a directory pins which *names* it has and which objects they lead to. It does not
pin those objects' *contents*.

`Store` adds three layers to the held directory, each answering a different question.

1. **Protocol: who may write.**
   - A version is filled only as drafts in a hidden directory
     (`.v000007.draft-<hex>`).
   - The version is claimed by `renameat2(hidden, "v000007", RENAME_NOREPLACE)`.
   - After the claim, no API writes into it: `VersionDraft` is spent and `Pinned` has no
     writer (both checkers reject `p.write`, `experiments/synthesis/misuse.py`).
   - Writers claim only the version after the one they read as latest, so a claim of *n*
     means "replace the current version if it is still *n − 1*". This is the conditional
     publication §2 could not give.
   - **[Measured]** `test_a_claimed_version_has_one_winner_and_no_visible_loser`: three
     writers claim version 1 behind a barrier, one wins, and the losers' versions never
     appear. **[Proven]** It follows from the sticky register (§2.2), assuming every
     writer follows the protocol.
2. **Detection: what was committed.**
   - Each version holds a `MANIFEST` (`name sha256` per member).
   - `commit` returns a `Version` whose `manifest` is the digest of that file.
   - `Pinned` reads the manifest once. Every member is read through the held directory
     and returned only if its digest matches: otherwise `Modified`.
   - **[Proven]** Assuming SHA-256's collision resistance and an authentic manifest
     digest, a pinned reader never returns bytes the version did not commit, whatever
     another writer did. That includes the dirty-`mmap` writer no observer sees.
   - This sidesteps the impossibility of §4. The reader does not compare two observations
     of its own. It compares against a commitment the producer made: the producer's
     cooperation, in its smallest form.
   - The digest must come from somewhere the writer of the files cannot reach: the run's
     own record (`Derivation`, `Run.published`), not the store. Without it, a writer that
     rewrites a member and its `MANIFEST` together is believed.
     `test_a_rewritten_manifest_is_caught_only_by_the_digest_the_commit_returned` shows
     both outcomes.
3. **Prevention: nobody can write (optional, privileged).**
   - `commit(immutable=True)` sets `FS_IMMUTABLE_FL` on every member *before* the claim,
     and on the version directory *after* it. An immutable directory cannot be renamed, so
     the claim must come first.
   - **[Measured]** `test_immutable_members_refuse_every_writer_tried`: on ext4 every
     move tried is refused with `EPERM`. That includes a writer that opened the member
     for writing, and mapped it shared, before the flag was set:

     | move | result |
     |---|---|
     | open for writing | `EPERM` |
     | write through a descriptor opened before the flag | `EPERM` |
     | `ftruncate`; and, in a probe, `fallocate`, `chmod`, `utime`, `setxattr` | `EPERM` |
     | rename, unlink, link a member | `EPERM` |
     | add a file to the version, rename the version | `EPERM` |
     | write through a shared mapping made before the flag (page clean or dirty) | `SIGBUS` |
     | a new shared writable mapping from a descriptor opened before | allowed; the first write `SIGBUS` |

   - **[Conjecture]** The mechanism of the `SIGBUS`: setting the flag writes back the
     file's pages and write-protects them, so the next write through any mapping faults,
     and the fault is refused for an immutable inode. This was not read in the kernel
     source.
   - **[Interpretation]** Here a privilege closes the one channel that §4 found invisible
     to every observer.
   - Limits:
     - it needs `CAP_LINUX_IMMUTABLE`;
     - anyone with that capability can clear the flag;
     - a member could be changed between being drafted and being flagged. Layer 2 detects
       that.
4. **Reclamation: a version disappears only when nobody holds it.**
   - `Pinned` takes a shared `flock` on the version's directory.
   - `Store.reclaim(n)` works as follows:
     - it takes an exclusive one without waiting, or raises `InUse`;
     - it refuses the latest version, so the current one never disappears;
     - it clears any immutable flags;
     - it unlinks the manifest before the members.
   - **[Measured]** `test_a_version_is_reclaimed_only_once_no_reader_holds_it`: a reader
     that opened the version just before reclamation waits for the lease, then finds no
     manifest and fails. It reads neither version.
   - The lease is advisory: it protects readers that pin, not readers that go by path.

**The reader protocol, then:**
1. `latest()`;
2. `pin(n, manifest=digest)`, with the digest from the derivation record when the reader
   has one;
3. read every member through the pin;
4. close.

**[Proven]** The members read are those committed as version *n*. The assumptions:
- writers follow the protocol (layer 1);
- an authentic digest (layer 2), or no writer below the root, or immutable members
  (layer 3) and nobody with `CAP_LINUX_IMMUTABLE` acting against the run.

A failed claim after members were flagged left the flagged draft behind: a directory that
only `CAP_LINUX_IMMUTABLE` could remove. The debris of a failing test showed it. `commit`
now abandons an unclaimed version whatever the failure, clearing flags first.
`test_a_claim_that_fails_after_flagging_its_members_leaves_nothing` keeps it fixed.

**[Conjecture]** fs-verity would serve better than the immutable flag:
- unprivileged;
- permanent;
- the kernel verifies every page against a Merkle tree as it is read;
- the kernel measures the digest itself (`FS_IOC_MEASURE_VERITY`), so verification
  would not need to read the whole member first.

It could not be tested: this kernel is built without `CONFIG_FS_VERITY`, and
`FS_IOC_ENABLE_VERITY` fails with `EOPNOTSUPP` on an ext4 image made with `-O verity`.
The experiment that would decide it: on a kernel with fs-verity, enable it on each member
before the claim and record the measured digests in the manifest. Then repeat the moves
of the table above as an unprivileged user.

## 4. A snapshot of several inputs: observation, exclusion, cooperation

#114 §3 proved that no observer can establish a snapshot of files that another writer
changes in place: a writer through dirty pages of a shared mapping can change a file and
change it back with no trace. The pipeline shows the consequence, and an exclusion that
removes it.

### 4.1 The incoherent pair

**[Measured]** `pair_updated_mid_entry` uses a writer that only ever writes the pair
(orders, prices) as a pair, in this order:
1. entry observes the orders (old);
2. the writer writes the new pair;
3. entry observes the prices (new);
4. the body reads the prices (new, as observed);
5. the writer writes the old pair back;
6. the body reads the orders (old, as observed).

The run succeeds on old orders and new prices, a pair that never existed. Every check
passed, including the new one of §5 that every read returns what was observed.

`invalidated()` flags the run afterwards, but only because the final state differs from
what was used. Observation can give detection after the fact, never a snapshot at the
time.

### 4.2 Read leases: an exclusion, not an observation

**[Measured]** The audit of #114 found, and a probe here confirmed, that the writer
leaving no trace of its *change* leaves a trace of its *capability*:
- `fcntl(F_SETLEASE, F_RDLCK)` fails with `EAGAIN` while any process has the file open for
  writing;
- this includes a process holding only a dirty shared writable mapping, its descriptor
  closed;
- the lease is granted once that process exits.

With the lease held:
- another process's open for writing blocks until the lease is given up;
- with `O_NONBLOCK` the open fails with `EAGAIN`, even from the holder's own process;
- either way the lease is broken, which the holder reads back with `F_GETLEASE`.

`fresh.Leases` and `collect(observer="lease")` build on this:
- every input is leased before it is copied; `Busy` if any has a writer;
- the copies are coherent only if the leases are unbroken after the last check (no break,
  and no size fallen: leases §3.1), and each name still leads to the object copied.

`Run(lease=True)` leases every held input at once, all or none, before observing any, and
refuses the step at exit unless the leases are unbroken.

**[Proven]** under the assumptions L1–L5 of the leases entry's proposition L, and only
with two additions to the mechanism, both made there:
- the size of every input is recorded once the leases are taken, and `unbroken()` asks
  for it unchanged as well as for every lease still `F_RDLCK`;
- inputs on a filesystem outside `fresh.LEASABLE` (ext2/3/4 and tmpfs, the ones tested)
  are refused.

With them, if every lease reads unbroken after the last read, every input's contents were
constant from the moment the sizes were recorded, and the copies are the state of every
input at that one instant.

> *Before:* "**[Proven]** Assumptions, all three documented in `fcntl(2)`: **L1:** a read
> lease is granted only when no process has the file open for writing, and any later open
> for writing or truncation breaks it; **L2:** every write to the file goes through an open
> file description; **L3:** the run owns the inputs or has `CAP_LEASE`, on a filesystem
> with leases (local; not NFS)." The argument then concluded from unbroken leases alone.
>
> **[Refuted]**, twice:
> - an `open` with `O_RDONLY | O_TRUNC` empties a leased file and leaves the lease intact
>   (leases §3.1), so L1's "or truncation" is false for that truncation. Two files emptied
>   that way, between their copies, gave a pair of copies that never coexisted, under
>   unbroken leases;
> - the kernel grants leases on `/proc` files, which change with no writer (leases §3.4),
>   so "a filesystem with leases" was not the condition.

Under L1–L3 this establishes a coherent snapshot of the *objects*, which no observer can
establish. **[Measured]** `test_a_read_lease_excludes_the_writer_no_observer_sees` and
`test_a_writer_that_arrives_during_a_leased_collect_is_held_off_and_seen` show it in
practice. So does the pipeline's `pair_updated_mid_entry_leased`: 3 of the writer's 4
opens are held off, and the run publishes nothing.

The guarantee is about objects, not names. Renaming a file does not break its lease. Names
are checked once more at the end, which misses a name changed and changed back. Whether
the directory's `ctime` is a sound version counter for names is a **[Conjecture]**:
- it is updated on every entry change;
- a directory cannot be written through a mapping;
- it relies on this kernel's timestamps always advancing.

**[Interpretation]** This revises the classification. Before the audit, "a coherent
snapshot of files others write in place" stood under *impossible without cooperation*. It
is impossible for *observers*. It is possible by *exclusion*, which needs the inputs'
ownership or `CAP_LEASE`, and a filesystem in `LEASABLE`, but not the writers'
cooperation. Ownership is not privilege: an ordinary user leases their own files
(`test_only_the_owner_or_CAP_LEASE_may_lease`). The writers are delayed, not asked: a
writer that opens an input waits until the step ends, or until
`/proc/sys/fs/lease-break-time` (45 s here) when the kernel breaks the lease. A writer
that truncates by `O_RDONLY | O_TRUNC` is not delayed at all; it is seen afterwards.

> *Before:* "possible by *exclusion*, which needs privilege (ownership or `CAP_LEASE`) and a
> local filesystem". **[Narrowed]**: ownership is no privilege, and "local" was not enough
> (leases §3.4).

The impossibility proof of #114 §3 is not wrong. It quantifies over observers, and a lease
is not one: it changes what other processes can do.

**A finding of the implementation:**
- A lease break is announced by a signal, `SIGIO` by default, whose default action ends
  the process.
- The first leased test therefore killed pytest silently: the output stopped, which read
  as a hang.
- A library must not leave a process exposed to a signal it did not ask for.
- `Leases` now takes every lease in a helper process that exits at once (leases §3.3).
  The leases stay on the descriptions the host holds, owned by a process that no longer
  exists, so a break signals no one. The host reads the break from the lease itself.

> *Before:* "`Leases` now: sends the announcement to a signal whose default is to ignore
> (`F_SETSIG`, `SIGURG`); then sends it to no one (`F_SETOWN`, 0); reads the break from the
> lease itself." **[Refuted]** as encapsulation (leases §3.2): `F_SETLEASE` makes the
> caller's process the owner, so between it and `F_SETOWN` 0 a break ran the host's own
> `SIGURG` handler. No order of calls in one process closes that window.

### 4.3 A copy can be torn

**[Measured]** A sealed copy is a single `pread`. Under a concurrent writer through a
mapping, a read of a 64-page file mixed two versions in 244 of 300 attempts, confirming
the #114 audit's probe. The writer stored the same byte at the start of every page,
alternating `a` and `b` versions:

```python
data = os.pread(fd, 64 * 4096, 0)
torn = len({data[i : i + 1] for i in range(0, len(data), 4096)}) > 1
```

**[Refuted]** "`Sealed`: it remains true" was read in #113 and #114 as "a snapshot of the
input". A `Sealed` copy cannot change. It need not ever have been the file's contents. The
event, object and copy distinction stands, with this narrowing.

Two things make a copy a state the file had:
- a lease held across the copy (§4.2);
- a digest committed by the producer (§3).

Every fresh and consistency test used one-page files, which is why this was never seen.

## 5. What building the pipeline changed in `Run`

Three defects of #113–#114's `Run` appeared only when the mechanisms were composed.

1. **A derivation could misstate what the step used.**
   - The derivation recorded the input's fingerprint at entry, while the body read it
     later.
   - A change in between (`test_a_held_input_does_not_keep_its_contents_but_a_sealed_copy_does`
     makes one) gave an output whose record named bytes it was not made from.
   - Now `events.Held` records a digest of what every read returned. At exit the run
     refuses (`Inconsistent`, nothing published) if any differs from the entry
     observation.
   - **[Proven]** For whole-file reads through `Held.read` and `seal`, the derivation
     records exactly the bytes used. Reads through the raw descriptor are outside this.
2. **A later step could consume a different object under the same name.**
   - Between two steps, another writer renamed a file over `staging/mon.csv`. `Report`
     then held that file.
   - Only `invalidated()` noticed, after the fact, by calling the staged output
     "superseded".
   - Now an input that the run itself published must be, at entry, that object with
     those contents, or the step is refused (`staged_replaced_between`).
3. **`Run.confirmed` was keyed by port name.**
   - `staged` is a port of both steps, so the second event overwrote the first.
   - The #114 audit found this; the same bug had been fixed there for `published` and
     `derivations` but not here.
   - It is keyed by path now.

**Another writer can name an unpublished draft.** The `O_TMPFILE` is reachable as
`/proc/<pid>/fd/N`, and `linkat(..., AT_SYMLINK_FOLLOW)` gives it a name, partial contents
and all, which survives the writer's death. **[Measured]** Who can do it:

| who | writer dumpable (default) | writer non-dumpable (`prctl(PR_SET_DUMPABLE, 0)`) |
|---|---|---|
| another process, same uid, unprivileged | names the draft | `EACCES` |
| root | names the draft | names the draft |

"Unnameable until published" therefore holds against other uids, and against the same uid
only if the run is non-dumpable. That is a process-wide setting, which a library should
not change silently.

`O_EXCL` on the `O_TMPFILE` would forbid every link, the writer's own publication
included.

## 6. Classification

Each row is shown by the test or scenario named. "Construction" means: on Linux ≥ 5.6
with `openat2`, the run's own code following its protocol, with no assumption about other
writers.

### By construction

| guarantee | mechanism | evidence |
|---|---|---|
| every path the run opens resolves beneath its root | `openat2(RESOLVE_BENEATH \| NO_SYMLINKS \| NO_XDEV)` | `landing_swapped_for_a_symlink`; `confined_test`, `aliasing_test` |
| an input is a regular file with one name, never a FIFO or a hard link from outside | judgement on the descriptor (#112) | `events_test::test_an_input_that_is_not_confined_is_not_held` |
| reads come from the object opened, whatever happens to its names | `Held` | `held_test` |
| a sealed copy never changes (not: was ever the file's state, §4.3) | memfd seals | `events_test` |
| a derivation records exactly the bytes the step read | `Held.used` checked at exit | `input_rewritten_during` |
| a later step consumes the object an earlier step of the run published, or refuses | the handoff check | `staged_replaced_between` |
| an output is invisible until published, never partial, and nothing is left if the writer fails or is killed | `O_TMPFILE` + `linkat` | `publish_test` |
| publication never replaces another writer's file | `create` (`EEXIST`) | `output_name_taken` |

### Under assumptions (named)

| guarantee | mechanism | assumption | evidence |
|---|---|---|---|
| a claimed version has one winner; a loser is never visible; beliefs match the state | `RENAME_NOREPLACE` (sticky register) | every writer follows the store protocol | `concurrent_producers`; `test_a_claimed_version_has_one_winner_and_no_visible_loser` |
| a pinned reader returns only bytes the version committed | manifest digest | SHA-256 collision resistance; the digest from the run's record | `member_tampered` |
| an unpublished draft cannot be named by another process | `O_TMPFILE` | the other process is another uid, or the run is non-dumpable; not root | §5 |
| an input is a coherent snapshot of several files others write in place | read leases, taken by a helper, with sizes | L1–L5 of proposition L (leases §4): ownership or `CAP_LEASE`; a filesystem in `LEASABLE`; contents change only through the filesystem's files (L3, L4) | `pair_updated_mid_entry_leased`; `tests/leases_test.py` |
| members of a committed version cannot change at all | `FS_IMMUTABLE_FL` | `CAP_LINUX_IMMUTABLE` to set it; nobody with it acting against the run | `test_immutable_members_refuse_every_writer_tried` |
| a version is not removed under a reader | `flock` lease | readers pin rather than go by path | `test_a_version_is_reclaimed_only_once_no_reader_holds_it` |
| `known()` | knowledge of this run's effects | nobody else writes below the root (closed world) | `input_rewritten_after` |
| "unchanged" and `invalidated()` | observation | the observer saw every change: false for dirty-mapping writers, and only between writebacks (#114 addendum) | `fresh_test` |
| an output survives a crash | file `fsync`, publish, directory `fsync` | the ext4 loop-device crash model of #114; not a device losing its cache, not other filesystems | `durability_test` (root only) |
| exchange-and-validate ends right | exchange, then validate | at most two concurrent writers; never intermediate states | `test_exchange_and_validate_over_every_schedule` |

### Impossible without the writers' cooperation (or exclusion, where named)

| what | why | what makes it possible |
|---|---|---|
| detecting every change by observation | a dirty-mapping writer changes and restores a file with no trace (#114 §3) | nothing observational; exclusion (leases) or prevention (immutable) removes the writer instead |
| a coherent snapshot of files others write in place, by observing them | the double collect is fooled (`pair_updated_mid_entry`) | exclusion (§4.2), or the producer's cooperation (land inputs as versions of a store) |
| preventing a writer with write permission from changing a published file | permission is permission | privilege (`FS_IMMUTABLE_FL`), or detection only (manifest) |
| replacing a name only if it still names a given object, against writers outside a protocol | no system call conditions on identity (§2); any construction binds only its participants | cooperation: the store protocol |
| knowing a checked fact still holds at its use, for anything neither held, sealed nor leased | another writer can act between check and use | holding (which object), sealing (which bytes), leasing (no writer) |

## 7. What the types reject

**[Measured]** `experiments/synthesis/misuse.py` has 11 misuses of the pipeline's ports.
Each is an error in both Pyright 1.1.407 and ty 0.0.90, and the example itself has none
(`experiments/typed_core/check.py` checks both directories). The misuses:
- holding an output;
- making an input;
- committing to a file;
- making a directory of versions;
- passing a held file where a sealed copy is required;
- sealing a draft;
- reading a draft;
- writing an input;
- writing a version as one file;
- sealing a version;
- writing through a pin.

What the types do not say, and runtime checks do:
- that a capability is spent (a published draft, a committed version);
- that a held object is still the one published;
- any assumption of §6.

The typed-core addendum records two places where the types claim more than the runtime:
- an event's type carries every atom its expression declares, not the atoms checked;
- a path derived from an event (`c.parent`, `c / ".."`) is still typed, and built, as
  that event.

## 8. Open questions

- **fs-verity (§3).** Does it give unprivileged immutable members with kernel-measured
  digests? The experiment is described there.
- **Names under leases.** Is a directory's `ctime` a sound version counter for its
  entries, making a leased snapshot of *names and* objects sound (§4.2)? Experiment:
  rename-away-and-back schedules against a directory-`ctime` observer, with multigrain
  timestamps on and off.
- **Helping.** Does `Store` need wait-freedom? Herlihy's helping would let a writer that
  keeps losing claim on another's behalf. No pipeline here needs it.
- **Exchange between shared names.** Can a correct conditional replace be built from it
  without fresh names (§2.2)?
- **Leases on other filesystems.** *Answered* (leases §3.4). tmpfs is tested and
  allowed. `/proc` is granted leases by the kernel while its contents change, so `Leases`
  refuses every filesystem it has not tested (`Unleasable`). xfs and btrfs await their
  tests; overlayfs and network or FUSE filesystems are refused on principle.

  > *Before:* "Leases on overlayfs, tmpfs and FUSE are untested. Should `Run(lease=True)`
  > fall back or refuse where they are unsupported? It refuses: `fcntl` raises." The
  > kernel does not raise for `/proc`; it grants.
- **Large members.** Verifying a member reads it whole before returning it. Streaming
  verification needs a per-chunk manifest, or fs-verity.

## 9. The stack, reviewed for consolidation

Nothing below is done. It is a proposal for when the research is reviewed for merging, and
no history is discarded by it.

**Dependencies.** The stack adds none: `hypothesis` was already a test dependency.
Everything Linux-specific is in `_experimental`, behind `UnsupportedPlatformError`, and
left out of the wheel.

**Duplicated prototypes.** Each was the right step when it was taken, and each was
superseded by the next.

| superseded | by | proposal |
|---|---|---|
| `knowledge.Tracker` (#108), `identity.IdentityTracker` (#110), `confined.run` (#112) | `events.Run` (#113–#114) | keep `Knowledge` and `IdentityKnowledge` as the analyses; keep one executor, `Run`; keep the earlier executors only as test oracles where tests use them as such (`confined.run`'s plain-vs-confined agreement property) |
| `identity.Held` | `events.Held` (typed, records reads) | one class |
| `identity.Beneath.hold` | `confined._open` (object judgement) | remove `hold`: it opens without judging (identity addendum) |
| `publish.Generation` | `publish.Store` | keep `Generation` only as the counterexample "a pinned directory is not a snapshot" |
| three `ctypes` paths to system calls (`openat2`, `renameat2`, inotify) and three `fcntl`/`ioctl` users (memfd seals, leases, immutable flag) | one `_linux` module | gather them, each with its platform check |

**Integration risks, highest first.**

1. **#113 changes the core typing of `PathExpr`.** It has two type parameters, overloads,
   and a `K` bound. It is the only change to `wend`'s public typing, and the typed-core
   addendum records unsoundnesses (events' atoms, derived paths) and a wide ty precision
   gap. It should be reviewed on its own, before anything stacked on it is considered.
2. **#107's `declares` is core API** (§10.1). It is small and well tested, but its
   containment row needs the correction in its addendum (lexical half only).
3. **#111 and #110 share a test.** `aliasing_test` relies on `Creatable(lnk/x)` passing,
   which #111 makes fail. That test is also the only one that kills the "creation keyed
   by first missing entry" mutant. Merging #111 first means rebuilding that test.
4. **Privileged tests skip silently.** These need root, loop devices, bind mounts or
   `CAP_LINUX_IMMUTABLE`:
   - the durability tests;
   - mount aliasing;
   - the confined mount moves;
   - the immutable tests.

   Unprivileged CI runs none of them, and four mutant kills depend on them. A marker
   (`@pytest.mark.privileged`) and one privileged CI job would make the gap visible.
5. **Runtime of the property tests.** The aliasing and confined suites dominate.
6. **Experimental code kept out of the wheel.** Shipping any of it would need the
   consolidation above first.

**A sensible order for review** (a proposal, not a request to merge):
1. #107: core, small.
2. #113's core typing alone (`_kinds`, `_expr`, `conditions`), separated from its
   experimental `events`.
3. The research stack as one branch of research history: #108 → #109 → #110 → #112, then
   the experimental half of #113, then #114 and this entry. It would be squashed into
   nothing; the commits are the record. It would be merged only once the consolidation
   above is done in a final commit of its own.
4. #111 after #110's test is rebuilt.

## References

- M. Herlihy, *Wait-free synchronization*, ACM TOPLAS 13(1):124–149, 1991: consensus
  numbers, and the universal construction.
- S. Plotkin, *Sticky bits and universality of consensus*, PODC 1989.
- Afek et al., *Atomic snapshots of shared memory*, JACM 40(4), 1993 (as in #114).
- `rename(2)` (`renameat2` flags), `fcntl(2)` (leases: `F_SETLEASE`, `F_GETLEASE`,
  `F_SETSIG`, `/proc/sys/fs/lease-break-time`), `ioctl_iflags(2)` (`FS_IMMUTABLE_FL`),
  `open(2)` (`O_TMPFILE` and `linkat`), `proc(5)` (`/proc/pid/fd` access),
  `prctl(2)` (`PR_SET_DUMPABLE`), the kernel's fs-verity documentation.
