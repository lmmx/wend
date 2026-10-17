"""The path expression algebra.

Normal form
-----------
Every expression is held as ``PathExpr(head, parts)``:

- ``head`` is where the path starts: relative (``REL``), a literal anchor
  (``Root("/")``), a path-valued parameter (``HeadParam``), or an operation that
  can only be computed once its inputs are bound (``Deferred``).
- ``parts`` is a tuple of ``Seg`` (exactly one path segment, built from literal
  text and formatted fields) and ``Splice`` (a sub-path parameter of zero or
  more segments).

Resolution validates that each ``Seg`` renders to exactly one canonical segment
(no separator, not "", ".", or a computed ".."), so the segment count of an
expression is known without its bindings. Structural operations (``parent``,
``name``, ``suffix``, ``relative_to``, matching) work on that static structure.
When structure is not enough (the last part is a ``Splice``, or a field might
contain the dot that decides a suffix), the operation is *deferred*: it is
evaluated with pathlib after binding. No rewrite ever changes a result.

Semantics
---------
For every accepted binding, ``expr.render(env)`` equals the eager pathlib
computation of the same operations on the formatted strings. Bindings that
would make eager pathlib silently change the segment structure are rejected
with `InvalidBindingError` instead.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, fields
from functools import cached_property
from pathlib import Path, PurePosixPath
from string.templatelib import Interpolation, Template
from typing import Any

from . import _spec
from ._params import MARKER_RE, Kind, Param, has_marker, lookup_marker
from .errors import (
    InvalidBindingError,
    MissingBindingError,
    NotStaticError,
    ParamConflictError,
    PathOperationError,
)


# ---------------------------------------------------------------------------
# Pieces: the contents of a segment or a symbolic string
# ---------------------------------------------------------------------------


class _Cached:
    """Frozen dataclasses whose cached properties (compiled functions, match
    plans, parameter tables) are derived state, left out of pickles and copies."""

    def __getstate__(self) -> dict[str, Any]:
        return {f.name: getattr(self, f.name) for f in fields(self)}  # type: ignore[arg-type]

    def __setstate__(self, state: dict[str, Any]) -> None:
        for k, v in state.items():
            object.__setattr__(self, k, v)


@dataclass(frozen=True)
class Const:
    """A concrete value whose formatting waits on a dynamic format spec."""

    value: Any


@dataclass(frozen=True)
class TextOp:
    """A name, stem or suffix of a path that is only known after binding."""

    op: str
    base: PathExpr


@dataclass(frozen=True)
class Field(_Cached):
    """A formatted interpolation.

    ``role="segment"`` marks a segment-valued parameter used as a path operand
    (its value is a path string); ``role="value"`` is a t-string field whose
    value is converted and formatted.
    """

    source: Param | Text | TextOp | Const
    conversion: str | None = None
    spec: tuple[str | Param, ...] = ()
    role: str = "value"

    @cached_property
    def static_spec(self) -> str | None:
        if all(isinstance(s, str) for s in self.spec):
            return "".join(self.spec)  # type: ignore[arg-type]
        return None

    @cached_property
    def facts(self) -> tuple[bool, bool]:
        """(dot_free, non_empty) guarantees, enforced at resolution."""
        if self.role == "segment" or self.static_spec is None:
            return False, False
        src = self.source
        declared = (
            src.type
            if isinstance(src, Param)
            else type(src.value)
            if isinstance(src, Const)
            else None
        )
        return _spec.facts(self.static_spec, self.conversion, declared)

    @cached_property
    def param_names(self) -> frozenset[str]:
        names = {s.name for s in self.spec if isinstance(s, Param)}
        src = self.source
        if isinstance(src, Param):
            names.add(src.name)
        elif isinstance(src, Text):
            names |= src.param_names
        elif isinstance(src, TextOp):
            names |= src.base.param_names
        return frozenset(names)

    def _params(self) -> list[Param]:
        out = [s for s in self.spec if isinstance(s, Param)]
        src = self.source
        if isinstance(src, Param):
            out.append(src)
        elif isinstance(src, Text):
            out.extend(src._params())
        elif isinstance(src, TextOp):
            out.extend(src.base.params.values())
        return out

    @property
    def pattern(self) -> str:
        src = self.source
        if isinstance(src, Param):
            inner = src.name
        elif isinstance(src, Text):
            inner = f"({src.pattern!r})"
        elif isinstance(src, TextOp):
            inner = f"{src.op}({src.base.pattern})"
        else:
            inner = repr(src.value)
        if self.conversion:
            inner += "!" + self.conversion
        spec = "".join(
            s if isinstance(s, str) else "{" + s.name + "}" for s in self.spec
        )
        if spec:
            inner += ":" + spec
        return "{" + inner + "}"


Piece = str | Field


def _norm(pieces: list[Piece] | tuple[Piece, ...]) -> tuple[Piece, ...]:
    """Merge adjacent literal pieces and drop empty ones."""
    out: list[Piece] = []
    for p in pieces:
        if isinstance(p, str):
            if not p:
                continue
            if out and isinstance(out[-1], str):
                out[-1] = out[-1] + p
                continue
        out.append(p)
    return tuple(out)


def _pieces_pattern(pieces: tuple[Piece, ...]) -> str:
    return "".join(
        p.replace("{", "{{").replace("}", "}}") if isinstance(p, str) else p.pattern
        for p in pieces
    )


def _guarantees_nondot(p: Piece) -> bool:
    if isinstance(p, str):
        return any(c != "." for c in p)
    if p.role == "segment":
        return False
    dot_free, non_empty = p.facts
    return dot_free and non_empty


def _may_contain_dot(p: Piece) -> bool:
    if isinstance(p, str):
        return "." in p
    return not p.facts[0]


@dataclass(frozen=True, repr=False)
class Text(_Cached):
    """A symbolic string: literal text and formatted fields.

    Produced by ``PathExpr.name``, ``.stem`` and ``.suffix``; usable in
    ``with_name``, ``with_stem``, as a path operand, and inside t-strings.
    """

    pieces: tuple[Piece, ...]

    @property
    def literal(self) -> str | None:
        if not self.pieces:
            return ""
        if len(self.pieces) == 1 and isinstance(self.pieces[0], str):
            return self.pieces[0]
        return None

    @cached_property
    def param_names(self) -> frozenset[str]:
        out: set[str] = set()
        for p in self.pieces:
            if isinstance(p, Field):
                out |= p.param_names
        return frozenset(out)

    def _params(self) -> list[Param]:
        return [q for p in self.pieces if isinstance(p, Field) for q in p._params()]

    @property
    def pattern(self) -> str:
        return _pieces_pattern(self.pieces)

    def __repr__(self) -> str:
        return f"Text({self.pattern!r})"

    def __add__(self, other: Any) -> Text:
        return Text(_norm(self.pieces + _to_text(other).pieces))

    def __radd__(self, other: Any) -> Text:
        return Text(_norm(_to_text(other).pieces + self.pieces))

    def render(self, mapping: Mapping[Any, Any] | None = None, /, **kw: Any) -> str:
        env = _make_env(mapping, kw)
        if any(_is_symbolic(v) for v in env.values()):
            return self.bind(env).render()
        _check_missing(self.param_names, env)
        return _render_pieces(self.pieces, env)

    def bind(self, mapping: Mapping[Any, Any] | None = None, /, **kw: Any) -> Text:
        env = _make_env(mapping, kw)
        if not (self.param_names & env.keys()):
            return self
        return Text(_bind_pieces(self.pieces, env))


def _to_text(x: Any) -> Text:
    if isinstance(x, Text):
        return x
    if isinstance(x, str):
        if has_marker(x):
            raise _fstring_error()
        return Text(_norm([x]))
    if isinstance(x, Param):
        return Text((Field(x),))
    if isinstance(x, Template):
        pieces: list[Piece] = []
        for item in x:
            if isinstance(item, str):
                pieces.append(item)
            else:
                pieces.extend(_interp_pieces(item))
        return Text(_norm(pieces))
    raise TypeError(f"Cannot use {type(x).__name__} as text")


def _text_as_segment(t: Text) -> Seg:
    for p in t.pieces:
        if isinstance(p, str) and ("/" in p or "\x00" in p):
            raise PathOperationError(
                f"Invalid name {t.pattern!r}: contains a separator"
            )
    lit = t.literal
    if lit is not None and lit in ("", "."):
        raise PathOperationError(f"Invalid name {lit!r}")
    return Seg(t.pieces)


# ---------------------------------------------------------------------------
# Parts and heads
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Seg(_Cached):
    """Exactly one path segment."""

    pieces: tuple[Piece, ...]

    @cached_property
    def literal(self) -> str | None:
        if len(self.pieces) == 1 and isinstance(self.pieces[0], str):
            return self.pieces[0]
        return None

    @cached_property
    def needs_check(self) -> bool:
        """Whether a rendering could be "", "." or ".." and must be validated."""
        if self.literal is not None:
            return False
        return not any(
            _guarantees_nondot(p) or (isinstance(p, Field) and p.role == "segment")
            for p in self.pieces
        )

    @cached_property
    def param_names(self) -> frozenset[str]:
        out: set[str] = set()
        for p in self.pieces:
            if isinstance(p, Field):
                out |= p.param_names
        return frozenset(out)


@dataclass(frozen=True)
class Splice:
    """A relative sub-path parameter: zero or more segments."""

    param: Param


Part = Seg | Splice


@dataclass(frozen=True)
class _Rel:
    def __repr__(self) -> str:
        return "REL"


REL = _Rel()


@dataclass(frozen=True)
class Root:
    anchor: str  # "/" or "//"


@dataclass(frozen=True)
class HeadParam:
    param: Param


@dataclass(frozen=True)
class Deferred:
    """An operation evaluated with pathlib once its inputs are bound."""

    op: str
    base: PathExpr
    arg: Any = None


Head = _Rel | Root | HeadParam | Deferred


# ---------------------------------------------------------------------------
# PathExpr
# ---------------------------------------------------------------------------


@dataclass(frozen=True, repr=False)
class PathExpr(_Cached):
    """A symbolic path. Build with `P`, `T`, or ``Param / ...``."""

    head: Head
    parts: tuple[Part, ...] = ()

    # -- construction -------------------------------------------------------

    def __truediv__(self, other: Any) -> PathExpr:
        return _join(self, _coerce(other, at_head=False))

    def __rtruediv__(self, other: Any) -> PathExpr:
        return _join(_coerce(other, at_head=True), self)

    def joinpath(self, *others: Any) -> PathExpr:
        out = self
        for o in others:
            out = out / o
        return out

    # -- introspection ------------------------------------------------------

    @cached_property
    def param_names(self) -> frozenset[str]:
        names: set[str] = set()
        h = self.head
        if isinstance(h, HeadParam):
            names.add(h.param.name)
        elif isinstance(h, Deferred):
            names |= h.base.param_names
            if isinstance(h.arg, (PathExpr, Text)):
                names |= h.arg.param_names
        for part in self.parts:
            if isinstance(part, Seg):
                names |= part.param_names
            else:
                names.add(part.param.name)
        return frozenset(names)

    @cached_property
    def params(self) -> dict[str, Param]:
        """Free parameters by name. Raises ParamConflictError on clashing declarations."""
        found: list[Param] = []
        h = self.head
        if isinstance(h, HeadParam):
            found.append(h.param)
        elif isinstance(h, Deferred):
            found.extend(h.base.params.values())
            if isinstance(h.arg, PathExpr):
                found.extend(h.arg.params.values())
            elif isinstance(h.arg, Text):
                found.extend(h.arg._params())
        for part in self.parts:
            if isinstance(part, Seg):
                for p in part.pieces:
                    if isinstance(p, Field):
                        found.extend(p._params())
            else:
                found.append(part.param)
        out: dict[str, Param] = {}
        for p in found:
            prev = out.setdefault(p.name, p)
            if prev != p:
                raise ParamConflictError(
                    f"Conflicting declarations for {p.name!r}: {prev!r} vs {p!r}"
                )
        return out

    def required_params(self) -> set[str]:
        """Names of all parameters needed to resolve this expression."""
        return set(self.param_names)

    @property
    def is_static(self) -> bool:
        """True if the expression has no free parameters."""
        return not self.param_names

    def is_absolute(self) -> bool | None:
        """True/False when known from structure, None when it depends on bindings."""
        h = self.head
        if isinstance(h, _Rel):
            return False
        if isinstance(h, Root):
            return True
        if isinstance(h, HeadParam) and h.param.kind is Kind.ABSOLUTE:
            return True
        return None

    @property
    def pattern(self) -> str:
        """A t-string-like rendering of the expression's structure."""
        h = self.head
        if isinstance(h, _Rel):
            base = ""
        elif isinstance(h, Root):
            base = h.anchor
        elif isinstance(h, HeadParam):
            base = "{" + h.param.name + "}"
        else:
            arg = ""
            if isinstance(h.arg, (PathExpr, Text)):
                arg = ", " + h.arg.pattern
            elif h.arg is not None:
                arg = ", " + repr(h.arg)
            base = f"{h.op}({h.base.pattern}{arg})"
        segs = [
            _pieces_pattern(p.pieces)
            if isinstance(p, Seg)
            else "{" + p.param.name + "...}"
            for p in self.parts
        ]
        return _combine(base, segs) if segs or base else "."

    def __repr__(self) -> str:
        return f"PathExpr({self.pattern!r})"

    __str__ = __repr__

    # -- structural path operations -----------------------------------------

    def _last_seg(self) -> Seg | None:
        if self.parts and isinstance(self.parts[-1], Seg):
            return self.parts[-1]
        return None

    def _empty_static(self) -> bool:
        """An expression that is just "." or an anchor."""
        return not self.parts and (
            isinstance(self.head, _Rel) or isinstance(self.head, Root)
        )

    def _static_path(self) -> PurePosixPath | None:
        if self.param_names or isinstance(self.head, Deferred):
            return None
        return PurePosixPath(_render_expr(self, {}))

    @property
    def parent(self) -> PathExpr:
        if self._last_seg() is not None:
            return PathExpr(self.head, self.parts[:-1])
        if self._empty_static():
            return self
        return PathExpr(Deferred("parent", self))

    @property
    def parents(self) -> tuple[PathExpr, ...]:
        out: list[PathExpr] = []
        cur = self
        while cur._last_seg() is not None:
            cur = cur.parent
            out.append(cur)
        if not cur._empty_static():
            raise NotStaticError(
                f"The parents of {self.pattern!r} depend on unbound parameters"
            )
        return tuple(out)

    @property
    def name(self) -> Text:
        seg = self._last_seg()
        if seg is not None:
            return Text(seg.pieces)
        if self._empty_static():
            return Text(())
        return Text((Field(TextOp("name", self)),))

    def _suffix_split(self) -> tuple[tuple[Piece, ...], tuple[Piece, ...]] | None:
        """Split the last segment into (stem, suffix) pieces when statically decidable."""
        seg = self._last_seg()
        if seg is None:
            return None
        if seg.literal is not None:
            p = PurePosixPath(seg.literal)
            suffix = p.suffix
            return _norm([p.stem]), _norm([suffix])
        pieces = seg.pieces
        for i in range(len(pieces) - 1, -1, -1):
            piece = pieces[i]
            if not _may_contain_dot(piece):
                continue
            if isinstance(piece, Field):
                return None  # the deciding dot may come from a value
            k = piece.rfind(".")
            if not (
                any(c != "." for c in piece[:k])
                or any(_guarantees_nondot(q) for q in pieces[:i])
            ):
                return None  # the dot might be stripped as a leading dot
            stem = _norm([*pieces[:i], piece[:k]])
            suffix = _norm([piece[k:], *pieces[i + 1 :]])
            return stem, suffix
        return pieces, ()

    @property
    def suffix(self) -> Text:
        split = self._suffix_split()
        if split is not None:
            return Text(split[1])
        if self._empty_static():
            return Text(())
        return Text((Field(TextOp("suffix", self)),))

    @property
    def stem(self) -> Text:
        split = self._suffix_split()
        if split is not None:
            return Text(split[0])
        if self._empty_static():
            return Text(())
        return Text((Field(TextOp("stem", self)),))

    @property
    def suffixes(self) -> tuple[Text, ...]:
        seg = self._last_seg()
        if seg is not None and seg.literal is not None:
            return tuple(Text((s,)) for s in PurePosixPath(seg.literal).suffixes)
        if seg is not None and not any(_may_contain_dot(p) for p in seg.pieces):
            return ()
        if self._empty_static():
            return ()
        raise NotStaticError(
            f"The suffixes of {self.pattern!r} depend on unbound parameters"
        )

    def with_name(self, name: Any) -> PathExpr:
        text = _to_text(name)
        new = _text_as_segment(text)
        if self._last_seg() is not None:
            return PathExpr(self.head, self.parts[:-1] + (new,))
        if self._empty_static():
            raise PathOperationError(f"{self.pattern!r} has an empty name")
        return PathExpr(Deferred("with_name", self, text))

    def with_suffix(self, suffix: str) -> PathExpr:
        if not isinstance(suffix, str):
            raise TypeError("suffix must be a str")
        if suffix and not suffix.startswith("."):
            raise PathOperationError(f"Invalid suffix {suffix!r}")
        if "/" in suffix or "\x00" in suffix:
            raise PathOperationError(f"Invalid suffix {suffix!r}")
        static = self._static_path()
        if static is not None:
            try:
                return _literal_expr(str(static.with_suffix(suffix)))
            except ValueError as e:
                raise PathOperationError(str(e)) from None
        split = self._suffix_split()
        if split is not None:
            stem, _ = split
            return PathExpr(self.head, self.parts[:-1] + (Seg(_norm([*stem, suffix])),))
        if self._empty_static():
            raise PathOperationError(f"{self.pattern!r} has an empty name")
        return PathExpr(Deferred("with_suffix", self, suffix))

    def with_stem(self, stem: Any) -> PathExpr:
        text = _to_text(stem)
        static = self._static_path()
        if static is not None and text.literal is not None:
            try:
                return _literal_expr(str(static.with_stem(text.literal)))
            except ValueError as e:
                raise PathOperationError(str(e)) from None
        split = self._suffix_split()
        if split is not None and text.literal is not None:
            _, suffix = split
            if not suffix:
                return self.with_name(text)
            if not text.literal:
                raise PathOperationError(f"{self.pattern!r} has a non-empty suffix")
            return self.with_name(Text(_norm([text.literal, *suffix])))
        if self._empty_static():
            raise PathOperationError(f"{self.pattern!r} has an empty name")
        return PathExpr(Deferred("with_stem", self, text))

    def relative_to(self, other: Any) -> PathExpr:
        """The path of self relative to other.

        Static when other is structurally a prefix of self, so a relation
        between unbound paths (``config.relative_to(root)``) needs no bindings.
        """
        o = _coerce(other, at_head=True)
        if o.head == self.head and self.parts[: len(o.parts)] == o.parts:
            return PathExpr(REL, self.parts[len(o.parts) :])
        a, b = self._static_path(), o._static_path()
        if a is not None and b is not None:
            try:
                return _literal_expr(str(a.relative_to(b)))
            except ValueError as e:
                raise PathOperationError(str(e)) from None
        return PathExpr(Deferred("relative_to", self, o))

    def is_relative_to(self, other: Any) -> bool:
        """True if structurally a prefix; raises NotStaticError if it depends on bindings."""
        o = _coerce(other, at_head=True)
        if o.head == self.head and self.parts[: len(o.parts)] == o.parts:
            return True
        a, b = self._static_path(), o._static_path()
        if a is not None and b is not None:
            return a.is_relative_to(b)
        raise NotStaticError(
            f"Whether {self.pattern!r} is under {o.pattern!r} depends on bindings"
        )

    # -- binding and resolution ---------------------------------------------

    def bind(self, mapping: Mapping[Any, Any] | None = None, /, **kw: Any) -> PathExpr:
        """Substitute some parameters, folding whatever becomes static.

        Values may be concrete (str, PathLike, ints for fields...) or symbolic:
        another PathExpr (rebasing), a Text, or a Param (renaming).
        """
        env = _make_env(mapping, kw)
        if not (self.param_names & env.keys()):
            return self
        return _bind_expr(self, env)

    def rebase(self, old: Any, new: Any) -> PathExpr:
        """Replace the prefix ``old`` (structurally) with ``new``."""
        rel = self.relative_to(old)
        if isinstance(rel.head, Deferred):
            raise NotStaticError(
                f"{old!r} is not a structural prefix of {self.pattern!r}"
            )
        return _coerce(new, at_head=True) / rel

    def render(self, mapping: Mapping[Any, Any] | None = None, /, **kw: Any) -> str:
        """Resolve to a canonical path string (equal to ``str(self.resolve(...))``)."""
        env = _make_env(mapping, kw)
        if any(_is_symbolic(v) for v in env.values()):
            return self.bind(env).render()
        _check_missing(self.param_names, env)
        return _render_expr(self, env)

    def resolve(
        self,
        mapping: Mapping[Any, Any] | None = None,
        /,
        *,
        cls: type = Path,
        **kw: Any,
    ) -> Any:
        """Resolve to a concrete path (``pathlib.Path`` unless ``cls`` is given)."""
        return cls(self.render(mapping, **kw))

    # -- matching and compilation (implemented in sibling modules) ----------

    def match(self, path: Any) -> Any:
        """Bindings that resolve to ``path``, None if none, AmbiguousMatchError if several."""
        from ._match import match

        return match(self, path)

    def match_all(
        self, path: Any, *, limit: int = 1000, fast: bool = True
    ) -> list[dict[str, Any]]:
        """All distinct verified bindings that render to ``path`` (up to ``limit``)."""
        from ._match import match_all

        return match_all(self, path, limit=limit, fast=fast)

    def compile(self) -> Any:
        """Compile to a specialised Python function, cached on the expression."""
        return self._compiled

    @cached_property
    def _compiled(self) -> Any:
        from ._compile import compile_expr

        return compile_expr(self)


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


def _fstring_error() -> TypeError:
    return TypeError(
        "A Param was formatted into a plain string (an f-string or str.format); "
        "use a t-string instead, e.g. T(t'chunk_{idx:04d}')"
    )


def _literal_expr(s: str) -> PathExpr:
    if has_marker(s):
        raise _fstring_error()
    p = PurePosixPath(s)
    anchor = p.anchor
    names = p.parts[1:] if anchor else p.parts
    head: Head = Root(anchor) if anchor else REL
    return PathExpr(head, tuple(Seg((n,)) for n in names))


def _param_expr(p: Param, *, at_head: bool) -> PathExpr:
    kind = p.kind
    if kind is Kind.AUTO:
        kind = Kind.PATH if at_head else Kind.SEGMENT
    if kind in (Kind.PATH, Kind.ABSOLUTE):
        return PathExpr(HeadParam(p))
    if kind is Kind.SEGMENT:
        return PathExpr(REL, (Seg((Field(p, role="segment"),)),))
    return PathExpr(REL, (Splice(p),))


def _coerce(x: Any, *, at_head: bool) -> PathExpr:
    if isinstance(x, PathExpr):
        return x
    if isinstance(x, Param):
        return _param_expr(x, at_head=at_head)
    if isinstance(x, Template):
        return _from_template(x)
    if isinstance(x, Text):
        return PathExpr(REL, (_text_as_segment(x),))
    if isinstance(x, (str, os.PathLike)):
        s = os.fspath(x)
        if isinstance(s, str):
            return _literal_expr(s)
    raise TypeError(f"Cannot use {type(x).__name__} as a path")


def _head_param(h: Deferred) -> Param | None:
    """The AUTO parameter at the root of a chain of deferred operations."""
    head: Any = h
    while isinstance(head, Deferred):
        head = head.base.head
    if isinstance(head, HeadParam) and head.param.kind is Kind.AUTO:
        return head.param
    return None


def _join(left: PathExpr, right: PathExpr) -> PathExpr:
    h = right.head
    if isinstance(h, _Rel):
        out = PathExpr(left.head, left.parts + right.parts)
    elif isinstance(left.head, _Rel) and not left.parts:
        return right  # "." is the identity for joins
    elif isinstance(h, Root):
        return right
    elif isinstance(h, HeadParam) and h.param.kind is Kind.AUTO:
        seg = Seg((Field(h.param, role="segment"),))
        out = PathExpr(left.head, left.parts + (seg,) + right.parts)
    elif isinstance(h, HeadParam) and h.param.kind is Kind.ABSOLUTE:
        return right
    elif isinstance(h, Deferred) and (p := _head_param(h)) is not None:
        # An AUTO parameter at the root of a deferred operation is moving
        # below the head, where it is a segment: re-apply the operations to
        # it as one, so (base / P(name).with_suffix(x)) cannot escape base.
        seg = PathExpr(REL, (Seg((Field(p, role="segment"),)),))
        return _join(left, right.bind({p.name: seg}))
    else:
        out = PathExpr(Deferred("join", left, PathExpr(h)), right.parts)
        out.params  # noqa: B018 - surface declaration conflicts at construction
        return out
    # Concatenation: merge the operands' cached parameter tables instead of
    # re-walking the tree (this also surfaces declaration conflicts now).
    merged = dict(left.params)
    for name, p in right.params.items():
        prev = merged.setdefault(name, p)
        if prev != p:
            raise ParamConflictError(
                f"Conflicting declarations for {name!r}: {prev!r} vs {p!r}"
            )
    if isinstance(h, HeadParam):
        prev = merged.setdefault(h.param.name, h.param)
        if prev != h.param:
            raise ParamConflictError(f"Conflicting declarations for {h.param.name!r}")
    out.__dict__["params"] = merged
    out.__dict__["param_names"] = frozenset(merged)
    return out


def _split_spec(spec: str) -> tuple[str | Param, ...]:
    if not has_marker(spec):
        return (spec,) if spec else ()
    out: list[str | Param] = []
    pos = 0
    for m in MARKER_RE.finditer(spec):
        if m.start() > pos:
            out.append(spec[pos : m.start()])
        out.append(lookup_marker(m.group(1)))
        pos = m.end()
    if pos < len(spec):
        out.append(spec[pos:])
    return tuple(out)


def _interp_pieces(interp: Interpolation) -> list[Piece]:
    v = interp.value
    conv = interp.conversion
    spec = _split_spec(interp.format_spec)
    if isinstance(v, Param):
        return [Field(v, conv, spec)]
    if isinstance(v, Text):
        if conv is None and not spec:
            return list(v.pieces)
        return [Field(v, conv, spec)]
    if isinstance(v, (PathExpr, Template)):
        raise TypeError(
            f"Cannot interpolate a path inside a segment ({interp.expression!r}); "
            "join paths with '/' instead"
        )
    if any(isinstance(s, Param) for s in spec):
        return [Field(Const(v), conv, spec)]
    s = format(_spec.convert(v, conv), "".join(spec))  # type: ignore[arg-type]
    if "/" in s or "\x00" in s:
        raise ValueError(
            f"Interpolation {interp.expression!r} formats to {s!r}, which contains a separator"
        )
    return [s]


def _from_template(t: Template) -> PathExpr:
    segments: list[list[str | Interpolation]] = [[]]
    anchor = ""
    for idx, item in enumerate(t):
        if isinstance(item, str):
            if idx == 0 and item.startswith("/"):
                anchor = (
                    "//"
                    if item.startswith("//") and not item.startswith("///")
                    else "/"
                )
            chunks = item.split("/")
            segments[-1].append(chunks[0])
            for c in chunks[1:]:
                segments.append([c])
        else:
            segments[-1].append(item)
    expr = PathExpr(Root(anchor)) if anchor else PathExpr(REL)
    emitted = bool(anchor)
    for seg in segments:
        items = [x for x in seg if x != ""]
        if not items:
            continue
        if len(items) == 1 and isinstance(items[0], Interpolation):
            interp = items[0]
            if (
                interp.conversion is None
                and not interp.format_spec
                and isinstance(
                    interp.value, (Param, PathExpr, Template, Text, str, os.PathLike)
                )
            ):
                expr = _join(expr, _coerce(interp.value, at_head=not emitted))
                emitted = True
                continue
        pieces: list[Piece] = []
        for x in items:
            if isinstance(x, str):
                pieces.append(x)
            else:
                pieces.extend(_interp_pieces(x))
        norm = _norm(pieces)
        if not norm or norm == (".",):
            continue
        expr = _join(expr, PathExpr(REL, (Seg(norm),)))
        emitted = True
    return expr


def P(x: Any = ".") -> PathExpr:
    """Make a path expression from a str, PathLike, Param, t-string, Text or PathExpr."""
    return _coerce(x, at_head=True)


def T(template: Template) -> PathExpr:
    """Make a path expression from a t-string."""
    if not isinstance(template, Template):
        raise TypeError("T() takes a t-string, e.g. T(t'data/{name}.csv')")
    return _from_template(template)


# ---------------------------------------------------------------------------
# Value validation (shared by the interpreter, bind and the compiler)
# ---------------------------------------------------------------------------


def _fspath_str(name: str, v: Any) -> str:
    if isinstance(v, str):
        s = v
    elif isinstance(v, os.PathLike):
        s = os.fspath(v)
        if not isinstance(s, str):
            raise InvalidBindingError(f"{name}={v!r}: bytes paths are not supported")
    else:
        raise InvalidBindingError(
            f"{name}={v!r}: expected str or os.PathLike (format other values inside a t-string field)"
        )
    if "\x00" in s:
        raise InvalidBindingError(f"{name}={s!r}: contains NUL")
    return s


def _segment_text(name: str, v: Any) -> str:
    """A segment value's text: a str or path as is, anything else formatted the
    way an f-string formats ``{v}``."""
    if isinstance(v, (str, os.PathLike)):
        return _fspath_str(name, v)
    if isinstance(v, (bytes, bytearray)):
        raise InvalidBindingError(
            f"{name}={v!r}: decode bytes before using them in a path"
        )
    try:
        s = format(v, "")
    except (TypeError, ValueError) as e:
        raise InvalidBindingError(f"{name}={v!r} cannot be formatted: {e}") from None
    if "\x00" in s:
        raise InvalidBindingError(f"{name}={s!r}: contains NUL")
    return s


def seg_value(p: Param, v: Any) -> str:
    p.check(v)
    s = _segment_text(p.name, v)
    if "/" in s:
        raise InvalidBindingError(
            f"{p.name}={s!r} is not a single path segment; declare {p.name!r} with "
            f"SubPath({p.name!r}) to bind multi-segment paths"
        )
    if s in ("", ".", ".."):
        raise InvalidBindingError(f"{p.name}={s!r} is not a valid path segment")
    return s


def canonical(s: str) -> str:
    """str(PurePosixPath(s)), skipping the parse when s is already canonical."""
    if s == "." or s == "/" or s == "//":
        return s
    if (
        s
        and s[-1] != "/"
        and "//" not in s[1:]
        and "/./" not in s
        and not s.startswith("./")
        and not s.endswith("/.")
    ):
        return s
    return str(PurePosixPath(s))


def head_value(p: Param, v: Any) -> str:
    p.check(v)
    s = canonical(_fspath_str(p.name, v))
    if p.kind is Kind.ABSOLUTE and not s.startswith("/"):
        raise InvalidBindingError(f"{p.name}={s!r} must be an absolute path")
    return s


def splice_value(p: Param, v: Any) -> list[str]:
    p.check(v)
    s = canonical(_fspath_str(p.name, v))
    if s.startswith("/"):
        raise InvalidBindingError(f"{p.name}={s!r} must be a relative path")
    if s == ".":
        return []
    parts = s.split("/")
    if ".." in parts:
        raise InvalidBindingError(f"{p.name}={s!r} must not contain '..'")
    return parts


def format_field(f: Field, v: Any, spec: str) -> str:
    try:
        s = format(_spec.convert(v, f.conversion), spec)
    except (TypeError, ValueError) as e:
        raise InvalidBindingError(
            f"Cannot format {v!r} with {f.pattern}: {e}"
        ) from None
    if "/" in s or "\x00" in s:
        raise InvalidBindingError(
            f"{f.pattern} formats {v!r} to {s!r}, which contains a separator"
        )
    dot_free, non_empty = f.facts
    if (dot_free and "." in s) or (non_empty and not s):
        raise InvalidBindingError(
            f"{f.pattern} formats {v!r} to {s!r}, breaking its format type"
        )
    return s


def check_seg(s: str) -> str:
    if s in ("", ".", ".."):
        raise InvalidBindingError(
            f"Segment renders to {s!r}, which is not a valid path segment"
        )
    return s


# ---------------------------------------------------------------------------
# Interpreter (the reference semantics)
# ---------------------------------------------------------------------------


def _make_env(mapping: Mapping[Any, Any] | None, kw: dict[str, Any]) -> dict[str, Any]:
    env: dict[str, Any] = {}
    if mapping:
        for k, v in mapping.items():
            env[k.name if isinstance(k, Param) else k] = v
    env.update(kw)
    return env


def _is_symbolic(v: Any) -> bool:
    return isinstance(v, (PathExpr, Text, Param, Template))


def _check_missing(names: frozenset[str], env: Mapping[str, Any]) -> None:
    missing = names - env.keys()
    if missing:
        raise MissingBindingError(set(missing))


def _combine(base: str, segs: list[str]) -> str:
    if not segs:
        return base or "."
    tail = "/".join(segs)
    if not base or base == ".":
        return tail
    if base.endswith("/"):
        return base + tail
    return base + "/" + tail


def _render_spec(spec: tuple[str | Param, ...], env: Mapping[str, Any]) -> str:
    return "".join(s if isinstance(s, str) else format(env[s.name], "") for s in spec)


def _render_field(f: Field, env: Mapping[str, Any]) -> str:
    src = f.source
    if isinstance(src, Param):
        v = env[src.name]
        if f.role == "segment":
            return seg_value(src, v)
        src.check(v)
    elif isinstance(src, Text):
        v = _render_pieces(src.pieces, env)
    elif isinstance(src, TextOp):
        v = _render_textop(src, env)
    else:
        v = src.value
    spec = f.static_spec
    if spec is None:
        spec = _render_spec(f.spec, env)
    return format_field(f, v, spec)


def _render_pieces(pieces: tuple[Piece, ...], env: Mapping[str, Any]) -> str:
    return "".join(p if isinstance(p, str) else _render_field(p, env) for p in pieces)


def _render_textop(t: TextOp, env: Mapping[str, Any]) -> str:
    return getattr(PurePosixPath(_render_expr(t.base, env)), t.op)


def _render_deferred(d: Deferred, env: Mapping[str, Any]) -> str:
    p = PurePosixPath(_render_expr(d.base, env))
    try:
        if d.op == "parent":
            r = p.parent
        elif d.op == "join":
            r = p / _render_expr(d.arg, env)
        elif d.op == "with_suffix":
            r = p.with_suffix(d.arg)
        elif d.op == "with_name":
            r = p.with_name(_render_pieces(d.arg.pieces, env))
        elif d.op == "with_stem":
            r = p.with_stem(_render_pieces(d.arg.pieces, env))
        elif d.op == "relative_to":
            r = p.relative_to(_render_expr(d.arg, env))
        else:  # pragma: no cover
            raise AssertionError(d.op)
    except InvalidBindingError:
        raise  # a binding inside the operation is invalid, not the operation
    except ValueError as e:
        raise PathOperationError(str(e)) from None
    return str(r)


def _render_expr(e: PathExpr, env: Mapping[str, Any]) -> str:
    h = e.head
    if isinstance(h, _Rel):
        base = ""
    elif isinstance(h, Root):
        base = h.anchor
    elif isinstance(h, HeadParam):
        base = head_value(h.param, env[h.param.name])
    else:
        base = _render_deferred(h, env)
    segs: list[str] = []
    for part in e.parts:
        if isinstance(part, Seg):
            lit = part.literal
            if lit is not None:
                segs.append(lit)
            else:
                s = _render_pieces(part.pieces, env)
                segs.append(check_seg(s) if part.needs_check else s)
        else:
            segs.extend(splice_value(part.param, env[part.param.name]))
    return _combine(base, segs)


# ---------------------------------------------------------------------------
# Binding (partial evaluation by rebuilding through the smart constructors)
# ---------------------------------------------------------------------------


def _bind_spec(
    spec: tuple[str | Param, ...], env: Mapping[str, Any]
) -> tuple[str | Param, ...]:
    out: list[str | Param] = []
    for s in spec:
        if isinstance(s, Param) and s.name in env:
            v = env[s.name]
            out.append(v if isinstance(v, Param) else format(v, ""))
        else:
            out.append(s)
    merged: list[str | Param] = []
    for s in out:
        if isinstance(s, str) and merged and isinstance(merged[-1], str):
            merged[-1] = merged[-1] + s
        elif s != "":
            merged.append(s)
    return tuple(merged)


def _bind_field(f: Field, env: Mapping[str, Any]) -> list[Piece]:
    spec = _bind_spec(f.spec, env)
    static = all(isinstance(s, str) for s in spec)
    spec_str = "".join(spec) if static else None  # type: ignore[arg-type]
    src = f.source

    def finish(value_source: Any, concrete: bool, value: Any = None) -> list[Piece]:
        # Validate against the original field's guarantees so that bind and
        # render accept exactly the same values.
        if concrete and spec_str is not None:
            return [format_field(f, value, spec_str)]
        return [Field(value_source, f.conversion, spec, f.role)]

    if isinstance(src, Param):
        if src.name not in env:
            return [Field(src, f.conversion, spec, f.role)]
        v = env[src.name]
        if f.role == "segment":
            if isinstance(v, Param):
                if v.kind not in (Kind.AUTO, Kind.SEGMENT):
                    raise InvalidBindingError(
                        f"Cannot rename segment {src.name!r} to {v!r}"
                    )
                return [Field(v, role="segment")]
            if isinstance(v, PathExpr):
                if (
                    isinstance(v.head, _Rel)
                    and len(v.parts) == 1
                    and isinstance(v.parts[0], Seg)
                ):
                    return list(v.parts[0].pieces)
                raise InvalidBindingError(
                    f"{src.name!r} must be bound to a single segment, got {v!r}"
                )
            if isinstance(v, Text):
                return list(_text_as_segment(v).pieces)
            return [seg_value(src, v)]
        if isinstance(v, Param):
            return [Field(v, f.conversion, spec)]
        if isinstance(v, Text):
            if f.conversion is None and not spec:
                return list(v.pieces)
            return finish(v, v.literal is not None, v.literal)
        if isinstance(v, (PathExpr, Template)):
            raise InvalidBindingError(f"Cannot bind field {f.pattern} to a path")
        src.check(v)
        return finish(Const(v), True, v)
    if isinstance(src, Text):
        t = Text(_bind_pieces(src.pieces, env))
        if f.conversion is None and not spec:
            return list(t.pieces)
        return finish(t, t.literal is not None, t.literal)
    if isinstance(src, TextOp):
        t = getattr(_bind_expr(src.base, env), src.op)
        if f.conversion is None and not spec:
            return list(t.pieces)
        return finish(t, t.literal is not None, t.literal)
    return finish(src, True, src.value)


def _bind_pieces(
    pieces: tuple[Piece, ...], env: Mapping[str, Any]
) -> tuple[Piece, ...]:
    out: list[Piece] = []
    for p in pieces:
        if isinstance(p, str) or not (p.param_names & env.keys()):
            out.append(p)
        else:
            out.extend(_bind_field(p, env))
    return _norm(out)


def _bind_head(h: Head, env: Mapping[str, Any]) -> PathExpr:
    if isinstance(h, _Rel) or isinstance(h, Root):
        return PathExpr(h)
    if isinstance(h, HeadParam):
        p = h.param
        if p.name not in env:
            return PathExpr(h)
        v = env[p.name]
        if isinstance(v, Param):
            return _param_expr(v, at_head=True)
        if isinstance(v, Template):
            v = _from_template(v)
        if isinstance(v, PathExpr):
            if p.kind is Kind.ABSOLUTE and v.is_absolute() is False:
                raise InvalidBindingError(
                    f"{p.name!r} must be bound to an absolute path"
                )
            return v
        if isinstance(v, Text):
            raise InvalidBindingError(f"Cannot bind path {p.name!r} to text")
        return _literal_expr(head_value(p, v))
    base = _bind_expr(h.base, env)
    arg: Any = h.arg
    if isinstance(arg, PathExpr):
        arg = _bind_expr(arg, env)
    elif isinstance(arg, Text):
        arg = Text(_bind_pieces(arg.pieces, env))
    if h.op == "parent":
        return base.parent
    if h.op == "join":
        return _join(base, arg)
    if h.op == "with_suffix":
        return base.with_suffix(arg)
    if h.op == "with_name":
        return base.with_name(arg)
    if h.op == "with_stem":
        return base.with_stem(arg)
    if h.op == "relative_to":
        return base.relative_to(arg)
    raise AssertionError(h.op)  # pragma: no cover


def _bind_part(part: Part, env: Mapping[str, Any]) -> PathExpr:
    if isinstance(part, Seg):
        if not (part.param_names & env.keys()):
            return PathExpr(REL, (part,))
        pieces = _bind_pieces(part.pieces, env)
        if len(pieces) == 1 and isinstance(pieces[0], str):
            check_seg(pieces[0])
            if "/" in pieces[0]:  # a Text bound into a segment
                raise InvalidBindingError(
                    f"Segment renders to {pieces[0]!r}, which contains a separator"
                )
        elif not pieces:
            check_seg("")
        return PathExpr(REL, (Seg(pieces),))
    p = part.param
    if p.name not in env:
        return PathExpr(REL, (part,))
    v = env[p.name]
    if isinstance(v, Param):
        return PathExpr(REL, (Splice(v),))
    if isinstance(v, Template):
        v = _from_template(v)
    if isinstance(v, PathExpr):
        if not isinstance(v.head, _Rel):
            raise InvalidBindingError(
                f"{p.name!r} must be bound to a relative path, got {v!r}"
            )
        return v
    return PathExpr(REL, tuple(Seg((s,)) for s in splice_value(p, v)))


def _bind_expr(e: PathExpr, env: Mapping[str, Any]) -> PathExpr:
    if not (e.param_names & env.keys()):
        return e
    out = _bind_head(e.head, env)
    for part in e.parts:
        out = _join(out, _bind_part(part, env))
    return out
