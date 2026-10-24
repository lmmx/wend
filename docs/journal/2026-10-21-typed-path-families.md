# 2026-10-21: Typed path families: one declaration, three algebras (research)

This entry asks what wend should become after 0.2.0, starting from the
[Future Paths](https://cog.spin.systems/future-paths) essays and the stock-take in
PR #105. It proposes one structure behind three of the essays' unrealised
ideas, namely static capabilities, a pattern language, and a whole-program
account of effects. It tests the central claims with prototypes in
`wend._experimental` (typed, patterns, obligations) and a harness in
`experiments/typed/`. Nothing here changes wend's public API.

Labels: **[Fact]**, **[Measured]**, **[Proven]**, **[Interpretation]**,
**[Conjecture]**, **[Proposal]**.

> **Audit, 2026-10-22.** The text below is kept as written. [The addendum](#addendum-audit-2026-10-22)
> records four counterexamples found later:
> - the obligations of §2.4 discharge on an existential overlap and ignore deletions;
> - §2.5's equivalence ignores conditions, including `Under`;
> - the event types carry atoms never checked;
> - the stub's three defects, fixed only in #113.
>
> It also records the harness failures that could have read as clean, the encodings
> abandoned before §2.2's, and how §1 maps onto the essays.

---

## 1. The thesis

**[Fact]** The essays ask for three things that ordinary path libraries cannot give:

- **Errors made unrepresentable.** Part 1 asks for `Path[Readable]` and
  `Path[Writable, MayCreate]` in signatures, for "making the error unrepresentable
  rather than implying a need for defensive programming", and for
  `serve_static(asset: Path[Under[STATIC_ROOT], Readable])`.
- **A report of a program's effects.** Part 2 asks: "could we give some sort of
  report on all the file system effects of a given program". Part 2 also sketches
  `BasedPath(Generic[T])`, a base carried as a type parameter.
- **A text syntax.** Part 4 sketches `parse_path_pattern(...)` as a new
  user-facing syntax.

**[Fact]** Part 1 also states the limit that any honest design has to respect: "there
is no function you could write that would infallibly tell you if the path will be OK
to use".

**[Interpretation]** The three ideas describe one object. A wend expression already
pairs two things. Its *language* is the set of strings it can render, fixed by the
normal form (head, parts, parameters). Its *declaration* is the set of conditions it
carries. Read this way, each of the three ideas is an interpretation of the pair:

| interpretation | reads | gives |
|---|---|---|
| static types | the declaration, abstracted | what a checker can certify before the program runs |
| effects | the declaration's verbs and state, related through the languages' overlap | what steps owe each other, across a program |
| patterns | the language, as text | strings, expressions and inferred layouts as representations of one normal form |

So the proposal is not three feature families. It is one structure, a *typed path
family* (language plus declaration), with three readings, each with a stated limit.

## 2. Semantics

### 2.1 Declarations and their strata

**[Fact]** `wend._experimental.typed.facts(e)` names an expression's declaration as a
set of *atoms*:

- the preconditions `read`, `write`, `create`, `list`, `exists`, `absent`, `file`
  and `dir`;
- the same eight prefixed with `post_` for postconditions;
- `Under[str]` for any containment, and `Under['<base>']` for a static base;
- a kind marker, `IsFile`, when `File` is declared on either side.

The marker exists because joining below such a path raises
(src/wend/_expr.py:490-497).

**[Fact]** The runtime gives each atom its meaning, and the atoms fall into three
strata by who makes them true (src/wend/conditions.py:1-21, 291-300):

| stratum | atoms | made true by | holds |
|---|---|---|---|
| containment | `Under[...]` | `render`, which checks every rendered path lexically | for every path the expression renders |
| state | `exists`, `absent`, `file`, `dir` (`post_*` at exit) | the filesystem; checked by `check`, `confirm` or a step | at the moment it is checked |
| permission | `read`, `write`, `create`, `list` | the environment; checked when a step runs | at the moment it is checked |

**[Interpretation]** This answers the question of permissions versus guarantees. A
static type certifies that *a declaration is present*, and that is the only thing a
type can promise about the filesystem. What the declaration guarantees, and when,
is the runtime's to say: always for containment, at a checked moment for state and
permission. The prototype keeps the two apart in its types:

- `PathExpr[C]` is a declaration;
- `Resolved[C]` is a path rendered from one, of which only the `Under` atoms are
  facts about the path;
- `Checked[C]` is a path whose preconditions held when its step started.

### 2.2 The static encoding

**[Fact]** `typed.pyi` gives `PathExpr` two phantom parameters:

- `C` is contravariant: the union of declared atoms as `Literal[...]` and `Under[...]`
  members, defaulting to `Never`.
- `K` is covariant: `IsFile` or the default `Unspecified`.

**[Proven]** For literal unions, `U₂ <: U₁` holds exactly when `U₂ ⊆ U₁`. So with `C`
contravariant, `PathExpr[U₁]` is assignable to `PathExpr[U₂]` exactly when `U₂ ⊆ U₁`.
In words: "declares at least these atoms" becomes subtyping. The defaults follow:

- `PathExpr[Never]`, the bare `PathExpr`, is assignable to every `PathExpr[U]` only
  when `U` is empty, so a bare annotation accepts any expression and promises
  nothing. That is the unknown-capability default the design called for.
- An unannotated derived expression is typed `PathExpr[Never]`, so it meets no
  requirement.

**[Fact]** `Under[B]` is invariant in `B`, and a base gets an identity only from a
literal string, through a `LiteralString` bound. Any other base gives `Under[str]`.
So `Under[str]` never stands in for `Under[Literal["/srv/static"]]`, and no base's
marker stands in for another's.

**[Fact]** The transfer rules mirror the runtime, operation by operation (§10 of
SEMANTICS.md, src/wend/_expr.py:1118-1155, src/wend/conditions.py:195-260):

| operation | runtime | static rule |
|---|---|---|
| `requires(cs)`, `ensures(cs)` | adds `cs` (a `File` first sets the kind) | `C ∪ atoms(cs)`; `IsFile` when `File` is the first argument |
| `bind`, `tag`, `P(e)` | keeps the declaration | keeps `C` and `K` |
| `rebase` | keeps it, moving any `Under` base that lies under the old base | keeps `C` and `K`; when any `Under` is declared, gives `PathExpr[Under[str], K]` |
| `/`, `joinpath`, `parent`, `with_*`, `sibling`, `cousin`, `under`, `relative_to` | drops it (a derived expression declares nothing) | `PathExpr[Never]` |
| `/` below a declared `File` | raises `PathOperationError` | `JoinBelowFile`, which is not a path; ty also warns that the overload is deprecated |
| `\|` | each alternative keeps its own | `PathUnion`, untyped |
| `resolve`, `check` | renders; checks preconditions | `Resolved[C, K]`, `Checked[C, K]` |

### 2.3 What this encoding can express

The result in this section is about *this* encoding: one contravariant union of
positive atoms, plus a covariant kind marker, and no other type-level state. It
says nothing about type systems in general. An encoding with explicit state
indices, negative atoms or typestate transitions is not ruled out by it.

**[Proven] The boundary of the capability-set encoding.**
- A requirement written `PathExpr[U]` accepts exactly the declarations `d` with
  `d ⊇ U`. A union of such requirements accepts a union of these filters.
- So the requirements these types can express are exactly the *upward-closed*
  families of declarations: if `d` is accepted, so is every `d' ⊇ d`.
- The proof is the subtyping fact in §2.2, with nothing else in the encoding that
  depends on an atom's absence.

**[Proven] Consequences.** Three properties are not upward closed, so no annotation
in this encoding can certify them (a richer encoding might):

- **`create`**, defined as `post_exists` without `exists` (src/wend/conditions.py:614-623).
  Adding `exists` removes the verb.
- **`delete`**, for the same reason.
- **Freedom from contradiction.** Adding `Absent` to `Readable` makes a declaration
  the runtime refuses.

The runtime has to check these when they are declared, and the effects graph has
to reason about them across steps. `experiments/typed/positive.py` records the
boundary as a case both checkers accept: a path that requires `exists` and ensures
`exists` meets a demand for `post_exists`, and it creates nothing.

**[Interpretation]** With this encoding, the boundary gives a division of labour:

- types certify the upward-closed part of a declaration;
- the runtime checks each declaration when it is made, and each state at its moment;
- the effects graph composes what one step ensures with what the next requires.

The split belongs to this encoding, not to the problem. A model of what a program
*knows* about a path before and after each operation, with explicit states and
transitions, could move some of the runtime's and the graph's work into types.
That model is the next question (see Decisions).

### 2.4 Effects as a function of the same atoms

**[Fact]** `obligations.verbs(atoms)` computes a port's effect verbs from its atoms
alone (src/wend/_experimental/obligations.py). `tests/obligations_test.py` checks
that it equals `wend.Step.effects` over 500 random declarations.

**[Interpretation]** The effects graph built from `Step.effects` therefore factors
through the same abstraction the static types carry. One declaration feeds the
checker, the runtime checks and the graph.

**[Fact]** `obligations(graph)` reads an `EffectGraph` as Hoare composition:

- an input's required state atoms are an obligation;
- a supplier whose ensured state covers them discharges it, if their overlap is YES;
- a partial or MAYBE supplier leaves the obligation possible, naming what it lacks;
- an input with no supplier is owed by the world.

Permissions are never discharged, since no step establishes one for another.

### 2.5 Patterns: three representations of one normal form

**[Fact]** `PathExpr.pattern` prints the normal form as a small term language
(src/wend/_expr.py:739-761). It has:
- segments of literal text and fields (`{name!conv:spec}`), with a dynamic spec's
  parameters written `{p}`;
- `{name...}` for a SubPath;
- deferred operations as calls: `join`, `parent`, `with_suffix`, `with_name`,
  `with_stem`, `relative_to`;
- `{stem(...)}`, `{name(...)}` and `{suffix(...)}` for text operations.

**[Fact]** The printing forgets three things:
- declarations: `{root}/{x}` prints the same for an untyped `x`, an `int` `x` and an
  `x` with choices, and those are three unequal expressions;
- conditions;
- in two shapes, structure (§4.6).

**[Fact]** `patterns.parse(pattern, params)` builds normal-form nodes directly:
- with the expression's own declarations, it is meant to invert the printing;
- without them, it builds the *principal* expression, which gives each name the
  most general declaration its position allows.

**[Interpretation]** Strings, expressions and inferred layouts then sit in one
picture:

- `infer` maps a set of paths to layouts that cover them;
- `parse` maps a pattern and its declarations to an expression;
- without declarations, `parse` maps a pattern to the principal expression, which
  renders and matches whatever any expression of that structure does.

Semantic equivalence is equality of normal forms, which compares head, parts and
parameters under §3.1's strict equality. Rendering on examples is not enough to
establish it, as the review of B1 pointed out; normal-form equality is the stronger
criterion, and §4.6 records where the printing fails it.

## 3. Worked examples

**[Fact]** A pipeline step, typed (experiments/typed/common.py):

```python
raw = (P(root) / "raw" / T(t"{name}.csv")).requires(File, Exists, Readable)
out = (
    (P(root) / "out" / T(t"{name}.parquet"))
    .requires(Absent, Creatable)
    .ensures(File, Exists)
)

type Input = Checked[Literal["read", "exists", "file"]]
type Output = Checked[Literal["create", "absent", "post_file"]]


def read(p: Input) -> bytes: ...
def write(content: bytes, p: Output) -> None: ...


class Convert(StepSpec):
    src = Uses(raw)
    dst = Uses(out)


with Convert(root="/data", name="a") as s:
    write(read(s.src), s.dst)  # accepted by Pyright and ty
    read(s.dst)  # error in both: an output is not declared readable
read(raw.resolve(root="/d", name="a"))  # error in both: rendered is not checked
```

**[Fact]** Containment under a literal base (experiments/typed/common.py, negative.py):

```python
STATIC: Final = "/srv/static"
asset = (P(STATIC) / AnyPath("rel")).requires(Under(STATIC), Readable)


def serve(p: Resolved[Literal["read"] | Under[Literal["/srv/static"]]]) -> str: ...


serve(asset.resolve(rel="logo.png"))  # accepted
serve(
    (P("/tmp") / AnyPath("r")).requires(Under("/tmp"), Readable).resolve(r="x")
)  # error: wrong base
serve(
    (P(STATIC) / AnyPath("r")).requires(Readable).resolve(r="x")
)  # error: no containment
```

**[Fact]** One declaration, read three ways (tests/obligations_test.py):
- `Clean.raw` is the expression the graph reads (`port.expr is Clean.raw`);
- its verbs from atoms, `{"read"}`, equal its runtime effect verbs;
- its static type in `with Clean(...) as s` is
  `Checked[Literal["read", "exists", "file"], IsFile]`;
- the graph reports `report.clean` as `possible` because `clean.clean` ensures
  `exists` but not `file`: a step that might leave a directory where the next step
  expects a file.

## 4. Counterexamples found, and what changed

Each rule in §2.2 was refined by a counterexample from the harness or the tests.
They are recorded here because each shows how a typing prototype can claim more
than the runtime establishes.

### 4.1 Kind is two facts, not one

**[Measured]** The first encoding had one kind parameter. The harness found four
unsound statements in both checkers. In each, `requires(File)` followed by
`ensures(Dir)` was typed `IsFile` while the runtime's last declaration was `Dir`.

**[Fact]** The runtime checks contradictions per side (src/wend/conditions.py:219-238).
So a step may require a file and ensure a directory, which is a legitimate
replacement.

**[Fact] Change:** kinds became atoms on each side (`file`, `post_dir`), and `K` kept
only what the join rule needs.

### 4.2 An unsolved type variable invents a declaration

**[Measured]** With `requires(self, kind, /, *rest: Condition[A1, Any])`, a call with
no `rest` left `A1` unsolved. Both checkers then revealed
`PathExpr[Unknown | Literal[...]]`, and `Unknown` in a contravariant slot satisfies
any requirement.

**[Measured]** With a `Never` default, ty still solved `A1` from the expected type at
a call site: `wants_readable(P("x").requires(File))` type-checked.

### 4.3 Covariance lets call-site inference widen a declaration

**[Measured]** With covariant condition parameters, Pyright 1.1.407 accepted
`wants_readable(P("x").requires(Exists))`: it solved `A1` as
`Literal["exists", "read"]` to fit the expected type.

**[Measured]** On seed 0, Pyright accepted 159 of 5,733 generated inline demands for
undeclared atoms, including an invented `Under['/srv/static']`. ty accepted none.

**[Fact] Change, for §4.2 and §4.3:** condition parameters are invariant, so an
argument binds its variable exactly. `requires` and `ensures` are overloaded by
arity, from 0 to 6 conditions, with one variable per argument, so no variable is
ever left for inference to solve.
- Beyond six conditions the new ones are not tracked, which is sound but imprecise.
- Both checkers then accept 0 of the same 5,733 demands.

### 4.4 `rebase` moves a declared base

**[Fact]** A base that lies under the old base moves with `rebase`. For example,
`Under('/srv/static')` rebased from `/srv/static` onto `/tmp` becomes `Under('/tmp')`
(tests/typed_test.py). A base outside it stays, and `render` still enforces it.

**[Measured]** The rule "rebase keeps `C`" gave four unsound statements and one
accepted inline demand, in both checkers.

**[Fact] Change:** when any `Under` is declared, `rebase` gives
`PathExpr[Under[str], K]`.

**[Fact]** The first harness missed this, because its generated `rebase` never moved
a declared base. A targeted chain now does, and the unit test that found it encoded
the wrong belief before it was corrected.

### 4.5 The checkers disagree on literal retention

**[Measured]** For `class Param[N: str]`, `Param("root")` is `Param[str]` in Pyright
and `Param[Literal["root"]]` in ty. With `N: LiteralString`, both keep the literal.

**[Fact]** A parameter-based `Under(P(root))` gets no identity in the prototype. Its
base becomes a literal when `root` is bound (src/wend/conditions.py:246-260), so "under
root" means "under whatever root was bound to by whoever built the value". That is
not the guarantee a server wants.

### 4.6 Two shapes the pattern language cannot tell apart

**[Measured]** Over the contract's hostile terms (tests/contract_test.py), parsing each
pattern with its declarations gave back the same normal form for 3,841 of 3,867
expressions, 99.3%. The other 26 have one of two shapes:

- **(a) A head parameter, or a relative first segment** that is a whole-segment field
  of a parameter of undeclared kind. Both print `{w}`.
  - `P("") / w` renders `w="a/b"` as `a/b`.
  - `(P("/anchored") / w).relative_to(P("/anchored"))` refuses it.
- **(b) A segment-role field inside a mixed segment,** such as `bk_{d}` from
  `T(t"bk_{P(d).name}")`. It prints like a value field but validates its value as a
  segment: it refuses `..`, `.`, `""` and bytes, where the value field renders them.

**[Fact]** A Segment parameter is never a head parameter in the normal form
(`P(Segment("x"))` is relative), so declarations resolve (a) for Segment parameters.

**[Measured]** At shape (a) there is no principal expression. A head parameter takes
`"a/b"` and refuses `0`, and a segment takes `0` and refuses `"a/b"`, so neither
declaration dominates the other.

**[Measured]** Outside both shapes, the principal expression rendered what the
expression rendered for its effective bindings (its defaults filled in). It also
matched every path the expression matched. Both checks ran over 1,500 generated
expressions each.

### 4.7 What the static types do not catch

**[Measured]** Some declarations the runtime refuses are accepted by both checkers,
such as `Absent` with `Readable`, or `File` with `Listable`: 54 of 1,536 statements on
seed 0, and 162 of 3,803 on seed 1. These declarations are not upward closed (§2.3).
The runtime refuses each when it is declared.

**[Fact]** Joining below a `File` gives `JoinBelowFile`, so any later use of the result
is an error. A bare `f / "x"` statement is reported only as ty's deprecation warning,
because Python has no negation types with which to forbid the call itself.

## 5. Measured

**[Measured]** `experiments/typed/check.py` runs Pyright 1.1.407 and ty 0.0.90, against
the installed wend runtime objects:
- 0 errors in `positive.py` and `common.py`;
- an error on each of the 17 marked lines of `negative.py`, and on no other line.

**[Measured]** `experiments/typed/soundness.py` generates chains of real operations.
For each statement it compares the revealed static type with `facts(e)`. Then it puts
each expression inline where atoms it does not declare are demanded:

| run | statements | unsound | exact | weaker | undeclared demands accepted | declared demands rejected |
|---|---|---|---|---|---|---|
| seed 0, 400 programs | 1,536 | 0 | 1,273 | 200 | 0 of 5,733 | 0 of 505 |
| seed 1, 1,000 programs | 3,803 | 0 | 3,120 | 508 | 0 of 14,122 | 0 of 1,233 |

- The two checkers gave identical counts in every row.
- "Weaker" means the static type names fewer atoms than the runtime declares. The
  causes are a `File` that is not the first argument, a base made static by `bind`,
  and declarations beyond six arguments.
- With either rule from §4.3 or §4.4 reverted, the same run reports the unsoundness.

**[Measured]** The runtime tests pass:
- `tests/typed_test.py`: 11 tests;
- `tests/obligations_test.py`: 7 tests, one of them a 500-example property;
- `tests/patterns_test.py`: 14 tests, the properties at 1,500 examples.

The full suite also passes: 944 tests, docs included.

## 6. Proven, tested, and open

**[Proven]**
- The subtyping reading of contravariant literal unions (§2.2).
- The boundary of the capability-set encoding, and its consequences (§2.3). Both
  are stated for that encoding only.

**[Measured], not proven:**
- The stub mirrors the runtime on the generated grammar of operations, in both
  checkers, at the versions pinned.
- Effect verbs factor through the atoms.
- The pattern round trip and principal-expression properties hold outside the two
  shapes in §4.6.

**[Conjecture]** These would need more work to establish:
- Soundness for operations outside the generated grammar: `Lens`, `Tree`
  attributes, `glob` results, unions and queries.
- Soundness for future checker versions; ty is in beta.
- Soundness for code that uses `Any` or `cast`. Those defeat any encoding.

**[Fact]** Not established at all:
- that the obligations view scales, or is useful on a real pipeline, beyond the
  three-step example;
- that the arity cap of six is enough in practice.

## 7. Architecture

**[Proposal]** The normal form stays the single source of truth. Each reading becomes
a function of it, with a contract in SEMANTICS.md and a test that fails when the
reading drifts from the runtime:

1. **`e.declares`, public.** The atom set of §2.1, documented with its strata.
   `facts` becomes this method. Types, effects, Pydantic and docs all read it.
2. **Generic `PathExpr` in core.** Add `Generic[C, K]` with PEP 696 defaults on the
   real class, rather than a separate stub, so the two cannot drift. Python 3.14,
   which wend requires, has PEP 695, 696 and 702 in the standard library, so this
   adds no dependency.
   - Run the soundness harness in CI with pinned checkers.
   - Bare `PathExpr` annotations keep meaning "any expression".
3. **Steps as classes.** `StepSpec` and `Uses` give typed `Checked` handles and serve
   the same declarations to effects and lineage. They also share their descriptor
   pattern with `schema.Tree`, which could adopt it.
4. **Pydantic.** `declared_by(annotation, expr)` checks at model build that a field's
   annotation claims no more than its `PathOf` expression declares. That is the
   runtime half of "the type never promises more".
5. **An injective pattern language.** Print shape (a) with an explicit relative
   marker (`./{w}`) and shape (b) with a segment marker. Then `parse(e.pattern, e.params)`
   inverts the printing everywhere, and `wend.parse` can be public. A textual form
   that also carries declarations and conditions (a round-trippable `repr`) would
   make text a complete representation.
6. **Obligations beside `EffectGraph`.** Promote them once overlap has its own
   SEMANTICS section (#89's promotion list, item 1).

## 8. Proposed implementation sequence

**[Proposal]** Each PR carries its contract and its tests. The stack is PR 1 → 2 → 3;
PRs 4 and 5 branch from PR 1.

1. **Declarations as a contract.** A SEMANTICS.md section on atoms, strata and the
   expressiveness boundary; `e.declares`; and the facts tests from this research.
   Runtime behaviour unchanged.
2. **Typed core.** `PathExpr[C, K]` in `_expr.py`, typed conditions, and the
   transfer rules of §2.2. `experiments/typed/` moves to `tests/typing/`, with a CI
   job that pins Pyright and ty and runs `check.py` and `soundness.py`.
   - Exit criteria: 0 unsound, 0 undeclared demands accepted, 0 declared demands
     rejected.
3. **Checked steps.** `Resolved`, `Checked`, `StepSpec` and `Uses`; `declared_by` at
   Pydantic model build; and the pipeline and untrusted-input guides rewritten around
   them, since the docs follow the design.
4. **An injective pattern language.** The two printing changes from §7.5, public
   `parse`, a SEMANTICS section on the pattern language, and the round-trip
   properties promoted.
   - Exit criterion: exact round trip on every generated term.
5. **Obligations.** Overlap's contract first, then `obligations` beside a promoted
   `EffectGraph`, with one real pipeline as its test.

**[Interpretation]** Each PR stands alone if later ones stall. PR 2 is the one that
changes what users write, and it is a change in kind: a misuse such as reading an
output, or serving a path from the wrong root, would be reported by the user's own
type checker before anything runs.

## Decisions (owner, 2026-10-22)

**[Decision]**
1. **Literal roots.** Containment identity comes from literal roots in the first sound
   implementation. Symbolic, parameter-dependent root identity stays a research goal,
   given rigorous semantics that claim no more than the checkers establish.
2. **Postconditions as types.** The state-transition semantics comes first. Before
   any type parameter is added, it must say what is certified, when it is checked,
   and when that knowledge is invalidated by later effects.
3. **Patterns.** The printed form becomes injective with respect to every distinction
   that affects rendering or matching: `./{w}` for a relative leading segment, and an
   explicit syntax for a segment-role field in a mixed segment. It will be tested on
   canonicalisation, declaration preservation, safety-relevant validation and
   semantic round-tripping, not on string equality.
4. **StepSpec and Tree.** Explore a common declarative foundation, and establish what
   the two share and what differs, without forcing one public class API.
5. **Next work.** Step 1 (the declarations contract and a public `e.declares`) first,
   then the typed core. Pattern-language design continues without a new
   implementation stack.

**[Decision]** The monotonicity result is stated for the capability-set encoding,
not for every static representation of effects or negative information (§2.3).

**[Decision]** The question for the next phase: can wend describe what a program
*knows* about a path before and after each operation? The candidate distinction is
between three things: a *declared* condition (an obligation), a *checked* condition
(true when it was checked), and *knowledge* (a checked fact that later effects have
not invalidated).

---

## Addendum: audit (2026-10-22)

This entry was audited, with the stack of research built on it (#107–#114), against the
commits, the tests and the session record. The stack's entries are on its branches;
their research index (`2026-10-22-research-index.md`, on the latest research branch)
places this entry first. Findings marked "re-run" were reproduced before being written.

### A.1 Counterexamples to this entry's claims

- **[Measured, re-run] §2.4's obligations discharge on an existential overlap, and
  ignore kills.** `obligations()` marks an input discharged if any supplier, with
  overlap verdict `"yes"`, ensures it. #89's YES means *some* binding makes the paths
  meet:
  - a step writing only `o/a.csv` discharges a reader of `o/{x}.csv`, for every `x`;
  - with a step deleting `o/a.csv` in between, the obligation is still "discharged via
    `a.out`". The deleter is listed only as a supplier that lacks `exists`.

  §2.4's "Hoare composition" needs two things this lacks: a supplier that covers *every*
  binding, which is what #109's must-equal and prefix cancellation give, and kills,
  which is what #108's forget rule gives. The obligations prototype was superseded by
  those analyses, which this entry could not link to.
- **[Measured, re-run] §2.5's equivalence ignores conditions.** "Semantic equivalence is
  equality of normal forms", but expressions with different conditions compare equal
  (SEMANTICS.md §10). For
  `guarded = (P(r) / AnyPath("x")).requires(Under(P(r)))`:
  - `parse(guarded.pattern, guarded.params) == guarded` is `True`;
  - yet `guarded` refuses `x="../etc/passwd"` with a containment error, while the
    parsed expression renders `/srv/../etc/passwd`.

  The round trip forgets the containment guard. §2.5 says printing "forgets
  conditions", but kept the equivalence claim, and the 3,841 of 3,867 figure was
  measured on terms without conditions. The owner's decision 3 asks for "safety-relevant
  validation", so a round trip must be checked with its conditions.
- **[Measured] §2.1: `Checked[C]` is "a path whose preconditions held when its step
  started".** The type carries every atom the expression declares, `post_*` included.
  An output's entry event is typed with `post_exists`, which no entry check examines.
  §3's own `Output = Checked[Literal["create", "absent", "post_file"]]` shows it. In
  #113 a second defect appeared: a path derived from an event (`c.parent`, `c / ".."`)
  is typed, and built, as that event. That breaks the containment of §3's
  `serve_static`. Both are in `2026-10-22-typed-core.md`, addendum A.1–A.2.
- **[Measured] Three defects of this stub, found only in #113.**
  - The overload `self: PathExpr[Any, IsFile] → JoinBelowFile` comes first, so a
    receiver of unknown kind becomes `JoinBelowFile`.
  - `K` is unbounded.
  - A literal `Under` does not declare `Under[str]`.

  The last accounts for most of §5's "weaker" statements. On the same 400 programs this
  harness gives 200 weaker, of which 170 lacked `Under[str]`; #113's gives 44. §5 named
  other causes.

### A.2 Harness failures that could have read as clean

**[Fact]**
- **Pyright refused to analyse** the module-level context file ("Code is too complex
  to analyze"). The harness first read that as no errors, then crashed on a missing
  `range`. It now writes one function per program.
- **A mutant that never applied.** The "revert the rebase rule" mutant silently failed
  to apply, because `ruff format` had rewrapped the overload. That run measured the
  fixed rule and reported 0 unsound. A redo with a formatting-tolerant substitution
  gave 4 unsound and 1 accepted demand.
- **A generator that could not reach the bug.** Earlier, the reverted rule also passed,
  for a different reason: random declarations mostly contradicted each other and ended
  the chain. Only 25 `rebase` statements were generated, none after a successful
  `Under(STATIC)`. The fix was a 70/30 split of consistent and random declarations,
  plus hand-written targeted chains. §4.1's and §4.4's bugs are detected by those chains.
- **A column that measured agreement with Pyright.** The "declared demands rejected"
  column draws its demands from Pyright's own `reveal_type`. It tests assignability
  against what Pyright believes, not completeness against the runtime, so it could not
  see the `Under[str]` gap above. Statements after a runtime raise are skipped: 72 at
  seed 0, 196 at seed 1.

### A.3 Checker discrepancies, in full

**[Measured]** With a `Never` default and *covariant* `Pre`/`Post`, seven inline calls
each falsely satisfied a demand:

| call | demand | accepted by |
|---|---|---|
| `requires(File)` | readable | ty |
| `requires()` | readable | both |
| `requires(Exists)` | readable | Pyright |
| `requires(Readable)` | read and write | both |
| `requires(Readable, Exists)` | read and write | Pyright |
| `ensures(Readable)` | a precondition `read` (a phase confusion) | Pyright |
| `x: PathExpr[Literal["read"]] = ...requires(Exists)` | readable | Pyright |

§4.2 attributes solving a variable from the expected type to ty alone, but Pyright did
too, for `requires()`. The phase confusion was not recorded. #113's audit found that
§4.3's "ty accepted none" holds only for single-atom demands, and that with this
encoding ty 0.0.90 cannot be both sound and precise (typed-core addendum A.3).

### A.4 Encodings abandoned before §2.2's

**[Fact]**
- **#105's probe gave each capability its own phantom parameter** (`PathExpr[Yes, W]`).
  It was replaced by a contravariant union of literal atoms. The reason recorded at the
  time was that "set inclusion maps to subtyping". The owner had asked "whether Yes and
  No should represent guaranteed capabilities or merely permitted operations", and that
  "the default should represent an unknown capability". The union with a `Never`
  default answers both: atoms are declared obligations, and the default declares
  nothing. `2026-10-22-declarations.md` (#107) records the decision that followed.
- **Containment keyed by a parameter's name** (`Under(base: Param[B])`) failed: Pyright
  widened `Param("root")` to `Param[str]`. That led to bases that are literal strings,
  bound by `LiteralString`.
- **`IsDir` and an `Unknown` root of kinds** were dropped.

### A.5 Labels that claim more than was shown

- **[Narrowed] §2.3, "exactly the upward-closed families" ([Proven]).** It needs
  assumptions the text leaves unnamed:
  - finitely many minimal elements, since Python unions are finite and `Under` atoms
    range over unboundedly many literals;
  - checkers that follow the variance rules of the typing spec;
  - atoms that are independent.
- **[Narrowed] §4.6, "At shape (a) there is no principal expression" ([Measured]).** It
  was shown for two candidate declarations, not in general.
- **[Refuted], then weakened twice: the principal expression.** The first claim was that
  it "keeps every reading".
  - Counterexample: for `{ds}.{dn}` on `q.r.7`, `e` reads `{dn: 7, ds: "q.r"}`, while
    the principal expression reads `{dn: "r.7", ds: "q"}` and `{dn: "7", ds: "q.r"}`,
    untyped and with an extra reading.
  - The claim became "matches some reading", with `limit=4`, plus filling in defaults.
  - Before that, a parser bug (nested `Text` sources losing their parameters'
    declarations) had made the round trip 88%, with 415 mismatches. After the fix it
    was 99.3%.
  - §4.6 states only the final form.
- **[Narrowed] §2.1, "containment always".** It holds for the *lexical* half only. The
  physical half (realpath) is checked at a moment, like a state, and a symlink made
  later ends it (SEMANTICS.md §10.1 as corrected; confined runs §4).
- **[Narrowed] §2.2, "a bare annotation accepts any expression".** It fails for a
  generic `K` without an upper bound, which #113 had to add.

### A.6 §1 against the essays

**[Fact]** Two points of [Future Paths](https://cog.spin.systems/future-paths) that §1
did not engage, quoted from the essays:
- **Capabilities.** The essays name "the things one can do with a path
  (read/write/create/delete/enumerate)". Of `Path[Writable, MayCreate]` they say "this
  introduces a sort of nullable type to the capability": "some things are going to
  always be created, some only maybe". The atoms do not match that one to one:
  - §2.3's effect `create`, which cannot be certified, is the "always created";
  - `MayCreate` corresponds to the permission atom `create` (`Creatable`), which can be;
  - the entry uses the one word for both;
  - `delete` has no atom at all. It is a verb, derived from `Absent` ensured but not
    required.
- **A text syntax.** §1 says Part 4 "asks for" a text syntax, and §7 proposes a public
  `parse`. The essay itself says a text-based pattern syntax "defeats the point of the
  current design (where Python t-strings handle the parsing)". A `parse` that is only
  the inverse of `.pattern`, for printing and round trips, sidesteps that reservation.
  §1 and §7 should have said so.

### A.7 Where this leads

In conceptual order, on the stack's branches:
1. `2026-10-22-declarations.md` (#107): declarations as obligations.
2. `2026-10-22-knowledge-states.md` (#108): knowledge and its invalidation.
3. `2026-10-22-symbolic-families.md` (#109): the same over families.
4. `2026-10-22-aliasing.md` and `2026-10-22-confined-runs.md` (#110, #112): identity
   and confinement.
5. `2026-10-22-typed-core.md` (#113): this entry's encoding moved into the core.
6. `2026-10-22-publication-and-consistency.md` (#114).
7. `2026-10-22-synthesis.md`.

The research index on the latest branch links them.
