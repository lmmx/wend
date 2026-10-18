"""Vectorised resolution with Polars (optional dependency: ``pip install wend[polars]``).

`resolve_frame` renders an expression for every row of a DataFrame whose
columns are named after the expression's parameters, after validating every
row with the same rules as `PathExpr.render`. `to_polars` returns the raw
``pl.Expr`` (no validation) for embedding in larger queries.

A lowering exists only where Polars reproduces `render` exactly: for every row,
`resolve_frame` either returns what `render` returns or raises because
`render` raises (null values are always rejected). Everything else raises
NotImplementedError; use ``expr.compile().many(rows)`` for those expressions.

What is lowered
---------------
Path operands (String columns):
    Path and absolute heads and `SubPath` splices, canonicalised exactly as
    ``str(PurePosixPath(s))``: ``a/``, ``./a``, ``a//b`` and ``/a/./b`` are
    normalised, exactly two leading slashes are kept, three or more become one,
    and an empty or dot-only relative path is ``.``. Segment parameters from
    String, integer (``str(v)``) and Boolean (``True``/``False``) columns.

Formatted fields with a static format spec:
    - Strings (String columns, ``!s`` conversions, nested text, and the
      ``name``/``stem``/``suffix`` of a path): ``[[fill]align][0][width]
      [.precision][s]`` with alignment ``<``, ``>`` or ``^``.
    - Integers (Int8 to Int64, UInt8 to UInt64; Int128 and UInt128 in decimal):
      types ``d``, ``b``, ``o``, ``x``, ``X`` or none, with any fill, all four
      alignments, sign (``+``, ``-``, space), ``#``, ``0``, width, and ``,`` or
      ``_`` grouping (zero padding included); ``!s``/``!r``/``!a`` (all give
      the decimal digits) followed by a string spec.
    - Booleans: an empty spec (``True``/``False``), a non-empty integer spec
      (Python formats a bool with a spec as 1 or 0), or a conversion followed
      by a string spec.

Deferred operations on unbound paths:
    ``parent``, ``with_name``, ``with_stem``, ``with_suffix``, a join with a
    path parameter, and the ``name``/``stem``/``suffix`` of such paths.

Refused (NotImplementedError):
    Float and other column types, and non-String columns at path positions;
    ``n``, ``c`` and float presentation types on integers, and bases other
    than ten on 128-bit integers; ``!r``/``!a`` on strings; specs that Python
    rejects for the column's type (a precision on an integer, a sign on a
    string...); format specs that contain a parameter; ``relative_to`` on
    unbound paths; a declared ``type=`` that the column's values are not
    instances of; and ``choices=`` not all of the column's value type.
"""

from __future__ import annotations

import os
import re
from functools import cache
from typing import Any


try:
    import polars as pl
except ImportError as e:  # pragma: no cover - exercised without polars installed
    raise ImportError("wend.frame needs Polars: pip install 'wend[polars]'") from e

from . import _expr as X
from ._params import Kind, Param
from .errors import InvalidBindingError, PathOperationError


def _refuse(what: str) -> NotImplementedError:
    return NotImplementedError(
        f"{what} cannot be lowered to Polars exactly; use expr.compile().many(rows)"
    )


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

# A separator followed by a run of empty and "." components: "//", "/./", "/.//./".
_EMPTY_RUN = r"/(?:\.?/)+"


def _maybe_noncanonical(c: pl.Expr) -> pl.Expr:
    """True for every string that ``str(PurePosixPath(s))`` changes.

    A string with none of these features is ".", "/", or a root of "" or "/"
    followed by components that are neither empty nor ".", so it is canonical.
    (A "//x" root is flagged without being changed; that only costs time.)
    """
    return (
        c.str.contains("//", literal=True)
        | c.str.contains("/./", literal=True)
        | c.str.starts_with("./")
        | c.str.ends_with("/.")
        | (c.str.ends_with("/") & (c != "/"))
        | (c == "")
    )


def _canonical(c: pl.Expr) -> pl.Expr:
    """``str(PurePosixPath(s))`` for every string ``s``.

    pathlib splits off a root ("//" for exactly two leading slashes, "/" for
    one or for three or more, "" otherwise) and keeps the components of the
    rest that are neither "" nor ".". Collapsing each separator together with
    the run of such components after it into one separator leaves no "//" and
    no "/./". The only differences from the canonical form left are then a
    leading "./", a trailing "/." or "/", and a "//" root collapsed to "/",
    each at most once; the remaining steps remove exactly those.
    """
    t = (
        c.str.replace_all(_EMPTY_RUN, "/")
        .str.strip_prefix("./")
        .str.strip_suffix("/.")
        .str.strip_suffix("/")
    )
    t = (
        pl.when(t != "")
        .then(t)
        .when(c.str.starts_with("/"))
        .then(pl.lit("/"))
        .otherwise(pl.lit("."))
    )
    two = c.str.starts_with("//") & ~c.str.starts_with("///")
    return pl.when(two).then(pl.concat_str([pl.lit("/"), t])).otherwise(t)


def _combine(base: pl.Expr, tail: pl.Expr) -> pl.Expr:
    """`_expr._combine` for a canonical base and the joined segments."""
    return (
        pl.when(tail == "")
        .then(base)
        .when(base == ".")
        .then(tail)
        .when(base.str.ends_with("/"))
        .then(pl.concat_str([base, tail]))
        .otherwise(pl.concat_str([base, pl.lit("/"), tail]))
    )


# The pathlib operations below take canonical path strings, whose components
# are never "" or "." and whose only trailing "/" is a root ("/" or "//").


def _dirname(b: pl.Expr) -> pl.Expr:
    """The path up to and including the separator before its name."""
    return b.str.replace(r"[^/]*$", "")


def _name(b: pl.Expr) -> pl.Expr:
    return pl.when(b == ".").then(pl.lit("")).otherwise(b.str.extract(r"([^/]*)$", 1))


# PurePath.suffix: the last "." and what follows, if a character other than
# "." comes before it. PurePath.stem is the rest of the name.
_SUFFIX = r"(?s)^\.*[^.].*(\.[^.]*)$"
_STEM = r"(?s)^(\.*[^.].*)\.[^.]*$"


def _suffix(name: pl.Expr) -> pl.Expr:
    return name.str.extract(_SUFFIX, 1).fill_null("")


def _stem(name: pl.Expr) -> pl.Expr:
    return pl.coalesce(name.str.extract(_STEM, 1), name)


def _parent(b: pl.Expr) -> pl.Expr:
    d = _dirname(b)
    return (
        pl.when(d == "")
        .then(pl.lit("."))
        .when(d.is_in(["/", "//"]))
        .then(d)
        .otherwise(d.str.strip_suffix("/"))
    )


def _join(b: pl.Expr, r: pl.Expr) -> pl.Expr:
    """``str(PurePosixPath(b) / r)`` for canonical ``b`` and ``r``."""
    return (
        pl.when(r.str.starts_with("/"))
        .then(r)
        .when(r == ".")
        .then(b)
        .otherwise(_combine(b, r))
    )


# ---------------------------------------------------------------------------
# Formatting (CPython's format-spec mini-language for str, int and bool)
# ---------------------------------------------------------------------------

_SPEC = re.compile(
    r"""
    (?:(?P<fill>.)?(?P<align>[<>=^]))?
    (?P<sign>[-+ ])?
    (?P<z>z)?
    (?P<alt>\#)?
    (?P<zero>0)?
    (?P<width>[0-9]+)?
    (?P<grouping>[,_])?
    (?:\.(?P<precision>[0-9]+)(?P<fgrouping>[,_])?)?
    (?P<type>[bcdeEfFgGnosxX%])?
    \Z
    """,
    re.VERBOSE | re.DOTALL,
)
_MAX_WIDTH = 1 << 16
_INT_BASES = {None: 10, "d": 10, "b": 2, "o": 8, "x": 16, "X": 16}
_INT_DTYPES: dict[Any, tuple[int, bool]] = {
    pl.Int8: (8, True),
    pl.Int16: (16, True),
    pl.Int32: (32, True),
    pl.Int64: (64, True),
    pl.UInt8: (8, False),
    pl.UInt16: (16, False),
    pl.UInt32: (32, False),
    pl.UInt64: (64, False),
}


class _Unsupported(Exception):
    pass


def _parse(spec: str) -> dict[str, str | None]:
    m = _SPEC.match(spec)
    if m is None:
        raise _Unsupported("not a standard format spec")
    d = m.groupdict()
    if d["width"] is not None and int(d["width"]) > _MAX_WIDTH:
        raise _Unsupported("width too large")
    return d


def _fill_align(d: dict[str, str | None], default: str) -> tuple[str, str]:
    """The fill character and alignment, resolved as CPython resolves them."""
    fill, align = d["fill"], d["align"]
    if d["zero"] and fill is None:
        # "0" before the width means fill "0" (and, for numbers, sign-aware
        # padding unless an alignment is given). After an explicit fill it is
        # just part of the width.
        fill = "0"
        if align is None and default == ">":
            align = "="
    return (" " if fill is None else fill), (align or default)


def _pad(s: pl.Expr, align: str, width: int, fill: str) -> pl.Expr:
    if not width:
        return s
    if align == "<":
        return s.str.pad_end(width, fill)
    if align == ">":
        return s.str.pad_start(width, fill)
    # "^": CPython puts the smaller half of the padding on the left.
    n = s.str.len_chars().cast(pl.Int64)
    left = n + (pl.lit(width, pl.Int64) - n).clip(lower_bound=0) // 2
    return s.str.pad_start(left, fill).str.pad_end(width, fill)


def _format_str(s: pl.Expr, spec: str) -> pl.Expr:
    """``format(s, spec)`` for str values."""
    if spec in ("", "s"):
        return s
    d = _parse(spec)
    if d["type"] not in (None, "s"):
        raise _Unsupported(f"type {d['type']!r} on a string")
    for key in ("sign", "z", "alt", "grouping", "fgrouping"):
        if d[key]:
            raise _Unsupported(f"{d[key]!r} on a string")  # Python raises
    fill, align = _fill_align(d, "<")
    if align == "=":
        raise _Unsupported("'=' alignment on a string")  # Python raises
    if d["precision"] is not None:
        s = s.str.head(int(d["precision"]))
    return _pad(s, align, int(d["width"] or 0), fill)


def _bool_text(c: pl.Expr) -> pl.Expr:
    return pl.when(c).then(pl.lit("True")).when(c.not_()).then(pl.lit("False"))


@cache
def _digit_table(base: int, upper: bool) -> tuple[int, pl.Series]:
    """Group size in bits, and the zero-padded digits of every group value."""
    bits, ndigits = {2: (16, 16), 8: (15, 5), 16: (16, 4)}[base]
    code = {2: "b", 8: "o", 16: "X" if upper else "x"}[base]
    return bits, pl.Series(
        [format(i, f"0{ndigits}{code}") for i in range(1 << bits)], dtype=pl.String
    )


def _radix(c: pl.Expr, dtype: Any, base: int, upper: bool) -> pl.Expr:
    """The digits of ``abs(c)`` in base 2, 8 or 16 (no sign, no prefix)."""
    width = _INT_DTYPES.get(dtype)
    if width is None:
        raise _Unsupported(f"base {base} digits of a {dtype} column")
    nbits, signed = width
    if signed:
        ci = c.cast(pl.Int64)
        neg = ci < 0
        # |v| = (-1 - v) + 1 for negative v, which never overflows.
        m = pl.when(neg).then(pl.lit(-1, pl.Int64) - ci).otherwise(ci).cast(
            pl.UInt64
        ) + neg.cast(pl.UInt64)
    else:
        m = c.cast(pl.UInt64)
    gbits, table = _digit_table(base, upper)
    lookup = pl.lit(table)
    groups = [
        lookup.gather(
            (m // pl.lit(1 << (gbits * k), pl.UInt64)) % pl.lit(1 << gbits, pl.UInt64)
        )
        for k in reversed(range(-(-nbits // gbits)))
    ]
    s = (
        groups[0] if len(groups) == 1 else pl.concat_str(groups)
    ).str.strip_chars_start("0")
    return pl.when(s == "").then(pl.lit("0")).otherwise(s)


def _group(digits: pl.Expr, size: int, sep: str) -> pl.Expr:
    """Insert ``sep`` between groups of ``size`` digits, from the right."""
    return (
        digits.str.reverse()
        .str.replace_all(f"(.{{{size}}})", "${1}" + sep)
        .str.strip_suffix(sep)
        .str.reverse()
    )


def _format_int(c: pl.Expr, dtype: Any, spec: str) -> pl.Expr:
    """``format(v, spec)`` for int values (CPython's format_long_internal)."""
    if spec in ("", "d"):
        return c.cast(pl.String)
    d = _parse(spec)
    t = d["type"]
    if t not in _INT_BASES:
        raise _Unsupported(f"type {t!r} on an integer")
    if d["z"] or d["precision"] is not None:
        raise _Unsupported("'z' or a precision on an integer")  # Python raises
    base = _INT_BASES[t]
    sep = d["grouping"]
    if sep == "," and base != 10:
        raise _Unsupported(f"',' with {t!r}")  # Python raises
    fill, align = _fill_align(d, ">")
    width = int(d["width"] or 0)
    plus = d["sign"] if d["sign"] in ("+", " ") else ""
    prefix = ""
    if d["alt"] and base != 10:
        prefix = {2: "0b", 8: "0o", 16: "0X" if t == "X" else "0x"}[base]
    if base == 10 and not plus and not sep:
        s = c.cast(pl.String)  # the decimal digits with their minus sign
        if align != "=":
            return _pad(s, align, width, fill)
        if fill == "0":
            return s.str.zfill(width) if width else s
    signed = dtype is None or _INT_DTYPES.get(dtype, (0, True))[1]
    neg = (c < 0) if signed else pl.lit(False)
    sign = pl.when(neg).then(pl.lit("-")).otherwise(pl.lit(plus))
    if base == 10:
        digits = c.cast(pl.String).str.strip_prefix("-")
    else:
        digits = _radix(c, pl.Int64 if dtype is None else dtype, base, t == "X")
    size = 3 if base == 10 else 4
    lead = pl.when(neg).then(pl.lit(1, pl.Int64)).otherwise(pl.lit(len(plus), pl.Int64))
    room = pl.lit(width - len(prefix), pl.Int64) - lead  # width left for the digits
    if sep and fill == "0" and align == "=":
        # CPython zero-pads inside the grouping: the fewest digits whose grouped
        # form is at least `room` wide, never starting with a separator.
        r = room.clip(lower_bound=1) - 1
        q, k = r // (size + 1), r % (size + 1)
        need = pl.when(k < size).then(q * size + k + 1).otherwise((q + 1) * size + 1)
        digits = _group(digits.str.pad_start(need, "0"), size, sep)
        return pl.concat_str([sign, pl.lit(prefix), digits])
    if sep:
        digits = _group(digits, size, sep)
    if align == "=":
        if width:
            digits = digits.str.pad_start(room.clip(lower_bound=0), fill)
        return pl.concat_str([sign, pl.lit(prefix), digits])
    return _pad(pl.concat_str([sign, pl.lit(prefix), digits]), align, width, fill)


def _accepts(declared: Any, kind: type) -> bool:
    """Whether every value of Python type ``kind`` passes ``isinstance(v, declared)``."""
    if declared is None:
        return True
    try:
        return issubclass(kind, declared)
    except TypeError:
        return False


# ---------------------------------------------------------------------------
# Lowering
# ---------------------------------------------------------------------------


class _Lowering:
    """Builds the output expression and the per-row checks that mirror render.

    Values used more than once (a path that an operation inspects several
    times, say) are bound with `let` instead of being repeated, which keeps the
    plan linear in the size of the expression. A binding is a frame column when
    ``staged`` (resolve_frame adds them with ``with_columns``) and otherwise a
    struct field (`to_polars` evaluates them inside ``struct.with_fields``).

    ``flags`` collects, per path column, a test that is true for every
    non-canonical value. When the flagged columns are known, ``canonical``
    names the columns that hold only canonical values: those are used as they
    are and the others are normalised. When it is None, each value is
    normalised if it is flagged.
    """

    def __init__(
        self,
        schema: pl.Schema | None,
        canonical: frozenset[str] | None = None,
        *,
        staged: bool = False,
    ) -> None:
        self.schema = schema
        self.canonical = canonical
        self.staged = staged
        self.checks: list[tuple[str, pl.Expr, type[Exception]]] = []
        self.flags: dict[str, pl.Expr] = {}
        self.lets: list[tuple[str, pl.Expr]] = []
        names = set() if schema is None else set(schema.names())
        prefix = "_wend_"
        while any(n.startswith(prefix) for n in names):
            prefix = "_" + prefix
        self.prefix = prefix

    def dtype(self, name: str) -> Any:
        return None if self.schema is None else self.schema.get(name)

    def check(
        self, what: str, bad: pl.Expr, exc: type[Exception] = InvalidBindingError
    ) -> None:
        self.checks.append((what, bad, exc))

    def let(self, e: pl.Expr) -> pl.Expr:
        if e.meta.is_column() or e.meta.is_literal():
            return e
        name = f"{self.prefix}{len(self.lets)}"
        self.lets.append((name, e))
        return pl.col(name) if self.staged else pl.field(name)

    def stage(self, lazy: pl.LazyFrame) -> pl.LazyFrame:
        for name, e in self.lets:
            lazy = lazy.with_columns(e.alias(name))
        return lazy

    def evaluate(self, out: pl.Expr, column: str) -> pl.Expr:
        """``out`` as one expression, its bindings evaluated in a struct.

        The struct starts from ``column`` so that it has the frame's length.
        """
        if not self.lets:
            return out
        s = pl.struct(pl.col(column).alias(self.prefix))
        for name, e in self.lets:
            s = s.struct.with_fields(e.alias(name))
        return s.struct.with_fields(out.alias(self.prefix)).struct.field(self.prefix)

    # -- columns -------------------------------------------------------------

    def kind(self, p: Param, spec_type: str | None = None) -> type:
        """The Python type of the column's values (str, int or bool)."""
        dt = self.dtype(p.name)
        if dt is None:  # no schema: the declared type or the spec decides
            if p.type is bool:
                return bool
            if p.type is int or (spec_type is not None and spec_type in "bdoxX"):
                return int
            return str
        if dt == pl.String:
            return str
        if dt == pl.Boolean:
            return bool
        if dt.is_integer():
            return int
        raise _refuse(f"Column {p.name!r} of type {dt}")

    def column(self, p: Param, kind: type) -> pl.Expr:
        """The column, checked like ``Param.check`` (nulls are always rejected)."""
        if not _accepts(p.type, kind):
            raise _refuse(
                f"{p.name!r} is declared {p.type!r} but its column holds {kind.__name__}"
            )
        c = pl.col(p.name)
        self.check(f"{p.name} is null", c.is_null())
        if p.choices is not None:
            if not all(type(v) is kind for v in p.choices):
                raise _refuse(f"Choices of {p.name!r} that are not all {kind.__name__}")
            self.check(f"{p.name} not in choices", ~c.is_in(list(p.choices)))
        return c

    def path(self, p: Param) -> pl.Expr:
        """A path operand's text (``_expr._fspath_str``), not yet canonical."""
        dt = self.dtype(p.name)
        if dt is not None and dt != pl.String:
            raise _refuse(f"Column {p.name!r} of type {dt} at a path position")
        c = self.column(p, str)
        self.check(f"{p.name} contains NUL", c.str.contains("\x00", literal=True))
        return c

    def canon(self, p: Param, c: pl.Expr) -> pl.Expr:
        if self.canonical is not None:
            return c if p.name in self.canonical else self.let(_canonical(c))
        flag = _maybe_noncanonical(c)
        self.flags[p.name] = flag
        return self.let(pl.when(flag).then(_canonical(c)).otherwise(c))

    def segment(self, p: Param) -> pl.Expr:
        """A segment parameter (``_expr.seg_value``)."""
        kind = self.kind(p)
        c = self.column(p, kind)
        if kind is int:
            return c.cast(pl.String)
        if kind is bool:
            return _bool_text(c)
        self.check(f"{p.name} contains NUL", c.str.contains("\x00", literal=True))
        self.check(f"{p.name} contains a separator", c.str.contains("/", literal=True))
        self.check(f"{p.name} is not a segment", c.is_in(["", ".", ".."]))
        return c

    # -- fields and text -----------------------------------------------------

    def field(self, f: X.Field) -> pl.Expr:
        src = f.source
        if f.role == "segment" and isinstance(src, Param):
            return self.segment(src)
        spec = f.static_spec
        if spec is None:
            raise _refuse(f"{f.pattern} (its format spec contains a parameter)")
        dtype = None
        if isinstance(src, Param):
            m = _SPEC.match(spec)
            kind = self.kind(src, m["type"] if m else None)
            value = self.column(src, kind)
            dtype = self.dtype(src.name)
        elif isinstance(src, X.Text):
            kind, value = str, self.let(self.text(src))
        elif isinstance(src, X.TextOp):
            kind, value = str, self.textop(src)
        else:
            raise _refuse(f.pattern)
        try:
            out = _format(value, kind, dtype, f.conversion, spec)
        except _Unsupported as e:
            raise _refuse(f"{f.pattern} ({e})") from None
        if kind is str or "/" in spec or "\x00" in spec:
            # Digits, signs, prefixes and separators never contain these; only
            # text and fill characters can (_expr.format_field).
            out = self.let(out)
            self.check(
                f"{f.pattern} formats to a separator",
                out.str.contains("/", literal=True),
            )
            self.check(
                f"{f.pattern} formats to NUL", out.str.contains("\x00", literal=True)
            )
        # The dot-free and non-empty guarantees of Field.facts hold for integer
        # formatting without a "." fill, so format_field's checks never fire.
        return out

    def text(self, t: X.Text) -> pl.Expr:
        terms = [pl.lit(p) if isinstance(p, str) else self.field(p) for p in t.pieces]
        if not terms:
            return pl.lit("")
        return terms[0] if len(terms) == 1 else pl.concat_str(terms)

    def textop(self, t: X.TextOp) -> pl.Expr:
        name = self.let(_name(self.let(self.expr(t.base))))
        if t.op == "name":
            return name
        if t.op == "stem":
            return _stem(name)
        if t.op == "suffix":
            return _suffix(name)
        raise _refuse(f"{t.op}({t.base.pattern})")  # pragma: no cover

    # -- paths ---------------------------------------------------------------

    def seg(self, s: X.Seg) -> pl.Expr:
        if s.literal is not None:
            return pl.lit(s.literal)
        out = self.text(X.Text(s.pieces))
        if s.needs_check:
            out = self.let(out)
            self.check(
                f"segment {X._pieces_pattern(s.pieces)} is empty or dots",
                out.is_in(["", ".", ".."]),
            )
        return out

    def splice(self, p: Param) -> pl.Expr:
        raw = self.path(p)
        # Checked on the raw text: canonicalisation keeps the root and every
        # component other than "" and ".", so these answers do not change.
        self.check(f"{p.name} must be relative", raw.str.starts_with("/"))
        self.check(f"{p.name} contains '..'", raw.str.contains(r"(^|/)\.\.(/|$)"))
        c = self.canon(p, raw)
        return pl.when(c == ".").then(None).otherwise(c)  # "." is zero segments

    def head(self, h: X.HeadParam) -> pl.Expr:
        p = h.param
        raw = self.path(p)
        if p.kind is Kind.ABSOLUTE:
            self.check(f"{p.name} must be absolute", ~raw.str.starts_with("/"))
        return self.canon(p, raw)

    def deferred(self, h: X.Deferred) -> pl.Expr:
        """``_expr._render_deferred``: a pathlib operation on a canonical path."""
        pattern = X.PathExpr(h).pattern
        if not X.PathExpr(h).param_names:
            return pl.lit(X._render_deferred(h, {}))
        if h.op == "relative_to":
            raise _refuse(f"{pattern!r} (relative_to of an unbound path)")
        b = self.let(self.expr(h.base))
        if h.op == "join":
            return _join(b, self.let(self.expr(h.arg)))
        if h.op == "parent":
            return _parent(b)
        name = self.let(_name(b))
        if h.op == "with_suffix":
            self.check(f"{pattern}: empty name", name == "", PathOperationError)
            return pl.concat_str([_dirname(b), _stem(name), pl.lit(h.arg)])
        new = self.let(self.text(h.arg))
        if h.op == "with_name":
            bad = (new == "") | (new == ".") | new.str.contains("/", literal=True)
            self.check(f"{pattern}: invalid name", bad, PathOperationError)
            self.check(f"{pattern}: empty name", name == "", PathOperationError)
            return pl.concat_str([_dirname(b), new])
        if h.op == "with_stem":
            suffix = self.let(_suffix(name))
            bad = (
                (name == "")
                | (new == "")
                | ((suffix == "") & (new == "."))
                | new.str.contains("/", literal=True)
            )
            self.check(f"{pattern}: invalid stem", bad, PathOperationError)
            return pl.concat_str([_dirname(b), new, suffix])
        raise _refuse(pattern)  # pragma: no cover

    def expr(self, e: X.PathExpr) -> pl.Expr:
        """The canonical rendering of ``e`` (``_expr._render_expr``)."""
        h = e.head
        segs = [
            self.seg(p) if isinstance(p, X.Seg) else self.splice(p.param)
            for p in e.parts
        ]
        tail = None
        if segs:
            tail = self.let(pl.concat_str(segs, separator="/", ignore_nulls=True))
        if isinstance(h, X._Rel) or isinstance(h, X.Root):
            anchor = "" if isinstance(h, X._Rel) else h.anchor  # type: ignore[union-attr]
            if tail is None:
                return pl.lit(anchor or ".")
            out = pl.concat_str([pl.lit(anchor), tail]) if anchor else tail
            return pl.when(tail == "").then(pl.lit(anchor or ".")).otherwise(out)
        base = self.head(h) if isinstance(h, X.HeadParam) else self.deferred(h)
        return base if tail is None else _combine(self.let(base), tail)


def _format(
    value: pl.Expr, kind: type, dtype: Any, conv: str | None, spec: str
) -> pl.Expr:
    """``format(convert(v, conv), spec)`` for a column of str, int or bool values."""
    if conv is not None:
        if kind is str:
            if conv != "s":
                raise _Unsupported(f"!{conv} on a string")
        elif kind is int:
            value = value.cast(pl.String)  # str, repr and ascii of an int agree
        else:
            value = _bool_text(value)
        return _format_str(value, spec)
    if kind is str:
        return _format_str(value, spec)
    if kind is bool:
        if spec == "":
            return _bool_text(value)
        # bool inherits int.__format__, which formats str(v) only for "".
        return _format_int(value.cast(pl.UInt8), pl.UInt8, spec)
    return _format_int(value, dtype, spec)


def to_polars(expr: X.PathExpr, schema: pl.Schema | None = None) -> pl.Expr:
    """Lower ``expr`` to a Polars expression named ``path`` (without validation).

    Rows that `render` accepts get exactly its result; other rows get
    unspecified values. Pass the frame's schema so integer and Boolean columns
    are formatted by their type rather than guessed from the expression.
    """
    if expr.is_static:
        return pl.lit(expr.render()).alias("path")
    low = _Lowering(schema)
    out = low.expr(expr)
    return low.evaluate(out, min(expr.param_names)).alias("path")


def resolve_frame(expr: X.PathExpr, df: pl.DataFrame | pl.LazyFrame) -> pl.Series:
    """Validate every row of ``df`` and render ``expr`` for each, as a String Series.

    A parameter with no column takes its default on every row, as `render`
    does for a missing binding (docs/SEMANTICS.md §3.1); a str, int or path
    default can be lowered. Declared ``Under`` conditions are checked on every
    row, as `render` checks them (§10).
    """
    out = _resolve_frame(expr, df)
    conds = expr.conditions
    if conds is not None:
        from .conditions import Under, contained
        from .errors import ContainmentError

        for base in conds.bases:
            if base.param_names:
                bs: Any = _resolve_frame(base, df)
            else:
                bs = [base.render()] * len(out)
            for i, (s, b) in enumerate(zip(out, bs, strict=True)):
                if not contained(s, b):
                    raise ContainmentError(
                        s, Under(base), f"is not under {b!r} (row {i})"
                    )
    return out


def _with_defaults(
    expr: X.PathExpr, lazy: pl.LazyFrame, missing: frozenset[str]
) -> pl.LazyFrame:
    """``lazy`` with a constant column for each missing parameter's default
    (§3.1). A null in a column is a value, not a missing binding."""
    params = expr.params
    unbound = {n for n in missing if not params[n].has_default}
    if unbound:
        raise X.MissingBindingError(unbound)
    cols = []
    for n in sorted(missing):
        d = params[n].default
        if isinstance(d, os.PathLike):
            d = os.fspath(d)
        if type(d) not in (str, int):
            raise NotImplementedError(
                f"The default of {n!r} ({d!r}) cannot be lowered to Polars;"
                " add a column for it"
            )
        cols.append(pl.lit(d, dtype=pl.String if type(d) is str else pl.Int64).alias(n))
    return lazy.with_columns(cols)


def _resolve_frame(expr: X.PathExpr, df: pl.DataFrame | pl.LazyFrame) -> pl.Series:
    lazy = df.lazy()
    schema = lazy.collect_schema()
    missing = expr.param_names - set(schema.names())
    if missing:
        lazy = _with_defaults(expr, lazy, missing)
        schema = lazy.collect_schema()
    if expr.is_static:
        out = pl.lit(expr.render()).alias("path")
        return lazy.with_columns(out).select("path").collect().to_series()
    # Read the input once, so that validation, the choice to skip normalisation
    # and the output all see the same rows.
    lazy = lazy.select(sorted(expr.param_names)).collect().lazy()
    low = _Lowering(schema, staged=True)
    low.expr(expr)
    canonical: frozenset[str] = frozenset()
    if low.checks or low.flags:
        staged = low.stage(lazy)
        flags = list(low.flags.items())
        found = (
            staged.select(
                [
                    bad.fill_null(False).any().alias(f"c{i}")
                    for i, (_, bad, _) in enumerate(low.checks)
                ]
                + [
                    flag.fill_null(False).any().alias(f"f{i}")
                    for i, (_, flag) in enumerate(flags)
                ]
            )
            .collect()
            .row(0)
        )
        for i, (what, bad, exc) in enumerate(low.checks):
            if found[i]:
                # The first failing row (a parallel arg_max may report a later one).
                first = bad.fill_null(False).arg_true().first()
                row = staged.select(first).collect().item()
                raise exc(f"Row {row}: {what}")
        # Columns whose values are all canonical skip normalisation.
        hits = found[len(low.checks) :]
        canonical = frozenset(name for (name, _), hit in zip(flags, hits) if not hit)
    low = _Lowering(schema, canonical, staged=True)
    out = low.expr(expr).alias("path")
    return low.stage(lazy).select(out).collect().to_series()
