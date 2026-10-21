"""Matching concrete paths against expressions (the inverse of resolution).

Matching enumerates candidate bindings structurally (one ``Seg`` per path
segment, a ``Splice`` per run of segments, a head parameter per prefix), parses
field text back into values with `_spec.invert`, and then *verifies* every
candidate by rendering it. A match is therefore always exact: rendering the
returned bindings reproduces the canonical form of the input path.

Several distinct verified bindings mean the path is ambiguous for this
expression; `match` raises `AmbiguousMatchError` rather than guessing.

Fast path: when every segment admits at most one parse by construction
(integer fields in a base's digit class, ``choices`` fields, at most one free
string field, each pinned by its neighbouring literals; docs/SEMANTICS.md §8)
and the split of the path among the head, the segments and at most one
``SubPath`` is forced, one regex ``fullmatch`` over the whole path is the only
possible parse. Such expressions skip the search; their result is still
verified by rendering. `glob` and inference use the same per-segment plans.
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterator, Mapping
from functools import lru_cache
from typing import Any

from . import _spec
from ._expr import (
    Const,
    Deferred,
    Field,
    HeadParam,
    PathExpr,
    Root,
    Seg,
    Splice,
    _Rel,
    _render_field,
    _render_spec,
    canonical,
    head_value,
    splice_value,
)
from ._params import Kind, Param
from .errors import (
    AmbiguousMatchError,
    InvalidBindingError,
    NotInvertibleError,
    WendError,
)


_UNSET = object()


class Match(Mapping[str, Any]):
    """A matched path and its bindings (a read-only mapping of name to value)."""

    __slots__ = ("bindings", "path")

    def __init__(self, path: str, bindings: dict[str, Any]) -> None:
        self.path = path
        self.bindings = bindings

    def __getitem__(self, key: str) -> Any:
        return self.bindings[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self.bindings)

    def __len__(self) -> int:
        return len(self.bindings)

    def __bool__(self) -> bool:
        # A match is truthy like re.Match, even with no bindings (a literal path).
        return True

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Match):
            return self.path == other.path and self.bindings == other.bindings
        if isinstance(other, Mapping):
            return self.bindings == dict(other)
        return NotImplemented

    __hash__ = None  # type: ignore[assignment]

    def __repr__(self) -> str:
        return f"Match({self.path!r}, {self.bindings!r})"


def _unify(env: dict[str, Any], name: str, value: Any) -> dict[str, Any] | None:
    prev = env.get(name, _UNSET)
    if prev is _UNSET:
        out = dict(env)
        out[name] = value
        return out
    if type(prev) is type(value) and prev == value:
        return env
    return None


def _accept(p: Param, value: Any) -> bool:
    if p.type is None and p.choices is None:
        return True
    try:
        p.check(value)
    except InvalidBindingError:
        return False
    return True


# -- reading choices back (docs/SEMANTICS.md §7) ---------------------------------
#
# A parameter that declares choices reads, in each position, every member whose
# rendering there is the text, as well as what its type or spec reads. A value
# read that equals a member is returned as that member when the member renders
# the same text, so a declared member reads back as itself.


def _texts_of(members: Any, render: Any) -> dict[str, tuple[Any, ...]]:
    """Each text ``render`` gives a member, with the members giving it
    (in repr order, so that readings come out in a fixed order)."""
    out: dict[str, list[Any]] = {}
    for m in sorted(members, key=repr):
        try:
            # A str subclass may come back as itself (a segment value is used
            # as is): the text is the plain str a path holds.
            text = str.__str__(render(m))
        except WendError, ValueError, TypeError, KeyError:
            continue  # a member that never renders here
        out.setdefault(text, []).append(m)
    return {t: tuple(ms) for t, ms in out.items()}


def _field_members(f: Field) -> dict[str, tuple[Any, ...]]:
    """`_texts_of` the choices of a field with a static spec (cached on it)."""
    cached = f.__dict__.get("_members")
    if cached is None:
        p = f.source
        assert isinstance(p, Param) and p.choices is not None
        cached = _texts_of(p.choices, lambda m: _render_field(f, {p.name: m}))
        f.__dict__["_members"] = cached
    return cached


@lru_cache(maxsize=1024)
def _path_members(p: Param, splice: bool) -> dict[str, tuple[Any, ...]]:
    assert p.choices is not None
    if splice:
        return _texts_of(p.choices, lambda m: "/".join(splice_value(p, m)) or ".")
    return _texts_of(p.choices, lambda m: head_value(p, m))


def _same(a: Any, b: Any) -> bool:
    return a is b or (type(a) is type(b) and a == b)


def _equal(a: Any, b: Any) -> bool:
    try:
        return a is b or bool(a == b)
    except Exception:  # a comparison that fails is no match
        return False


def _verdict(texts: dict[str, tuple[Any, ...]], read: Any) -> Any:
    """How the members' readings relate to today's (``read(text)``): True if
    every member already reads back as itself, so reading members changes
    nothing; else, if each member's text is its alone and today reads it as
    a value equal to the member, the map from text to member (a one-parse
    plan can then return the member); else None (only the full search reads
    the members)."""
    canon: dict[str, Any] = {}
    trivial = True
    for text, members in texts.items():
        if len(members) > 1:
            return None  # members that render alike: a path with two readings
        m = next(iter(members))
        try:
            today = read(text)
        except NotInvertibleError:
            return None
        if not any(_same(v, m) for v in today):
            trivial = False
            if not any(_equal(v, m) for v in today):
                return None
        canon[text] = m
    return True if trivial else canon


def _field_verdict(f: Field) -> Any:
    """`_verdict` for a field with choices and a static spec (cached on it)."""
    cached = f.__dict__.get("_verdict", _UNSET)
    if cached is _UNSET:
        cached = _verdict(_field_members(f), lambda t: _type_values(f, t, {}))
        f.__dict__["_verdict"] = cached
    return cached


@lru_cache(maxsize=1024)
def _path_verdict(p: Param, splice: bool) -> Any:
    """`_verdict` for a head (``splice=False``) or SubPath with choices."""
    return _verdict(_path_members(p, splice), lambda t: [t] if _accept(p, t) else [])


def _with_members(values: list[Any], members: tuple[Any, ...]) -> list[Any]:
    """``values`` (read as the type or spec reads them), each replaced by the
    member it equals if that member renders the same text, then the members
    that render the text and are not read already."""
    out: list[Any] = []

    def add(v: Any) -> None:
        if not any(_same(o, v) for o in out):
            out.append(v)

    for v in values:
        add(next((m for m in members if _equal(m, v)), v))
    for m in members:
        add(m)
    return out


def _path_readings(p: Param, text: str, splice: bool) -> list[Any]:
    """The values a head (``splice=False``) or SubPath parameter reads from
    the path text ``text``."""
    values = [text] if _accept(p, text) else []
    if p.choices is None or _path_verdict(p, splice) is True:
        return values
    return _with_members(values, _path_members(p, splice).get(text, ()))


def _field_values(f: Field, text: str, env: dict[str, Any]) -> list[Any]:
    values = _type_values(f, text, env)
    src = f.source
    if not isinstance(src, Param) or src.choices is None:
        return values
    if f.static_spec is not None:
        if _field_verdict(f) is True:
            return values  # every member already reads back as itself
        members = _field_members(f).get(text, ())
    else:  # the spec depends on bindings: render each member with them
        name = src.name
        texts = _texts_of(src.choices, lambda m: _render_field(f, {**env, name: m}))
        members = texts.get(text, ())
    return _with_members(values, members)


def _type_values(f: Field, text: str, env: dict[str, Any]) -> list[Any]:
    src = f.source
    if isinstance(src, Const):
        raise NotInvertibleError(
            f"{f.pattern} has a format spec that depends on unbound parameters"
        )
    if not isinstance(src, Param):
        raise NotInvertibleError(
            f"{f.pattern} derives from another path and cannot be inverted"
        )
    if f.role == "segment":
        if not text or text in (".", ".."):
            return []
        if src.type is None or src.type is str:
            return [text] if _accept(src, text) else []
        # A typed segment was formatted like an f-string's {v}; invert that.
        return [v for v in _spec.invert(text, "", None, src.type) if _accept(src, v)]
    spec = f.static_spec
    if spec is None:
        try:
            spec = _render_spec(f.spec, env)
        except KeyError:
            raise NotInvertibleError(
                f"{f.pattern} has a format spec that depends on unbound parameters"
            ) from None
        except InvalidBindingError:
            return []  # a nested spec value is rejected, or cannot be formatted
    return [
        v for v in _spec.invert(text, spec, f.conversion, src.type) if _accept(src, v)
    ]


def _match_seg(seg: Seg, text: str, env: dict[str, Any]) -> Iterator[dict[str, Any]]:
    lit = seg.literal
    if lit is not None:
        if text == lit:
            yield env
        return
    pieces = seg.pieces
    n = len(pieces)

    def rec(i: int, pos: int, env: dict[str, Any]) -> Iterator[dict[str, Any]]:
        if i == n:
            if pos == len(text):
                yield env
            return
        piece = pieces[i]
        if isinstance(piece, str):
            if text.startswith(piece, pos):
                yield from rec(i + 1, pos + len(piece), env)
            return
        allowed = None
        if (
            piece.role == "value"
            and isinstance(piece.source, Param)
            and piece.static_spec is not None
        ):
            allowed = _spec.allowed_chars(
                piece.static_spec, piece.conversion, piece.source.type
            )
        limit = len(text)
        if allowed is not None:
            limit = pos
            while limit < len(text) and text[limit] in allowed:
                limit += 1
        nxt = pieces[i + 1] if i + 1 < n else None
        if nxt is None:
            ends = [len(text)] if limit == len(text) else []
        elif isinstance(nxt, str):
            ends = []
            j = text.find(nxt, pos)
            while j != -1 and j <= limit:
                ends.append(j)
                j = text.find(nxt, j + 1)
        else:
            ends = list(range(pos, limit + 1))
        src = piece.source
        read = (
            _field_values
            if isinstance(src, Param) and src.choices is not None
            else _type_values
        )
        for end in ends:
            for v in read(piece, text[pos:end], env):
                env2 = _unify(env, piece.source.name, v)  # type: ignore[union-attr]
                if env2 is not None:
                    yield from rec(i + 1, end, env2)

    yield from rec(0, 0, env)


# ---------------------------------------------------------------------------
# Fast path: regex plans that admit at most one parse (docs/SEMANTICS.md §8)
# ---------------------------------------------------------------------------

# How a regex group becomes a value: as is, by int(), as a whole segment
# (never "." or ".."), or as a SubPath (zero groups or text mean ".").
_STR, _INT, _SEG, _SPLICE = range(4)

# (name, param, kind, base, check): ``base`` is an int field's base; ``check``
# says whether the value needs `_accept` (the parameter declares choices, or
# a type the conversion does not already guarantee). A dict is a check that
# then maps the text to the choice member it renders (`_verdict`).
type _Conv = tuple[str, Param, int, int, bool | dict[str, Any]]


class SegPlan:
    """A regex that parses one segment in at most one way, and its group conversions.

    ``src`` never matches a ``/``, so it can be embedded in a whole-path regex.
    ``bind(text, env)`` (generated on first use by `_seg_fast`) returns
    ``env`` extended with the segment's bindings, or None.
    """

    __slots__ = ("bind", "conv", "may_be_empty", "src")

    def __init__(self, src: str, conv: tuple[_Conv, ...], may_be_empty: bool) -> None:
        self.src = src
        self.conv = conv
        self.may_be_empty = may_be_empty
        self.bind: Any = None


def _field_shape(f: Field, alone: bool) -> tuple[Any, ...] | None:
    """("int", digits, base) | ("choice", strings) | ("str",) | ("seg",), or None."""
    src = f.source
    if not isinstance(src, Param) or f.conversion is not None or f.static_spec is None:
        return None
    if src.choices is not None and _field_verdict(f) is None:
        return None  # only the full search reads these members back
    if f.role == "segment":
        return ("seg",) if alone and src.type in (None, str) else None
    spec = f.static_spec
    if src.type in (None, int):
        digits = _spec.plain_int(spec, src.type)
        if digits is not None:
            return ("int", *digits)
    if src.type in (None, str) and spec == "":
        if src.choices is None:
            return ("str",)
        if all(type(c) is str for c in src.choices):
            # A choice containing "/" can never render (a field has no separator).
            vals = tuple(sorted(c for c in src.choices if "/" not in c))
            return ("choice", vals) if vals else None
    return None


def _prefix_unique(choices: tuple[str, ...], lit: str) -> bool:
    """No text starts with both ``c + lit`` and ``c2 + lit`` for distinct choices.

    Two such choices are prefix-related, and ``c + lit`` and ``c2`` are then
    prefixes of one text, so one is a prefix of the other. Only pairs where
    ``c`` is a proper prefix of ``c2`` need checking; in sorted order the
    strings that start with ``c`` follow it contiguously.
    """
    cs = sorted(choices)
    for i, c in enumerate(cs):
        j = i + 1
        while j < len(cs) and cs[j].startswith(c):
            rest = cs[j][len(c) :]
            if rest.startswith(lit) or lit.startswith(rest):
                return False
            j += 1
    return True


def _forced_from_left(shape: tuple[Any, ...], nxt: Any) -> bool:
    """Whether the field's end is forced by its start and the piece after it."""
    if shape[0] == "int":
        return isinstance(nxt, str) and nxt != "" and nxt[0] not in shape[1]
    if shape[0] == "choice":
        return _prefix_unique(shape[1], nxt if isinstance(nxt, str) else "")
    return False


def _forced_from_right(shape: tuple[Any, ...], prv: Any) -> bool:
    """Whether the field's start is forced by its end and the piece before it."""
    if shape[0] == "int":
        return (
            isinstance(prv, str)
            and prv != ""
            and prv[-1] not in shape[1]
            and prv[-1] != "-"
        )
    if shape[0] == "choice":
        return _prefix_unique(
            tuple(c[::-1] for c in shape[1]),
            prv[::-1] if isinstance(prv, str) else "",
        )
    return False


def _has_pivot(pieces: tuple[Any, ...], shapes: list[Any], fields: list[int]) -> bool:
    """Whether some field k (a free string field, if any) leaves every field
    before it forced from the left and every field after it forced from the
    right. A free field is forced from neither side, so there is at most one."""
    free = [i for i in fields if shapes[i][0] in ("str", "seg")]
    for k in free or fields:
        if all(
            _forced_from_left(shapes[i], pieces[i + 1])
            if i < k
            else i == k or _forced_from_right(shapes[i], pieces[i - 1])
            for i in fields
        ):
            return True
    return False


def seg_plan(seg: Seg) -> SegPlan | None:
    """A regex plan if ``seg`` has at most one parse, else None (cached on the Seg)."""
    cached = seg.__dict__.get("_plan", _UNSET)
    if cached is not _UNSET:
        return cached
    plan = _build_seg_plan(seg)
    seg.__dict__["_plan"] = plan
    return plan


def _build_seg_plan(seg: Seg) -> SegPlan | None:
    pieces = seg.pieces
    shapes: list[tuple[Any, ...] | None] = []
    for p in pieces:
        if isinstance(p, str):
            if not p or "/" in p:
                return None
            shapes.append(None)
        else:
            shape = _field_shape(p, len(pieces) == 1)
            if shape is None:
                return None
            shapes.append(shape)
    fields = [i for i, s in enumerate(shapes) if s is not None]
    if not fields or not _has_pivot(pieces, shapes, fields):
        return None
    rx: list[str] = []
    conv: list[_Conv] = []
    for p, shape in zip(pieces, shapes, strict=True):
        if isinstance(p, str):
            rx.append(re.escape(p))
            continue
        src = p.source
        assert isinstance(src, Param) and shape is not None
        # True: check the value; a dict: check it, then return the member
        # its text renders (`_verdict`).
        check = _field_verdict(p) if src.choices is not None else False
        kind = shape[0]
        if kind == "int":
            rx.append(f"(-?[{shape[1]}]+)")
            conv.append((src.name, src, _INT, shape[2], check))
        elif kind == "choice":
            alts = sorted(shape[1], key=lambda c: (-len(c), c))
            rx.append("(" + "|".join(map(re.escape, alts)) + ")")
            conv.append((src.name, src, _STR, 0, check))
        elif kind == "str":
            rx.append("([^/]*)")
            conv.append((src.name, src, _STR, 0, check))
        else:
            rx.append("([^/]+)")
            conv.append((src.name, src, _SEG, 0, check))
    may_be_empty = all(s is not None and s[0] != "int" for s in shapes)
    return SegPlan("".join(rx), tuple(conv), may_be_empty)


# The plans' hot loops are generated Python, like `_compile`'s renderers: one
# function per plan, with the groups' conversions and checks inlined. Sources
# depend only on the plan's shape, so their code objects are shared.


@lru_cache(maxsize=512)
def _code(name: str, args: str, body: tuple[str, ...]) -> Any:
    src = f"def {name}({args}):\n" + "".join(f"    {ln}\n" for ln in body)
    return compile(src, f"<wend match {name}>", "exec")


def _define(name: str, args: str, body: list[str], ns: dict[str, Any]) -> Any:
    exec(_code(name, args, tuple(body)), ns)  # noqa: S102
    return ns[name]


def _conversions(
    conv: tuple[_Conv, ...], ns: dict[str, Any], first: dict[str, str]
) -> list[str]:
    """Statements turning groups ``g0, g1, ...`` into values ``v0, v1, ...``.

    Each statement returns None where the full search rejects the value. A
    name seen before (``first`` maps names to the variable holding their first
    value) must have the same type and value; new names are added to ``first``.
    """
    out: list[str] = []
    ints = [f"v{i} = int(g{i}, {c[3]})" for i, c in enumerate(conv) if c[2] == _INT]
    if ints:  # int() refuses decimal strings beyond its digit limit
        out += [
            "try:",
            *(f"    {s}" for s in ints),
            "except ValueError:",
            "    return None",
        ]
    for i, (name, p, kind, _, check) in enumerate(conv):
        g, v = f"g{i}", f"v{i}"
        if kind == _STR:
            out.append(f"{v} = {g}")
        elif kind == _SEG:
            out += [f"if {g} == '.' or {g} == '..':", "    return None", f"{v} = {g}"]
        elif kind == _SPLICE:
            out += [
                f"{v} = {g} or '.'",
                f"if '..' in {v}.split('/'):",
                "    return None",
            ]
        if check:
            ns[f"_p{i}"] = p
            out += [f"if not _accept(_p{i}, {v}):", "    return None"]
        if isinstance(check, dict):  # the member a choice's text stands for
            ns[f"_c{i}"] = check
            text = v if kind == _SPLICE else g
            out.append(f"{v} = _c{i}.get({text}, {v})")
        w = first.setdefault(name, v)
        if w != v:
            out += [f"if type({v}) is not type({w}) or {v} != {w}:", "    return None"]
    return out


def _unpack(n: int) -> list[str]:
    return [", ".join(f"g{i}" for i in range(n)) + ", = m.groups()"] if n else []


def _seg_binder(fullmatch: Any, conv: tuple[_Conv, ...]) -> Any:
    ns: dict[str, Any] = {"_rx": fullmatch, "_accept": _accept, "_U": _UNSET}
    first: dict[str, str] = {}
    body = ["m = _rx(text)", "if m is None:", "    return None", *_unpack(len(conv))]
    body += _conversions(conv, ns, first)
    for name, v in first.items():
        body += [
            f"p = env.get({name!r}, _U)",
            f"if p is not _U and (type(p) is not type({v}) or p != {v}):",
            "    return None",
        ]
    # A new dict: callers may share env between branches.
    body.append(
        "return {**env, " + ", ".join(f"{k!r}: {v}" for k, v in first.items()) + "}"
    )
    return _define("_bind", "text, env", body, ns)


def _seg_fast(plan: SegPlan, text: str, env: dict[str, Any]) -> dict[str, Any] | None:
    bind = plan.bind
    if bind is None:
        bind = plan.bind = _seg_binder(re.compile(plan.src).fullmatch, plan.conv)
    return bind(text, env)


def _expr_plan(expr: PathExpr) -> Any:
    """``f(canonical_path) -> verified bindings | None`` when ``expr`` admits at
    most one parse of any path, else None (cached on the expression)."""
    cached = expr.__dict__.get("_match_plan", _UNSET)
    if cached is not _UNSET:
        return cached
    plan = _build_expr_plan(expr)
    expr.__dict__["_match_plan"] = plan
    return plan


def _build_expr_plan(expr: PathExpr) -> Any:
    h = expr.head
    if isinstance(h, Deferred):
        return None
    conv: list[_Conv] = []
    pre: list[str] | None = None  # the segments before the Splice, if any
    items: list[str] = []
    for part in expr.parts:
        if isinstance(part, Splice):
            if pre is not None or isinstance(h, HeadParam):
                return None  # two variable extents: the split is not forced
            pre, items = items, []
            p = part.param
            verdict = _path_verdict(p, True) if p.choices is not None else False
            if verdict is None:
                return None  # only the full search reads these members back
            check = (
                verdict
                if isinstance(verdict, dict)
                else (p.type is not None or p.choices is not None)
            )
            conv.append((p.name, p, _SPLICE, 0, check))
            continue
        lit = part.literal
        if lit is not None:
            if "/" in lit:
                return None
            items.append(re.escape(lit))
            continue
        sp = seg_plan(part)
        if sp is None:
            return None
        # Segments of a canonical path are never empty; saying so keeps the
        # split at separators unique even for a segment regex that allows "".
        items.append("(?=[^/])" + sp.src if sp.may_be_empty else sp.src)
        conv.extend(sp.conv)
    head_verdict: Any = False
    if isinstance(h, HeadParam) and h.param.choices is not None:
        head_verdict = _path_verdict(h.param, False)
        if head_verdict is None:
            return None  # only the full search reads these members back
    tail = "/".join(items)
    ns: dict[str, Any] = {
        "_accept": _accept,
        "_render": expr._compiled._fn,
        "_errors": (WendError, ValueError),
    }
    first: dict[str, str] = {}
    body: list[str] = []
    if isinstance(h, HeadParam):
        # The tail's segments hold no "/", so the head ends at the separator
        # before the last len(items) segments: one rsplit finds it.
        k = len(items)
        if k:
            ns["_rx"] = re.compile(tail, re.DOTALL).fullmatch
            body += [
                f"parts = s.rsplit('/', {k})",
                f"if len(parts) > {k}:",
                "    h = parts[0]",
                "    m = _rx(s, len(h) + 1)",
                "    if h == '' or h == '/':",
                "        h += '/'",  # the path's anchor
                "else:",
                "    m = _rx(s)",
                "    h = '.'",
                "if m is None:",
                "    return None",
            ]
        else:
            body.append("h = s")
        p = h.param
        if p.kind is Kind.ABSOLUTE:
            body += ["if h[0] != '/':", "    return None"]
        if p.type is not None or p.choices is not None:
            ns["_ph"] = p
            body += ["if not _accept(_ph, h):", "    return None"]
        if isinstance(head_verdict, dict):
            ns["_ch"] = head_verdict
            body.append("h = _ch.get(h, h)")
        first[p.name] = "h"
    else:
        anchor = re.escape(h.anchor) if isinstance(h, Root) else ""
        if pre is None:
            src = anchor + tail if items else anchor or r"\."
        elif pre and items:
            src = f"{anchor}{'/'.join(pre)}/(?:(.+)/)?{tail}"
        elif pre:
            src = f"{anchor}{'/'.join(pre)}(?:/(.+))?"
        elif items:
            src = f"{anchor}(?:(.+)/)?{tail}"
        else:
            src = f"{anchor}(.*)"
        ns["_rx"] = re.compile(src, re.DOTALL).fullmatch
        body += ["m = _rx(s)", "if m is None:", "    return None"]
    body += _unpack(len(conv))
    body += _conversions(tuple(conv), ns, first)
    body += [
        "env = {" + ", ".join(f"{k!r}: {v}" for k, v in first.items()) + "}",
        "try:",  # verify by rendering, as the full search does
        "    if _render(env) == s:",
        "        return env",
        "except _errors:",
        "    pass",
        "return None",
    ]
    return _define("_match", "s", body, ns)


def _match_parts(
    parts: tuple[Seg | Splice, ...],
    i: int,
    names: list[str],
    j: int,
    env: dict[str, Any],
) -> Iterator[dict[str, Any]]:
    if i == len(parts):
        if j == len(names):
            yield env
        return
    part = parts[i]
    if isinstance(part, Seg):
        if j < len(names):
            for env2 in _match_seg(part, names[j], env):
                yield from _match_parts(parts, i + 1, names, j + 1, env2)
        return
    rest_min = sum(1 for p in parts[i + 1 :] if isinstance(p, Seg))
    for k in range(j, len(names) - rest_min + 1):
        chunk = names[j:k]
        if ".." in chunk:
            break
        text = "/".join(chunk) or "."
        p = part.param
        if p.choices is None:  # the common case, inline
            if not _accept(p, text):
                continue
            values: Any = (text,)
        else:
            values = _path_readings(p, text, splice=True)
        for value in values:
            env2 = _unify(env, p.name, value)
            if env2 is not None:
                yield from _match_parts(parts, i + 1, names, k, env2)


def _candidates(
    expr: PathExpr, anchor: str, names: list[str]
) -> Iterator[dict[str, Any]]:
    h = expr.head
    if isinstance(h, _Rel):
        if not anchor:
            yield from _match_parts(expr.parts, 0, names, 0, {})
        return
    if isinstance(h, Root):
        if anchor == h.anchor:
            yield from _match_parts(expr.parts, 0, names, 0, {})
        return
    if isinstance(h, Deferred):
        raise NotInvertibleError(
            f"{expr.pattern!r} starts with a deferred {h.op!r}; bind its parameters before matching"
        )
    assert isinstance(h, HeadParam)
    p = h.param
    if p.kind is Kind.ABSOLUTE and not anchor:
        return
    rest_min = sum(1 for q in expr.parts if isinstance(q, Seg))
    if rest_min == len(expr.parts):  # no Splice: the head's extent is fixed
        ks = [len(names) - rest_min] if len(names) >= rest_min else []
    else:
        ks = list(range(0, len(names) - rest_min + 1))
    for k in ks:
        for value in _path_readings(p, _join_head(anchor, names[:k]), splice=False):
            yield from _match_parts(expr.parts, 0, names, k, {p.name: value})


def _join_head(anchor: str, names: list[str]) -> str:
    if anchor:
        return anchor + "/".join(names)
    return "/".join(names) or "."


def _canonical(path: Any) -> str:
    s = os.fspath(path)
    if not isinstance(s, str):
        raise TypeError("match() takes a str or os.PathLike")
    return canonical(s)


def split_canonical(s: str) -> tuple[str, list[str]]:
    """(anchor, segment names) of a canonical POSIX path string."""
    anchor = "//" if s.startswith("//") else "/" if s.startswith("/") else ""
    rest = s[len(anchor) :]
    return anchor, (rest.split("/") if rest and rest != "." else [])


def match_all(
    expr: PathExpr, path: Any, *, limit: int = 1000, fast: bool = True
) -> list[dict[str, Any]]:
    """All distinct verified bindings under which ``expr`` resolves to ``path``."""
    return _match_all(expr, _canonical(path), limit, fast)


def _match_all(expr: PathExpr, s: str, limit: int, fast: bool) -> list[dict[str, Any]]:
    plan = _expr_plan(expr) if fast else None
    if plan is not None:
        env = plan(s)
        return [] if env is None else [env]
    anchor, names = split_canonical(s)
    out: list[dict[str, Any]] = []
    render = expr._compiled.render
    for env in _candidates(expr, anchor, names):
        if any(env == o and all(type(env[k]) is type(o[k]) for k in env) for o in out):
            continue
        try:
            ok = render(env) == s
        except WendError, ValueError:
            ok = False
        if ok:
            out.append(env)
            if len(out) >= limit:
                break
    return out


def match(expr: PathExpr, path: Any) -> Match | None:
    s = _canonical(path)
    found = _match_all(expr, s, 2, True)
    if not found:
        return None
    if len(found) > 1:
        raise AmbiguousMatchError(s, _match_all(expr, s, 1000, True))
    return Match(s, found[0])
