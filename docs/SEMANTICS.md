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
- matching raises rather than choosing between readings (§7).

`glob`'s symlink policy is a traversal policy documented on `glob`, outside this
contract. This version adds connectivity (§9) and conditions (§10). Later versions are expected to
extend the contract for union expressions and Windows path flavours.

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
  not expect). A format call that raises makes the binding invalid.

Text containing NUL is invalid.

| kind | requirement | contributes |
|---|---|---|
| PATH | none | `PurePosixPath(s)` |
| ABSOLUTE | `PurePosixPath(s)` is absolute | `PurePosixPath(s)` |
| SEGMENT | no `/`; `s` not in `{"", ".", ".."}` | the single segment `s` |
| SUBPATH | `PurePosixPath(s)` is relative and has no `..` part | `PurePosixPath(s)` |

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
  - the field's text is `format(convert(v, c), s)`, and a `format` call that
    raises makes the binding invalid;
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
applying §2–§5. It either yields a path (or string), or fails with an invalid
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
   unbound parameters raise `MissingBindingError`.

## 7. Matching

`match_all(e, path)` returns bindings `b` with `e.render(b) == str(PurePosixPath(path))`:

- **Soundness:** every returned binding renders to the path.
- **Completeness:** every binding that renders to the path appears in the
  result (up to `limit`). Field values are parsed as the parameter's declared
  `type`, or the type the format spec implies (`d` → `int`, `f` → `float`,
  otherwise `str`).
- `match` returns the single binding, `None` if there is none, and raises
  `AmbiguousMatchError` if there are several.

## 8. What is guaranteed by construction, and what is only tested

| property | status |
|---|---|
| a `match`/`glob` result renders to its path (matching soundness) | **by construction**: every candidate is checked by rendering before it is returned |
| a compiled function raises the same errors as the interpreter | **by construction**: any exception in the fast path re-runs the interpreter |
| the matching fast path returns at most one binding | **argued** (below) and tested |
| obligations 1–3 above (agreement, no spurious rejection, strictness) | **tested** (Hypothesis, independent reference evaluator). Random terms cover every term of §1, every parameter kind, nested format specs, text fields, and values whose `__format__` breaks their format type |
| below a literal base, no binding of an `AUTO`, `Segment` or `SubPath` parameter leads outside it, whatever operations the term applies | **tested** (Hypothesis, random terms) |
| `rebase(old, new)` equals building the expression afresh with `new` in place of `old` (§9) | **tested** (Hypothesis, random terms and substitutions) |
| a join equals its `base` joined with its `base_rel` | **tested** |
| a path rendered with `Under(b)` declared is contained in `b`, and every contained rendering is returned unchanged (§10) | **by construction** (each render checks the rendered strings) and **tested** (Hypothesis, random terms and bases, interpreted and compiled) |
| matching completeness | **tested** (Hypothesis round trips; exhaustive enumeration over small domains) |
| compiled successes equal interpreted successes | **tested** |
| Polars results equal `render` | **tested**, on the supported subset |
| every observed path matches an inferred layout | **by construction** (inference verifies each path and raises otherwise) and tested |

**Fast-path uniqueness argument.** A fast-path segment is a sequence of
literal strings and fields in which:

- every integer field is followed by a literal whose first character is not a
  digit (or by the end of the segment);
- at most one string field appears, and only after the last other field.

The regex is built from fixed literals, integer fields `-?[0-9]+`, and the
final string field `.*`. It is matched against the whole segment. Reading left
to right:

- a literal must match at a fixed position;
- an integer field is a maximal digit run: it cannot stop earlier, because the
  next character must begin the following literal, which is not a digit; and
  it cannot extend further;
- the final string field ends where the trailing literal must begin, at a
  fixed distance from the end.

So each field's span is forced, and at most one parse exists. Values come from
the spans by `int()` or identity, so at most one binding exists per segment.
With no `SubPath` and a fixed head extent, the expression has at most one
candidate overall.

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
| `Creatable` | `p` exists, or its nearest existing ancestor is a directory with `access(·, W_OK \| X_OK)` | capability error |

Checks describe the filesystem at the moment they run. They are not atomic
with any later use of the path, and `access` reports the real user's
permissions. Like `glob`'s symlink policy, they catch mistakes and state
intent; they are not a sandbox.
