# 2026-10-22: Consolidating the research stack: a plan (proposal)

The owner asked for a plan to consolidate the duplicated executors. Synthesis §9 proposed
one in a table. This entry makes it concrete:
- what each duplicate is, and what depends on it, counted in the tree at #115's head;
- the target;
- the commits that would reach it, in order, each with its check;
- what must not change;
- what the owner decides.

**Nothing here is done.** It needs the owner's approval, and no research history is
discarded by it. Every commit it proposes is a new commit on top of the stack, and the
stack's commits stay as they are.

## 1. What is duplicated, and what depends on it

**[Measured]** Counted with `grep` over `src/` and `tests/` at #115's head:

| component | from | what it is now | its users in `src/` | its users in `tests/` |
|---|---|---|---|---|
| `knowledge.Tracker` | #108 | an executor that checks, learns and forgets, keyed by strings | none (`identity` imports only `knowledge`'s constants and `Entry`) | `knowledge_test`, `families_test`, `aliasing_test` |
| `identity.IdentityTracker` | #110 | the same, facts keyed by what each check reads | none | `aliasing_test` |
| `confined.run` | #112 | an executor over `Confined` or `Plain`, eliding checks a plan knows | none | `confined_test`: the plain-vs-confined agreement property, never-outside, the moves table |
| `events.Run` | #113–#115 | the executor of typed steps: ports, holds, seals, drafts, versions, leases, derivations | `experiments/synthesis/pipeline.py` | `events_test`, `lifecycle_test`, `leases_test`, `synthesis_test`, the typed-core experiments |
| `identity.Held` | #110 | a held descriptor, judged at no point | `events.Held` extends it | `held_test`, `aliasing_test` |
| `identity.Beneath.hold` | #110 | opens beneath a root without judging the object (identity addendum) | none | `aliasing_test` only |
| `publish.Generation` | #114 | several outputs published as one directory | none | `consistency_test`, `lifecycle_test`, `synthesis_test` (the counterexample "a pinned directory is not a snapshot") |
| Linux system calls | #110–#115 | `openat2` (`identity`, by `ctypes` syscall), `renameat2` (`publish`, by libc), `FS_IOC_*FLAGS` (`publish`, by `ioctl`), inotify and `fstatfs` (`fresh`, by `ctypes`), leases (`fresh`, `fcntl` and a helper), memfd seals (`events`, `fcntl`) | five modules | through them |

**The executors differ in what they guarantee, not only in code.**
- **`Tracker`** checks by path and keys facts by string. It is sound only under the
  closed world and lexical identity (#108).
- **`IdentityTracker`** keys facts by read set. It is sound without lexical identity,
  and still under the closed world (#110).
- **`confined.run`** resolves every path beneath the root, and judges objects on their
  descriptors (#112).
- **`Run`** does all of `confined.run`'s resolution and judgement, judges a held
  input's kind on its descriptor as well (typed-core §6), adds the typed ports and the
  mechanisms of #114 and the synthesis, and keys knowledge by string. That is
  sound because a confined run is alias-free (aliasing §5). It does not elide checks.

## 2. The target

**One executor, `events.Run`, and the analyses as libraries.**
- **Knowledge.** `knowledge.Knowledge` (string-keyed) and `identity.IdentityKnowledge`
  (read-set-keyed) stay, as analyses. `Run` keeps `Knowledge`, which a confined run makes
  sound. `IdentityKnowledge` stays the model for a run that is not confined, and the
  oracle that string keys agree with it on alias-free runs.
- **Elision.** `confined.run`'s plan elision moves into `Run`, as an option. It keeps the
  rule that after a failure nothing is elided (#112's mutant table: "the plan kept after
  a step fails").
- **Oracles.** `Tracker`, `IdentityTracker` and `confined.run` move to `tests/`, renamed as
  what they are now: references the tests compare against.
  - `confined.run` with `Plain` is the agreement property's other side, so it cannot
    simply be deleted.
  - Nothing in `src/` uses any of them.
- **`Held`.** One class. `identity.Held`'s behaviour moves into `events.Held`.
  `identity.Held` stays as an alias for one release, then goes.
- **`Beneath.hold`.** It goes. It opens without judging the object, which #112 showed to
  be the hole (hard links, FIFOs). `aliasing_test`'s one use moves to `Confined._open`.
- **`Generation`.** It stays only as the counterexample, moved into `tests/` with the
  test that shows a pinned directory is not a snapshot. `Store` is the mechanism.
- **System calls.** They move into one module, `_linux`, each with its platform check
  and its `errno` translation. The five modules import from it.

## 3. The commits, in order

Each is a commit of its own, checked by the full suite, the privileged CI job, both type
checkers' marker suites, and the mutation harness. Each mutant must still meet its
expectation after the move, for the harness checks the moved code.

1. **`_linux`.** Move the system-call wrappers, with no change of behaviour.
   - The harness's passages move with them: its mutants name file and text, so this is
     the commit that will find a passage gone.
   - Check: all mutants meet their expectation; the privileged job passes.
2. **`Held`.** Merge the two classes and remove `Beneath.hold`.
   - Check: `held_test` and `aliasing_test` unchanged in outcome.
   - Check: the "objects of any kind allowed" and "hard-linked files allowed" mutants
     still killed, and so is "a held input's kind is left to the earlier check": the
     merged class must keep the kind judgement at the hold.
3. **Elision in `Run`.** Port `confined.run`'s elision, with its after-failure rule.
   - Port the agreement property to `Run`: a run of the plan with elision equals a
     checked run.
   - Check: the "plan kept after a step fails" mutant, re-targeted at `Run`, is killed.
4. **Oracles to `tests/`.** Move `Tracker`, `IdentityTracker`, `confined.run` and `Plain`
   into `tests/oracles.py`.
   - Check: every test that imported them passes unchanged but for the import.
5. **`Generation` to `tests/`.** Check: the counterexample test passes.
6. **Typing.** `Run.enter`'s stub (`events.pyi`) gains the elision option.
   - Check: `experiments/typed_core/check.py` in both checkers, with its markers
     extended.

**Not proposed:** changing any guarantee. Every row of synthesis §6, as revised by the
leases and drafts entries, must hold after step 6 as before step 1.

## 4. What must not change

The tests and records that pin the current behaviour, and so must pass, or meet their
expectation, after every commit:
- the 1,184 tests at #115's head, as root: 1,165 in `tests/` and the documentation's 19
  examples. Also those the unprivileged job runs, with the privileged ones listed as
  not run;
- the 31 privileged tests, in the CI job that requires them;
- the mutation harness: each of its 65 mutants meets its expectation;
- `experiments/typed_core/check.py`: every file matches its markers in Pyright and ty;
- the soundness experiment of #113: 0 unsound in 400 programs, every target reached;
- the example pipeline's ten scenarios, each with the outcome synthesis §6 classes it
  under.

## 5. Risks

- **The merge order of the PRs.** The plan assumes the stack is merged as one branch of
  history, as synthesis §9 proposed. Done on unmerged branches, each commit would have
  to be merged up the stack again.
- **#111.** If #111 merges first, `identity._key`'s creation clause becomes removable
  (aliasing addendum A.2). That is a separate, later commit, with the creation mutant
  moved to "survives, equivalent".
- **#113's core typing.** It is in `src/wend`, not `_experimental`. Consolidating the
  experimental half does not touch it, and it should be reviewed alone first.
- **The harness's passages.** Moving code breaks them by design. Step 1 must update them
  in the same commit, or the harness reports "passage occurs 0 times", correctly.

## 6. What the owner decides

- whether to consolidate at all before the research is reviewed, or after;
- whether the oracles move to `tests/` or stay in `_experimental` with docstrings saying
  what they are;
- whether `Generation` is kept anywhere outside the tests;
- whether `identity.Held` keeps an alias for a release.
