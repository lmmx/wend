"""Format-spec analysis: static facts about formatted fields, and inversion.

A t-string interpolation keeps its conversion and format spec. Two things are
derived from them here:

- *facts*: whether every value accepted for the field formats without a ``.``
  and to a non-empty string. Name operations (suffix, stem) use these facts to
  stay static; resolution enforces them, so a fact can never be wrong for an
  accepted value.
- *inversion*: candidate values whose formatting reproduces a given text. Only
  candidates that round-trip exactly through ``format`` are returned.
"""

from __future__ import annotations

import ast
import re
import sys
from dataclasses import dataclass, field
from functools import lru_cache
from types import NoneType, UnionType
from typing import Any


_SPEC_RE = re.compile(
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

INT_TYPES = frozenset("bdoxX")
FLOAT_TYPES = frozenset("eEfFgG%")
_INT_CHARS = frozenset("0123456789+- _,#xXoObBabcdefABCDEF")
# Presentation types under which an int writes characters outside _INT_CHARS:
# c any character, n the locale's separators, a float type a point or "%".
_UNPRUNED_TYPES = FLOAT_TYPES | {"c", "n"}


@dataclass(frozen=True, slots=True)
class Spec:
    fill: str | None
    align: str | None
    sign: str | None
    z: bool  # the "z" flag: a negative zero formats as zero
    alt: bool  # the "#" flag
    zero: bool  # the "0" flag before the width
    width: int | None
    grouping: str | None
    precision: int | None
    type: str | None
    # The types an untyped field with this spec reads (§7), set once here:
    # parse_spec is cached, and matching asks for every field it reads.
    reads: tuple[type, ...] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "reads", _implied(self))

    @property
    def fill_char(self) -> str:
        return self.fill if self.fill is not None else " "

    def padding(self, numeric: bool) -> tuple[str, str]:
        """The fill character and alignment ``format`` pads a value with.

        CPython's rules: the ``0`` flag without an explicit fill pads with
        ``0``, and without an explicit alignment it also makes a number's
        padding sign-aware (``=``). Otherwise strings align left and numbers
        right.
        """
        if self.fill is None and self.zero:
            return "0", self.align or ("=" if numeric else "<")
        return self.fill_char, self.align or (">" if numeric else "<")

    @property
    def str_formats(self) -> bool:
        """Whether a ``str`` formats under this spec.

        CPython refuses a sign, ``z``, ``#``, grouping and ``=`` alignment for
        strings, and every presentation type but ``s``.
        """
        return self.type in (None, "s") and not (
            self.sign or self.z or self.alt or self.grouping or self.align == "="
        )


@lru_cache(maxsize=1024)
def parse_spec(spec: str) -> Spec | None:
    """Parse a standard format spec, or return None if it is not one."""
    m = _SPEC_RE.match(spec)
    if m is None:
        return None
    width, precision = m["width"], m["precision"]
    return Spec(
        m["fill"],
        m["align"],
        m["sign"],
        m["z"] is not None,
        m["alt"] is not None,
        m["zero"] is not None,
        int(width) if width else None,
        m["grouping"],
        int(precision) if precision else None,
        m["type"],
    )


# The type each presentation type implies for an untyped field.
_TYPE_READS: dict[str, tuple[type, ...]] = {
    **dict.fromkeys("bcdnoxX", (int,)),
    **dict.fromkeys(FLOAT_TYPES, (float,)),
    "s": (str,),
}


def implied_types(info: Spec | None) -> tuple[type, ...]:
    """The types an untyped field with this spec reads (§7); see `_implied`."""
    return (str,) if info is None else info.reads  # nothing formats if None


def _implied(info: Spec) -> tuple[type, ...]:
    """The types an untyped field with this spec reads (§7).

    A presentation type implies one. Without one, the field reads the first of
    ``str``, ``int`` and ``float`` that formats under the spec: ``str`` unless
    the spec has an option only numbers take (a sign, ``z``, ``#``, grouping
    or ``=``), else ``int`` unless it has one ints refuse (``z`` or a
    precision), else ``float``. The one exception is a spec that zero-pads
    like a number (the ``0`` flag before a width, with no alignment or
    precision: ``05``), which reads ``int`` as well as ``str`` (issue #45).
    """
    if info.type is not None:
        return _TYPE_READS[info.type]
    if info.str_formats:
        if (
            info.zero
            and info.width is not None
            and not info.align
            and info.precision is None
        ):
            return (str, int)
        return (str,)
    if info.precision is None and not info.z:
        return (int,)
    return (float,)


def facts(spec: str, conversion: str | None, declared: Any) -> tuple[bool, bool]:
    """Return (dot_free, non_empty) guarantees for a field.

    Only integer formatting is trusted: ``n`` (locale separators) and ``c``
    (any character) are excluded, and a ``.`` fill character voids dot-freedom.
    """
    if conversion is not None:
        return False, False
    info = parse_spec(spec)
    if info is None:
        return False, False
    int_like = info.type in INT_TYPES or (info.type is None and declared is int)
    if not int_like:
        return False, False
    return info.fill_char != ".", True


_PLAIN_INT_SPEC = re.compile(r"(?:0[0-9]+)?([bdoxX]?)")
# Presentation type -> (the digits it writes, the base that reads them back).
INT_DIGITS = {
    "b": ("01", 2),
    "o": ("01234567", 8),
    "d": ("0123456789", 10),
    "x": ("0123456789abcdef", 16),
    "X": ("0123456789ABCDEF", 16),
}


def plain_int(spec: str, declared: Any) -> tuple[str, int] | None:
    """(digits, base) when every int formats under ``spec`` as ``-?[digits]+``.

    Covers the presentation types ``b``, ``d``, ``o``, ``x`` and ``X`` with an
    optional zero-padded width (``05x``), and an empty or width-only spec for a
    parameter declared ``int``. Anything else (signs, grouping, ``#``, fills,
    space padding) returns None. ``declared`` must be None or ``int``.
    """
    m = _PLAIN_INT_SPEC.fullmatch(spec)
    if m is None:
        return None
    t = m[1]
    if not t:
        if declared is not int:
            return None  # an untyped "" or "05" spec reads str values too (§7)
        t = "d"
    return INT_DIGITS[t]


def allowed_chars(
    spec: str, conversion: str | None, declared: Any
) -> frozenset[str] | None:
    """Characters a formatted field may contain, used to prune matching (None = any)."""
    if conversion is not None:
        return None
    info = parse_spec(spec)
    if info is None or info.type in _UNPRUNED_TYPES:
        return None
    if declared is not int and (declared is not None or info.reads != (int,)):
        return None  # only an int field is pruned
    return _INT_CHARS | {info.fill_char}


def convert(value: Any, conversion: str | None) -> Any:
    if conversion is None:
        return value
    if conversion == "r":
        return repr(value)
    if conversion == "s":
        return str(value)
    if conversion == "a":
        return ascii(value)
    raise ValueError(f"Unknown conversion {conversion!r}")


_PREFIXES = frozenset(("0b", "0B", "0o", "0O", "0x", "0X"))
_BASES = {"b": 2, "o": 8, "x": 16, "X": 16}
# (fill, alignment) pairs whose readings `int` already folds into one: it
# skips zeros after the sign and base prefix, and spaces before the sign.
_INT_SAFE_PADDING = frozenset((("0", "="), (" ", ">")))


def unpad(text: str, info: Spec | None, numeric: bool) -> list[str]:
    """Every text that ``format`` could have padded to ``text`` under ``info``.

    ``format`` pads a text shorter than the width up to exactly the width, so
    only a text of the width's length can be padded. Its readings are then each
    number of fill characters taken off the padded side (both sides for ``^``,
    split as ``format`` splits them), from none up to the whole run: the value
    may itself begin or end with the fill character. ``=`` pads after a
    number's sign and base prefix. ``numeric`` selects the defaults that
    ``format`` uses for numbers rather than strings.
    """
    if info is None or not info.width or len(text) != info.width:
        return [text]
    fill, align = info.padding(numeric)
    n = len(text)
    if align == "<":
        run = n - len(text.rstrip(fill))
        return [text[: n - k] for k in range(run + 1)]
    if align == ">":
        run = n - len(text.lstrip(fill))
        return [text[k:] for k in range(run + 1)]
    if align == "^":
        lead = n - len(text.lstrip(fill))
        trail = n - len(text.rstrip(fill))
        out = []
        for p in range(n + 1):  # p fill characters: p // 2 before, the rest after
            left, right = p // 2, p - p // 2
            if left > lead or right > trail:
                break
            out.append(text[left : n - right])
        return out
    # "=": the fill sits after the sign and base prefix. The fill may itself
    # be a sign character, so the padding may start after any such head.
    heads = [0, 1] if text[0] in "-+ " else [0]
    heads += [h + 2 for h in heads if text[h : h + 2] in _PREFIXES]
    out = [text]
    for h in heads:
        run = n - h - len(text[h:].lstrip(fill))
        out += [text[:h] + text[h + k :] for k in range(1, run + 1)]
    return out


def _int_candidates(text: str, info: Spec | None) -> list[Any]:
    if info is None:
        cores = [text]
    elif info.type == "c":
        return [ord(c) for c in unpad(text, info, True) if len(c) == 1]
    elif info.padding(True) in _INT_SAFE_PADDING:
        cores = [text]  # every reading of this padding is the same integer
    else:
        cores = unpad(text, info, True)
    base = _BASES.get(info.type or "d", 10) if info is not None else 10
    out: list[Any] = []
    for core in cores:
        try:
            out.append(int(core.replace(",", "").replace("_", ""), base))
        except ValueError:
            pass
    return out


def _float_candidates(text: str, info: Spec | None) -> list[Any]:
    percent = info is not None and info.type == "%"
    out: list[Any] = []
    for core in unpad(text, info, True):
        s = core.replace(",", "").replace("_", "")
        if percent:
            if not s.endswith("%"):
                continue
            s = s[:-1]
        try:
            out.append(float(s) / 100 if percent else float(s))
        except ValueError:
            pass
    return out


# Reading untrusted text never raises: text that is not a value of a type
# gives no candidate, however the parser rejects it. literal_eval raises
# SyntaxError, ValueError, TypeError (an unhashable key, as in "{[1]: 2}"),
# MemoryError or RecursionError (deep nesting); a declared type's constructor
# raises whatever it raises (Decimal: decimal.InvalidOperation).


def _literal(text: str) -> list[Any]:
    """The value of the Python literal ``text`` (as ``!r`` and ``!a`` write it)."""
    try:
        return [ast.literal_eval(text)]
    except Exception:
        return []


def _construct(tt: Any, texts: list[str]) -> list[Any]:
    """Values of the declared type ``tt`` whose ``str`` may be one of ``texts``.

    That is ``tt(t)`` for each text ``t`` that ``tt`` accepts, but for
    ``bool`` (``bool(t)`` is true for any ``t`` but ``""``) the texts
    ``True`` and ``False``.
    """
    if tt is bool:
        return [b for t in texts for b in (False, True) if t == str(b)]
    if tt is NoneType:
        return [None for t in texts if t == "None"]
    out: list[Any] = []
    for t in texts:
        try:
            out.append(tt(t))
        except Exception:
            pass
    return out


def _distinct(values: list[Any]) -> list[Any]:
    """``values`` without repeats, where values of different types differ."""
    if len(values) < 2:
        return values
    out: list[Any] = []
    seen: set[tuple[type, Any]] = set()
    for v in values:
        try:
            key = (type(v), v)
            if key in seen:
                continue
            seen.add(key)
        except TypeError:  # unhashable: a literal's list, or a signalling NaN
            if any(_same(v, o) for o in out):
                continue
        out.append(v)
    return out


def _same(a: Any, b: Any) -> bool:
    """Whether ``a`` and ``b`` are the same candidate: equal and of one type,
    or, for values that refuse comparison (a signalling NaN), of one repr."""
    if type(a) is not type(b):
        return False
    try:
        return bool(a == b)
    except Exception:
        return repr(a) == repr(b)


def _members(declared: Any) -> tuple[Any, ...]:
    """The types a declared ``type=`` admits, in order: the type itself, or
    each member of a tuple or union, as ``isinstance`` reads them."""
    if isinstance(declared, tuple):
        return tuple(t for d in declared for t in _members(d))
    if isinstance(declared, UnionType):
        return _members(declared.__args__)
    return (declared,)


def _read(text: str, spec: str, info: Spec | None, tt: Any) -> list[Any]:
    """Candidates of type ``tt`` that may format (with no conversion) to ``text``."""
    # An int (and a bool, which is one) formats under a float presentation
    # type as the float it converts to.
    floats = info is not None and info.type in FLOAT_TYPES
    if tt is int:
        if floats:
            return [int(x) for x in _float_candidates(text, info) if x.is_integer()]
        return _int_candidates(text, info)
    if tt is str:
        return unpad(text, info, False)
    if tt is float:
        return _float_candidates(text, info)
    if tt is bool:
        # A bool formats as True or False under the empty spec, and as the
        # number 1 or 0 under any other.
        if not spec:
            return _construct(bool, [text])
        nums = _float_candidates(text, info) if floats else _int_candidates(text, info)
        return [x == 1 for x in nums if x == 0 or x == 1]
    # Another declared type: its own __format__ may pad either way.
    texts = unpad(text, info, False) + unpad(text, info, True)
    return _construct(tt, list(dict.fromkeys(texts)))


# Presentation types under which a float (or Decimal) writes at least
# ``precision`` digits, as a float's alternate form of g and G does, keeping
# trailing zeros.
_PRECISION_DIGITS = frozenset("fFeE%")


def _decimal(t: Any) -> bool:
    decimal = sys.modules.get("decimal")  # imported if Decimal is declared
    return decimal is not None and t is decimal.Decimal


def _standard(declared: Any) -> bool:
    """Whether values of ``declared`` format by the standard mini-language
    (None: the str, int and float an untyped field reads). None itself
    formats under no spec but the empty one, so it never breaks a bound."""
    if declared is None:
        return True
    return all(
        t in (str, int, float, bool, NoneType) or _decimal(t)
        for t in _members(declared)
    )


def _too_short(
    text: str, info: Spec | None, conversion: str | None, declared: Any
) -> bool:
    """Whether ``text`` is shorter than anything the spec formats.

    Under the standard mini-language a result is never shorter than its
    width, nor, under ``fFeE%`` or a float's alternate form of ``g``, than
    its precision, except that inf and nan ignore precision. A spec read from the
    path itself (``{w:d}_{u:{w}}``) can ask for a billion characters, which
    formatting a candidate would allocate: such text has no reading.
    """
    if info is None or not (conversion is not None or _standard(declared)):
        return False
    n = len(text)
    if info.width is not None and info.width > n:
        return True
    return (
        conversion is None
        and info.precision is not None
        and info.precision > n
        and (
            info.type in _PRECISION_DIGITS
            or (
                info.alt
                and info.type in (None, "g", "G")
                and not any(
                    map(_decimal, _members(declared))
                )  # Decimal's drops the zeros
            )
        )
        and not ("inf" in text.lower() or "nan" in text.lower())
    )


def invert(text: str, spec: str, conversion: str | None, declared: Any) -> list[Any]:
    """Values v such that ``format(convert(v, conversion), spec) == text``.

    Candidates are read from every unpadded form of ``text`` (`unpad`), parsed
    as the field's type (§7), and kept only if they format back to ``text``.
    """
    info = parse_spec(spec)
    if _too_short(text, info, conversion, declared):
        return []
    cands: list[Any]
    if conversion is not None:
        cores = unpad(text, info, False)  # a conversion formats a str
        if conversion != "s":
            cands = [v for c in cores for v in _literal(c)]
        elif declared is None:
            cands = cores
        else:  # the declared types' values whose str is the text
            cands = [
                v
                for tt in _members(declared)
                for v in (cores if tt is str else _construct(tt, cores))
            ]
    else:
        # A declared type, or each member of a declared tuple or union, in
        # order; untyped, the types the spec implies (str, then int, for
        # zero padding).
        types = implied_types(info) if declared is None else _members(declared)
        cands = [v for tt in types for v in _read(text, spec, info, tt)]
    out: list[Any] = []
    for v in _distinct(cands):
        try:
            ok = format(convert(v, conversion), spec) == text
        except Exception:  # a candidate that cannot format is no reading
            ok = False
        if ok:
            out.append(v)
    return out
