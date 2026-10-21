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

### 2.3 What the types can express

**[Proven] The expressiveness boundary.**
- A requirement written `PathExpr[U]` accepts exactly the declarations `d` with
  `d ⊇ U`. A union of such requirements accepts a union of these filters.
- So the requirements these types can express are exactly the *upward-closed*
  families of declarations: if `d` is accepted, so is every `d' ⊇ d`.
- The proof is the subtyping fact in §2.2, with nothing else in the encoding that
  depends on an atom's absence.

**[Proven] Consequences.** Three properties are not upward closed, so no annotation
in this encoding can certify them:

- **`create`**, defined as `post_exists` without `exists` (src/wend/conditions.py:614-623).
  Adding `exists` removes the verb.
- **`delete`**, for the same reason.
- **Freedom from contradiction.** Adding `Absent` to `Readable` makes a declaration
  the runtime refuses.

The runtime has to check these when they are declared, and the effects graph has
to reason about them across steps. `experiments/typed/positive.py` records the
boundary as a case both checkers accept: a path that requires `exists` and ensures
`exists` meets a demand for `post_exists`, and it creates nothing.

**[Interpretation]** That boundary is the division of labour the thesis needs:

- types certify the upward-closed part of a declaration;
- the runtime checks each declaration when it is made, and each state at its moment;
- the effects graph composes what one step ensures with what the next requires.

None of the three can do another's job.

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
- The expressiveness boundary and its consequences (§2.3).

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
