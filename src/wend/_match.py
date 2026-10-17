"""Matching concrete paths against expressions (the inverse of resolution).

Matching enumerates candidate bindings structurally (one ``Seg`` per path
segment, a ``Splice`` per run of segments, a head parameter per prefix), parses
field text back into values with `_spec.invert`, and then *verifies* every
candidate by rendering it. A match is therefore always exact: rendering the
returned bindings reproduces the canonical form of the input path.

Several distinct verified bindings mean the path is ambiguous for this
expression; `match` raises `AmbiguousMatchError` rather than guessing.

Fast path: when every segment is deterministic by construction (integer
``d`` fields followed by a literal that does not start with a digit, at most
one string field and only as the segment's last field) and the head's extent
is fixed, a single regex ``fullmatch`` per segment is the only possible parse.
Such expressions skip the search; their result is still verified by rendering.
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterator, Mapping
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
    canonical,
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


def _field_values(f: Field, text: str, env: dict[str, Any]) -> list[Any]:
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
            spec = "".join(
                s if isinstance(s, str) else format(env[s.name], "") for s in f.spec
            )
        except KeyError:
            raise NotInvertibleError(
                f"{f.pattern} has a format spec that depends on unbound parameters"
            ) from None
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
        for end in ends:
            for v in _field_values(piece, text[pos:end], env):
                env2 = _unify(env, piece.source.name, v)  # type: ignore[union-attr]
                if env2 is not None:
                    yield from rec(i + 1, end, env2)

    yield from rec(0, 0, env)


_INT_SPEC = re.compile(r"(?:0[0-9]+)?d?")


def seg_plan(seg: Seg) -> tuple[re.Pattern[str], list[tuple[Param, str]]] | None:
    """A regex plan if ``seg`` has at most one parse, else None (cached on the Seg)."""
    cached = seg.__dict__.get("_plan", _UNSET)
    if cached is not _UNSET:
        return cached
    plan = _build_seg_plan(seg)
    seg.__dict__["_plan"] = plan
    return plan


def _build_seg_plan(seg: Seg) -> tuple[re.Pattern[str], list[tuple[Param, str]]] | None:
    pieces = seg.pieces
    field_at = [i for i, p in enumerate(pieces) if isinstance(p, Field)]
    if not field_at:
        return None
    rx: list[str] = []
    conv: list[tuple[Param, str]] = []
    for i, p in enumerate(pieces):
        if isinstance(p, str):
            rx.append(re.escape(p))
            continue
        src = p.source
        if (
            not isinstance(src, Param)
            or p.conversion is not None
            or p.static_spec is None
        ):
            return None
        nxt = pieces[i + 1] if i + 1 < len(pieces) else None
        if isinstance(nxt, Field):
            return None  # adjacent fields
        if p.role == "segment":
            if len(pieces) != 1 or src.type not in (None, str):
                return None
            rx.append("(.+)")
            conv.append((src, "seg"))
            continue
        spec = p.static_spec
        if (
            src.type in (None, int)
            and _INT_SPEC.fullmatch(spec)
            and (spec or src.type is int)
        ):
            if nxt is not None and nxt[0] in "0123456789":
                return None
            rx.append("(-?[0-9]+)")
            conv.append((src, "int"))
        elif src.type in (None, str) and spec == "" and i == field_at[-1]:
            rx.append("(.*)")
            conv.append((src, "str"))
        else:
            return None
    return re.compile("".join(rx)), conv


def _seg_fast(
    plan: tuple[re.Pattern[str], list[tuple[Param, str]]],
    text: str,
    env: dict[str, Any],
) -> dict[str, Any] | None:
    rx, conv = plan
    m = rx.fullmatch(text)
    if m is None:
        return None
    out = dict(env)  # one copy per segment; callers may share env between branches
    for (p, kind), g in zip(conv, m.groups(), strict=True):
        if kind == "int":
            v: Any = int(g)
        elif kind == "seg" and g in (".", ".."):
            return None
        else:
            v = g
        if not _accept(p, v):
            return None
        prev = out.get(p.name, _UNSET)
        if prev is _UNSET:
            out[p.name] = v
        elif type(prev) is not type(v) or prev != v:
            return None
    return out


def _expr_plan(expr: PathExpr) -> list[Any] | None:
    cached = expr.__dict__.get("_match_plan", _UNSET)
    if cached is not _UNSET:
        return cached
    plan: list[Any] | None = []
    if isinstance(expr.head, Deferred) or any(
        isinstance(p, Splice) for p in expr.parts
    ):
        plan = None
    else:
        for part in expr.parts:
            assert isinstance(part, Seg)
            if part.literal is not None:
                plan.append(part.literal)
            else:
                sp = seg_plan(part)
                if sp is None:
                    plan = None
                    break
                plan.append(sp)
    expr.__dict__["_match_plan"] = plan
    return plan


def _fast_candidate(
    expr: PathExpr, plan: list[Any], anchor: str, names: list[str]
) -> dict[str, Any] | None:
    h = expr.head
    n = len(plan)
    env: dict[str, Any] | None = {}
    if isinstance(h, _Rel) or isinstance(h, Root):
        if anchor != ("" if isinstance(h, _Rel) else h.anchor) or len(names) != n:
            return None
        rest = names
    else:
        assert isinstance(h, HeadParam)
        k = len(names) - n
        if k < 0 or (h.param.kind is Kind.ABSOLUTE and not anchor):
            return None
        value = _join_head(anchor, names[:k])
        if not _accept(h.param, value):
            return None
        env = {h.param.name: value}
        rest = names[k:]
    for step, name in zip(plan, rest, strict=True):
        if isinstance(step, str):
            if step != name:
                return None
        else:
            env = _seg_fast(step, name, env)  # type: ignore[arg-type]
            if env is None:
                return None
    return env


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
        value = "/".join(chunk) or "."
        if not _accept(part.param, value):
            continue
        env2 = _unify(env, part.param.name, value)
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
        value = _join_head(anchor, names[:k])
        if not _accept(p, value):
            continue
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
    s = _canonical(path)
    anchor, names = split_canonical(s)
    out: list[dict[str, Any]] = []
    render = expr._compiled.render
    plan = _expr_plan(expr) if fast else None
    if plan is not None:
        env = _fast_candidate(expr, plan, anchor, names)
        if env is None:
            return []
        try:
            return [env] if render(env) == s else []
        except WendError, ValueError:
            return []
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
    found = match_all(expr, path, limit=2)
    if not found:
        return None
    if len(found) > 1:
        raise AmbiguousMatchError(_canonical(path), match_all(expr, path))
    return Match(_canonical(path), found[0])
