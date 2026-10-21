# 2026-10-21: What `choices=` and `type=` promise (research)

This entry continues PR #89. The overlap research found a parameter whose
declared value renders a path that `match` cannot read back. This entry
asks what `choices=` and `type=` should promise. Core wend is unchanged:
the rules proposed here exist only as a private prototype
(`wend._experimental.choices`) and as tests.

The evidence:
- `docs/journal/scripts/2026-10-21-choices-audit.py`, a compatibility
  audit of 678 cases, 510 of them accepted;
- `tests/choices_semantics_test.py`.

Labels: **[Fact]**, **[Measured]**, **[Interpretation]**, **[Proposal]**, **[Decision]**.

---

## Summary

- **[Measured]** 43 of 108 bindings of a *declared member* render a path
  that `match` does not read back. That is 40% across the audit's forms:
  untyped numeric, `bool`, `None` and `Decimal` choices; `IntEnum` and
  `Enum` members; path-valued choices of a head or a SubPath.
- **[Fact]** Two further core findings came out of the audit:
  - `Param` equality breaks its own invariant, so the template cache can
    swap one declaration's choices for another's;
  - equal members of different types collapse silently at declaration.
- **[Measured]** The fourth option you asked about (called D below) can be
  done without touching `render`. `match` reads a choice parameter as each
  member whose rendering is the text, and its own readings become the
  member they stand for. Measured effects:
  - every declared member reads back, with its value and type;
  - no path that reads back today is lost;
  - no output changes;
  - 13 readings change type to the declared member (`"train"` →
    `Split.TRAIN`);
  - the only new ambiguity is between distinct members that render alike
    (`{"1", 1}`).
- **[Interpretation]** D fixes members. It cannot fix values that *equal*
  a member but render differently: `1.0` for `{1}`, `True` for
  `type=int`. Those 229 bindings need an acceptance decision:
  - render them as the member (B), which changes 229 outputs silently;
  - refuse them (E), which changes no output but errors on 229;
  - or keep today's unreadable paths (C).
- **[Proposal]** In order:
  1. fix the equality bug;
  2. add D to `match`;
  3. refuse colliding members at declaration;
  4. bring in E through a warning period, not B.

## The guarantees, defined

**[Fact]** Five properties, for an expression `e`, a binding `env` and a path
`p`:

| Property | Statement | Today |
|---|---|---|
| Acceptance | `env` passes `type`/`choices` ⇒ `e.render(env)` succeeds, or fails only by §4's segment rules | Holds |
| Soundness ("path round-trip") | `b ∈ e.match_all(p)` ⇒ `e.render(b) == p` | Holds by construction (§8): every reading is rendered before it is returned |
| Path completeness | `e.render(env) == p` ⇒ `e.match_all(p)` is non-empty | **Fails** for 271 of 510 accepted bindings, 43 of 108 declared members |
| Representative recovery | `e.match_all(e.render(env))` contains each value's representative (the member it equals; `int(v)` under `type=int`), of that type | Fails wherever completeness does, and for 13 more |
| Value recovery | `e.match_all(e.render(env))` contains `env` itself, same types | Cannot hold in general: formatting is lossy (`{u:.3}`) and many values render alike (`Quiet(3)` and `3`) |

**[Interpretation]** "Path round-trip" as the review phrased it
(`render(match(path))` reproduces the path) is soundness, which already
holds. The property that fails is its converse, path completeness. §7
states completeness for bindings ("every binding that renders to the path
appears in the result"), with listed limits. The question is which limits
are deliberate and which are gaps. Value recovery is the review's third
guarantee and cannot be promised. Representative recovery is the
strongest version that can.

## Findings in core

### 1. Param equality breaks its own invariant

**[Fact]**

```python
first = Param("c", choices={1})
P("x") / T(t"{first}.txt")
second = Param("c", choices={True})
e = P("x") / T(t"{second}.txt")
e.params["c"].choices  # frozenset({1}), not {True}
```

`Param.__eq__` carries the comment "equal Params must be interchangeable
(the template cache relies on it)".
- It compares `default` strictly, as §3.1 requires: same type, `==` and
  `repr`.
- It compares `choices` with frozenset equality, under which `{1}`,
  `{True}`, `{1.0}`, `{Decimal("1.0")}` and `{One.ONE}` are equal, and so
  are `{Split.TRAIN}` and `{"train"}`.
- The template cache (`_expr._TEMPLATES`) then returns the first such
  declaration's Param for a later one.

So a parameter's choices depend on what else the process built first,
and this affects `repr`, `match`, `glob`, schema enumeration and the
overlap analysis. It contaminated this audit's first run and these tests;
both now clear the cache per declaration, with a comment saying why.

**[Proposal]** Compare `choices` member by member under §3.1's rule
(same type, `==` and `repr`). The hash can stay as it is. A strict xfail
(`test_core_keeps_each_declaration_of_choices`) records the bug. This is a
fix to code that contradicts its own comment, not a change of semantics.

### 2. Declared members that do not read back

**[Measured]** Of 108 bindings of a declared member across the forms
`x/{c}.txt`, `x/{c}`, `x/{c:>4}`, `x/{c!r}` and `x/{c:d}`, plus a head
and a SubPath, 43 render a path that `match_all` returns nothing for:

| Declaration | Members not read back |
|---|---|
| untyped `{1}`, `{1, 2}`, `{1.5}`, `{0.0}`, `{Decimal("1.0")}` | 19 |
| untyped `{True}`, `{None}`, `{nan}` | 9 |
| untyped `{One.ONE}` (IntEnum), `{Colour.RED}`; `type=Colour` | 12 |
| untyped `{Split.TRAIN}` under `!r` | 1 |
| `AnyPath` head `{PurePosixPath("/a")}`; `SubPath` `{PurePosixPath("a/b")}` | 2 |

The causes:
- **Untyped fields.** An untyped field reads the types its spec implies
  (§7): `str` under `""` and `>4`. `"1" in {1}` is false. §7's limit "an
  untyped field reads only the types its spec implies" covers this for
  template fields, but no limit says that a declared member can be
  unreadable.
- **Other positions.** A whole segment, a head and a SubPath read text as
  `str`. A path-valued member never equals a string (`PurePosixPath("/a")
  != "/a"`), and no limit in §7 covers these positions.
- **Enums.** An `Enum` member renders `Colour.RED`, which no type reads
  back. `!r` texts that are not literals are a documented limit.

`type=int` with `choices={1}` reads back, which is the workaround today.
Strict xfails record the gaps: `test_core_reads_back_every_declared_member`
and `test_core_reads_back_path_valued_choices`.

### 3. Equal members of different types collapse at declaration

**[Fact]** `choices` is stored as a `frozenset`, which keeps one of two
equal members (the first given):

| Declared | Stored |
|---|---|
| `[1, True]` | `{1}` |
| `[True, 1]` | `{True}` |
| `[1, 1.0]` | `{1}` |
| `["train", Split.TRAIN]` | `{"train"}` |

A declaration that lists `True` then accepts it, because `True == 1`, and
renders `x/True`, which nothing reads back. Under option B it would
render `1` or `True` depending on the order of the list.

**[Proposal]** Refuse, at declaration, two members that are equal but
differ in type or `repr`, with a message naming them. §3.1 already treats
`1`, `True` and `1.0` as different defaults. The cost is that a
declaration listing both `"train"` and `Split.TRAIN` would raise.

This covers only members the `frozenset` would silently merge (equality
collisions). Distinct members that merely *render* alike (`{"1", 1}`)
stay legal, and `match_all` returns both readings (see Decisions).

### 4. Equal values that render differently (the bool case, generalised)

**[Measured]** 229 accepted bindings render differently from their
representative:

| Category | Count | Example |
|---|---|---|
| Another numeric type | 82 | `1.0`, `Decimal("1.0")`, `1+0j`, `Fraction(1)` for `{1}`; `0` for `{0.0}` |
| A subclass with its own `__format__` | 76 | a `str` subclass that upper-cases; an `int` subclass that formats as letters |
| `repr` differs under `!r` | 44 | `Split.TRAIN` for `{"train"}` |
| `bool` for `int` | 27 | `True` for `type=int` or `{1}` |

Today these render paths that do not read back. §7 documents the `bool`
case for typed fields ("an `int` field does not read `True`"); the rest
follow from the same rule.

## The options, measured

**[Measured]** The audit simulated each option from outside wend. It
counts accepted bindings whose path is not read back (completeness) and
those whose value is not recovered.

| Option | Accepted | Not read back | Value not recovered (`==`) | Outputs changed | Refused, accepted today |
|---|---|---|---|---|---|
| C, today | 510 | 271 | 290 | 0 | 0 |
| D-union | 510 | 186 | 192 | 0 | 0 |
| D-members | 510 | 226 | 232 | 0 | 0 |
| D-fallback | 510 | 186 | 205 | 0 | 0 |
| **D-canonical** | 510 | 186 | 192 | 0 | 0 |
| A | 139 | 40 | 46 | 0 | 371 |
| A + D-canonical | 139 | 1 | 4 | 0 | 371 |
| B | 510 | 216 | n/a | 229 | 0 |
| B + D-canonical | 510 | 18 | n/a | 229 | 0 |
| E | 281 | 86 | 102 | 0 | 229 |
| **E + D-canonical** | 281 | 1 | 4 | 0 | 229 |

On the 108 declared members, every D variant reads back all 108. All
except D-fallback also recover each one with its type. D-fallback misses
8, because it keeps today's reading where one exists.

**The options:**
- **A** (exact types): a choice accepts only a member's exact type, and
  `type=` only exact instances. It refuses 371 bindings, among them
  `StrEnum` members for string choices, `IntEnum` for `type=int`, and
  `int` subclasses that format as ints.
- **B** (render the member): renders each value as its representative.
- **C** (status quo, documented).
- **D** (`match` reads members). Four variants:
  - D-union adds member readings to today's;
  - D-members uses members only. It loses 40 paths that read back today,
    such as `1.0` for `{1}` under `!r`;
  - D-fallback reads members only where today finds nothing;
  - D-canonical adds member readings and replaces a reading by the member
    it equals when that member renders the same path.
- **E** (faithful rendering): accept a value only if it renders exactly
  as its representative would, in each field it fills. Output is
  unchanged for everything accepted.

**[Measured] What D-canonical changes where `match` already succeeds.**
- *Soundness:* 0 unsound readings. Every reading is re-verified by
  rendering.
- *No lost paths:* 0 paths that read back today stop reading back.
- *Changed readings:* 13 readings become the declared member:

  | Declaration | Form | Reading today | Reading under D-canonical |
  |---|---|---|---|
  | `{Split.TRAIN}` | `x/{c}` and others | `"train"` | `Split.TRAIN` |
  | `{True}` | `x/{c:d}` | `1` | `True` |
  | `{One.ONE}` | `x/{c:d}` | `1` | `One.ONE` |

  Each new value compares equal to the old, and is a subclass of the old
  type or the member itself.
- *New ambiguity:* 18 `AmbiguousMatchError`s, all for `{"1", 1}`. There,
  `x/1.txt` really is the rendering of two declared members, and today
  `match` silently returns `"1"`.

D-union, by contrast, adds 31 spurious ambiguities: `1` and `True` read
from one member `True`.

**[Measured] Representative recovery under E + D-canonical.** It holds for
277 of 281 accepted bindings. The 4 exceptions are NaN: three read back
but compare unequal (`nan != nan`), and one is §7's documented `!r`
limit. The one unread path is the same `!r` case.

## Counterexamples to keep in mind

1. **`choices` acceptance is equality.** `1.0`, `True`, `1+0j`,
   `Decimal("1.0")`, `Fraction(1)` and `One.ONE` all pass `{1}`, and render
   six different texts.
2. **Representative depends on order.** Under B, `choices=[1, True]` and
   `[True, 1]` would render `True` differently, since the frozenset keeps
   whichever came first.
3. **Acceptance under E depends on the spec.** `True` under `type=int` is
   refused in `{n}` (`True` vs `1`) and accepted in `{n:d}` (`1` vs `1`).
   `Split.TRAIN` for `{"train"}` is accepted in `{c}` and refused in
   `{c!r}`.
4. **A member need not render what an equal value renders.** For
   `choices={1}` under `!r`, `1.0` renders `1.0` and the member `1`
   renders `1`. Replacing a reading by its member without re-verifying is
   unsound; the first version of the prototype did exactly that.
5. **NaN.** `choices={nan}` accepts only that NaN object (identity in the
   set). Another NaN is refused, and NaN never compares equal on
   recovery.
6. **`match` never says `True` for an `int` field**, even where `True` is
   the only declared member: `{True}` under `{c:d}` reads the int `1`.

## Proposed SEMANTICS.md wording

**[Proposal]** For §3, after "Declared `type` and `choices` are checked
against `v` as given":

> **Choices.** `choices` is a set of members. A value is accepted if it is
> a member or compares equal to one; that member is its *representative*.
> Two members that compare equal but differ in type or `repr` (`1`, `True`
> and `1.0`, as for defaults in §3.1) cannot be declared together.
> Declarations compare their choices member by member under the same rule.

For §7, under *Completeness*, new first bullet:

> - A parameter that declares `choices` reads, in each position, every
>   member whose rendering there is the text, as well as the values its
>   type or spec reads (below). A value read that equals a member is
>   returned as that member when the member renders the same path. So
>   every declared member reads back as itself, and a path is ambiguous
>   when two members render it alike.

For §7, under *Limits* (until E lands):

> - A value accepted because it equals a member, or is an instance of the
>   declared type, but that renders differently from its representative
>   (`1.0` for `choices={1}`, `True` for `type=int` under `{n}`) renders a
>   path that may not read back. *[With E: such a value is an invalid
>   binding.]*

For §8's table:

> | every declared member of `choices` reads back as itself (path completeness for members) | **tested** (members of every kind, in every position) |

## Recommendation

**[Proposal]** In order, each a separate core change:

1. **Fix Param equality** (finding 1). It is a bug against the code's
   stated invariant, with no semantic change, and the strict xfail turns
   green.
2. **D-canonical in `match`** (finding 2). It changes no output, loses no
   path, makes 13 readings more precise, and raises the new ambiguity only
   for genuinely ambiguous declarations. In core it is a per-field rule:
   - in `_field_values`, compare the text with each member's rendering
     under the field's static spec (a finite set, cacheable per field), and
     map today's readings to their members;
   - for a whole segment, a head or a SubPath, compare the text with each
     member's `os.fspath` or `{m}` text;
   - the fast path's "choice" shape could then cover non-string choices
     too, as an alternation of the members' texts.

   `type=SomeEnum` could read its members the same way, since an `Enum`
   type is a finite set of members.
3. **Refuse equality-colliding members** (finding 3) in 0.2.0. A
   declaration that lists `1` and `True` is almost certainly a mistake,
   and §3.1 already draws the line. Members that only render alike are
   not refused.
4. **E, staged.** In 0.2.0, warn when a binding renders unlike its
   representative, naming the value, the field and the two texts. Refuse
   it in a later release. B is rejected:
   - it changes 229 outputs silently, so files land at different paths
     with no error;
   - it depends on declaration order (counterexample 2);
   - it turns `choices` from an acceptance constraint into a
     representation rule, which is a different contract.

   E makes the same 229 cases loud instead. Together with D, it gives
   representative recovery: every accepted binding reads back as its
   representatives, except where formatting is lossy (§7 limits) or
   members render alike (ambiguity).
5. **Keep §7's `bool` rule as documented until E.** E subsumes it: `True`
   under `type=int` in `{n}` becomes an invalid binding instead of an
   unreadable path.

**[Measured]** For the overlap analysis, D and E would make choices exact
in strict mode, so the numeric-twins workaround and part of
`builtin_values` could go.

## Decisions (owner, 2026-10-21)

**[Decision]** The trade-offs this entry left open were decided as
follows. They are design decisions for future core work, each to land as
its own focused change, not changes made in this PR:

1. **Faithful rendering is checked per field.** A value's text depends on
   the field's spec (`True` renders `True` in `{n}` and `1` in `{n:d}`),
   so E is a field-level guarantee. Parameter-level checks (`Param.check`,
   and integrations that call only it) enforce only format-independent
   invariants. The core semantics are not weakened to suit integrations.
2. **`match` returns the declared member,** including `Enum` and
   `StrEnum` members (`Split.TRAIN`, not `"train"`). The 13 type changes
   the audit found are documented and tested when D lands, and every
   reading stays verified by rendering.
3. **Custom `__format__` is not banned.** The contract is faithfulness:
   a value accepted through a choice must render as its member does, in
   the field at hand. A custom formatter that does so is fine. Accepted
   values that do not are warned about during a transition, and
   rejecting those specific bindings is considered after it.
4. **Legitimate ambiguity is preserved.** Distinct members that render
   alike (`{"1", 1}`) are allowed, and `match_all` returns each reading;
   `match` raises `AmbiguousMatchError` as for any ambiguous path. Only
   accidental conflation is fixed: `Param` equality (finding 1) and
   members a `frozenset` collapses (finding 3). wend does not require
   every expression to be invertible.

## Remaining trade-offs

- **Type changes from D-canonical.** Code comparing with `==`, or treating
  the value as a `str`, is unaffected; code checking `type(x) is str` is
  not. To be named in the release notes.
- **Prototype cost.** The prototype matches once per combination of
  members, which is exponential in the number of choice parameters. That
  is fine for tests, not for the matcher; the per-field rule above is
  linear.
- **Redundant verification.** The prototype's final verification step is
  redundant: every source of readings is already verified, and a
  mutation that removes it survives the tests. It is kept as defence in
  depth.
