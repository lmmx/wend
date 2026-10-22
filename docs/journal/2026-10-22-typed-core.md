# 2026-10-22: The typed core, and three guarantees as three types (research)

[The typed path families entry](2026-10-21-typed-path-families.md) (#106) gave wend's
declarations a static type, but in a separate facade module.
[Confinement is not consistency](2026-10-22-confinement-is-not-consistency.md) then
separated three things a program can know:
- that a fact **was true**;
- **which object** it is acting on;
- that a fact **remains true**.

This entry asks two questions:
1. Can core `wend.PathExpr` itself carry #106's encoding, and at what cost to runtime
   and to type inference on existing code?
2. Can the types keep the three guarantees apart, so that a checked fact cannot silently
   become a durable one?

The changes are in `src/wend/_kinds.py`, `conditions.py`, `_expr.py` and
`_experimental/events.py` (with `events.pyi`). The static programs and the soundness
harness are in `experiments/typed_core/`; the runtime tests are in
`tests/events_test.py`.

Labels: **[Fact]**, **[Measured]**, **[Proven]**, **[Interpretation]**,
**[Conjecture]**, **[Proposal]**.

> **Audit, 2026-10-22.** The text below is kept as written. [The addendum](#addendum-audit-2026-10-22)
> records two ways the types claim more than the checks (an event's type carries every
> declared atom; a path derived from an event is still that event), a much wider ty gap
> than §4 says, what the soundness harness could not see, and how the corrections of §3
> were measured.

---

## 1. The change

**[Fact]** `PathExpr` is now generic, `PathExpr[C, K]`, as in #106:
- `C` is contravariant: the union of declared atoms, with `post_*` for postconditions
  and `Under[...]` markers. Its default is `Never`, which declares nothing.
- `K` is covariant: `IsFile` once `File` is declared, `Unspecified` otherwise.

`Condition` is generic over the atom it adds when required (`Pre`) and when ensured
(`Post`). `File` is a `FileCondition`, which also sets `IsFile`. `requires` and
`ensures` take #106's fixed-arity overloads: one type variable per condition, `File`
first. `bind`, `rebase` and `tag` keep `[C, K]`, and derived expressions declare
nothing.

**[Fact]** `check()` returns `Checked[C, K]` and `confirm()` returns
`Confirmed[C, K]`. Both are `Path` subclasses, and neither is a subclass of the other.
Each is an **event**: the atoms held when checked, at a step's entry or at its exit.

## 2. What it costs

**[Measured] At runtime, nothing per operation.** Alternating runs, best of 5:

| operation | before | after |
|---|---|---|
| construct `P(root) / "raw" / T(...)` | 5.7–6.2 µs | 5.6–6.1 µs |
| `requires(File, Exists, Readable)` | 2.7–3.2 µs | 2.7–3.1 µs |
| `requires(...).ensures(...)` | 5.3–6.2 µs | 5.2–5.7 µs |
| `render` | 3.0–3.2 µs | 3.0–3.4 µs |

`import wend` takes about 3–4 ms more (median 33.7 → 37.2 ms), which goes on the
overload declarations.

**[Measured] For type checking, after three corrections (§3).** Errors on the
repository's own code, with Pyright 1.1.407 and ty 0.0.90:

| target | Pyright, before → after | ty, before → after |
|---|---|---|
| `src/` | 0 → 0 | 9 → 9 (the same, at shifted lines) |
| `tests/` | 196 → 198 | 127 → 127 |
| `examples/` | 5 → 5 | 3 → 3 |

The two new Pyright errors in `tests/` are one true positive, counted twice:
`conditions_test.py:72` passes the string `"Exists"` to `requires`, to test the runtime's
`TypeError`. ty reports the same line instead of one it no longer reports. Checker run
times did not change (about 7 s for Pyright, 0.4 s for ty).

## 3. Three corrections that measuring found

**[Fact]** The first version cost 31 Pyright errors in `src/` and 46 in `tests/`. Each
cause is a property of the encoding that #106's facade, having no internal code and no
untyped callers, could not show:

1. **`K` needs an upper bound.** Core helpers annotated with a bare `PathExpr`, which
   means `PathExpr[Never, Unspecified]`, received `self` of type `PathExpr[C, K]`. With
   `K` unbounded, that is not assignable. `bound=Unspecified` removes almost all of the
   31. The rest needed the same bound on `P`'s own type parameter, and two `cast`s
   where the runtime carries the declarations through a helper typed bare.
2. **An unknown kind must not read as a File.** The overload that rejects a join below a
   File (`self: PathExpr[Any, IsFile] → JoinBelowFile`) came first, and a receiver of
   unknown kind matches it. An untyped pytest fixture passed through `P` was enough:
   `P(dist) / x` became `JoinBelowFile`, and 44 of the new errors in `tests/` followed.
   The fix is a marker, `NotFile`, disjoint from `IsFile` and never produced. The first
   overload asks for it, so an unknown kind takes it and joins as a path, and only a
   known `IsFile` reaches the rejecting overload.
3. **A literal base is also "some base".** `Under("/srv")` declared only
   `Under[Literal["/srv"]]`, so it did not satisfy a demand for `Under[str]` ("under its
   own base"), in either checker. #106's runtime facts count both atoms, so the old
   static type was sound but incomplete. Every `Under` now also declares `Under[str]`.

## 4. What the static types say

**[Measured]** Running `experiments/typed_core/check.py`:
- **`positive.py`** has no errors in either checker, apart from one known ty gap;
- **`negative.py`** has an error on exactly its 13 marked lines, in both checkers;
- every ty message names the intended reason.

The misuses rejected:
- a checked path where a held file is asked;
- a held file where a sealed copy is asked;
- an entry event where an exit event is asked, and the reverse;
- an output where a readable input is asked;
- read access where write access is asked;
- holding an expression not declared a File, or not declared Readable;
- joining below a File;
- an absence (a fact about a name) asked of a held object;
- an event widened to atoms that were not checked;
- `Confirmed` assigned to `Checked`.

**[Measured] The ty gap.** ty 0.0.90 takes the `File`-first overload with two further
conditions only when the call has no expected type:
- `x = P("a").requires(File, Exists, Readable)` gives `IsFile`;
- the same call inside `reveal_type`, or in an annotated assignment, takes the general
  overload and gives `Unspecified`.

With none or one further condition, ty is consistent; Pyright is consistent in every
case. The result claims less, never more, so the gap is in precision, not soundness.
`check.py` expects it with an `# E-ty:` marker, so a fixed ty will show as a mismatch.
The latest ty available here was 0.0.90.

**[Measured] The soundness harness**, ported from #106 to core types, ran 400 random
programs and 1,511 statements (seed 1). In each statement the types were revealed and
compared with what the runtime declares:

| | Pyright | ty |
|---|---|---|
| unsound (static claims an atom or kind the runtime lacks) | **0** | **0** |
| exact / weaker | 1,413 / 36 | 1,413 / 36 |
| undeclared atoms demanded in context, accepted | 0 of 5,645 | 0 of 5,645 |
| declared atoms demanded in context, rejected | 0 of 507 | 0 of 507 |
| rejected at runtime, not statically | 57 | 57 |

The 57 are declarations the runtime refuses and the types do not model: contradictions
such as `Exists` with `Absent`, and a `rebase` that is not static. They are imprecise,
not unsound.

## 5. The three guarantees, as three types

**[Fact]** `wend._experimental.events` builds the layer above the core:

| guarantee | type | given by | durable? |
|---|---|---|---|
| it was true | `Checked[C, K]` at entry, `Confirmed[C, K]` at exit | `Run.enter`, stamped with an epoch | no: `Run.known(event)` says whether *this run* has invalidated it, assuming no other writer |
| which object | `Held[Literal["read"], IsFile]` | a `Holds` port, opened beneath the root and judged on its descriptor | its object, kind and access, while open |
| it remains true | `Sealed` | `seal(held)`: a memfd with write, shrink and grow sealed | its contents, for every holder |

- `Holds` accepts only an expression declaring `File`, `Exists` and `Readable`, at type
  level and at runtime.
- `Run` executes confined (`confined.Confined`) and keys its knowledge by rendered
  strings (`Knowledge`). Confinement removes aliasing as a source of error, by the
  bridge of [the aliasing entry](2026-10-22-aliasing.md#5-the-bridge-alias-free-runs),
  and nothing more. Another writer can still change, create or delete an ordinary file
  inside the root. So `Run.known(event)` is knowledge **conditional on the closed
  world** (no writer below the root but the run's own steps), not a fact about the
  filesystem now.

**[Interpretation]** No API converts one guarantee into another:
- `seal` takes a `Held`, not a `Checked`;
- nothing takes a `Checked` where a `Held` is needed;
- `known` answers about the run, never about the world.

This is the review's requirement in types: *a checked fact must not silently become a
timeless guarantee*.

## 6. Whether `Held` gives what its type claims

**[Measured]** From `tests/events_test.py` (13 tests) and `tests/held_test.py`:

| after the hold | the held input |
|---|---|
| its name is renamed, unlinked, or replaced by renaming another file over it | the same object (device, inode); reads the original contents |
| its contents are rewritten by another writer | the same object; reads the **new** contents |
| another name is linked to it | the same object, now with two names; the one-name rule held at the open, not since |
| its `path` is opened again after a replacement | another object: `path` is only the name it was opened by |
| an outside file is swapped in as a hard link, between the check and the hold | refused: the hold judges the object on its own descriptor |
| it is sealed, then the file is rewritten | the sealed copy keeps the original contents; writing to it is refused (`EPERM`) |

**[Fact]** `Held[Literal["read"], IsFile]` claims a regular file (an inode's type never
changes) and read access (the descriptor was opened read-only). Both hold while it is
open. It claims nothing about contents, size, names, or the number of names. A
function that needs unchanging contents asks for `Sealed`.

**[Measured]** Three mutants of the layer, each rejected:

| mutant | rejected by |
|---|---|
| `known` always true | the invalidation test |
| no write seal | the sealed-copy test |
| inputs held without the object judgement | only the swap-between-check-and-hold test |

The last one survived at first. The check of `Readable` already judges the object, so
the hold's own judgement matters only in the race between the two opens, which no
test produced until one was written for it.

**[Fact]** `Run.known` is blind to other writers. Another process deletes a file that a
`Checked` event examined, and `known` still answers true. That is its definition, not a
defect, so the test asserts it.

## 7. Limits

- **[Fact]** Only inputs held for reading exist. Outputs held for writing (`O_TMPFILE`
  then `linkat`, see the synthesis §3) are not built.
- **[Fact]** The atoms and epoch of an event live in its `__dict__` at runtime, untyped.
  The ports of a `Spec` are typed through descriptors, as in #106. `PathUnion` is not
  generic.
- **[Fact]** The costs were measured on this repository's code only.
- **[Interpretation]** The generic core is research. Section 3 shows that the encoding's
  interaction with unknown types and internal annotations matters more than its
  runtime cost; code that relies heavily on inference elsewhere could find more cases.

---

## Addendum: audit (2026-10-22)

The journals of the research stack were audited against the commits, the tests and the
session record. The audit's probes ran in both checkers (Pyright 1.1.407, ty 0.0.90).
A1 and A2 and the ty gap of A3 were re-run here. They change what this entry claims, so
they come first.

### A.1 Refuted: an event's type is the atoms checked

**[Measured]** `Checked[C, K]` and `Confirmed[C, K]` carry `C`, the expression's
*whole* declaration, both phases. The runtime event carries only the atoms its check
examined. So the type claims checks that never happened:
- for an output `out = e.requires(Absent, Creatable).ensures(File, Exists)`,
  `out.check()` is typed
  `Checked[Literal["absent", "create", "post_file", "post_exists"], IsFile]`, while its
  runtime atoms are `{"absent", "create"}`;
  - both checkers accept it where `Checked[Literal["post_exists"], IsFile]` is asked, at
    entry, before the file exists;
- for an input with no postconditions, `raw.confirm()` is typed with `read`, and both
  checkers accept it where `Confirmed[Literal["read"], IsFile]` is asked. `confirm`
  checked nothing.

§1's "Each is an **event**: the atoms held when checked" is true of the runtime, not of
the type. The knowledge entry's "A static type can carry this faithfully" (§6 there) is
refuted with it.

`negative.py`'s "an event widened to atoms that were not checked" assumed the
checked-atoms reading. It rejects widening *beyond the declaration*, which is not the
same thing.

**[Interpretation]** The cause is structural. One parameter `C` holds both phases,
distinguished only by the `post_` prefix, and Python's types cannot filter a union by
prefix. The repair is two parameters, `PathExpr[Pre, Post, K]`, with
`check() -> Checked[Pre, K]` and `confirm() -> Confirmed[Post, K]`. That changes every
overload, so it is recorded here as **[Proposal]**, not made.

### A.2 Refuted: a path derived from an event is not that event

**[Measured]** `Checked` and `Confirmed` subclass `pathlib.Path`, and pathlib builds
derived paths with `type(self)` (`with_segments`). So `c.parent`, `c.with_name("x")` and
`c / "below"` are all, statically *and at runtime*, `Checked` with the original atoms:
- at runtime they are `Checked` instances without the `atoms` and `epoch` that
  `Run.known` reads;
- statically, both checkers accept `was_readable(c.parent)`, a directory never checked;
- with `serve` demanding `Checked[Literal["read"] | Under[Literal["/srv/static"]]]`, both
  accept `serve(ok.parent.parent)` and `serve(ok / ".." / ".." / "etc" / "passwd")`.

That is a containment failure in the essay's own `serve_static` example. #106's
JoinBelowFile rule does not reach events, which are not `PathExpr`s.

#106 saw the mechanism ("Path subclass ok", in its probe of a `Path` subclass) and did
not follow it.

**[Proposal]** Events should not *be* paths. Two ways to get there:
- an event holding a plain `path` attribute. This breaks `check()`'s contract of
  returning a `Path`;
- `with_segments` returning a plain `Path`. This fixes the runtime, but the static
  types still say `Checked`, and overriding the derived methods with a wider return type
  is an incompatible override in Pyright.

Neither is made. This is the largest open question of the typed core.

### A.3 ty's gap is much wider than §4 says

**[Refuted] §4: "With none or one further condition, ty is consistent".** ty 0.0.90
gives `P("a").requires(Exists, Readable)` the type `PathExpr[Never, Unspecified]`, even
with no expected type (`reveal_type`). Every atom is dropped. Re-run here:
- `b: PathExpr[Literal["exists", "read"]] = P("a").requires(Exists, Readable)` is
  rejected by ty and accepted by Pyright;
- a single condition is fine;
- an inline `Holds((P(root) / ...).requires(File, Exists, Readable))` is rejected by ty;
- the chained `.requires(File).requires(Exists, Readable)` comes out as
  `PathExpr[Literal["file"], IsFile]`.

`common.py` avoids all of this by binding `raw` to a name first. So ty rejects ordinary
inline declarations. That costs precision, not soundness, but it is far from the corner
case §4 describes.

**[Measured]** The audit's minimal model shows the trade-off:
- with `Pre` invariant (#106's fix for Pyright's widening), ty rejects 2 valid
  assignments;
- with `Pre` covariant, ty accepts 3 of 5 widenings to unions of several atoms, which
  is unsound, and Pyright accepts 4 of 5.

#106 §4.3's "ty accepted none" holds only for single-atom demands. With this encoding,
ty 0.0.90 cannot be both sound and precise.

### A.4 What the soundness harness could not see

**[Fact]** "0 unsound in 1,511 statements" covers only the transfer rules of `PathExpr`:
- its grammar has no `check`, `confirm`, `Run`, `Held`, `Sealed` or `Makes`, so it could
  not find A1 or A2;
- its statement phase reveals a variable with no expected type, so it could not find
  A3;
- its context phase demands single atoms only, takes its must-pass demands from
  Pyright's types for both checkers, and never demands `IsFile` of a File expression.

**[Fact]** One targeted case never ran its target. Chain t3 (bind makes `Under(P(root))`
static, then rebase) raises `NotStaticError` at its last step. At seed 1, only 3 of 79
random rebases moved a static `Under`.

**[Fact]** Of the 57 "rejected at runtime, not statically":
- 52 are contradictions;
- 4 are `joinpath` below a File: only `/` has the JoinBelowFile overload, and `joinpath`
  is typed `PathExpr[Never, Unspecified]`;
- 1 is a rebase.

§4 names only contradictions and rebase.

**[Fact]** The test `a_name_fact_is_not_an_object_fact` passes by plain set inclusion.
`Held[Literal["exists"]]` would be rejected the same way, so it cannot show the
name-versus-object distinction its comment claims.

### A.5 How §2 and §3 were measured

- **[Fact]** The three corrections went in together before the next measurement: the
  bound on `K`, narrowing `P`'s overload, and `NotFile`. So "removes almost all of the
  31" is a diagnosis, not a measurement. The 31 also included a
  `reportOverlappingOverload` on `P`, fixed by the narrowing and not mentioned above.
- **[Fact]** `NotFile` fixed Pyright only.
  - ty's error count on `tests/` was 127 before and after.
  - ty instead gives `Unknown` for a join onto a receiver of unknown kind, and warns
    `deprecated: nothing can be joined below a path declared a File`. That is 103
    warnings at 9bc511c: 101 in `tests/`, and 2 in `src/` (`_params.py:129`,
    `infer.py:580`).
  - The first version's cost in ty, `src/` 9 → 38 errors, was not reported.

  "No new false positives" (df1ca7c) is true of errors, not of warnings.
- **[Fact]** The `import wend` median of §2 is the median of the best three of five
  runs (33.7 and 37.2 ms), not of all runs.
- **[Measured]** The audit ran both harnesses on the same 400 programs (seed 0), and
  "weaker" in #106 was mostly correction 3:
  - #106: 1,273 exact, 200 weaker. 170 of the 200 lacked `Under[str]`, 156 for that
    alone;
  - this entry: 1,429 exact, 44 weaker (25 kind, 18 literal `Under`, 1 other atom).

  #106's journal named other causes for its "weaker".
- **[Fact] Smaller lessons of the harness.**
  - The formatter wrapped marked statements, moving `# E:` below the line the error
    reported, so `check.py` read the pair as one missing and one unexpected error. Each
    marked statement now stays on one line.
  - Pyright rejected an implicit type alias inside a function, so it is a module-level
    `type` alias.
  - `P` was made positional-only, then reverted before any measurement. The record
    does not say why.

### A.6 History and decisions not recorded above

- **[Refuted], then rewritten in place.** The first text of §5 said string-keyed
  knowledge was "sound against aliasing by the bridge". The owner objected that the
  statement "needs a narrower scope", and 5672297 rewrote it to the conditional reading
  above. The rewrite replaced the earlier text, which this addendum restores to the
  record.
- **[Narrowed] §5, "Confinement removes aliasing as a source of error".** It omits case
  folding, which `openat2` does nothing about (aliasing §9, assumption 3).
- **[Fact] `Confirmed` kept.** The owner suggested `CheckedAt` or `VerifiedAt`, "if that
  makes the temporal semantic" clear, because a confirmation records something true at
  one moment. `Confirmed` was kept; its docstring and this entry state the temporal
  reading. The record has no explicit decision.
- **[Fact] Two discrepancies from #114.**
  - ty kept the `Verdict` literal union through a dict comprehension in
    `Derivation.stale`, and rejected adding `"superseded"`. An annotation fixed it.
  - The `events.pyi` stub lacked `Sealed`'s constructor, which Pyright rejected.
- **[Narrowed] §5–§6, `Sealed`.** "It remains true" is true of the copy: it cannot
  change. It is not a snapshot of the file. A copy made while a writer acts on a
  multi-page file can be a state the file never had: 244 of 300 reads were torn in the
  synthesis's measurement (`2026-10-22-synthesis.md` §4.3).
- **[Superseded] §7, "Outputs held for writing … are not built".** #114 built `Draft`
  and `Makes`. Its negatives are 17 of 17, not §4's 13.

### A.7 Where this leads

- `2026-10-22-publication-and-consistency.md` (#114) adds drafts, publication and
  observation.
- `2026-10-22-synthesis.md` composes the whole stack. Its `experiments/synthesis/misuse.py`
  adds 11 type-level rejections in a pipeline's terms.
- The research index, `2026-10-22-research-index.md`, orders the entries.
