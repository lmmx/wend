# 2026-10-22: Confinement is not consistency (research synthesis)

This entry draws together what the last three research entries found about
time-of-check to time-of-use (TOCTOU):
- [what a program knows about a path](2026-10-22-knowledge-states.md) (#108);
- [when two strings name one file](2026-10-22-aliasing.md) (#110);
- [running the plan confined to its root](2026-10-22-confined-runs.md) (#112).

It records the conclusions an owner review drew from them, and the counterexamples
found while testing those conclusions. Experiments and numbers stay in their own
entries; this one keeps the argument.

Labels: **[Fact]**, **[Measured]**, **[Proven]**, **[Interpretation]**,
**[Conjecture]**, **[Proposal]**.

> **Audit, 2026-10-22.** The text below is kept as written. [The addendum](#addendum-audit-2026-10-22)
> corrects §2 (what `RESOLVE_NO_XDEV` buys; the FIFO did not pass every check), marks
> §7's narrowed claim as an extension of the owner's sentence, and points to the later
> entries that answered §3–§4's open questions. One of those answers changes this
> entry's table of kernel mechanisms: read leases.

---

## The central insight

> **A static analysis can be logically correct while its conclusions are unsafe to act
> upon, if the execution environment does not preserve the assumptions on which that
> analysis depends.**

The analysis of families (#109) is sound under a closed world and lexical identity.
Acting on it, by skipping a check it proves redundant, is safe only while those
assumptions hold. So the execution mechanism is part of the semantics, not an
implementation detail.

**[Interpretation]** Three different things can be known about a path, and wend's design
has to keep them apart:

| guarantee | what it says | what can provide it |
|---|---|---|
| **it was true** | a check found the atom true of the path, at that moment | a check event: `Checked` at a step's entry, `Confirmed` at its exit |
| **which object** | the operations act on the object that the check examined | a held descriptor, or operations relative to a held directory |
| **it remains true** | the atom still holds now | a closed world (dataflow knowledge, not enforceable); a kernel-backed object whose property cannot change; or a new check, which is a new event |

None of the three implies another. A checked fact must never silently become one of
the other two.

## 1. The problem

**[Fact]** Checking a filesystem property and using the path are separate events:
1. check that `/workspace/stage/output` is safe to write;
2. another process replaces `stage` with a symlink to `/outside`;
3. the pipeline opens or deletes `/workspace/stage/output`, and the kernel follows the
   new link out of the workspace.

**[Interpretation]** Skipping checks makes this sharper. Without a plan, the check comes
just before the use. With a plan, a check is replaced by an inference from checks made
in earlier steps, possibly much earlier. A static plan inherits TOCTOU *across steps*:
- every fact it relies on was true when checked;
- it stays true only if nothing outside the plan acted since.

## 2. What the confined executor establishes

**[Fact] By design.** `wend._experimental.confined.Confined` makes every check and every
operation through descriptors opened by `openat2` beneath the root, with:
- `RESOLVE_BENEATH`: never above the root;
- `RESOLVE_NO_SYMLINKS`: no symlink, at any component;
- `RESOLVE_NO_XDEV`: no mount crossed, bind mounts included;
- `..` and absolute paths refused.

Parents are made with `mkdirat`, one directory at a time. Deletion opens each
subdirectory beneath its parent under the same flags. Each resolution is therefore
decided by the kernel *at the moment of use*: the guarantee moves from an earlier
observation to the operation that touches the resource.

**[Fact] Also by design, since this review.** Path confinement is not object confinement,
so each object opened is judged on its descriptor, which no later rename can redirect:
- a regular file must have exactly one name;
- anything but a regular file or a directory is refused;
- opens are non-blocking, and a file is truncated only after the judgement.

**[Measured] Tested** (tests in `tests/confined_test.py`; moves and numbers in
[confined runs](2026-10-22-confined-runs.md) §4–§5):

| another writer's move | ordinary operations | confined |
|---|---|---|
| a file swapped for a symlink out, after its check | read the outside file; checking everything did not help, since checks follow links | refused (`ELOOP`) |
| a dangling link at a name whose absence the plan knows | wrote through it, only when the check was elided | refused |
| a stage directory replaced by a link, between check and use | wrote, read or deleted outside | refused |
| a bind mount over a stage, between check and use | deleted outside files through it | refused (`EXDEV`) |
| a stage relinked to another stage *inside* the root | deleted the source while the plan believed it exists; nothing escaped | refused |
| **a file replaced by a hard link to an outside file** | read it | **first version: read and overwrote it**; now refused (two names) |
| **a FIFO planted at an input's name** | blocked indefinitely | **first version: blocked**; now refused at once |

**[Fact]** The last two rows are counterexamples to the first confined executor, found
in testing the owner's caution that confinement is not identity. Each passed every
check: the path really is beneath the root, with no link and no mount. The kernel's
resolution flags constrain *paths*; the objects at the end of them need their own
judgement.

**[Fact]** Mutating each defence shows what each buys:
- `RESOLVE_BENEATH` alone stops every *escape* tried;
- `NO_SYMLINKS` and `NO_XDEV` guard the plan's lexical identity inside the root;
- the one-name rule guards against hard-linked objects;
- the kind rule guards against FIFOs;
- non-blocking opens keep the kind rule reachable (with blocking opens, the suite hung
  on the FIFO);
- truncating after the judgement keeps a refused file intact.

Every mutant is rejected by a test.

**[Fact]** The mechanism is Linux-only, and experimental. `Beneath` refuses where
`openat2` is unavailable, and never falls back:
- on another platform it raises `UnsupportedPlatformError` before any system call,
  because the system call number means something else there;
- where the kernel lacks `openat2` (`ENOSYS`) or a seccomp filter refuses it (`EPERM`),
  it raises at construction, not at the first access.

## 3. Five properties, separated

**[Interpretation]** The owner review asked for these to be kept apart:

| property | meaning | provided by | not covered | status |
|---|---|---|---|---|
| **Path-resolution confinement** | each resolution stays below the root and reads the string as written | `openat2` flags, no `..` (and, for objects, the one-name and kind rules) | content; changes between operations | by design, tested |
| **Resource identity across operations** | two operations act on one object | a held descriptor; `*at()` operations relative to a held directory | name membership: rename, unlink and replace leave the descriptor on the old object | tested (below) |
| **Freshness of checked facts** | a fact checked earlier still holds | a closed world, not enforceable; immutable objects; re-checking | any other writer | dataflow only; kernel immutability probed |
| **Consistency across steps** | every step sees one state of the tree | nothing here | — | open |
| **Durable guarantees of held objects** | facts that survive whatever happens to names | descriptor semantics | content, size, names | tested (below) |

**[Measured]** What a held descriptor keeps, on this kernel (ext4,
`tests/held_test.py`):

| event after the open | the held descriptor |
|---|---|
| the name is renamed | the same object; reads the original |
| the name is unlinked | the same object, now with no name (`nlink` 0); reads the original |
| the name is replaced by renaming another file over it | the old object; the name now reads the new file |
| the contents are rewritten through the name | reads the *new* contents |
| the file is truncated | reads nothing |
| the file is written through a hard link | reads what was written |

**[Fact]** Access is checked when a file is opened, so removing permissions later does
not affect a held descriptor (open(2)). This cannot be shown here: the tests run as
root, which bypasses permission bits for new opens too.

**[Fact]** So a descriptor stabilises *which object*, and *the access checked at open*.
It does not freeze contents, size, or the object's names.

**[Measured]** Kernel mechanisms that keep more. The first four are tests in
`tests/held_test.py`; the rest were probed once on this machine and not kept:

| mechanism | here | what it gives |
|---|---|---|
| immutable flag (`FS_IMMUTABLE_FL`, needs `CAP_LINUX_IMMUTABLE`) | tested | writes and unlinks refused, for root too, until the flag is cleared |
| sealed memfd copy (`F_SEAL_WRITE`, `SHRINK`, `GROW`) | tested | contents immutable for every holder, including another descriptor for the same object: a snapshot in memory |
| `O_TMPFILE` then `linkat` | tested | an output nameless until whole, then published |
| `renameat2(RENAME_NOREPLACE)` | tested | publish without clobbering (`EEXIST`) |
| `renameat2(RENAME_EXCHANGE)` | probed | swap two names atomically |
| read lease (`F_SETLEASE`) | probed: granted | per fcntl(2), a writer's open is delayed and the holder notified: notice, not prevention |
| reflink snapshot (`FICLONE`) | probed: `ENOTSUP` on ext4 | a copy-on-write snapshot of contents |
| fs-verity | probed: `ENOTSUP` here | contents read-only and verified for ever |

## 4. What remains unsolved

**[Fact]**
- **Arbitrary concurrent mutation inside the root:**
  - existence: deletion and creation;
  - permissions: they affect later opens, not held ones;
  - contents and size;
  - renames, which move names between objects.

  Confinement turns many of these into failed accesses, but it prevents none.
- **Hard links in general.** The one-name rule refuses any multiply linked regular
  file. That is a cost: legitimate hard-link farms (package stores, `cp -al`
  snapshots) are refused too. It also judges only at the open: a name added later
  makes the held object visible elsewhere. Directories cannot be hard-linked.
- **Transactional consistency.** No mechanism here gives a pipeline one consistent
  view of a tree across its steps.
- **Case folding**, untestable on this kernel.

**[Conjecture]** Consistency across steps could be approached in two ways:
- **Detection.** Fingerprint each input when it is first held (device, inode, size,
  `mtime`, a content hash), and revalidate before each later use. Build systems take
  this route with content digests. It detects; it does not prevent.
- **Prevention, by snapshot.** Use a sealed copy, a reflink or a filesystem snapshot,
  where available.

Outputs can be published atomically (`O_TMPFILE` then `linkat`, or `renameat2`), so a
reader never sees a partial file. None of this is built yet.

## 5. What this means for the types

**[Interpretation]** Four layers, each with its own lifetime:

| layer | example | what it certifies | how long |
|---|---|---|---|
| declaration | `PathExpr.declares` | the obligations stated | always: a property of the expression |
| check event | `Checked` (entry), `Confirmed` (exit) | the atoms held of that path when checked | that moment; carries its epoch |
| knowledge | `known()` | no effect *of this program* has invalidated the event since | until such an effect; blind to other writers |
| held object | `Held[...]` | kind, identity, and access checked at open, of an open object | while it stays open |

**[Proposal]** What follows for the API:
- `Checked` and `Confirmed` stay events. Their names should not suggest persistence,
  and nothing converts them into a held guarantee implicitly.
- `known()` says "not invalidated by this program". A fresh check is a new event.
- `Held[...]` may claim only object facts that the descriptor keeps:
  - its kind (`IsFile`);
  - the access it was opened with (`read`, `write`);
  - its identity.

  It must not claim facts about names (`absent`, `create`), about contents, or about
  size.
- A function that needs durable *content* must ask for a sealed or immutable object,
  which is a different type again.

The typed-core work that follows tests whether Pyright and ty can enforce these lines.

## 6. The relationship to the essays

**[Interpretation]** Future Paths argued that *a path should be a plan, not a value*
([trajectory](2026-10-17-trajectory-40.md) §1).
- Part 1 asked for paths that carry intent: `Under[ROOT]`, capabilities,
  must/must-not exist. Those are now declarations, atoms and their check events.
- Part 2 asked for relations as values. Overlap and prefix cancellation now decide
  which paths can interfere.
- Parts 4 and 5 asked to "build once, resolve many". The plan over families is built
  once and run under every binding.

This work adds a link the essays did not make. Each of the three is a theory of what
paths *mean*, and acting on that meaning is safe only under conditions that the
execution has to provide. They form one architecture:

1. **Path algebra:** what each expression can denote, symbolically.
2. **Symbolic dependency analysis:** which obligations follow from which, before any
   binding.
3. **Constrained execution:** the runtime enforces the assumptions under which (2) is
   safe to act on, and turns violations into errors.
4. **Typed knowledge of program state:** types and runtime state record which of the
   three guarantees each fact carries.

## 7. Claims, narrowed

**[Fact]** The confined-runs entry first answered "can symbolic overlap reasoning
support sound pre-execution analysis of actual pipelines?" with *yes, for atoms of
names*. That overstated it. What the evidence supports is narrower:

> Confined execution prevented the tested path-resolution attacks from escaping the
> workspace, and the tested object attacks too once objects were judged on their
> descriptors, while preserving the behaviour of honest runs.

The plan's conclusions remain facts about the past (*it was true*). Confinement adds
*which path*, and holding adds *which object*. *It remains true* is still provided only
by a closed world, or by kernel-backed immutability, which nothing here uses yet.

`openat2` does not solve TOCTOU in general. It solves path resolution at the moment of
use.

## References

- PRs: #107 (declarations), #108 (knowledge), #109 (families), #110 (aliasing and
  identity), #111 (`Creatable` across broken links), #112 (confined runs).
- Tests: `tests/knowledge_test.py`, `tests/families_test.py`, `tests/aliasing_test.py`,
  `tests/confined_test.py`, `tests/held_test.py`.
- [openat2(2)](https://man7.org/linux/man-pages/man2/openat2.2.html);
  [fcntl(2)](https://man7.org/linux/man-pages/man2/fcntl.2.html), for leases and seals;
  [cap-std](https://github.com/bytecodealliance/cap-std), the same discipline in Rust.

---

## Addendum: audit (2026-10-22)

### A.1 Corrections

- **[Refuted] §2, "`RESOLVE_BENEATH` alone stops every *escape* tried".** Without
  `RESOLVE_NO_XDEV`, a bind mount below the root leads outside, and the mutant escapes.
  `BENEATH` stops links that leave the root, and `NO_XDEV` stops mounts that do. Only
  `NO_SYMLINKS` guards identity alone. The details are in
  `2026-10-22-confined-runs.md`, addendum A.1.
- **[Refuted] §2, the FIFO row "passed every check".** The FIFO probe checked only
  `exists` and `read`. The pipelines' read role declares `File`, which refuses a FIFO in
  both executors. The FIFO is a hazard when the plan elides `File`, or when a FIFO is
  swapped in after the check. The hard link did pass every check.
- **[Narrowed] §7, the narrowed claim.** The owner's sentence was: "Confined execution
  prevented the tested path-resolution attacks from escaping the workspace while
  preserving the behaviour of honest runs." The version above adds "and the tested
  object attacks too once objects were judged on their descriptors". That is an
  extension, and it should have been marked as one.

  "Honest runs" also needs a precondition since objects are judged. An honest tree with
  a multiply linked file or a special file below the root is refused confined and read
  plain (`2026-10-22-confined-runs.md`, addendum A.2).
- **[Narrowed] §3, two meanings of "durable".** In "durable guarantees of held objects"
  it means *persisting across changes of names*. In #114 it means *surviving a crash*.
  The two are unrelated.

### A.2 What later work answered

Each item below was open when this entry was written. The text above is kept as the
state of knowledge at the time.

- **§4's conjectured fingerprint** was "(device, inode, size, `mtime`, a content hash)".
  #114 measured that it needs `ctime` as well: a rewrite with `mtime` restored is seen
  only by `ctime`. Even then, a writer through dirty pages of a shared mapping escapes
  every observer, but only while the page stays dirty: the first write after writeback
  moves `ctime` again (`2026-10-22-synthesis.md` §4).
- **"None of this is built yet" (§4) and "Consistency … open" (§3).**
  - #114 built observation, drafts, publication and generations.
  - The synthesis built versioned stores, pinned and verified reads, and leased
    snapshots.
- **"It remains true … by kernel-backed immutability, which nothing here uses yet" (§7).**
  `Store.commit(immutable=True)` uses it. With the flag set, every write tried is
  refused, including through a shared mapping made before the flag (`SIGBUS`).
- **§3's read-lease row.** It said "notice, not prevention". That is right about a
  writer who arrives later: its open is delayed, and the holder is notified. It missed
  the other half: a read lease is *refused* while any process has the file open for
  writing, including the dirty-mapping writer no observer sees. Together the two halves
  give an interval in which no writer exists, and with it a coherent snapshot of several
  files by exclusion (`2026-10-22-synthesis.md` §4.2).

  This entry, and #114 after it, filed multi-file consistency under "needs
  cooperation". It needs either cooperation or privilege, ownership or `CAP_LEASE`.
- **Typed-core §5's "Confinement removes aliasing as a source of error"** omits case
  folding, which `openat2` does nothing about (aliasing §9, assumption 3). The
  typed-core addendum records it.

### A.3 Where this leads

The research index, `2026-10-22-research-index.md` on the latest research branch,
orders the entries. `2026-10-22-synthesis.md` §6 holds the current classification of
every guarantee.
