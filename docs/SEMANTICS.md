# wend semantic contract

This document fixes what a wend expression *means*, independently of how
`src/wend` computes it. The audit tests (`tests/contract_test.py`) evaluate
expressions with a separate reference evaluator written from this document
alone (`tests/reference.py`). That evaluator does not use wend's normal form,
simplifications, matcher or compiler.

Paths are POSIX paths with `pathlib.PurePosixPath` semantics throughout.

## 1. Terms

An expression is built from these terms:

| term | built by |
|---|---|
| literal path `s` | `P("a/b")`, `x / "a/b"` |
| parameter operand `p` | `P(p)`, `x / p`, `p / x` |
| template `t` | `T(t"...")`, `x / t"..."` |
| join `a / b` | `/`, `joinpath` |
| `parent(a)`, `with_suffix(a, s)`, `with_name(a, n)`, `with_stem(a, s)`, `relative_to(a, b)` | the methods of the same names |
| `name(a)`, `stem(a)`, `suffix(a)` | properties; these yield strings, not paths |

## 2. Position of a parameter operand

A parameter declared `Kind.AUTO` takes its kind from its position:

- **head**: nothing precedes it in the joined expression except empty
  relative paths (`"."`, `""`). It acts as `Kind.PATH`.
- **elsewhere**: it acts as `Kind.SEGMENT`.

Joining `a / b` where `a` is an empty relative path leaves the head position of
`b` unchanged; any other `a` puts `b`'s first operand in a non-head position.
A parameter declared with an explicit kind keeps it wherever it appears.

## 3. Values of parameter operands

Let `v` be the bound value. It must be a `str` or an `os.PathLike` returning
`str`, without NUL. Otherwise the binding is **invalid**. Declared `type` and
`choices` are checked against `v` as given.

| kind | requirement | contributes |
|---|---|---|
| PATH | none | `PurePosixPath(v)` |
| ABSOLUTE | `PurePosixPath(v)` is absolute | `PurePosixPath(v)` |
| SEGMENT | no `/`; `v` not in `{"", ".", ".."}` | the single segment `v` |
| SUBPATH | `PurePosixPath(v)` is relative and has no `..` part | `PurePosixPath(v)` |

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
- **anything else**: a *formatted segment*. Each interpolation becomes
  `format(convert(v, conversion), spec)`, where `v` is the bound value of a
  `Param`, or the interpolated constant; `type` and `choices` are checked
  first, and a `format` call that raises makes the binding invalid. Each formatted field must contain neither `/` nor NUL, and the
  concatenated segment must not be `""`, `"."` or `".."`. Otherwise the binding
  is invalid.

The template's value is its anchor joined with its segments in order, using
pathlib join semantics.

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
| obligations 1–3 above (agreement, no spurious rejection, strictness) | **tested** (Hypothesis, independent reference evaluator) |
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
