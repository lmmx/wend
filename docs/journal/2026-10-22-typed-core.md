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
| it was true | `Checked[C, K]` at entry, `Confirmed[C, K]` at exit | `Run.enter`, stamped with an epoch | no: `Run.known(event)` says whether *this run* has invalidated it |
| which object | `Held[Literal["read"], IsFile]` | a `Holds` port, opened beneath the root and judged on its descriptor | its object, kind and access, while open |
| it remains true | `Sealed` | `seal(held)`: a memfd with write, shrink and grow sealed | its contents, for every holder |

- `Holds` accepts only an expression declaring `File`, `Exists` and `Readable`, at type
  level and at runtime.
- `Run` executes confined (`confined.Confined`), so its knowledge is the string-keyed
  `Knowledge`, sound against aliasing by the bridge of
  [the aliasing entry](2026-10-22-aliasing.md#5-the-bridge-alias-free-runs).

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
