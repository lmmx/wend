"""Vectorised resolution with Polars (optional dependency: ``pip install wend[polars]``).

`resolve_frame` renders an expression for every row of a DataFrame whose
columns are named after the expression's parameters, after validating every
row with the same rules as `PathExpr.render`. `to_polars` returns the raw
``pl.Expr`` (no validation) for embedding in larger queries.

Only formatting that Polars reproduces exactly is lowered: string columns,
integer columns with ``d``/``0Nd``/``Nd`` specs, and string padding with
``<N``/``>N``. Anything else raises NotImplementedError; use
``expr.compile().many(rows)`` for those expressions.
"""

from __future__ import annotations

from typing import Any


try:
    import polars as pl
except ImportError as e:  # pragma: no cover - exercised without polars installed
    raise ImportError("wend.frame needs Polars: pip install 'wend[polars]'") from e

from . import _expr as X
from ._params import Kind, Param
from ._spec import parse_spec
from .errors import InvalidBindingError


_CANON = r"^(//?)?[^/]*(/[^/]+)*$"
_DOT_PART = r"(^|/)\.(/|$)"


class _Lowering:
    def __init__(self, schema: pl.Schema | None) -> None:
        self.schema = schema
        self.checks: list[tuple[str, pl.Expr]] = []

    def dtype(self, name: str) -> Any:
        return None if self.schema is None else self.schema.get(name)

    def check(self, what: str, bad: pl.Expr) -> None:
        self.checks.append((what, bad))

    def string_col(self, p: Param) -> pl.Expr:
        c = pl.col(p.name)
        self.check(f"{p.name} is null", c.is_null())
        self.check(f"{p.name} contains NUL", c.str.contains("\x00", literal=True))
        if p.choices is not None:
            self.check(f"{p.name} not in choices", ~c.is_in(list(p.choices)))
        dt = self.dtype(p.name)
        if dt is not None and dt != pl.String:
            raise NotImplementedError(
                f"Column {p.name!r} must be String for a path position, got {dt}"
            )
        return c

    def field(self, f: X.Field) -> pl.Expr:
        src = f.source
        if (
            not isinstance(src, Param)
            or f.static_spec is None
            or f.conversion is not None
        ):
            raise NotImplementedError(f"{f.pattern} cannot be lowered to Polars")
        if f.role == "segment":
            dt = self.dtype(src.name)
            if dt is not None and dt.is_integer():
                # A segment formats a non-path value like f"{v}"; for an
                # integer that is its decimal string, which can't be a
                # separator, empty, "." or "..".
                if src.type not in (None, int):
                    raise NotImplementedError(
                        f"{src.name!r} is declared {src.type!r} but the column is integer"
                    )
                c = pl.col(src.name)
                self.check(f"{src.name} is null", c.is_null())
                if src.choices is not None:
                    self.check(
                        f"{src.name} not in choices", ~c.is_in(list(src.choices))
                    )
                return c.cast(pl.String)
            c = self.string_col(src)
            self.check(
                f"{src.name} contains a separator", c.str.contains("/", literal=True)
            )
            self.check(f"{src.name} is not a segment", c.is_in(["", ".", ".."]))
            self.check(f"{src.name} contains NUL", c.str.contains("\x00", literal=True))
            return c
        c = pl.col(src.name)
        self.check(f"{src.name} is null", c.is_null())
        if src.choices is not None:
            self.check(f"{src.name} not in choices", ~c.is_in(list(src.choices)))
        dt = self.dtype(src.name)
        spec = f.static_spec
        info = parse_spec(spec)
        if info is None:
            raise NotImplementedError(
                f"Format spec {spec!r} cannot be lowered to Polars"
            )
        if dt is None and (info.type == "d" or src.type is int):
            dt = pl.Int64  # no schema: an integer spec or declared type decides
        if dt is not None and dt.is_integer():
            if src.type not in (None, int):
                raise NotImplementedError(
                    f"{src.name!r} is declared {src.type!r} but the column is integer"
                )
            s = c.cast(pl.String)
            if spec in ("", "d"):
                return s
            if (
                info.type in (None, "d")
                and info.width is not None
                and spec == f"0{info.width}{info.type or ''}"
            ):
                return s.str.zfill(info.width)
            if (
                info.type in (None, "d")
                and info.width is not None
                and spec
                in (
                    f"{info.width}{info.type or ''}",
                    f">{info.width}{info.type or ''}",
                )
            ):
                return s.str.pad_start(info.width, " ")
            raise NotImplementedError(
                f"Integer format spec {spec!r} cannot be lowered to Polars"
            )
        if dt is None or dt == pl.String:
            if src.type not in (None, str):
                raise NotImplementedError(
                    f"{src.name!r} is declared {src.type!r} but the column is String"
                )
            if spec in ("", "s"):
                out = c
            elif (
                info.type in (None, "s")
                and info.width is not None
                and info.align in ("<", ">")
            ):
                fill = info.fill_char
                if (
                    spec
                    != f"{info.fill or ''}{info.align}{info.width}{info.type or ''}"
                ):
                    raise NotImplementedError(
                        f"String format spec {spec!r} cannot be lowered to Polars"
                    )
                out = (
                    c.str.pad_end(info.width, fill)
                    if info.align == "<"
                    else c.str.pad_start(info.width, fill)
                )
            else:
                raise NotImplementedError(
                    f"String format spec {spec!r} cannot be lowered to Polars"
                )
            self.check(
                f"{f.pattern} formats to a separator",
                out.str.contains("/", literal=True),
            )
            self.check(
                f"{f.pattern} formats to NUL", out.str.contains("\x00", literal=True)
            )
            return out
        raise NotImplementedError(
            f"Column {src.name!r} of type {dt} cannot be formatted in Polars"
        )

    def seg(self, s: X.Seg) -> pl.Expr:
        if s.literal is not None:
            return pl.lit(s.literal)
        terms = [pl.lit(p) if isinstance(p, str) else self.field(p) for p in s.pieces]
        out = terms[0] if len(terms) == 1 else pl.concat_str(terms)
        if s.needs_check:
            self.check(
                f"segment {X._pieces_pattern(s.pieces)} is empty or dots",
                out.is_in(["", ".", ".."]),
            )
        return out

    def splice(self, p: Param) -> pl.Expr:
        c = self.string_col(p)
        self.check(
            f"{p.name} is not canonical",
            (~c.str.contains(_CANON) | c.str.contains(_DOT_PART)) & (c != "."),
        )
        self.check(
            f"{p.name} is not canonical",
            (c.str.ends_with("/") & (c != "/")) | (c == ""),
        )
        self.check(f"{p.name} must be relative", c.str.starts_with("/"))
        self.check(f"{p.name} contains '..'", c.str.contains(r"(^|/)\.\.(/|$)"))
        return pl.when(c == ".").then(None).otherwise(c)

    def expr(self, e: X.PathExpr) -> pl.Expr:
        h = e.head
        segs = [
            self.seg(p) if isinstance(p, X.Seg) else self.splice(p.param)
            for p in e.parts
        ]
        tail = pl.concat_str(segs, separator="/", ignore_nulls=True) if segs else None
        if isinstance(h, X._Rel) or isinstance(h, X.Root):
            anchor = "" if isinstance(h, X._Rel) else h.anchor  # type: ignore[union-attr]
            if tail is None:
                return pl.lit(anchor or ".")
            out = pl.concat_str([pl.lit(anchor), tail]) if anchor else tail
            return (
                pl.when(out == pl.lit(anchor))
                .then(pl.lit(anchor or "."))
                .otherwise(out)
            )
        if isinstance(h, X.Deferred):
            if X.PathExpr(h).param_names:
                raise NotImplementedError(
                    f"{e.pattern!r} has a deferred {h.op!r}; bind it first"
                )
            return self.expr(
                X._literal_expr(X._render_deferred(h, {})) / X.PathExpr(X.REL, e.parts)
            )
        p = h.param
        head = self.string_col(p)
        self.check(
            f"{p.name} is not canonical",
            (~head.str.contains(_CANON) | head.str.contains(_DOT_PART)) & (head != "."),
        )
        self.check(
            f"{p.name} is not canonical",
            (head.str.ends_with("/") & ~head.is_in(["/", "//"]))
            | (head == "")
            | head.str.starts_with("///"),
        )
        if p.kind is Kind.ABSOLUTE:
            self.check(f"{p.name} must be absolute", ~head.str.starts_with("/"))
        if tail is None:
            return head
        return (
            pl.when(tail == "")
            .then(head)
            .when(head == ".")
            .then(tail)
            .when(head.str.ends_with("/"))
            .then(pl.concat_str([head, tail]))
            .otherwise(pl.concat_str([head, pl.lit("/"), tail]))
        )


def to_polars(expr: X.PathExpr, schema: pl.Schema | None = None) -> pl.Expr:
    """Lower ``expr`` to a Polars expression (without validation)."""
    return _Lowering(schema).expr(expr)


def resolve_frame(expr: X.PathExpr, df: pl.DataFrame | pl.LazyFrame) -> pl.Series:
    """Validate every row of ``df`` and render ``expr`` for each, as a String Series."""
    lazy = df.lazy()
    schema = lazy.collect_schema()
    missing = expr.param_names - set(schema.names())
    if missing:
        raise X.MissingBindingError(set(missing))
    low = _Lowering(schema)
    out = low.expr(expr)
    if low.checks:
        flags = lazy.select(
            [
                bad.fill_null(False).arg_max().alias(f"i{i}")
                for i, (_, bad) in enumerate(low.checks)
            ]
            + [
                bad.fill_null(False).any().alias(f"a{i}")
                for i, (_, bad) in enumerate(low.checks)
            ]
        ).collect()
        for i, (what, _) in enumerate(low.checks):
            if flags[f"a{i}"][0]:
                raise InvalidBindingError(f"Row {flags[f'i{i}'][0]}: {what}")
    return lazy.select(out.alias("path")).collect().to_series()
