# 2026-10-22: Freshness, publication and consistency (research)

[Confinement is not consistency](2026-10-22-confinement-is-not-consistency.md) left three
problems open, and the owner review asked for all three at once. They differ in kind:

| problem | what it asks | what fingerprinting gives |
|---|---|---|
| freshness under other writers | is a fact checked earlier still true? | detection at the moments one looks |
| outputs held for writing | does a step write the object it means to, and when does that become visible? | almost nothing: a different design is needed |
| consistency across steps | do several operations see one state of the tree? | detection of some changes, never consistency |

**[Interpretation]** Publishing an output is the counterpart of acquiring an input:
- holding a descriptor fixes *which object* a reader reads;
- a writer needs to fix *which object* it writes, *when* it becomes visible, *who* else
  can change it, and *what* is left if it fails.

This entry gives each of the three problems a prototype, adversarial tests and a
verdict, then joins them in one state-transition model, tied to the effects algebra.

The prototypes:
- `wend._experimental.fresh`: observers, revalidation, a double collect;
- `wend._experimental.publish`: drafts, publication policies, generations, derivations;
- `Makes` ports in `events`.

The tests are `tests/fresh_test.py`, `publish_test.py`, `consistency_test.py`,
`lifecycle_test.py` and `durability_test.py`.

Labels: **[Fact]**, **[Measured]**, **[Proven]**, **[Interpretation]**,
**[Conjecture]**, **[Proposal]**.

---

## 1. Freshness: what can be known, observed, or only promised

**[Fact]** Three observers of a file, between two moments:
- **metadata**: the object (device, inode), size, `mtime`, `ctime`;
- **contents**: a SHA-256 digest;
- **a watch**: inotify on the held object, from one moment to the other.

`revalidate` compares two observations made by the same observer. It answers one of:
- `unchanged`, meaning unchanged *as observed*;
- `changed`;
- `replaced` (the name means another object);
- `gone`;
- `refused` (the name no longer resolves to a confined object).

**[Measured]** Which observer sees which move of another writer (`tests/fresh_test.py`,
each cell a test; Linux 6.18, ext4). ✓ means the change was seen.

| another writer's move | metadata | contents | both | watch |
|---|---|---|---|---|
| same-size rewrite | ✓ | ✓ | ✓ | ✓ |
| rewrite, then `mtime` restored with `utime` | ✓ (`ctime` moved) | ✓ | ✓ | ✓ |
| change, then change back | ✓ | | ✓ | ✓ |
| a new file renamed over the name | ✓ | ✓ | ✓ | ✓ |
| a write through a hard link | ✓ | ✓ | ✓ | ✓ |
| `mmap`, first write to a clean page | ✓ | ✓ | ✓ | |
| `mmap`, write to an already dirty page | | ✓ | ✓ | |
| `mmap`, dirty page changed and changed back | | | | |

**[Measured]** Timestamps here are fine-grained. In a probe on this machine, none of
4,000 same-size rewrites left `(mtime, ctime)` unchanged, whether or not anyone looked
in between. That is a property of this kernel and filesystem, not of POSIX, so it is
recorded here and not kept as a test.

**[Fact]** The `mmap` rows are the decisive ones:
- A write into a page that a shared mapping has already dirtied takes no page fault, so
  the kernel updates neither time. Even `msync` did not change them.
- inotify reports nothing for `mmap` and `msync`. The man-pages project records this
  as documented behaviour, and tested `munmap` when adding it (see References).

So the last row is a change that leaves **no trace for any observer**: no time, size or
event changes, and the contents are equal at both moments.

**[Interpretation]** What each observer gives:

| | what it yields | under what assumption |
|---|---|---|
| **knowable**, for the interval between two observations | that nothing changed | metadata, if every change advances `ctime`: false for writers through dirty mapped pages; the watch, if no change escapes inotify: false for `mmap`, and it can overflow |
| **observable** only | equality of contents at two instants | contents digest, always; it says nothing about in between |
| **needs cooperation** | that a fact *remains* true | read leases give notice, not prevention; advisory locks bind only writers who take them; the immutable flag needs privilege; a sealed copy freezes a copy, not the file |

**[Fact]** So `known()`, as #113 now states, is knowledge conditional on the closed
world, and revalidation is observation. Neither is a guarantee that a fact holds now.

## 2. Outputs held for writing

**[Fact]** A `Draft` is a write capability for a new object with no name. It is made
with `O_TMPFILE` in a directory held beneath the root. `Draft.publish(name, policy)`
gives the object its name in one system call:
- `"create"`: `linkat`, which refuses an existing name;
- `"replace"`: link under a fresh name, then `renameat` over the name;
- `"exchange"`: `renameat2(RENAME_EXCHANGE)`. With `expect`, the object the caller last
  saw at the name, it undoes the swap and raises `Conflict` if that is not what it
  displaced.

Publishing closes the draft, spending the capability. With `durable=True` the file is
synced before publication and the directory after.

**[Measured]** Three ways of writing `out/final.csv` (`tests/publish_test.py`):

| | writing the final name directly | a temporary name, then `rename` | a draft, then publish |
|---|---|---|---|
| a reader polling the name sees a partial file | **yes** | no | no |
| the writer killed half way (`SIGKILL`) leaves | a partial file at the final name | an orphaned temporary file | **nothing** |
| `out/` swapped for a link out of the root before the write | writes outside | writes outside (the temporary name is made by path) | refused (the directory is held beneath the root) |
| `out/` moved, and a link put in its place, *during* the write | — | — | published into the held directory, wherever it now is; `at_path` is false |
| another writer creates the name after our check | clobbered | clobbered (`rename` replaces) | `"create"` refuses (`EEXIST`) and their file survives |
| two writers of one name, interleaved | **a file neither wrote** | each whole | each whole; the last published wins |

**[Measured]** Readers polling a name that 8 writers replaced 160 times saw only whole
versions.

**[Fact] The intended object, not the intended path.** Publication is into the directory
*object* held when the draft was made. If another writer moves that directory, the
output lands in it, wherever it is now. No filesystem primitive ties the publication to
a path at its instant: the directory can be moved just before or just after. `Published`
therefore records `at_path`, whether the path still led to that directory just after.
It is an observation.

**[Measured] Compare-and-swap is not available on names.** The closest primitive is
exchange with `expect`, and the test shows its cost:
- another writer publishes between our observation and our exchange;
- the exchange detects it and swaps back, so their update survives;
- but our version *was* the file between the two exchanges, and a reader could have
  read it.

A lost update is prevented, at the price of a withdrawn version being visible. Avoiding
both needs coordination, such as a lock all writers take.

**[Measured] Durability, in a crash model** (`tests/durability_test.py`, root and loop
devices).
- **The setup.** An ext4 image is loop-mounted, committing its journal only every 60 s.
  The old version is synced first.
- **The crash.** Straight after the publication, the image is copied without any sync.
  The copy is mounted, replaying the journal. Three runs gave the same result:

| protocol | what the crash left |
|---|---|
| write the final name directly | the old version |
| temporary name and `rename`, nothing synced | the old version |
| temporary name and `rename`, the file synced | the old version: the rename itself was lost |
| draft, published without syncs | the old version |
| draft, published, *only the directory* synced, replacing | the new version (ext4 flushes data on a rename over a file) |
| draft, published, *only the directory* synced, creating | **the name, with 0 bytes** |
| draft, file synced, published, directory synced | **the new version** |

**[Interpretation]** Publication was atomic in every case: old or new, never torn.
Durability needed both syncs:
- **the directory's**, after publication: without it the publication is lost;
- **the file's**, before: without it a new name can survive with no contents.

ext4 masks the second only when a rename replaces a file. That is the dependence on
filesystem-specific "persistence properties" that Pillai et al. measured. This crash
model has no device that reorders its own writes or loses a volatile cache.

## 3. Consistency across steps

**[Fact]** The five things a pipeline with several inputs and outputs might want, and
what they need:

| | ordinary primitives | needs coordination | impossible under our assumptions |
|---|---|---|---|
| **detecting changes** | yes, partly: the table of §1 | | detecting *every* change, by observation alone |
| **an immutable snapshot of one input** | yes: `Sealed` (a sealed memfd copy); a reflink where the filesystem has them | | |
| **publishing one output atomically** | yes: a draft and `linkat`/`rename`; durable with both syncs | | |
| **a coherent snapshot of several inputs** | | yes: a producer publishing *generations*, a reader holding one; or privilege (filesystem snapshots) | knowing it, by observation, against a writer who leaves no trace |
| **committing several outputs atomically** | yes, for readers that hold the generation directory: one exchange publishes all | reclaiming old generations needs to know no reader still holds them | for readers that open each output by name separately |

**[Measured] A snapshot that never existed** (`tests/consistency_test.py`).
- **The setup.** Two inputs, `a` and `b`. Another writer changes both together, as one
  transaction of its own.
- **The schedule** of the double collect:
  1. copy `a`;
  2. the writer sets `(a1, b1)`;
  3. copy `b`;
  4. the writer sets `(a0, b0)`;
  5. check `a`;
  6. the writer sets `(a1, b1)`;
  7. check `b`.

  The copies are `(a0, b1)`, which never existed together, and each check finds its file
  as it was copied.
- **The results.** With writes through `write()`, metadata, both together, and the watch
  all reject the snapshot. Contents alone accept it, since the change was undone. With
  the same moves made through dirty mapped pages, **all four observers accept it**.

**[Proven] No observer can know that two files were copied coherently.**

The model:
- each read of a file happens at one instant;
- two reads happen at different instants;
- another writer can change a file without any trace except its contents at the moment
  it is read. This is the dirty-page writer of §1, as measured.

Under that model, the reader's observations do not determine whether its copies of two
files ever held together.

*Argument.* Take any reader, and an execution in which the files never change. Its
reads return some values at instants t₁ < t₂ < …. Build a second execution in which
the writer makes each file hold the value the reader will read from it only at the
instants it is read, and something else otherwise. Every read returns what it returned
in the first execution, and no observation differs, since the writer leaves no trace.
But the reads of different files happen at different instants, so no two of the copied
values ever held together. The reader cannot tell the two executions apart.

**[Interpretation]** The double collect, the classic shared-memory snapshot algorithm,
is correct only if the reader can see every change, as with sequence numbers in shared
memory. Wait-free snapshots need writers' help (Afek et al., 1993). Files give neither,
for an uncooperative writer. Hence the "needs coordination" column: the producer must
cooperate.

**[Measured] Generations** (`publish.Generation`). Each output is drafted into a fresh
hidden directory and published there. The directory is synced, then exchanged with the
current generation in one `renameat2`.
- **Holding a generation is coherent.** A reader holding the generation directory read
  one generation of every file, while a commit happened between its reads. A reader
  going by name read `(A1, B2)`.
- **Under a busy producer**, with 59 generations committed while 3 readers held and
  read, no reader saw a mixture.
- **Outputs published one by one**, each replaced whole, were seen half-updated.
- **Reclaiming a generation a reader still holds** makes the reader's next read fail
  (`ENOENT`). It is never a wrong read, because a removed directory takes no new entries.
  Reclaiming safely needs a grace period, which is reader cooperation.

**[Proven] Why a held generation is coherent.** The assumptions:
- every file of a generation is published into its directory before the directory is
  published;
- nothing writes into a published generation. This is the producer's protocol, the
  cooperation.

Under them, every name a reader resolves relative to a held generation directory reaches
a file of that generation, with the contents it had at commit. The held descriptor fixes
the directory object (#110, #112). Its entries do not change after commit, by the
protocol, and if the generation is reclaimed, lookups fail. The argument relies on the
protocol and on the kernel's semantics for descriptors, and is tested above; it is not
checked by a machine.

## 4. One state-transition model

**[Interpretation]** The pieces form one model, not a set of wrappers. Each artefact
moves through states by events. Each event carries one kind of guarantee, with its own
lifetime and its own cause of invalidation:

| event | from → to | guarantee | lasts | invalidated by | made by |
|---|---|---|---|---|---|
| **check** (`Checked`, `Confirmed`) | name → checked | *it was true*, at that instant | for ever, as history | — (it is history) | `Run.enter` |
| **knowledge** (`Run.known`) | checked → known | no step *of this run* has invalidated it | until such a step | a mutation of this run; blind to other writers | the forget rule (#108) |
| **observation** (`Fingerprint`) | name → observed | the object and its state, as the observer saw it | for ever, as history | — | `observe` |
| **revalidation** | observed → unchanged as observed / changed / replaced / gone / refused | detection, at a second instant | — | — | `revalidate` |
| **hold** (`Held`) | name → held object | *which object*, with kind and access | while open | nothing; its contents and names are not covered | a `Holds` port |
| **seal** (`Sealed`) | held → sealed copy | *it remains so*, for the copy | while open | nothing: the kernel refuses writes | `seal` |
| **draft** (`Draft`) | directory → private object | an exclusive write capability, for an object no one can name | until published or abandoned | publication, failure or exit (nothing is left) | a `Makes` port |
| **publication** (`Published`) | draft → name bound to object | *visible from now*, whole; old or new for readers, never torn | as history; `current()` observes whether it still holds | another writer's replacement or modification (detected, not prevented) | `Draft.publish` |
| **durability** | published → durable | survives a crash | — | — | file sync, publication, directory sync |
| **generation commit** | hidden directory → published directory | *visible together*, to readers that hold it | while held and not reclaimed | reclamation (reads fail closed) | `Generation.commit` |
| **derivation** (`Derivation`) | inputs observed + output published → a result *because of* them | the result follows from inputs *as observed* | until an input changes as observed, or the output is superseded | `stale`; downstream through `invalidated` | `Run` at a step's exit |

**[Interpretation]** Three rules hold across the table:
1. **No event converts into another of a different kind.** A check is not a hold. A
   hold is not a seal. A publication is not durability. The types of #113 enforce the
   first two statically.
2. **Every guarantee names its assumption:**
   - a check, none;
   - knowledge, the closed world;
   - a hold, a descriptor;
   - a seal, the kernel's seals;
   - a draft's privacy, other users (a process allowed to inspect ours can still reach
     it through `/proc/<pid>/fd`);
   - publication's atomicity, `rename(2)`;
   - durability, both syncs and the filesystem;
   - a generation's coherence, the producer's protocol;
   - a derivation, the observer's blind spots.
3. **What is detected is never promoted to what is known.** `revalidate`, `current`,
   `stale` and `at_path` are observations. Only seals and the producer's protocol give
   facts that persist.

## 5. Connecting to the effects algebra

**[Fact]** wend's declared verbs map onto these transitions:

| declared | at runtime |
|---|---|
| read (`File`, `Exists`, `Readable`) | check, hold, observe; optionally seal |
| create (`Absent`, `Creatable` → `File`, `Exists`) | draft, then publish with `"create"` |
| write over an existing file | draft, then publish with `"replace"`, or `"exchange"` with `expect` |
| delete (`Exists` → `Absent`) | unlink: visibility ends |
| several outputs of a step together | a generation, published by one exchange |

**[Fact]** `Run` now runs `Holds` and `Makes` ports together (`tests/lifecycle_test.py`):
- an output is a draft inside the step. A concurrent reader never saw it, and saw it whole
  afterwards;
- a failed step publishes nothing and leaves nothing;
- a name taken by another writer during the step fails the step, and their file
  survives;
- two outputs of one step are each whole, but not published together.

Each output gets a `Derivation` recording the held inputs' fingerprints.

**[Interpretation]** Two things this gives the effects graph:
- **A time axis.** An output is visible from its publication event, and a consumer's
  observation of it must follow that event. A generation makes a set of outputs visible
  at one event.
- **Invalidation.** `invalidated(derivations)` reads the graph as a dependency graph
  whose edges carry observations. When another writer changed the first input of a
  two-step chain, the second step's own input was unchanged, so its derivation was not
  stale. The closure still put both outputs in doubt: `mid` because `raw` changed, and
  `final` because `mid` is in doubt.

wend can then say *when* a result became valid and visible, and what would put it in
doubt. That goes beyond which files a pipeline uses.

**[Fact]** Statically, `Makes` accepts only an expression declaring a new file, and
yields a `Draft`. Both checkers reject using a draft as a held input, sealing it, or
using a held input as a draft (`experiments/typed_core`: 17 of 17 misuses rejected
in each).

## 6. Mutants

**[Measured]** Each mechanism mutated, and what rejected it:

| mutant | rejected by |
|---|---|
| `"create"` renames over the name | the clobbering test; the durability-protocol test |
| a draft has a name from the start (no `O_TMPFILE`) | the killed-writer test, the failed-draft test, the derivation test |
| no directory sync | the durability-protocol test |
| exchange ignores `expect` | the lost-update test |
| a derivation ignores its output | the derivation test |
| the double collect does not resolve names again | the rename-over test, added for it |
| the double collect ignores its watch | the observer table of the snapshot test |

**[Fact]** The rename-over test was added because the name check survived at first. The
first mutant of it was syntactically broken, and the harness read the collection error
as "no failure". The harness now reports collection errors.

## 7. Proven, tested, and not covered

- **[Proven], under stated assumptions:**
  - no observer can know that copies of two files were coherent, against a writer who
    leaves no trace (§3);
  - a held generation is coherent under the producer's protocol (§3);
  - a draft is unnameable until published (`open(2)`, `O_TMPFILE`);
  - publication is atomic for readers (`rename(2)`);
  - `"create"` never clobbers (`linkat`).
- **[Measured] Tested here:**
  - the observer table;
  - partial visibility, killed writers, path swaps, clobbering and interleaving;
  - the visible withdrawal by compare-and-swap;
  - durability in the crash model;
  - generations under a busy producer;
  - the lifecycle through `Run`.
- **[Fact] Not covered:**
  - real power loss, and devices that reorder writes;
  - filesystems other than ext4, timestamps coarser than here;
  - writers that are other users (the tests run as root);
  - fsync semantics on NFS or fsspec stores;
  - a transaction across several directories;
  - read leases and locks as runtime mechanisms (probed in #112, not built).

## References

- Afek, Attiya, Dolev, Gafni, Merritt, Shavit, *Atomic snapshots of shared memory*,
  [JACM 40(4):873–890, 1993](https://projects.csail.mit.edu/jacm/References/afekadgms1993:873.html);
  an [introduction to double collects](https://cs.yale.edu/homes/aspnes/pinewiki/AtomicSnapshots.html).
- Pillai et al., [*All File Systems Are Not Created Equal*](https://research.cs.wisc.edu/adsl/Publications/alice-osdi14.html),
  OSDI 2014; and [*Crash Consistency*](https://cacmb4.acm.org/magazines/2015/10/192379-crash-consistency/fulltext),
  CACM 2015, on syncing the directory of a rename.
- inotify and `mmap`: the [man-pages change](https://git.tldp.org/LDP/man-pages/src/commit/7a8110f6af9f3f7f76b7ff6f054cbad64b5de83a)
  recording that `mmap`, `msync` and `munmap` produce no events.
- `open(2)` (`O_TMPFILE`), `rename(2)` (`renameat2`), `link(2)`, `fsync(2)`.
