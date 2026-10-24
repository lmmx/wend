# 2026-10-22: Declarations are obligations, not facts (#107)

`e.declares` (docs/SEMANTICS.md §10.1) names what an expression declares:
- its `requires` atoms;
- its `ensures` atoms;
- its `Under` bases.

It is the one change of the research programme made to wend's core API, and every later
entry builds on it:
- the knowledge analysis (#108) learns and forgets atoms;
- the typed core (#113) carries them in a type parameter;
- `Makes` and `Holds` (#113, #114) check them before a port is accepted.

This entry was written after the fact, during the journal audit of 2026-10-22, from the
commit (04fa23f), its tests and the session record. Until now the reasons lived only in
the session. Labels as in the other research entries.

## 1. What a declaration was taken to mean, and what it means now

The design entry of #106 (`2026-10-21-typed-path-families.md`, on #106's branch) read a
declaration three ways:
- as a type;
- as an effect;
- as an obligation.

Its type reading started from #105's capability probe, in which a phantom type parameter
per capability (`PathExpr[Yes, W]`) said what an expression *could* do. The owner then
qualified the thesis before #107 was written:

> the static type describes declared obligations, not necessarily facts known to be true.
> […] `PathExpr[Exists]` must not silently mean "this path exists." The difference
> between an unchecked expression and a path whose conditions have actually been
> verified is fundamental. And even a checked existence fact can become stale if another
> step deletes the file.

**[Refuted]** The reading of a declared atom as a capability the path *has*. A declared
`Exists` is a promise the program makes about a path, to be checked.

The specification now keeps three things apart:
- **declared**: what the expression states;
- **checked**: what a check found, at an instant;
- **known**: what is still believed after the effects since. #108 added this last one.

**[Fact]** §10.1 groups atoms by what makes them true:
- **containment**, made true by rendering;
- **state** (`exists`, `absent`, `file`, `dir`), made true by the filesystem when a
  check finds it;
- **permission** (`read`, `write`, `create`, `list`), made true by the filesystem for the
  real user when a check finds it.

"A checked state or permission is true at the moment of the check and no later."

## 2. Development

- `declares` is defined structurally:
  - `requires` and `ensures` add atoms;
  - `bind` and `rebase` keep them and map `Under` bases;
  - every other operation's result declares nothing;
  - a union declares the meet (`&`) of its alternatives' declarations.
- `Step.effects` became a function of the declaration (`Declarations.verbs`):
  - each permission atom is a verb;
  - `create` and `delete` come from `exists` and `absent` ensured but not required.
- **[Refuted]** A test of `verbs` was vacuous. Its assertion ended `... or atom`, which is
  always true, so it proved nothing. It was replaced by an explicit table of expected
  verbs before the commit.
- **[Fact]** Declaring more never removes a permission verb, but it can remove `create`
  or `delete`, which depend on an atom being *absent* from `requires`. §10.1 states this,
  because a type encoding that orders declarations by inclusion (#106, #113) can certify
  only the properties that persist when atoms are added.

## 3. Corrections from later work

These change the specification, which has been corrected in place: §10.1 states the
current theory, and this entry records why.

- **[Refuted] "Containment holds for every path the expression renders."** It holds for
  the *lexical* half only.
  - `render` checks that the rendered string is below the base's, with no `..` after it.
    That is a fact about strings, and it holds for every rendered path.
  - §10's `Under` also requires `realpath(p)` to be the base's realpath or below it.
    That half is checked by `check` and `Step`, like a state atom, at an instant.
  - A symlink planted later puts the path outside: confined-runs §4 found this, and the
    aliasing entry §5.
  - §10.1's table now says so.
- **[Measured] A union's verbs are not the meet of its alternatives' verbs.** Take
  `e = (P(r)/"a.csv").requires(File, Exists, Readable).ensures(Exists)`, which reads, and
  `o = (P(r)/"o").requires(Absent, Creatable).ensures(File, Exists)`, which creates.
  - `(e | o).declares.verbs == {"create"}`, though `e` creates nothing.
  - The meet keeps `exists` ensured, which both ensure, and drops every `requires` atom,
    which they do not share. "Ensured but not required" then reads as creation.
  - The verbs of a meet are neither the intersection (`{}`) nor the union
    (`{"read", "create"}`) of the alternatives' verbs. This follows from the non-monotone
    `create` and `delete` above.
  - `Step` refuses union ports, so `Step.effects` is unaffected. Any analysis that takes
    a union's verbs from its declaration would be wrong. §10.1 now says so.
- **[Refuted] in the typed core (#113): the type of a check event carries the whole
  declaration.** `check()` returns `Checked[C, K]`, where `C` holds *both* phases' atoms.
  The event of an output's entry check is therefore typed with `post_exists` and
  `post_file`, which no entry check examines. The runtime event carries only the atoms
  checked. The typed-core addendum records this.

## 4. Where this leads

- The knowledge analysis (`2026-10-22-knowledge-states.md`) builds on the
  declared/checked/known distinction.
- The typed core (`2026-10-22-typed-core.md`) and its addendum take it into types.
- The research index (`2026-10-22-research-index.md`, on the latest research branch)
  orders all the entries.
