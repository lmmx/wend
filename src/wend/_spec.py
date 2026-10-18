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
    zero: bool  # the "0" flag before the width
    width: int | None
    type: str | None

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
    def reads_int(self) -> bool:
        """Whether an untyped field with this spec also reads ints (§7).

        The ``0`` flag before a width, with no alignment and no presentation
        type (``05``), is Python's zero padding for numbers. A ``str`` formats
        under it too, filled on the right.
        """
        return self.zero and self.width is not None and not self.align and not self.type


@lru_cache(maxsize=1024)
def parse_spec(spec: str) -> Spec | None:
    """Parse a standard format spec, or return None if it is not one."""
    m = _SPEC_RE.match(spec)
    if m is None:
        return None
    width = m["width"]
    return Spec(
        m["fill"],
        m["align"],
        m["zero"] is not None,
        int(width) if width else None,
        m["type"],
    )


def target_type(spec: str, conversion: str | None, declared: Any) -> Any:
    """The Python type a matched field value is parsed into."""
    if conversion is not None:
        return None  # conversions are inverted via the conversion itself
    if declared is not None:
        return declared
    return _implied_type(parse_spec(spec))


def _implied_type(info: Spec | None) -> Any:
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
            return None  # an untyped "" or "05" spec reads str values too (§7)
        t = "d"
    return INT_DIGITS[t]


def allowed_chars(
    spec: str, conversion: str | None, declared: Any
) -> frozenset[str] | None:
    """Characters a formatted field may contain, used to prune matching (None = any)."""
    if target_type(spec, conversion, declared) is not int:
        return None
    info = parse_spec(spec)
    if info is None or info.type in ("c", "n"):
        return None  # c writes any character, n the locale's separators
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
        except TypeError:  # unhashable, from a literal
            if any(type(v) is type(o) and v == o for o in out):
                continue
        out.append(v)
    return out


def invert(text: str, spec: str, conversion: str | None, declared: Any) -> list[Any]:
    """Values v such that ``format(convert(v, conversion), spec) == text``.

    Candidates are read from every unpadded form of ``text`` (`unpad`), parsed
    as the field's type (§7), and kept only if they format back to ``text``.
    """
    info = parse_spec(spec)
    cands: list[Any]
    if conversion is not None:
        cores = unpad(text, info, False)  # a conversion formats a str
        if conversion == "s":
            cands = cores
        else:
            cands = []
            for c in cores:
                try:
                    cands.append(ast.literal_eval(c))
                except ValueError, SyntaxError, MemoryError, RecursionError:
                    pass
    else:
        tt = declared if declared is not None else _implied_type(info)
        if tt is int or tt is bool:
            cands = _int_candidates(text, info)
        elif tt is float:
            cands = _float_candidates(text, info)
        elif tt is str:
            cands = unpad(text, info, False)
            if declared is None and info is not None and info.reads_int:
                cands = cands + _int_candidates(text, info)
        else:  # another declared type: its own __format__ may pad either way
            cands = []
            for c in dict.fromkeys(unpad(text, info, False) + unpad(text, info, True)):
                try:
                    cands.append(tt(c))
                except TypeError, ValueError:
                    pass
    out: list[Any] = []
    for v in _distinct(cands):
        try:
            ok = format(convert(v, conversion), spec) == text
        except TypeError, ValueError:
            ok = False
        if ok:
            out.append(v)
    return out
