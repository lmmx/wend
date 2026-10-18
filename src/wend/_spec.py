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
from dataclasses import dataclass
from functools import lru_cache
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


@dataclass(frozen=True, slots=True)
class Spec:
    fill: str | None
    align: str | None
    width: int | None
    type: str | None

    @property
    def fill_char(self) -> str:
        return self.fill if self.fill is not None else " "


@lru_cache(maxsize=1024)
def parse_spec(spec: str) -> Spec | None:
    """Parse a standard format spec, or return None if it is not one."""
    m = _SPEC_RE.match(spec)
    if m is None:
        return None
    width = m["width"]
    return Spec(m["fill"], m["align"], int(width) if width else None, m["type"])


def target_type(spec: str, conversion: str | None, declared: Any) -> Any:
    """The Python type a matched field value is parsed into."""
    if conversion is not None:
        return None  # conversions are inverted via the conversion itself
    if declared is not None:
        return declared
    info = parse_spec(spec)
    if info is not None and info.type is not None:
        if info.type in INT_TYPES or info.type == "c":
            return int
        if info.type in FLOAT_TYPES:
            return float
    return str


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
            return None  # an untyped "" or "05" spec formats (and parses) a str
        t = "d"
    return INT_DIGITS[t]


def allowed_chars(
    spec: str, conversion: str | None, declared: Any
) -> frozenset[str] | None:
    """Characters a formatted field may contain, used to prune matching (None = any)."""
    if target_type(spec, conversion, declared) is not int:
        return None
    info = parse_spec(spec)
    if info is None:
        return None
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


def _int_candidates(text: str, info: Spec | None) -> list[Any]:
    s = text
    if info is not None and info.fill is not None and not info.fill.isdigit():
        s = s.replace(info.fill, "")
    s = s.replace(" ", "").replace(",", "").replace("_", "")
    base = 10
    t = info.type if info is not None else None
    if t == "c":
        return [ord(text)] if len(text) == 1 else []
    if t == "b":
        base = 2
    elif t == "o":
        base = 8
    elif t in ("x", "X"):
        base = 16
    try:
        return [int(s, base)]
    except ValueError:
        return []


def _float_candidates(text: str, info: Spec | None) -> list[Any]:
    s = text
    if info is not None and info.fill is not None and not info.fill.isdigit():
        s = s.replace(info.fill, "")
    s = s.replace(" ", "").replace(",", "").replace("_", "")
    scale = 1.0
    if info is not None and info.type == "%":
        if not s.endswith("%"):
            return []
        s, scale = s[:-1], 100.0
    try:
        return [float(s) / scale]
    except ValueError:
        return []


def _str_candidates(text: str, info: Spec | None) -> list[str]:
    fill = info.fill_char if info is not None else " "
    out: list[str] = []
    for c in (text, text.rstrip(fill), text.lstrip(fill), text.strip(fill)):
        if c not in out:
            out.append(c)
    return out


def invert(text: str, spec: str, conversion: str | None, declared: Any) -> list[Any]:
    """Values v such that ``format(convert(v, conversion), spec) == text``."""
    if conversion in ("r", "a"):
        try:
            cands: list[Any] = [ast.literal_eval(text)]
        except ValueError, SyntaxError, MemoryError, RecursionError:
            return []
    elif conversion == "s":
        cands = [text]
    else:
        info = parse_spec(spec)
        tt = target_type(spec, conversion, declared)
        if tt is int or tt is bool:
            cands = _int_candidates(text, info)
        elif tt is float:
            cands = _float_candidates(text, info)
        elif tt is str:
            cands = _str_candidates(text, info)
        else:
            cands = []
            for c in _str_candidates(text, info):
                try:
                    cands.append(tt(c))
                except TypeError, ValueError:
                    pass
    out: list[Any] = []
    for v in cands:
        try:
            ok = format(convert(v, conversion), spec) == text
        except TypeError, ValueError:
            ok = False
        if ok and not any(type(v) is type(o) and v == o for o in out):
            out.append(v)
    return out
