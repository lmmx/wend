# wend.frame

Vectorised resolution with Polars (optional dependency: `pip install wend[polars]`).

`resolve_frame` renders an expression for every row of a DataFrame whose columns are named after the expression's parameters, after validating every row with the same rules as `PathExpr.render`. `to_polars` returns the raw `pl.Expr` (no validation) for embedding in larger queries.

A lowering exists only where Polars reproduces `render` exactly: for every row, `resolve_frame` either returns what `render` returns or raises because `render` raises (null values are always rejected). Everything else raises NotImplementedError; use `expr.compile().many(rows)` for those expressions.

### What is lowered

Path operands (String columns): Path and absolute heads and `SubPath` splices, canonicalised exactly as `str(PurePosixPath(s))`: `a/`, `./a`, `a//b` and `/a/./b` are normalised, exactly two leading slashes are kept, three or more become one, and an empty or dot-only relative path is `.`. Segment parameters from String, integer (`str(v)`) and Boolean (`True`/`False`) columns.

**Formatted fields with a static format spec**

- Strings (String columns, `!s` conversions, nested text, and the `name`/`stem`/`suffix` of a path): `[[fill]align][0][width]   [.precision][s]` with alignment `<`, `>` or `^`.
- Integers (Int8 to Int64, UInt8 to UInt64; Int128 and UInt128 in decimal): types `d`, `b`, `o`, `x`, `X` or none, with any fill, all four alignments, sign (`+`, `-`, space), `#`, `0`, width, and `,` or `_` grouping (zero padding included); `!s`/`!r`/`!a` (all give the decimal digits) followed by a string spec.
- Booleans: an empty spec (`True`/`False`), a non-empty integer spec (Python formats a bool with a spec as 1 or 0), or a conversion followed by a string spec.

**Deferred operations on unbound paths**

`parent`, `with_name`, `with_stem`, `with_suffix`, a join with a path parameter, and the `name`/`stem`/`suffix` of such paths.

Refused (NotImplementedError): Float and other column types, and non-String columns at path positions; `n`, `c` and float presentation types on integers, and bases other than ten on 128-bit integers; `!r`/`!a` on strings; specs that Python rejects for the column's type (a precision on an integer, a sign on a string...); format specs that contain a parameter; `relative_to` on unbound paths; a declared `type=` that the column's values are not instances of; and `choices=` not all of the column's value type.

## to\_polars

```python
to_polars(expr: PathExpr, schema: Schema | None = None) -> Expr
```

Lower `expr` to a Polars expression named `path` (without validation).

Rows that `render` accepts get exactly its result; other rows get unspecified values. Pass the frame's schema so integer and Boolean columns are formatted by their type rather than guessed from the expression.

## resolve\_frame

```python
resolve_frame(expr: PathExpr, df: DataFrame | LazyFrame) -> Series
```

Validate every row of `df` and render `expr` for each, as a String Series.

A parameter with no column takes its default on every row, as `render` does for a missing binding (docs/SEMANTICS.md §3.1); a str, int or path default can be lowered. Declared `Under` conditions are checked on every row, as `render` checks them (§10).
