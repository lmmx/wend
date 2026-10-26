# 2026-10-26: Two load-sensitive failures, and an inode number reused (#ABA)

During #130, two tests failed under heavy load, each passing on a re-run:
- `synthesis_test.py::test_exchange_and_validate_loses_an_update_with_three_writers`;
- `declares_test.py::test_bind_rebase_tag_and_p_keep_the_atoms`.

Neither file was touched there, and the first failed on master too, so they were set
aside as pre-existing. This entry finds out what they were. The first is a defect in
`publish`'s exchange-and-validate, which load makes likely. The second did not fail
again in 300 runs, and what it was is not recorded: §5 says what was tried and what is
left.

Labels: **[Fact]**, **[Measured]**, **[Proven]**.

## 1. The three writers: an inode number reused

**[Measured]** After a restart of the container, the test failed in 38 of 40 runs,
under a load of about four busy processes. Every failure was the same: writer C believed
`"published"`, where the schedule makes it `"conflict"`.

**[Measured]** A probe recorded the inode number of each writer's draft, in six runs.
Every time, B's draft had the number of `X0`, the object all three writers observed:

| `X0` | A | B | C | beliefs |
|---|---|---|---|---|
| 2596977 | 2596994 | 2596977 | 2597009 | A, C published; B conflict |
| 2597105 | 2597121 | 2597105 | 2597137 | the same |

(four more runs alike). The filesystem was ext4.

**[Proven]** What happens. The writers observe `X0` as `(st_dev, st_ino)`.
1. A exchanges its draft in, finds `X0` came out, and unlinks it. `X0`'s inode is free.
2. B's draft is made after that, and ext4 gives it `X0`'s number.
3. B exchanges in, finds A's object, and undoes.
4. C exchanges in before B's undo, and finds B's object. B's object has `X0`'s
   `(st_dev, st_ino)`, so it passes for `X0`, and C believes it published.

Load makes step 2 likely: the threads start apart, and B makes its draft after A has
finished. The test's schedule fixes the order of the exchanges, not of the drafts.

**[Proven]** The defect is not the three writers'. With two, A publishes twice, its
second draft is given `X0`'s number, and B, still expecting `X0`, replaces A's second
version, told that nothing changed: an update lost. SEMANTICS §14.4 promised two writers
detection.

**[Measured]** The fix:
- `publish.identity()` gives `(st_dev, st_ino, generation)`. The generation is ext4's
  `FS_IOC_GETVERSION`, drawn anew for each inode, or `None` where the filesystem keeps
  none.
- `expect` may be an identity; then the generation is compared too.
- `publish_test::test_a_reused_inode_number_passes_for_the_object_observed` makes drafts
  until one is given the observed number (at once, on ext4), publishes it, and shows:
  - an `expect` of `(st_dev, st_ino)` accepting it;
  - an identity refusing it.

  It skips only where the filesystem refuses the ioctl.
- The three-writer test holds `X0` open, so its number is not reused, and tests what
  it was written for, the lost update. 0 failures in 30 runs, under the same load.

## 2. Found on the way: a draft that lost its name

**[Measured]** After a `Conflict`, the docstring said the draft was "unpublished, and
live". Publishing it again fails with `ENOENT`. `linkat` names an `O_TMPFILE` object
only while it has never had a name. An `"exchange"` or `"replace"` first links the draft
under a fresh name, and a failure unlinks it, so the object can never be named again.

A refused `"create"` makes no link, and its draft can still be published
(`test_create_never_clobbers_where_checking_first_does`). After any failure past the
link, `Draft.nameable` is now false, and `publish` refuses with that reason. The draft can
still be written, read and abandoned.

## 3. Mutants

Against `tests/publish_test.py` and `tests/synthesis_test.py`:

| mutant | killed by |
|---|---|
| the generation ignored | `test_a_reused_inode_number_passes_for_the_object_observed` |
| the generation never read (`None`) | the same; it skips only where the ioctl is refused |
| a draft that lost its name still nameable | the same, and `test_exchange_with_expect_undoes_a_lost_update_but_was_visible` |
| the identity taken of the name, not of what came out | the same, and the three-writer test |

## 4. What this does not fix

- Elsewhere a `(st_dev, st_ino)` names an object only while something holds it:
  - `Generation` compares directories it holds open;
  - fingerprints also compare contents and times.

  Each such comparison should be audited for an object that may be gone.
- On filesystems with no generation (tmpfs, many others), an identity is the number
  alone. tmpfs numbers inodes from a counter, so reuse there needs a wrap.

## 5. The declares test: not reproduced

**[Fact]** The failure was seen once, in a full run of the suite under heavy load:
`FAILED tests/declares_test.py::test_bind_rebase_tag_and_p_keep_the_atoms - hy...`.
pytest truncated the message to its first characters, the start of a Hypothesis error
(`hypothesis.errors....`), and the session kept nothing more. The record of "fails on
master once in six runs" was of the two files run together, and those runs are
indistinguishable from the synthesis test's failure, which shared them.

**[Measured]** Tried since, on master's tree:

| what | runs | failures of this test |
|---|---|---|
| alone, Hypothesis seeds 0 to 149 | 150 | 0 |
| the file alone, random seeds | 40 | 0 |
| alone, `PYTHONHASHSEED` 0 to 79, seed 0 | 80 | 0 |
| with `synthesis_test.py`, under a load of about five processes | 30 | 0 (the synthesis test failed in 23) |

**[Proven]** Two causes ruled out by reading the code:
- `declarations` keeps the bases `Under` in a list, in order, and `moved` maps them in
  order. So the order the test asserts does not depend on string hashing (the hash
  sweep agrees).
- The test sets `deadline=None` and suppresses `too_slow`, the two checks Hypothesis
  times.

**[Fact]** What is left is not decided. A health check that counts rejected examples
(`filter_too_much`) fails only on rare seeds, and none of the 270 seeds tried
triggered it. A cache shared with tests earlier in the same process could also change
an example's result on replay, which Hypothesis reports as flaky. Neither is shown.
The test stays as it is, and a failure next time should be recorded in full (`-rf`, and
the Hypothesis seed it prints).
