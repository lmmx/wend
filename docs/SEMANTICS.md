# wend semantic contract

This document fixes what a wend expression *means*, independently of how
`src/wend` computes it. The audit tests (`tests/contract_test.py`) evaluate
expressions with a separate reference evaluator written from this document
alone (the first half of that file). That evaluator does not use wend's normal
form, simplifications, matcher or compiler.

Paths are POSIX paths with `pathlib.PurePosixPath` semantics throughout.

## Status

Contract version 0.2, **proposed**. It describes wend as it will be released as
0.2.0, and is ratified by that release; until then any section may change. A
change to this document comes with the matching change to the reference
evaluator in `tests/contract_test.py`, and the reverse.

Decisions this version adopts, provisional until ratification:

- the hybrid semantics of §6, with its three refinements: structural
  elimination, non-strict evaluation, and whole-segment interpolations joined
  like `/`;
- a parameter after the head binds one segment unless declared otherwise (§2,
  §3);
- a non-path value at a segment position is formatted natively, so `None` gives
  `"None"`; a declared `type=` rejects values of other types (§3);
- integer-formatted fields keep their format type (§4);
- matching raises rather than choosing between readings (§7);
- a parameter's default stands in for an absent binding when a path is
  rendered, and nowhere else: not in `bind`, matching or discovery (§3.1).

`glob`'s symlink policy is a traversal policy documented on `glob`, outside this
contract. This version adds parameter defaults (§3.1), connectivity (§9),
conditions (§10), unions and queries (§11), schemas (§12) and lineage (§13).
A later version is expected to extend the contract for Windows path flavours.
§14 describes the experimental run model of `wend._experimental` on the research
branches. It is not part of the contract. §15 adds relations between families
(`wend.relate`) and effects across a pipeline (`wend.effects`).

## 1. Terms

An expression is built from these terms:

| term | built by |
|---|---|
| literal path `s` | `P("a/b")`, `x / "a/b"` |
| parameter operand `p` | `P(p)`, `x / p`, `p / x` |
| template `t` | `T(t"...")`, `x / t"..."` |
| text field | `name(a)`, `stem(a)` or `suffix(a)` interpolated into a template |
| join `a / b` | `/`, `joinpath` |
| `parent(a)`, `with_suffix(a, s)`, `with_name(a, n)`, `with_stem(a, s)`, `relative_to(a, b)` | the methods of the same names |
| `name(a)`, `stem(a)`, `suffix(a)` | properties; these yield strings, not paths |
| `child`, `under`, `sibling(a, n)`, `cousin(a, p, *names)`, `rebase` | the methods of the same names, defined in §9 by `parent` and `/` |
| `requires(a, *cs)`, `ensures(a, *cs)` | the methods of the same names; they denote `a` and declare conditions (§10) |
| `tag(a, **kw)` | the method of the same name; it denotes `a` and attaches tags (§13) |
| union `a₁ \| … \| aₙ` | `\|`, `U(...)`, `U(t"...{Alt(...)}...")`; not an expression, an ordered set of them (§11) |

## 2. Position of a parameter operand

A parameter declared `Kind.AUTO` takes its kind from its position:

- **head**: nothing precedes it in the joined expression except statically
  empty terms (below). It acts as `Kind.PATH`.
- **elsewhere**: it acts as `Kind.SEGMENT`. This includes a parameter whose own
  expression applied operations to it before being joined below a non-empty
  term: in `base / P(p).with_suffix(".png")`, `p` is a segment and the
  operation applies to it as one.

Joining `a / b` where `a` is statically empty leaves the head position of `b`
unchanged; any other `a` puts `b`'s first operand in a non-head position. A
parameter declared with an explicit kind keeps it wherever it appears.

A term is **statically empty** when its structure makes it `.` for every
binding, that is, when it is relative and its number of segments is
statically 0. The number of segments is static for:

- a parameter-free term: the segments of its value;
- a segment parameter: 1;
- a template: the count of its segments (§4), when every path operand in it
  has a static count;
- `a / b`: the sum of the two counts;
- `parent(a)`: one fewer than `a`'s count, and never below 0;
- `with_suffix`, `with_name` and `with_stem` of `a`: `a`'s count;
- `relative_to(x, x)`: 0, and `relative_to(x / y, x)`: `y`'s count.

- `sibling` and `cousin`: as their definitions in §9.

It is not static otherwise (for example, for a `PATH` or `SUBPATH` parameter).

## 3. Values of parameter operands

Let `v` be the bound value. Declared `type` and `choices` are checked against
`v` as given. Its text `s` is then:

- for `PATH`, `ABSOLUTE` and `SUBPATH`: `v` itself if it is a `str`, or
  `os.fspath(v)` if it is an `os.PathLike` returning `str`. Any other value is
  **invalid**, as it would be for pathlib.
- for `SEGMENT`: the same for `str` and `os.PathLike`. `bytes` are invalid.
  Any other value is formatted as an f-string formats `{v}`, so `3` gives
  `"3"` and `None` gives `"None"` (a declared `type=` rejects values you do
  not expect). A format call that fails makes the binding invalid (§4).

Text containing NUL is invalid. No path can contain NUL, so the rule
applies to literal text too: a literal path, template text, name, stem or
suffix containing NUL is an operation error, and a bound value containing
NUL is an invalid binding.

| kind | requirement | contributes |
|---|---|---|
| PATH | none | `PurePosixPath(s)` |
| ABSOLUTE | `PurePosixPath(s)` is absolute | `PurePosixPath(s)` |
| SEGMENT | no `/`; `s` not in `{"", ".", ".."}` | the single segment `s` |
| SUBPATH | `PurePosixPath(s)` is relative and has no `..` part | `PurePosixPath(s)` |

### 3.1 Defaults

A parameter may declare a default `d`: `Param(name, default=d)`, or the same
keyword on `Segment`, `SubPath`, `AnyPath` and `Absolute`.

**Declaration.** The default is part of the declaration. Two declarations that
differ only in their defaults are different, so using both under one name is
a declaration conflict. Two defaults are the same only if they have the same
type, compare equal and have the same `repr`: `1`, `True` and `1.0` compare
equal but render apart. Choices compare the same way, member by member:
`choices={1}`, `{True}` and `{1.0}` are equal sets but different
declarations.

`d` must be hashable, and must be a valid binding as far as the declaration
alone decides:
- it satisfies `type` and `choices`;
- for an explicit kind, it meets that kind's requirement in the table above;
- for `AUTO`, whose kind depends on position (§2), it is a path or a value a
  segment can format.

Wherever the parameter is used, its default is checked again like any binding,
so an `AUTO` default such as `"/srv"` is valid at the head and invalid below it.

**Rendering.** Let `env⁺` be `env` extended, for every parameter of `e` that
declares a default and whose name `env` does not bind, with that default.
Every route that renders `e` with `env` renders it with `env⁺`, and §6 holds
with `R(e, env⁺)` in place of `R(e, env)`. The routes are `render`, `resolve`,
compiled renderers, `Under` bases (§10), a lens's target, and `resolve_frame`
for a parameter with no column.

So rendering with a default is rendering with the default bound explicitly.
Only an absent name takes its default: a name bound to any value, `None`
included, is bound to that value (§3). A parameter without a default that
`env` does not bind is a missing binding, and `required_params(e)` lists
exactly those.

**Binding.** `bind` is partial evaluation and does not apply defaults. A
parameter it is not given stays free, with its declaration and so its
default. `e.defaults` gives the free parameters' defaults by name, and
`e.bind(e.defaults)` applies them.

**Matching and discovery** do not use defaults (§7). A default does not make
any part of a path optional: a path must contain every part of `e`, defaulted
or not. Each reading binds every parameter to what the path holds, whether or
not it equals the default. `glob` does not fix an unbound defaulted parameter
to its default; it discovers its values, and an unbound head is an error as
before.

### 3.2 Environments

An environment is given as a mapping keyed by name or by `Param`, or as an
object, plus keyword bindings, which take precedence. An object binds its
declared fields by name:
- the fields of a dataclass, attrs or Pydantic instance (and a model's extra
  fields);
- the fields of a named tuple;
- for any other object, its instance attributes (`vars`).

Properties, methods and Pydantic computed fields bind nothing. `wend.bindings`
gives the mapping an object stands for. How an environment is given does not
change its meaning.

## 4. Templates

A t-string's literal text is split at every `/`. The pieces between separators
form *segments*. A leading `/` (or exactly `//`) anchors the path, as in
pathlib. A segment is one of:

- **literal text only**: dropped if it is `""` or `"."`; otherwise a segment
  (a literal `..` is kept, as pathlib keeps it);
- **a single interpolation with no conversion and no format spec, whose value
  is a `Param`, `str`, `os.PathLike`, path expression or template**: a *path
  operand*, joined exactly as `/` joins it (§2, §3 for parameters; literal
  path semantics for strings);
- **anything else**: a *formatted segment*, the concatenation of its literal
  text and its *fields*. A field is an interpolation with value `v`,
  conversion `c` and spec `s`:
  - `v` is the bound value of a `Param`, checked against its `type` and
    `choices` first; an interpolated constant; or the string `name(a)`,
    `stem(a)` or `suffix(a)` of a path expression `a`, evaluated as an
    expression of its own;
  - a spec may contain nested parameters (`{x:0{w}d}`). Each is checked
    against its declaration and replaced by `format(w, "")`. A spec with no
    nested parameter is *static*;
  - the field's text is `format(convert(v, c), s)`. A `format` call *fails*
    when it raises `TypeError`, `ValueError` or an `ArithmeticError`, such
    as the `OverflowError` of `{n:c}` with `n=-1` or of `{n:f}` with
    `n=10**400`. A failing call, for a field or for a nested spec
    parameter, makes the binding invalid; any other exception (from a
    value's own `__format__`, say) propagates;
  - the text must contain neither `/` nor NUL;
  - an *integer-formatted* field (no conversion, a static spec, and a
    presentation type of `b`, `d`, `o`, `x` or `X`, or no presentation type
    with an `int` parameter or constant) must also be non-empty, and must
    contain no `.` unless `.` is its fill character. Structural operations
    rely on these guarantees, for example a static suffix after `{n:04d}`, so a
    value whose `__format__` breaks them is invalid.

  The concatenated segment must not be `""`, `"."` or `".."`. Otherwise the
  binding is invalid.

The template's value is its anchor joined with its segments in order, using
pathlib join semantics.

### 4.1 Differences from formatting the t-string as an f-string

Conversions (`!r`, `!s`, `!a`), format specs (nested ones such as `{x:{w}}`
included), `{x=}` text, and the text of any value at a segment position are
exactly what Python's formatting produces. The template then differs from
`PurePosixPath(f-string)` only where the structure would otherwise change:

| template and binding | f-string, then `PurePosixPath` | wend | why |
|---|---|---|---|
| `t"{root}/data"`, `root=""` | `/data` | `data` | a whole-segment interpolation is joined like `/`, so an empty value is the empty path, not an anchor |
| `t"data/{x}"`, `x="a/b"` | `data/a/b` | invalid | after the head, a parameter is one segment unless declared `SubPath` or `AnyPath` |
| `t"data/{x}"`, `x` in `""`, `"."`, `".."` | `data`, `data`, `data/..` | invalid | a segment cannot vanish or climb |
| `t"data/{x:.0}"`, `x="abc"` | `data` | invalid | a formatted segment cannot be empty |
| `t"{x}{y}"`, `x="a/"` | `a/b` | invalid | a formatted field cannot contain `/` |
| `t"{root}/data"`, `root=3` | `3/data` | invalid | path positions take paths (§3) |
| `t"data/{x}"`, `x=b"q"` | `data/b'q'` | invalid | bytes are not text |
| `t"data/{x}"`, `x` an `os.DirEntry` | `data/<DirEntry 'q'>` | `data/q` | a path-like value contributes `os.fspath(v)` |

## 5. Operations

- `a / b` is `R(a) / R(b)` (pathlib: an absolute right side replaces the left).
- `parent`, `with_suffix`, `with_name`, `with_stem`, `relative_to`, `name`,
  `stem` and `suffix` are the pathlib operations on the values of their
  operands. A `ValueError` from pathlib is an **operation error**.

## 6. The reference value and wend's obligations

The reference value `R(e, env)` evaluates every sub-term (it is strict),
applying §2–§5, with each parameter whose name `env` does not bind taking its
default (§3.1). It either yields a path (or string), or fails with an invalid
binding or an operation error.

wend's obligations, for every expression `e` and environment `env`:

1. **Agreement.** If `R(e, env)` yields `x`, then `e.render(env)` returns
   `str(x)` (and `name`/`stem`/`suffix` render to the reference string).
2. **No spurious rejection.** If `R(e, env)` yields a value, wend does not
   raise.
3. **Strictness without elimination.** If `e` consists only of joins of
   relative literals, parameters and templates (no operation can discard a
   sub-term), then `e.render(env)` raises exactly when `R(e, env)` fails.
4. **Permitted non-strictness.** Otherwise, if `R(e, env)` fails, wend may raise
   or may return a value. It returns a value only when the failing sub-term is
   one that a structural operation discards:
   - the dropped last segment of `parent`;
   - the replaced last segment of `with_name`/`with_suffix`/`with_stem`;
   - the prefix removed by `relative_to`;
   - everything before an absolute join.
5. **Errors are typed.** Invalid bindings raise `InvalidBindingError`;
   operation errors raise `PathOperationError` (both are `ValueError`s);
   unbound parameters without a default raise `MissingBindingError`.

## 7. Matching

`match_all(e, path)` returns bindings `b` with `e.render(b) == str(PurePosixPath(path))`:

- **Soundness:** every returned binding renders to the path.
- **Completeness:** every binding that renders to the path appears in the
  result (up to `limit`), with the *limits* below. Field values are parsed
  as the parameter's declared `type` (each member in order, for a tuple or
  union of types such as `int | None`, as `isinstance` reads them), or as
  the types its format spec implies:
  - a presentation type implies one: `s` → `str`; `b`, `c`, `d`, `n`, `o`,
    `x`, `X` → `int`; `e`, `E`, `f`, `F`, `g`, `G`, `%` → `float`;
  - without one, the first of `str`, `int` and `float` that formats under
    the spec. A `str` takes no sign, `z`, `#`, grouping or `=` alignment,
    and an `int` no `z` or precision, so `{u}`, `{u:>5}` and `{u:.3}` read
    `str`; `{u:+5}`, `{u:,}`, `{u:=5}`, `{u: }`, `{u:_}` and `{u:#}` read
    `int`; `{u:z}` and `{u:+.3}` read `float`. Such a field reads what a
    field declared with that type reads, where reading `str` would find
    nothing.
  - The exception: an untyped field whose spec zero-pads like a number (the
    `0` flag before a width, with no alignment, precision or presentation
    type, as in `{u:05}`) is read both as `str` and as `int`. `format` fills
    a `str` with `0` on the right and an `int` with `0` after its sign, so
    `00005` reads as `"00005"` and `5`, and `ab000` as `"ab"`, `"ab0"`,
    `"ab00"` and `"ab000"`.
- **Choices:** a parameter that declares `choices` also reads, in each
  position (a field, a whole segment, a head or a `SubPath`), every member
  whose rendering there is the text. A value read as above that equals a
  member is returned as that member when the member renders the same text.
  So every declared member reads back as itself (`choices={1}` reads
  `x/1.txt` as `1`, and `choices=set(Split)` reads `train` as
  `Split.TRAIN`). Distinct members that render alike (`{"1", 1}`) make the
  path ambiguous. A value accepted because it equals a member but rendering
  differently from it (`1.0` for `choices={1}`) is read back only as the
  rules above read its text.
- **Declared types:** a field reads values of exactly its declared type: an
  `int` field does not read `True`, although `{n:d}` renders it as `1`.
  (Under `!r` and `!a` it reads the literal the text spells, if the declared
  type accepts it: `{n!r}` reads `False` for an `int` field.) A `bool`
  formats as `True` or `False` under the empty spec and as the number `1` or
  `0` under any other, so a `bool` field reads `True` and `False` from those
  texts. An `int` or a `bool` formats under a float presentation type (`e`,
  `f`, `g`, `%`, ...) as the float it converts to, and is read from it.
  Under `!s`, a declared type reads each value whose `str` is the text:
  `int(text)`, `float(text)` or `T(text)` for another type `T`, and `True` or
  `False` for `bool`.
- **Padding:** a field padded to its width is read with every number of fill
  characters that `format` could have added, from none to the whole run on
  the padded side (both sides for `^`, after the sign for `=`). A value may
  itself begin or end with the fill character: `{u:x<5}` reads `abxxx` as
  `"ab"`, `"abx"`, `"abxx"` and `"abxxx"`, and `{n:->4d}` reads `---5` as `5`
  and `-5`.
- **Limits:** completeness does not hold where formatting discards part of
  a value, so that a field's text has more preimages than its readings:
  infinitely many, or more than one value of the type represents. Soundness
  still holds there: every returned binding is verified by rendering.
  - A precision truncates a `str`: `{u:.3}` renders `abc` for every `u` that
    starts with `abc`. The field reads its text, `"abc"`, alone.
  - A float presentation type (`e`, `f`, `g`, `%`, ...) rounds: `{x:.1f}`
    renders `0.5` for every float from about `0.45` to `0.55`. The field
    reads `float(text)` alone, and an `int` field the integer of that float:
    `{n:.1e}` renders `1234` as `1.2e+03`, read as `1200` alone. Floats an
    untyped spec implies (`{u:+.3}`) are read the same way.
  - An untyped field reads only the types its spec implies (above), so a
    float that renders under an untyped spec that implies `str` or `int` is
    not read: `{u:05}` renders `5.0` as `005.0`, read as `"005.0"` and
    `"005."` only, and `{u:+}` renders it as `+5.0`, read as nothing.
  - `n` writes the current locale's separators. Its text is read as if
    they were `,` or `_`, or there were none, as in the default C locale.
  - `!r` and `!a` are read with `ast.literal_eval`, so a value whose repr is
    no literal (`inf`, `nan`, most objects) is not read. A text that repr
    could not have written (an escape repr never writes, such as `\+`, an
    f-string, or a number run into a word, as in `1if`) is refused before
    `literal_eval`, which would warn about it. Rendering would not verify
    such a text anyway, so no reading is lost.

  In these cases `match` may return one binding where several render to the
  path, rather than raise `AmbiguousMatchError`: it reports ambiguity among
  the readings, not among every preimage.
- `match` returns the single binding, `None` if there is none, and raises
  `AmbiguousMatchError` if there are several.
- **Defaults** play no part (§3.1). Every returned binding binds every
  parameter of `e` to what the path holds, so a path that leaves out a
  defaulted part does not match, and verification never fills in a default.

## 8. What is guaranteed by construction, and what is only tested

| property | status |
|---|---|
| a `match`/`glob` result renders to its path (matching soundness) | **by construction**: every candidate is checked by rendering before it is returned |
| a compiled function raises the same errors as the interpreter | **by construction**: any exception in the fast path re-runs the interpreter |
| the matching fast path returns at most one binding | **argued** (below) and tested |
| every declared member of `choices` reads back as itself, and the fast path agrees with the full search | **tested** (Hypothesis, members of mixed types in every position) |
| obligations 1–3 above (agreement, no spurious rejection, strictness) | **tested** (Hypothesis, independent reference evaluator). Random terms cover every term of §1, every parameter kind, nested format specs, text fields, parameters with defaults, and values whose `__format__` breaks their format type |
| rendering with a default equals rendering with it bound explicitly, interpreted and compiled; `bind` leaves defaulted parameters free; every reading binds every parameter (§3.1) | **tested** (Hypothesis, random terms with defaulted parameters, and environments that leave them unbound) |
| below a literal base, no binding of an `AUTO`, `Segment` or `SubPath` parameter leads outside it, whatever operations the term applies | **tested** (Hypothesis, random terms) |
| `rebase(old, new)` equals building the expression afresh with `new` in place of `old` (§9) | **tested** (Hypothesis, random terms and substitutions) |
| a join equals its `base` joined with its `base_rel` | **tested** |
| a path rendered with `Under(b)` declared is contained in `b`, and every contained rendering is returned unchanged (§10) | **by construction** (each render checks the rendered strings) and **tested** (Hypothesis, random terms and bases, interpreted and compiled) |
| `declares` names the declared conditions, follows `bind`, `rebase` and the other operations as §10 says, and a union declares what all its alternatives declare (§10.1) | **tested** (Hypothesis, random terms, declarations and operations) |
| `Step.effects` is `declares.verbs` (§10.1) | **by construction** |
| a union's readings of a path are exactly its alternatives' verified readings, and `match` reports one, none, or ambiguity accordingly (§11) | **by construction** (readings are the alternatives' `match_all`) and **tested** (Hypothesis, random pairs of terms) |
| an inferred schema, declared with `from_inferred` or written out with `source()`, validates the tree it was inferred from (§12) | **tested** (Hypothesis, random trees with and without empty directories; real trees in the journal) |
| matching completeness, outside the limits of §7 | **tested** (Hypothesis round trips; exhaustive enumeration over small domains, which also checks that the limits return only verified bindings) |
| compiled successes equal interpreted successes | **tested** |
| a compiled set (`compile_many`) gives each expression's rendering, in order, and the first failing expression's error | **by construction** (any exception in the shared fast path re-renders each expression with the interpreter, in order) and **tested** (Hypothesis, random sets of terms) |
| Polars results equal `render` | **tested**, on the supported subset |
| every observed path matches an inferred layout of its kind (file or directory), and the layouts' counts partition the observed paths of each kind | **by construction** (inference verifies each path against its layout and the counts per kind, and raises otherwise) and tested |

**Fast-path uniqueness argument.** A fast-path segment is a sequence of
literals and fields (no conversion, a static spec), where each field is:

- an *integer* field (untyped or `type=int`): spec `[0N]t` with `t` one of
  `b d o x X`, or `[0N]` with `type=int` (`t = d`). Its renderings are
  `-?D+` for the digit class `D` of `t` (`01`, `0-7`, `0-9`, `0-9a-f`,
  `0-9A-F`). An untyped field with spec `05` also reads `str` values (§7),
  so it is not one;
- a *choice* field (untyped or `type=str`): spec `""` and `choices` that are
  all `str`. Its renderings are the choices;
- a *free* string field (untyped or `type=str`): spec `""`, any text without
  `/`. A whole-segment parameter is free too, as the segment's only piece.

The segment needs a *pivot* field (the free field, if any). Every field before
the pivot must be *forced from the left* by the piece after it. Every field
after the pivot must be *forced from the right* by the piece before it:

| field | forced from the left | forced from the right |
|---|---|---|
| integer, class `D` | the next piece is a literal not starting with a character in `D` | the previous piece is a literal not ending with a character in `D` or `-` |
| choice; `L` is the literal on that side, `""` for a field | for distinct choices `c` and `c + r`, neither of `r` and `L` is a prefix of the other | the mirror: for `c` and `r + c`, neither of `r` and `L` is a suffix of the other |
| free | never | never |

Reading from the start of the segment, each piece before the pivot starts at a
forced position and ends at a forced one:

- a literal has a fixed length;
- an integer field `-?D+` ends at the first character after its digits that
  is not in `D`, since the next literal starts there;
- a choice field can be only one choice: if `c` and `c + r` both fit, then `r`
  and `L` both start the rest of the text, so one is a prefix of the other.

Reading from the end gives the mirror argument for the pieces after the pivot.
There, an integer field starts where its maximal run of `D` characters
starts, or one character earlier if that character is `-`. The previous
literal cannot end with either character, so it cannot take that position
instead. The pivot takes the text in between. Every span is forced, and
values come from spans by `int(span, base)` or identity, so each segment has
at most one binding. The padding readings of §7 add none: these fields are
padded only with `0`s after an integer's sign, and taking any of those off
leaves the same integer.

A free field is never forced: it may contain any literal next to it. So there
is at most one per segment, and only as the pivot. `{a}{b}`, `{n:02d}{w}` and
`{w}-{n:d}` are ambiguous (for the last, `x--5` is `w="x", n=-5` or
`w="x-", n=5`) and use the full search. `choices` make a field's values
finite, so the condition is checked on the declared values.

The whole path is one regex `fullmatch` on the canonical path. Each segment
regex matches only non-empty text without `/`, so segments line up with
separators:

- under a literal or root head without a `SubPath`, the segments are the
  path's components;
- under a literal or root head with one `SubPath`, the segments before it take
  the first components and those after it the last ones. Both counts are
  fixed, so the `SubPath` takes the run in between (`.` when empty);
- under a head parameter without a `SubPath`, the segments take the last
  components and the head the rest.

A head parameter with a `SubPath`, two `SubPath`s, or a deferred head have no
forced split. For example, `root / SubPath("s") / "x"` reads `/a/b/x` both as
`root="/a/b", s="."` and as `root="/a", s="b"`. Those use the full search,
which reports the ambiguity. Fast results are still verified by rendering.
The tests enumerate every two-field segment template over these field kinds
and boundary literals, and check that a plan never meets an ambiguous path
and agrees with the full search.

## 9. Connectivity

An expression records how it was built: the public operation and the
arguments it was given, its *derivation*. A derivation is not part of the path
an expression denotes. Expressions compare and hash by the paths they denote,
and rendering, matching and every obligation above ignore derivations.

- `x / y`, `x.child(*parts)` and `y.under(x)` are joins. A join's **base** is
  its left operand `x`. Its **relative part** (`base_rel`) is its right
  operand, in the position the join gave it (§2). Bases chain:
  `(root / "a" / "b").base.base` is `root`, and `relative_to` flattens a chain.
- `sibling(a, n)` is `parent(a) / n`.
- `cousin(a, p, *names)` starts at `parent(a)`. Each component of the relative
  path `p` is either `..`, which takes the parent, or a name, which is joined.
  Then each of `names` is joined. An absolute `p` is an operation error.
- `rebase(a, new)`, for `a` built by a join, is `new / base_rel(a)`.
- `rebase(a, old, new)` rebuilds `a` with `new` in place of every expression in
  its derivation that is equal to `old`, re-applying each recorded operation.
  Positions, structural results and errors are therefore those of building the
  substituted expression afresh: rebasing a path moves its siblings, cousins
  and suffix variants with it. If `old` is not in `a`'s derivation, `old` must
  be a structural prefix of `a`, and the result is `new / relative_to(a, old)`.

## 10. Conditions

An expression may declare *conditions*: what its path must be when it is used
(`requires`) and after it has been produced (`ensures`). Like a derivation,
conditions are not part of the path an expression denotes. Expressions with
different conditions compare and hash equal, and §6's obligations are about the
path alone. Conditions only add failures:

- `render(e.requires(Under(b)), env)` is `render(e, env)` if that path is
  *contained* in `render(b, env)`. Otherwise it is a containment error (a
  binding error). Every route that renders applies this: `resolve`, compiled
  renderers, verification in `match` and `glob`, lenses, and `resolve_frame`.
  `b`'s parameters must be among `e`'s.
- A path `p` is contained in a base `q` when `p == q`, or when `p` and `q` have
  the same anchor, `q`'s components are a prefix of `p`'s, and no component
  after them is `..`. The rule is lexical and conservative: `/srv/a/../b` is not
  contained in `/srv`.
- Joining onto an expression declared `File` (in either phase) is an operation
  error: nothing is below a file.
- Declaring two conditions that cannot hold together in one phase (`Exists` and
  `Absent`, `File` and `Dir`, `Absent` with `Readable` or `Listable`, `File` and
  `Listable`) is an operation error.

Conditions belong to the expression they are declared on. `bind` and `rebase`
keep them, and pass each `Under` base through the same binding or rebasing.
Every other operation's result has none, including an argument that an
operation returns unchanged.

Everything else is checked against the filesystem by an explicit step:
`check(e, env)` for `requires`, `confirm(e, env)` for `ensures`, or a `Step`
grouping several paths. Each step renders first, so containment is checked
before anything is looked up, and raises the first condition that fails:

| condition | holds when | otherwise |
|---|---|---|
| `Under(b)` | contained in `b`, and `realpath(p)` is `realpath(b)` or below it | containment error |
| `Exists` | `stat(p)` succeeds (symlinks followed) | missing-path error |
| `Absent` | `lstat(p)` fails: nothing at the name, not even a broken link | path-exists error |
| `File` / `Dir` | `p` is missing, or is a regular file / a directory | wrong-kind error |
| `Readable` | `p` exists and `access(p, R_OK)` | missing-path or capability error |
| `Listable` | `p` is a directory and `access(p, R_OK \| X_OK)` | missing-path, wrong-kind or capability error |
| `Writable` | `p` exists and `access(p, W_OK)` (with `X_OK` for a directory), or `p` is `Creatable` | capability error |
| `Creatable` | `p` exists, or no broken symlink occupies `p` or a name above it, and its nearest existing ancestor is a directory with `access(·, W_OK \| X_OK)` | capability error |

A check has three outcomes: the condition holds, it is known not to (the
errors above), or it *cannot be determined*. The last is an indeterminate
error, never a known failure. Locally, a path that cannot be examined (a
`stat` that fails other than by the path being missing: no permission to
look, a symlink loop) is indeterminate.

Checks run on the local disk unless given another filesystem (`fs=`, as
`glob` takes). On an fsspec filesystem, which has no permission bits, each
condition is what the store can report:

| condition | holds when | otherwise |
|---|---|---|
| `Under(b)` | contained in `b` (a store has no symlinks, so a path resolves to itself) | containment error |
| `Exists`, `Absent`, `File`, `Dir` | as above, from a metadata lookup | as above; a lookup the store refuses is indeterminate, not absent |
| `Readable` | an object, on a store whose metadata takes the same permission as the content (S3, GCS, Azure, memory); a directory, as `Listable` | missing-path error; indeterminate on other stores |
| `Listable` | a directory whose listing succeeds | missing-path, wrong-kind, or capability error if the listing is refused |
| `Writable`, `Creatable` | the memory filesystem; `Creatable` also when `p` exists | capability error on read-only filesystems (HTTP, archives); indeterminate elsewhere, since a store cannot report whether a write would succeed without writing |

A union's `first` raises an indeterminate error rather than skip an
alternative it could not check, and a query's condition filter raises it
rather than drop the path.

Checks describe the filesystem at the moment they run. They are not atomic
with any later use of the path, and `access` reports the real user's
permissions. Like `glob`'s symlink policy, they catch mistakes and state
intent; they are not a sandbox.

### 10.1 Declarations

`e.declares` names what an expression declares as a value, `Declarations`, with
three parts:

- `requires`: the *atoms* declared by `requires`;
- `ensures`: the atoms declared by `ensures`;
- `under`: the bases of the `Under` conditions of either phase, in declaration
  order, each once.

Each condition other than `Under` declares one atom:

| condition | `Exists` | `Absent` | `File` | `Dir` | `Readable` | `Writable` | `Creatable` | `Listable` |
|---|---|---|---|---|---|---|---|---|
| atom | `exists` | `absent` | `file` | `dir` | `read` | `write` | `create` | `list` |

A declaration is an obligation that the expression states. It is not a fact about
the filesystem. Atoms are grouped by what makes them true, and so by when they hold:

| group | atoms | made true by | holds |
|---|---|---|---|
| containment, lexical | `under` | `render`, which checks every rendered path (§10) | for every path the expression renders |
| containment, physical | `under` | the filesystem: `realpath(p)` at or below `realpath(b)` (§10) | when a check finds it, like a state |
| state | `exists`, `absent`, `file`, `dir` | the filesystem | when a check finds it: `check` for `requires`, `confirm` for `ensures`, a `Step` on entry and exit |
| permission | `read`, `write`, `create`, `list` | the filesystem's permissions for the real user | when a check finds it |

Only the lexical half of containment is a fact about every rendered path. The
physical half can be ended by a symlink made after the check, like any checked
state.

A checked state or permission is true at the moment of the check and no later.
The contract does not say how long it lasts: any effect on the path may end it,
whether by a later step of the same program or by another process. Checking a
declaration certifies it once. Nothing in wend certifies that a checked fact still
holds.

`declares` follows the conditions (§10):

- `requires` and `ensures` add their atoms and bases;
- `bind` and `rebase` keep the atoms, and pass each base through the same binding
  or rebasing (a base not built from a rebasing's `old` is kept);
- every other operation's result declares nothing.

A union declares what every alternative declares (`&` of their declarations: the
atoms of each phase common to all, and the bases common to all). A path the union
describes comes from one alternative, so only the common declarations hold of it.
A union's effects are not those of its declaration: the verbs below are not
monotone, so the verbs of `&` can name an effect no alternative has (an
alternative that reads and ensures `exists`, and one that creates, have a meet
whose verbs are `create`). `Step` does not accept unions.

The effects of §10's `Step` are a function of the declaration (`Declarations.verbs`):

- each permission atom of either phase is a verb of the same name;
- `create` is also a verb when `exists` is ensured but not required;
- `delete` is a verb when `absent` is ensured but not required.

Declaring more never removes a permission verb, but it can remove `create` or
`delete`, because those two depend on an atom being *absent* from `requires`. This
matters to any representation that orders declarations by inclusion. Such an
ordering can certify every property that persists when atoms are added, and only
those.

### 10.2 Evidence

`check` and `confirm` return the path they checked: a path, which claims
nothing about it. `checked` and `confirmed` perform the same checks and return
*evidence* instead. Precisely, `e.checked(env)`:

1. renders `e` with `env`, and fails with a containment error unless each
   `Under` base of `e.requires` contains it lexically (§10);
2. checks each condition of `e.requires` against the filesystem (`fs=`, or the
   local disk), containment first, then state, then permissions, and raises
   the first that fails, as `check` does. Locally, the state atoms (`exists`,
   `absent`, `file`, `dir`) are read from one `stat` and one `lstat` of the
   rendered path; each permission atom is its own `access` call, and physical
   containment its own resolution;
3. returns a `Checked` recording the rendered path, the atoms of `e.requires`
   and the rendered `Under` bases it was found under (lexically, and after
   resolving symlinks).

`e.confirmed(env)` is the same for `e.ensures`, returning a `Confirmed`. There
is no evidence of a check that failed: either call raises instead.

What the evidence states, and what it does not:

- **Which conditions.** Exactly those of one phase: an entry check
  (`checked`) certifies what the expression requires and none of what it
  ensures; a confirmation (`confirmed`) the reverse.
- **Which path.** The rendered path, a name. Not an object: the state atoms,
  each permission and containment are separate lookups of the name, so they
  may have been found true of different objects if another process changed
  the name between them.
- **Which moment.** Each condition held at some instant during the call, not
  necessarily all at the same instant. Outside a step the evidence has no
  epoch; a step (`Run`, research) stamps its own.
- **Containment, relative to the base as it is.** Physical containment
  compares `realpath(p)` with `realpath(b)`, both at that moment. If the base
  itself is redirected (replaced by a symlink), what lies below it moves with
  it and containment still holds: `Under` confines a path to its base, not
  the base to where it was. Fixing the base needs it held (a directory
  opened once, and every path resolved beneath it).
- **After.** Nothing. Evidence is a record of the past: a later change to the
  filesystem does not update it, and nothing about it says that the conditions
  still hold. Whether they are still believed is knowledge (§10.1, and the
  research analyses), conditional on what else may have written.
- **One subject.** Evidence is not a path and has none of a path's
  operations. `.path` gives the path it is about, as an ordinary path;
  anything derived from that path carries no evidence. `os.fspath` gives the
  same path, unchanged, and nothing else does. Evidence cannot be altered
  once made. It can be constructed directly, as any value can be cast; such a
  value certifies nothing.

The rule these state: *evidence does not survive an operation that changes its
subject*, whether a different path, a later moment or the other phase.

For a type checker, `PathExpr` has three parameters, a Hoare triple's
{C} e {Q}: `C` what it requires, `K` whether it is declared a File, `Q` what
it ensures. `checked` returns `Checked[C, K]` and `confirmed` returns
`Confirmed[Q, K]`. The operations carry them as §10 and §10.1 carry the
declarations themselves: `requires` adds to `C` and `ensures` to `Q`; `bind`,
`tag` and `P` keep all three; `rebase` keeps each phase's `Under` only as
`Under[str]`, since it moves the bases; every other operation's result, a
union included, declares nothing.

## 11. Unions and queries

A **union** `u = a₁ | … | aₙ` is an ordered, non-empty sequence of
expressions without repeats (equal alternatives keep the first). `|` and
`U(...)` flatten unions. Each alternative is an ordinary expression: unions
live outside the normal form, so every rule above applies to each alternative
unchanged.

**Alternatives in a t-string.** In a t-string given to `U`, an interpolation
`Alt(o₁, …, oₘ)` stands for `m` templates, one per option, with the option
spliced in place as text (a str), as a template (a t-string, which may hold
further alternatives), or as a parameter field. An interpolation whose value
is a union stands for one template per alternative, each joining that
alternative like any interpolated path. A template with several such
interpolations stands for the product of their options, the leftmost varying
slowest. Only `U`, `|`, and `/` with a union or with such a t-string produce
unions. `Alt` and union values are errors in `T`, `P`, names and suffixes.

**Operations distribute.** For a path operation `op` (`/` on either side,
`joinpath`, `child`, `under`, `parent`, `with_name`, `with_suffix`,
`with_stem`, `relative_to`, `bind`, `requires`, `ensures`):
`op(u) = U(op(a₁), …, op(aₙ))`. An operation error in any alternative is the
union's error. `u / v` for two unions is the product `U(aᵢ / bⱼ)` in order.

**Rendering.** A union with one alternative renders as that alternative. With
more, `render` is an operation error, because no single path is meant.
`renderings(u, env)` is the tuple of the alternatives' renderings, failing as
soon as one does. `first(u, env)` is an effect: it renders every alternative
(a rendering error is an error, not a reason to skip one) and returns the
first whose path exists and meets its own `requires`, checked as in §10. If
none qualifies, it is a no-alternative error listing what was tried.

**Matching.** The readings of a path `s` by `u` are the pairs `(i, env)` for
every verified reading `env` of `s` by `aᵢ` (§7). `match` returns the only
reading, with its alternative. It returns nothing when there are none, and is
an ambiguity error when there are several, whether one alternative or two
produced them. As in §7, wend does not choose between readings: alternatives
that overlap are disambiguated by declaring a field's `type` or `choices`.

**Discovery.** `glob(u)` yields, in path order, every path some alternative's
`glob` finds, with its reading. A path with several readings, because two
alternatives find it or one finds it under two bindings, is ambiguous and is
never yielded. As for an expression, `glob`'s `ambiguous=` option decides what
happens to it. The default raises an ambiguity error listing every reading
with its alternative. All of these errors are reported in path order, before
the first path is yielded.

**Queries.** A query is a source (an expression or a union) with filters.
- `q - x` admits a path when `x` has no reading of it.
- `q & x` admits a path when `x` has exactly one reading of it that agrees
  with the bindings so far (two agreeing readings are an ambiguity error). It
  adds that reading's bindings.
- `q.where(p…)` admits a path when every predicate holds:
  - a condition holds when §10's check passes;
  - a filesystem predicate (`modified_after`, `larger_than`, ...) holds when
  the stat it makes satisfies it;
  - a callable holds when it returns true for the match.

Filters form a conjunction, so their order does not change which paths are
admitted. wend evaluates pattern filters first, then callables, then
predicates that touch the filesystem. `glob(q)` streams the source's results
through the filters. Its `ambiguous=` option also covers the ambiguity errors of
`&`, each reported when the stream reaches its path. `match(q, s)` applies the
filters to the source's reading of `s`.

## 12. Schemas

A **schema** (`wend.schema.Tree`) names the entries of a layout. An entry is a
relative expression `e` (a fragment; a leading parameter is a segment, or a
splice for `SubPath`), a kind (file or directory) and a cardinality `[lo, hi]`
with `lo ∈ {0, 1}` and `hi ∈ {1, ∞}` (exactly one by default). An entry may be
built from another (`data / "raw"`). The relation is kept: in a bound schema,
the second's base is the first.

**Binding.** A schema bound to a root `r` and bindings `env` gives, for each
entry, `bind(r / e, env)`. It requires the entry's kind (§10), and also
`Exists` when the entry is exactly one and literal. Binding is pure.

**Validation** is an effect that observes the tree under `render(r)` as
`infer` does:
- real directories are descended;
- symlinked directories are neither descended nor reported, though an entry
  may match one;
- a symlink counts as a file or a directory by its target;
- names starting with `.` are skipped when the schema says `hidden = False`;
- paths under `ignore` patterns and inside `open` directory entries are not
  looked at.

An entry's matches are the observed paths of its kind that `glob(r / e)`
finds. For every directory `d` that matches `parent(r / e)` (the one directory,
when the parent is literal), unless `d` is hidden or ignored as above:
- some match must lie at or below `d` when `lo = 1`, otherwise it is a
  *missing* problem. For a fixed-depth entry this means directly in `d`. A
  recursive (`SubPath`) parent matches directories that may hold only
  subdirectories, and this reading agrees with `infer`'s `optional`;
- at most one match may lie directly in `d` when `hi = 1`, otherwise it is a
  *too-many* problem.

An observed path that no entry matches, and that is not a directory of a
path some entry matches or names literally, is a stray. Only the topmost
stray is reported.
- A stray is *wrong-kind* if an entry of the other kind matches it.
- Otherwise it is *misfiled* if its name matches some entry's last segment.
- Otherwise it is *extra*, reported with the nearest directory entry above it.

A missing path that a wrong-kind stray occupies is reported once, as
wrong-kind. Paths that several entries match are listed as overlaps, which
are not problems. Validation reports every problem, not the first.

**Scaffolding** is an effect. It creates the directories of directory
entries and the parent directories of file entries, missing ancestors first.
With `files=True` it also creates an empty file for each required file entry,
with `O_CREAT | O_EXCL`, so nothing is overwritten. An entry with unbound
parameters is created once per combination of their declared `choices`, and
skipped when one has none.

**Inference round trip.** `from_inferred(s)` makes one entry per layout:
- the same pattern and kind;
- the same cardinality: optional when the layout is, and many when the
  layout is (some observed directory holds more than one of its paths
  directly). A layout reports its cardinality with the type entries declare.

`hidden` is set as inference observed the tree. `Tree.source()` writes a schema
as Python that rebuilds the same entries. An inferred schema's declaration
validates the tree it was inferred from, with one exception: a symlinked
directory that matches a `dir` layout which is not many, in a directory that
also holds an observed path of that layout. Inference does not observe the
symlinked directory, but validation counts it as a match, so the directory
holds two.

## 13. Lineage

**Tags.** `tag(e, **kw)` denotes `e`. Tags are metadata, as conditions are
(§10): outside equality and hashing, kept by `bind` and `rebase`, and absent
from every other operation's result. The tags *of* an expression in the
lineage sense, `lineage.tags(e)`, are the union of the tags on every expression
in `e`'s derivation (§9), sources first, so a nearer expression's tag wins.

**Lineage of expressions** is the derivation (§9):
- `upstream(e)` is every expression the derivation reaches, sources first,
  each listed once;
- `explain(e)` writes each recorded operation out.

Both are pure.

**Lineage of artefacts** is an append-only ledger of records. A record says
that path `o` was made from paths `i₁ … iₙ` by an operation, with the
bindings, tags and content digests at that time. Paths are made absolute and
normalised, and a path's latest record is its provenance.
- `upstream(o)` follows provenance from `o` to its inputs, transitively.
- `downstream(i)` follows it from `i` to the paths made from it, using each
  path's latest record.
- `stale(o)` lists the inputs of `o`'s provenance that are missing now, or
  whose current digest differs from the recorded one. It does not recurse:
  combine it with `downstream` for transitive invalidation.

Recording and checking staleness read files, so they are effects.
`Ledger.run(step, env)` runs a `Step` (§10). On success it records every path
the step declares it creates, writes or deletes as made from the paths it
declares it reads.

**Content keys.**
- `content_key(p₁ … pₙ)` is the first 16 hex digits of the SHA-256 of the
  files' digests, in order. It is an effect.
- `values_key(**v)` is the same of the values' canonical JSON, with keys
  sorted. It is pure.

A key is bound to an ordinary parameter, so `render` stays pure and `match`
reads the key back. Whether a keyed path still names its inputs is a check
done now: recompute the key and compare.

## 14. Runs (experimental)

This section states the run model of `wend._experimental` as it stands. Nothing in it
is public API, and nothing in it is promised beyond what each statement says. The
journals hold how it was found (`docs/journal/2026-10-22-research-index.md`); this is the
result, stated once.

Each guarantee below is one of three kinds:
- **by construction**: it follows from the mechanism, on Linux, for every other process;
- **under named assumptions**: it holds if they do, and the assumptions are listed;
- **detected, not prevented**: the run notices the violation and refuses or reports it.

The test that pins each statement is named with it.

### 14.1 A run and its steps

A `Run(root)` executes steps confined to `root`. Every path a step names is resolved by
`openat2` beneath the root, with no symlinks and no mount crossings
(`RESOLVE_BENEATH | RESOLVE_NO_SYMLINKS | RESOLVE_NO_XDEV`).

A step is a `Spec` whose ports are expressions (§10), each one of four kinds:
- `Uses`: checked only;
- `Holds`: an input, held open for reading;
- `Makes`: one output, written as a draft and published on exit;
- `Commits`: a version of a store.

`Run.enter(spec, env)` does the following, in order:
1. Renders every port with `env`, and checks every port's `requires` beneath the root.
   A failure refuses the step, and nothing is held, written or learned.
2. Opens every `Holds` input. The open is non-blocking and the object is judged on its
   descriptor, not by the earlier check: it must be a regular file with one name
   (`events_test::test_a_swap_between_the_check_and_the_hold_is_judged_at_the_hold`).
   With `lease=True`, it then takes read leases on all of them together (§14.5).
3. Observes each held input (its identity and a digest of its contents), and refuses an
   input that this run published unless it is still that object with those contents.
4. Gives the body each port: evidence (§10.2), a `Held` input, a `Draft`, or a
   `VersionDraft`. A `Makes` output's missing directories, and a `Commits` port's store
   directory, are made here. They are visible at once, and stay if the step fails.
5. On exit, it forgets what the step's declared mutations may change, and refuses the
   step (`Inconsistent`, nothing published) in either of two cases:
   - a read of a held input returned bytes other than those observed at entry;
   - with `lease=True`, the leases are broken.
6. Publishes each draft (policy `create`, durable) and commits each version, then
   checks every port's `ensures` and records it as `Confirmed` evidence. Each output is
   published whole, one after another, not all together: a failure part-way leaves the
   earlier outputs published. A failed postcondition raises after publication, and the
   outputs stay published. A `Commits` port publishes several members together.

Confinement is **by construction**. A step's paths and its held objects never reach
outside the root, whatever another writer does to names inside it. It is a property of
`Confined`, through which `Run`, its drafts and its store resolve every path. It is
tested on #112's executor, which uses the same `Confined`
(`confined_test::test_a_confined_run_never_reaches_outside_the_root`, the moves
table), and on `Run` under ten scheduled moves
(`synthesis_test::test_the_pipeline_under_interference`).
Confinement is of resolution and of objects. It is not of contents or of time: another
process may change a held object's contents, and names change between steps.

### 14.2 What the run knows

`Run.known(event)` says whether no step of this run has invalidated `event`'s atoms
since it was checked. It is knowledge *under the closed world*: true if no process
outside the run writes below the root. It is not a statement about the filesystem now
(`events_test::test_known_is_blind_to_another_writer`).

Facts are keyed by rendered path. That is sound when distinct strings name distinct
entries, which the aliasing entry's uniqueness lemma gives under its conditions
(aliasing §5). Within `Run` those conditions hold:
- rendering gives strings with no `.` or empty component (§3, §4);
- rendering can give a `..` component (§4), and `Run` refuses a path with one, by
  lexical containment;
- resolution follows no symlink and crosses no mount.

The lemma's remaining assumption belongs to the filesystem: different names in one
directory are different entries. Case folding breaks it. So `known()` is sound, under
the closed world, on case-sensitive filesystems. Hard links need not be excluded: a
mutation through one name changes no atom of another (aliasing §5).

### 14.3 Held inputs and sealed copies

A `Held` input is the object its descriptor refers to, `(device, inode)`, judged on
that descriptor at open: confined, a regular file, one name.
- **Durable while it is held:** which object it is, its kind, its access mode.
- **Not durable:** its contents, size and names.

A `Sealed` copy is a memfd with every write, shrink and grow sealed. It is **by
construction** immutable.

Whether it is a version the input ever had is a separate question.
- **With a lease** it is, **under the assumptions** of §14.5.
- **Without one** it need not be. A concurrent writer can tear it: 244 of 300 reads of
  a 64-page file mixed two versions (synthesis §4.3).
  `leases_test::test_a_leased_copy_is_one_version_and_an_unleased_one_need_not_be`
  repeats it as the control of the leased case.

What the step used is recorded: `Held.used` holds a digest of every `read()`. At exit
the run refuses a step whose reads differ from the entry observation. **Detected.** A
body that reads the descriptor directly is not recorded.

### 14.4 Drafts and publication

A `Draft` is a new object with no name: `O_TMPFILE` in a directory held beneath the
root. `publish(name, policy)` changes the target name in one system call. For
`replace` and `exchange` the draft is first linked under a hidden fresh name
(`.<name>.<random>`), visible in a listing until the call.
- **`create`** (`linkat`) never replaces a name. **By construction**
  (`publish_test::test_create_never_clobbers_where_checking_first_does`).
- **`replace`** links under a fresh name and renames over the target. Readers see the
  old object or the new, whole. **By construction.**
- **`exchange` with `expect`** detects another writer's publication and undoes its own
  swap. It is not a compare-and-swap:
  - a reader can see the withdrawn version;
  - with three or more writers it can lose an update and report the survivor as the
    failure (`synthesis_test::test_exchange_and_validate_over_every_schedule`).

A draft's file is synced, then published, then its directory synced (`durable=True`).
A crash then leaves the new version, in the one crash model tested.
- **The model.** ext4 on a loop device. The image is copied unsynced while it is
  mounted, and its journal is replayed. That is not a power failure: a real device can
  reorder or lose writes it acknowledged.
- **Other syncs.** With only the directory synced, a crash *can* leave the name with 0
  bytes. On ext4, `auto_da_alloc` hides this when the draft replaces a file.
- **What the tests assert** (`durability_test`): the full protocol's outcome strictly;
  every other protocol's outcome as one its syncs permit; and each counterexample as
  possible (seen at least once in five attempts). An absent sync permits loss; it does
  not promise it.

**Under assumptions:** that crash model.

**A draft is nameless, not private.** Every process that passes `ptrace`'s read check
on the writer can reach it through `/proc/<pid>/fd`: the writer's uid while it is
dumpable, and root. Each such process can read it, write into it and name it
(`drafts_test`). Taking its descriptor with `pidfd_getfd` needs `ptrace` attach, which
Yama can narrow. Without Yama, or with `ptrace_scope` 0, the same processes can. With
`ptrace_scope` 1 the writer's uid can only from an ancestor of the writer, and root
still can (measured on CI's kernel; the tests expect what the scope they find
implies). Other unprivileged uids can do none of these.

### 14.5 Leases

`Leases(fds)` takes read leases on open files, all or none.
- A helper process takes them and exits. The leases stay on the descriptions the host
  holds, owned by no living process, so no break signals the host
  (`leases_test::test_no_signal_of_a_break_reaches_the_host`).
- It refuses filesystems not in `LEASABLE` (ext2/3/4, tmpfs), the ones tested. From
  Linux 7.0 the kernel itself refuses leases on a filesystem that does not opt in;
  procfs does not, ext4 and tmpfs do. Before 7.0 the kernel leases `/proc` files,
  whose contents change with no writer
  (`leases_test::test_a_proc_file_is_refused_a_lease_or_changes_under_it`).
- It records each file's size.
- `unbroken()` holds when every lease is still a read lease and every size is unchanged.

**Proposition L, under assumptions** (leases §4). Suppose read leases on read-only
descriptions of files in `LEASABLE` were all granted by `t₀`, and each size was recorded
at `t₁ ≥ t₀`. Suppose that at `t₂ ≥ t₁` every lease still reads as a read lease and every
size is the one recorded: `unbroken()` holds. Then every file's contents were constant
on `[t₁, t₂]`, and the copies are the state of all the files at the one instant `t₁`.
The assumptions:
- **L1, grant:** a read lease is granted only with no writer.
- **L2, break:** an open for writing, and `truncate(2)`, break it.
- **L3, the ways contents change:** contents change only through a writable
  description, by `truncate(2)`, or by an `open` with `O_TRUNC`. An `O_RDONLY` open with
  `O_TRUNC` empties a file without breaking its lease, and the recorded size detects it.
  Each call listed is tested; that the list is complete is a conjecture (leases §4).
- **L4:** nothing changes the storage beneath the filesystem.
- **L5:** the holder takes no lease again in between.

Leases need the files' owner or `CAP_LEASE`. They exclude writers; they do not ask for
their cooperation. A writer is delayed until the leases are given up, or for at most
`lease-break-time`.

### 14.6 Versions

A `Store` holds versions `v000001`, `v000002`, … of a set of outputs.
- **Claiming.** A version is claimed by renaming a filled hidden directory with
  `RENAME_NOREPLACE`. **By construction**, each version name holds one directory, and a
  claim either installs it or fails.
- **What the claim relies on.** That the directory claimed is the writer's, complete and
  unwritten, rests on every process that may rename in the store's directory following
  the store protocol. Those are the writer's uid, root, and other uids with write
  permission on a directory that is not sticky. The writer holds its hidden directory
  by descriptor, and checks its identity before and after the claim. A move, a
  replacement or an early claim by another process is **detected** (`Inconsistent`, no
  `Version` returned), never prevented (`drafts_test`).
- **Privacy while filled.** The hidden directory is private (mode 0700) from other
  users. Its name is listed to anyone who can read the store's directory.
- **Pinned reads.** A `Pinned` reader holds the version's directory with a shared
  `flock`, and checks every member against the manifest. Given the digest the commit
  returned, it never returns bytes the version did not commit. **Under assumptions:**
  SHA-256's collision resistance; and that the reader has the writer's digest, not
  merely the `MANIFEST` on disk.
- **Immutable members.** With `CAP_LINUX_IMMUTABLE`, members are made immutable. On
  ext4 they refuse every write tried
  (`synthesis_test::test_immutable_members_refuse_every_writer_tried`). That includes
  a descriptor opened for writing before the flag, and a shared mapping made before it,
  its page clean or dirty: setting the flag writes the pages back and write-protects
  them, and ext4 refuses the next write fault with `SIGBUS`. A member could still be
  changed between being drafted and being flagged, which the manifest detects. An
  ordinary user cannot set the flag. For them the manifest only detects a change.

### 14.7 What needs privilege

| guarantee | an ordinary user | needs |
|---|---|---|
| confinement of paths and objects | yes | nothing |
| drafts private from other uids | yes | nothing |
| drafts private from the writer's own uid | only by running non-dumpable (process-wide) | nothing more |
| a leased, single-version copy | for files the user owns | `CAP_LEASE` for others' |
| a committed member that cannot change | no; detection only | `CAP_LINUX_IMMUTABLE` |
| the crash model's evidence | no (loop devices, mounts) | root, in tests |

The tests that need privilege are marked `privileged`. CI runs them as root, in a job
where one that skips fails (`tests/conftest.py`).

## 15. Relations between families

`relate(a, b)` says how the paths two expressions render relate, before any binding.
Paths are compared as strings (lexical identity), not as filesystem objects: rendered,
then split into an anchor (`""`, `"/"` or `"//"`) and segments as `PurePosixPath` splits
them. Nothing here looks at a filesystem, so "never the same" means never the same
string, and two strings can still name one file (§15.4). Two paths are:
- **the same**, when anchor and segments are equal;
- one **inside** the other, when they share the anchor and its segments are the
  other's followed by one or more segments (a `..` segment is a segment like any
  other);
- one **containing** the other, the reverse;
- otherwise neither.

### 15.1 The bindings considered

With `shared=True` (the default) a parameter name takes one value on both sides, as
the paths of one run of a pipeline do. The bindings considered are those under which
**both** expressions render (§3.1: an unbound parameter with a default renders its
default). With `shared=False`, every binding of `a` is paired with every binding of
`b`.

### 15.2 The answers

Each of `same`, `inside` (`a` inside `b`) and `contains` (`a` containing `b`) is one
of:

| answer | meaning |
|---|---|
| `"always"` | it holds for every binding considered |
| `"sometimes"` | it holds for at least one, shown by an `Example` whose bindings render both paths |
| `"never"` | it holds for none |
| `"unknown"` | neither was established |

`"always"` is vacuous if no binding renders both; the `Example`, when one is found,
shows that one does. `Relation.kind` summarises: `"same"`, `"inside"` or `"contains"`
when that is always; `"disjoint"` when all three are never; `"overlapping"` when one is
sometimes; `"unknown"` otherwise. A union relates as its alternatives do: never when
every pair is never, sometimes when one pair shows it, and never always.

### 15.3 How each answer is proved

1. **Rendering is a function of structure.** Two pieces of normal form with equal
   structure, comparing parameters by name, render equal text for one binding. A
   parameter's declaration (type, choices, kind) decides which bindings are accepted,
   never what an accepted one renders. Defaults are the exception: a name both sides
   give different defaults renders differently when unbound, and is not compared
   equal. So are a parameter's two roles: alone in a segment it is segment-valued and
   renders `os.fspath` of a `str` or path, `format(v, "")` of anything else; in text it
   renders `format` of its value after its conversion, with its spec. A value of a
   type of its own may render the two apart. With `builtin_values=True` (below) a
   *plain* field, one with no spec and no conversion but `!s`, is compared equal in
   either role: for a value of a builtin type each of these is `str(v)`.
2. **Anchors.** Paths with different anchors are never the same, nor nested. A literal
   head has one anchor (`""` for a relative path, `/`, or `//`). An `Absolute`
   parameter renders `/` or `//`: POSIX keeps a leading `//` as an anchor of its own.
   A name changed by `with_name`, `with_suffix` or `with_stem`, and a parent, keep their
   base's anchor. A path made relative (`relative_to`) has none: pathlib's
   `relative_to` returns a relative path. A join keeps its left side's anchor where the
   right side renders a relative path, and takes the right side's where it renders an
   absolute one. Other heads may render any.
3. **A changed name is its base's parent and one segment.** When the name is unknown
   until binding, `with_name`, `with_suffix` and `with_stem` are deferred (§9). Each
   renders its base's parent, then one segment:
   - `with_name(n)` renders `n` exactly;
   - `with_suffix(s)` renders some text, then `s`;
   - `with_stem(t)` renders `t`, then some text; there is no view where `t` is `.` or
     `..`, since the stem `..`, or `.` before the suffix `.`, renders the name `..`,
     which no segment does (§3).

   The relation reasons on this *view* of the expression. The view renders what the
   expression renders, and more, since its text stands for any text. So the view
   proves `"never"`, nesting by depth (4), and that one operation is the same as itself.
   The text is one parameter on both sides only where the operation renders one text
   on both: its structure is equal, and so is each of its names' default, or its lack
   of one. A name defaulted differently on each side renders each side's own default
   when unbound (1), so its texts are two.
   It shows `"sometimes"` only through a binding of the expressions themselves. Where
   the view leaves an answer unknown, the expressions are asked as they are.
   - An empty stem is no stem: `.csv` has no suffix, so
     `({root}/raw/{day}.csv).with_suffix(".parquet")` renders `r/raw/.csv.parquet`
     where `day` is empty.
   - Its relation to `{root}/raw/{day}.parquet` is therefore `"sometimes"`, not
     `"always"`, as wend's own deferral of the operation implies.
   - Where a changed suffix or stem's base ends in literal text with a dot, the change
     is also written out *by how the base's name splits*. pathlib takes the suffix from
     the name less its leading dots, so the last dot of that text starts the suffix
     unless every character before it is a dot. `with_suffix(".parquet")` of
     `{day}.csv` renders `{day}.parquet`, or `.csv.parquet` where `day` renders dots
     alone (`""` included); `with_stem("summary")` renders `summary.csv`, or `summary`.
     On every binding the change renders what the case that holds renders under the
     same binding, and the cases keep the base's own fields, so `day` is still `day`:
     two changes of one base are `"never"` related where no case of one meets a case
     of the other, and `{day}.parquet` never meets `summary.csv` nor `summary`.
   - A parent deferred because its base ends in a `SubPath` is written out the same way:
     where the `SubPath` renders a segment or more, the parent is the base with a
     `SubPath` of all but the last in its place; where it renders none, the parent of
     what precedes it. `parent({root}/raw/{rel...})` is `{root}/raw/{rest...}` or
     `{root}`, so it is never `{root}/out/x`. The new `SubPath` is one on both sides
     under the same condition as a view's text.
   - A name of `..` has no suffix, so `with_suffix("")` keeps it: `{root}` with the
     suffix `""` renders `a/..` from `root="a/.."`. The overlap analysis (§15.5) allows
     `..` wherever a changed name may render it.
4. **Prefix cancellation.** Under shared bindings, a head and leading parts that are
   equal by (1) render one string `s` wherever both expressions render. That includes a
   deferred head: its operation is pathlib's, applied to what its base renders, so two
   deferred heads of equal structure render one string, unless a parameter inside them
   has a different default on each side. Joining `s` onto a relative remainder is
   injective and keeps "inside", so `a` and `b` relate exactly as their remainders do,
   and every expression is always itself. Under independent bindings only literal heads
   and literal segments cancel.
5. **Structure decides** when:
   - the remainders are both empty: the same, always;
   - one is empty and the other holds a segment: inside or containing, always. A
     `SubPath` may be empty, so alone it decides nothing;
   - at some position both remainders hold segments, every earlier position does too,
     and the two segments there render different text on every run: never, all
     three. Two segments' pieces are compared as characters and fields: equal pieces
     at either end cancel (a field only under shared bindings, by (1)), and the
     segments differ when what remains differs in a character, or one side is empty
     and the other holds one. `{day}.csv` and `{day}.csv.gz` never meet; `{day}.csv`
     and `{other}.csv` may. A field alone in a segment renders a segment-valued
     parameter, which a value of a type of its own may render apart from the same
     value in text, so it does not cancel against one there unless
     `builtin_values=True` and the one in text is plain (1);
   - both are segments alone, which decides by depth. A segment renders exactly one
     segment, never `""`, `.` or a separator (§3), so each remainder renders a fixed
     number of them. Paths of different depths are never the same, and paths of equal
     depths are never one inside the other.
6. **Otherwise the overlap analysis decides** (`wend._overlap`, §15.5): `same` asks
   whether the remainders can render one path; `inside` whether `a`'s can render one
   strictly below `b`'s, built as `b`'s remainder, a segment parameter and a `SubPath`;
   `contains` the reverse. Its NO is `"never"`, except for `inside` and `contains` when
   the inner side may render a `..` segment (a literal one, a head parameter or a
   deferred head), which a segment parameter and a `SubPath` cannot spell: that is
   `"unknown"`. Its YES is `"sometimes"` only once a binding of the whole expressions
   confirms it; its MAYBE is `"unknown"`.

`builtin_values=True` assumes bound values are of builtin types, as the overlap
analysis does, which proves more answers `"never"`. It also compares a plain field
equal in either role (1), so a shard directory `{split}` and its manifest
`{split}.json` never meet. `Relation.assumptions` names it when an answer may rely on
it: whenever the overlap analysis used it, and whenever a name is a plain field in both
roles.

### 15.4 Effects across steps

`wend.effects.EffectGraph(steps)` relates the paths named steps declare (`Step.effects`,
§10.1), shared bindings by default. A port supplies its path if it declares `create`
or `write`, deletes it if it declares `delete`, and is an input if it declares `read`
or `list`. A port that requires `Exists` observes its path's existence. A port that
declares none of these has no known effect. `unassigned` lists the ports that declare
no verbs.

**What it promises, and on what.** The graph's guarantees are about declared effects.
They hold for a run only if every step's declarations describe what its code does to
the filesystem, and only for the paths as strings (below). Two steps in one stage of
`stages()` cannot interfere *through the effects they declare*. That is no promise that
two arbitrary step bodies may run at once: a body that opens, makes or removes a path
it does not declare (an undeclared side effect) is outside the graph.

**A declared path covers what lies below it.** A path may name a directory, unless
nothing says otherwise, so a step that writes it may write anything inside it, one that
reads it may read anything inside it, and one that deletes it deletes everything inside
it. Two ports *touch* when their paths are the same, or one is inside the other (§15,
lexically), and every link asks all three. Its certainty is that of the three taken
together: `"always"` if one holds always, `"never"` if all three are never, `"sometimes"`
if one is shown on some binding, and `"unknown"` otherwise.

| link | between ports of two steps | when |
|---|---|---|
| dependency, `via="read"` or `"list"` | a supplier and a reader or lister | they touch: the reader runs after |
| dependency, `via="exists"` | a supplier and a port that requires `Exists` | they touch: the requirer runs after (see parents, below) |
| hazard | a reader, lister or `Exists` requirer, and a deleter | they touch: the reader runs before |
| conflict, `via="path"` | two suppliers; a supplier and a deleter; two deleters | they touch: never at once |
| conflict, `via="path"` | a port with no known effect, and any other | they touch: never at once |
| conflict, `via="parent"` | two suppliers, one checking `Creatable` or `Writable` | a directory above both may be missing (below): never at once |

Two deletions conflict because a step that deletes a path its neighbour already deleted
may fail. A port with no known effect may write: it is kept apart from every port it
touches, and orders nothing, since nothing says which way.

**Parents a creation may make.** Creating a path whose parent is missing needs the
parent made first. What a step does about that is part of its effect, and the graph
reads it from the declarations as follows:

| what a step does | how it is declared | what the graph does |
|---|---|---|
| requires its parent directory to exist | the parent as a port: `requires(Exists, Dir)` | the step runs after every step that may make the parent: one that creates it (as sure as their paths' relation), or that creates a path below it (`"unknown"`: only if the parent was missing); and before every step that may delete it |
| makes missing parents idempotently (`os.makedirs(..., exist_ok=True)`) | nothing: assumed for every parent a step does not declare | two such creations below one missing directory do not conflict |
| makes a directory exclusively (plain `mkdir`), or requires it absent | the directory as a port: `requires(Absent)`, `ensures(Exists, Dir)` | the directory's port touches every path below it, so every step that touches them is linked to it |
| checks it may create or write a path (`Creatable`, `Writable`) | the check | it conflicts (`"unknown"`, `via="parent"`) with a creation in another step below a directory above both that may be missing: making that directory changes which ancestor the check finds; unless either step requires a path inside that directory to exist (below) |
| has effects it does not declare | cannot be | outside the graph: nothing is promised |

**A step that needs the directory makes nothing there.** Where either of the two steps
requires a path always strictly inside the shared directory to exist (`Exists`, or
`Readable` or `Listable`, which imply it), the parent conflict is dropped. While the
directory is missing, that path is too, so the step's check fails whatever the other
does, and its code, which runs only once its checks pass, makes nothing; once the
directory exists, neither step makes it. Where the other step makes that very path, a
dependency links the two already. The shared directory is the one before the first
position at which the two paths' segments differ on every run (§15.3, 5).

A directory *may be missing* unless it is the anchor (`/`, or the working directory for a
relative path), or lies at or above a path given in `EffectGraph(..., existing=[...])`:
paths that exist before the pipeline runs and that no step deletes. A step that may
delete one of them, or a directory above it, makes the graph raise `ValueError`. Without
`existing`, any directory above a created path may be missing, `{root}` included: every
creation check under `{root}` then conflicts with every other creation there. With
`existing=[P(root)]`, only creations below one directory under the root, which may be
missing, conflict with creation checks below it. The bound is exact where the two paths
part at a literal segment or are siblings, and conservative (a conflict) where their
structure does not say which directory they share.

A pair whose relation is `"never"` has no link, and nothing else is dropped: `"always"`,
`"sometimes"` and `"unknown"` links are all kept, and every query but those given
`certain=True` counts them all, which is the only safe reading for deciding what may run
at once or in which order:
- `order()` puts each step after every step it may depend on, and each deleter after the
  readers of what it deletes. It is None when these links form a cycle.
- `stages()` groups steps no link joins, whatever its certainty.
- `independent(x, y)` holds when no link joins `x` and `y`.
- `cycles()` lists the cycles of the links `order()` follows. `cycles(certain=True)`
  keeps the links that hold on every run: a cycle among them is unavoidable. A cycle
  found only without it is possible, not proved: it rests on a link that holds on some
  runs, or is not ruled out, and may depend on the bindings.
- `dependencies(certain=True)` keeps the `"always"` dependencies: a lower bound, for
  reports, never for scheduling.

`tests/effects_test.py`'s oracle renders every port of generated pipelines under
hundreds of bindings and checks, path against path:
- a step reading or requiring what another writes comes after it, in `order()` and
  `stages()`;
- a step reading what another deletes comes before it;
- two steps whose paths touch, where either changes its path or has no known effect,
  never share a stage;
- nor do two that create paths below a directory other than the anchor, where either
  checks it may create its own.

Identity is lexical: rendered paths are compared as strings, not as filesystem objects,
so two spellings of one file (a symlink, a relative and an absolute path, `..`, case on a
case-insensitive filesystem, a hard link) are two paths here. A missing link is only as
good as the convention that every step spells a file one way.

### 15.5 The overlap analysis

The engine behind §15.3 (6), private as `wend._overlap`: it asks whether two
expressions can render one path, answering YES with a witness both render, NO when no
*shape* of one meets a shape of the other, or MAYBE. A shape over-approximates the
paths an expression renders: an anchor and a sequence of segments drawn from regular
languages, or runs of them, built from the expression's literals, fields, finite
domains, `SubPath`s and heads. Every rule keeps every path the contract lets the
expression render, so disjoint shapes are disjoint paths. Its derivation, measurements
and limits are in `docs/journal/2026-10-20-overlap-research-89.md`.

### 15.6 What a requirement relies on

`EffectGraph.obligations(schedule=None)` says, for every atom a port requires, whether
the pipeline itself establishes it. The atoms are those of §10's conditions: `exists`,
`absent`, `file`, `dir`, `read`, `list`, `create` and `write`. A schedule is an order of
step names, or a list of groups whose steps may run in any order or at once; the default
is `stages()`, and a graph with a cycle needs one given. Each `Obligation` has one of
four statuses:

| status | means | what is promised |
|---|---|---|
| `"discharged"` | an earlier fact (`by`) makes the atom true of the port's path | on every run where every step of an earlier group completed, the atom holds when the step starts |
| `"refuted"` | an earlier fact (`by`) makes the atom false of the path | on every such run, the step's check fails |
| `"at risk"` | a fact that may make it false is known (`by`), or a step (`by`) may have changed a fact that made it true | nothing |
| `"external"` | nothing in the pipeline bears on it | nothing: the world must provide it |

**Facts and how long they last.** A run knows an atom of a path from the moment a check
of it passes: a step's precondition when the step starts, or its postcondition once it
completes. The fact lasts until a declared change that may touch the path: a port of a
step that may run in between, which supplies or deletes a path touching it (§15.4, all
three relations), or declares nothing of its path. Within a group, a step's own
judgement uses only what was known before the group, less anything another step of the
group may change; what a group's steps check or promise is known from the next group on.
`create` and `write` are never kept: whether a path may be created depends on which
directories above it exist and on permissions at that moment, and every creation may
change that (§15.4, parents).

**Which paths a fact is of.** A fact is of the paths the relation proves the same on
every run (`same` is `"always"`, §15.3), and only those. More are derived:
- a passed `read` says the path exists, and a passed `list` that it exists as a
  directory (§10's table: `Readable` needs the path to exist, `Listable` a directory);
- a path known to exist (or to be readable or listable) that is always *inside* another
  makes the other exist, as a directory (`exists`, `dir`);
- a path known absent makes every path always inside it absent.

**Paths given as existing** (`EffectGraph(..., existing=[...])`, §15.4) are facts from
the start that no step forgets: the graph refuses a step that may delete one or a
directory above it, so each exists throughout, and so does every directory above it.
Such a fact names, as `by`, a port of no step (`by.step == ""`). It says a path exists,
not that it is a directory: only the directories above it are.

A fact refutes an atom it excludes: `exists` and `absent`, `absent` and `read` or `list`,
`file` and `list`, and `file` and `dir` of a path known to exist (both hold of a missing
path, §10).

**Identity is not freshness.** Two spellings the relation proves the same name one string
on every run, so a check of one is a check of the other, at the moment it ran. Whether it
still holds is a separate question, answered by what may run in between: the fact is kept
only while no step that may run in between declares a change that may touch either. The
answers rest on three assumptions, `wend.effects.ASSUMPTIONS`:
- **closed world**: nothing outside the steps changes their paths while they run;
- **declared effects**: each step's declarations describe what its code does;
- **lexical identity**: two spellings of one file, which the relation sees as two paths
  (§15.4), do not occur.

`tests/effects_test.py` checks the promise against the disk: random pipelines over
families whose bindings collide (`tests/families_test.py`'s generator), each run in a
real directory under four bindings, in order and by stages (a group's steps in both
orders). Wherever every earlier group completed, every discharged atom holds when its
step starts, and every step with a refuted atom fails.
