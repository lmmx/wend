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
from types import MappingProxyType
from typing import (
    TYPE_CHECKING,
    Any,
    ClassVar,
    Generic,
    Literal,
    NamedTuple,
    Never,
    cast,
    overload,
)

from . import _spec
from ._kinds import (
    X1,
    X2,
    X3,
    X4,
    X5,
    X6,
    C,
    Checked,
    Confirmed,
    IsFile,
    JoinBelowFile,
    K,
    NotFile,
    Q,
    Unspecified,
)
from ._params import MARKER_RE, NO_DEFAULT, Kind, Param, has_marker, lookup_marker
from .errors import (
    InvalidBindingError,
    MissingBindingError,
    NotStaticError,
    ParamConflictError,
    PathOperationError,
    show,
)


if TYPE_CHECKING:
    from ._union import PathUnion
    from .conditions import Condition, Conditions, Declarations, FileCondition, Under
    from .query import Query


# What ``format`` raises for a value it cannot format: TypeError (a type the
# spec does not take), ValueError (an invalid spec, or an int beyond the digit
# limit) and OverflowError, an ArithmeticError (a ``c`` field out of range, an
# int too large for a float presentation type). Each makes the binding invalid.
FORMAT_ERRORS = (TypeError, ValueError, ArithmeticError)


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

    def __post_init__(self) -> None:
        # Literal text is never NUL (§3), however the Text was built: its
        # pieces reach paths unchecked (as a stem, or spliced into a t-string).
        for p in self.pieces:
            if isinstance(p, str) and "\x00" in p:
                if has_marker(p):
                    raise _fstring_error()
                _check_literal(p)

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

    def render(self, mapping: Any = None, /, **kw: Any) -> str:
        env = _make_env(mapping, kw)
        if any(_is_symbolic(v) for v in env.values()):
            return self.bind(env).render()
        missing = self.param_names - env.keys()
        if missing:
            env = _with_defaults(self._params(), env, missing)
        return _render_pieces(self.pieces, env)

    def bind(self, mapping: Any = None, /, **kw: Any) -> Text:
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
        _check_literal(x)
        return Text(_norm([x]))
    if isinstance(x, Param):
        return Text((Field(x),))
    if isinstance(x, Template):
        pieces: list[Piece] = []
        for item in x:
            if isinstance(item, str):
                _check_literal(item)
                pieces.append(item)
            else:
                pieces.extend(_interp_pieces(item))
        return Text(_norm(pieces))
    raise TypeError(f"Cannot use {type(x).__name__} as text")


def _text_as_segment(t: Text) -> Seg:
    for p in t.pieces:
        if isinstance(p, str) and "/" in p:
            raise PathOperationError(
                f"Invalid name {t.pattern!r}: contains a separator"
            )
        if isinstance(p, str):
            _check_literal(p)
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

    @cached_property
    def suffix_split(self) -> tuple[tuple[Piece, ...], tuple[Piece, ...]] | None:
        """(stem, suffix) pieces when the split is statically decidable."""
        if self.literal is not None:
            p = PurePosixPath(self.literal)
            suffix = p.suffix
            return _norm([p.stem]), _norm([suffix])
        pieces = self.pieces
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


class Derivation(NamedTuple):
    """How an expression was built: the public operation ``op`` applied to
    ``args``, as they were passed (§9).

    Recorded by the operations themselves and left out of equality and hashing,
    so expressions still compare by the paths they denote.
    """

    op: str
    args: tuple[Any, ...]

    def __repr__(self) -> str:
        shown = ", ".join(
            a.pattern if isinstance(a, PathExpr) else repr(a) for a in self.args
        )
        return f"Derivation({self.op}: {shown})"


_NAME_OPS = frozenset({"with_name", "with_suffix", "with_stem"})


# ---------------------------------------------------------------------------
# PathExpr
# ---------------------------------------------------------------------------


@dataclass(frozen=True, repr=False)
class PathExpr(_Cached, Generic[C, K, Q]):  # noqa: UP046 (variance is declared, not inferred)
    """A symbolic path. Build with `P`, `T`, or ``Param / ...``.

    For a type checker, ``C`` is what it requires, ``K`` whether it is
    declared a File, and ``Q`` what it ensures (`wend._kinds`)."""

    head: Head
    parts: tuple[Part, ...] = ()
    # How the expression was built (§9). Not a dataclass field: it takes no
    # part in construction, equality or hashing; operations set it per instance.
    derivation: ClassVar[Derivation | None] = None
    # Declared conditions (§10), metadata like the derivation.
    conditions: ClassVar[Conditions | None] = None
    # Tags (§13): what the path is for or where it came from, also metadata.
    tags: ClassVar[Mapping[str, Any]] = MappingProxyType({})

    def __getstate__(self) -> dict[str, Any]:
        state = super().__getstate__()
        if self.derivation is not None:
            state["derivation"] = self.derivation
        if self.conditions is not None:
            state["conditions"] = self.conditions
        if self.tags:
            state["tags"] = dict(self.tags)
        return state

    def __setstate__(self, state: dict[str, Any]) -> None:
        tags = state.pop("tags", None)
        super().__setstate__(state)
        if tags:
            self.__dict__["tags"] = MappingProxyType(tags)

    # -- construction -------------------------------------------------------

    # A receiver of unknown kind must take the first overload, or a join
    # onto an untyped expression would read as one below a File: NotFile is
    # disjoint from IsFile, and an unknown K matches it first.
    @overload
    def __truediv__(
        self: PathExpr[Any, NotFile, Any], other: PathUnion
    ) -> PathUnion: ...
    @overload
    def __truediv__(
        self: PathExpr[Any, NotFile, Any],
        other: str
        | os.PathLike[str]
        | Param
        | PathExpr[Any, Any, Any]
        | Text
        | Template,
    ) -> PathExpr: ...
    # Not @deprecated: a receiver of unknown kind matches this overload too,
    # and ty then warned at every join onto one (103 times in tests/). The
    # result, JoinBelowFile, is not a path, which is enough to reject a use.
    @overload
    def __truediv__(self: PathExpr[Any, IsFile, Any], other: Any) -> JoinBelowFile: ...
    @overload
    def __truediv__(self, other: PathUnion) -> PathUnion: ...
    @overload
    def __truediv__(
        self, other: str | os.PathLike[str] | Param | PathExpr | Text | Template
    ) -> PathExpr: ...
    def __truediv__(self, other: Any) -> Any:
        if _is_alternation(other):
            from ._union import union

            return union((self,)) / other
        if self.conditions is not None:
            from .conditions import declares_file

            if declares_file(self):
                raise PathOperationError(
                    f"{self.pattern!r} is declared a File: nothing can be"
                    " joined below it"
                )
        # §2: an operand joined onto the empty path is still at the head.
        empty = isinstance(self.head, _Rel) and not self.parts
        return _derived(
            _join(self, _coerce(other, at_head=empty)), "join", (self, other)
        )

    def __rtruediv__(self, other: Any) -> PathExpr:
        left = _coerce(other, at_head=True)
        return _derived(_join(left, self), "join", (left, self))

    def joinpath(self, *others: Any) -> PathExpr:
        out = self
        for o in others:
            out = out / o
        return out

    # -- unions and queries (§11) -------------------------------------------

    def __or__(self, other: Any) -> PathUnion:
        """The union of this path and ``other``: ``a | b`` (§11)."""
        from ._union import union

        return union((self, other))

    def __ror__(self, other: Any) -> PathUnion:
        from ._union import union

        return union((other, self))

    def __sub__(self, other: Any) -> Query:
        """A query for the paths this one finds that ``other`` does not match."""
        from .query import Query

        return Query(self) - other

    def __and__(self, other: Any) -> Query:
        """A query for the paths this one finds that ``other`` also matches."""
        from .query import Query

        return Query(self) & other

    def where(self, *predicates: Any) -> Query:
        """A query for the paths this one finds for which every predicate holds."""
        from .query import Query

        return Query(self).where(*predicates)

    # -- connectivity (§9) ----------------------------------------------------

    def child(self, *parts: Any) -> PathExpr:
        """``self / part / ...``, remembering ``self`` as the base (§9)."""
        return self.joinpath(*parts)

    def under(self, base: Any) -> PathExpr:
        """``base / self``: place a relative fragment under ``base``."""
        b = _coerce(base, at_head=True)
        return b / self

    @property
    def base(self) -> PathExpr | None:
        """The path this one was joined onto, or None if it was not built by a
        join. Bases chain: ``(root / "a" / "b").base.base`` is ``root``."""
        d = self.derivation
        return d.args[0] if d is not None and d.op == "join" else None

    @property
    def base_rel(self) -> PathExpr | None:
        """What was joined onto `base`, as an expression in that position."""
        d = self.derivation
        if d is None or d.op != "join":
            return None
        b = d.args[0]
        return _coerce(d.args[1], at_head=isinstance(b.head, _Rel) and not b.parts)

    def sibling(self, name: Any) -> PathExpr:
        """``self.parent / name``, remembering that it is defined by ``self``:
        rebasing ``self`` elsewhere moves the sibling with it (§9)."""
        return _derived(self.parent / name, "sibling", (self, name))

    def cousin(self, path: Any, *names: Any) -> PathExpr:
        """A path reached from this one's directory: ``path`` is relative to
        ``self.parent``, its leading (or any) ``..`` steps up structurally, and
        ``names`` are joined after it. ``x.cousin("../out", "y.csv")`` is
        ``x.parent.parent / "out" / "y.csv"``, defined by ``x`` (§9)."""
        rel = PurePosixPath(os.fspath(path))
        if rel.is_absolute():
            raise PathOperationError(
                f"cousin() takes a relative path, not {str(rel)!r}"
            )
        out = self.parent
        for part in rel.parts:
            out = out.parent if part == ".." else out / part
        out = out.joinpath(*names)
        return _derived(out, "cousin", (self, path, *names))

    def derived_from(self, other: Any) -> bool:
        """Whether ``other`` is among the expressions this one was built from."""
        o = _coerce(other, at_head=True)
        return _rederive(self, o, o, {}) is not None

    # -- conditions (§10) -----------------------------------------------------

    @overload
    def requires(self) -> PathExpr[C, K, Q]: ...
    @overload
    def requires(
        self, file: FileCondition, /
    ) -> PathExpr[C | Literal["file"], IsFile, Q]: ...
    @overload
    def requires(
        self, file: FileCondition, c1: Condition[X1, Any], /
    ) -> PathExpr[C | Literal["file"] | X1, IsFile, Q]: ...
    @overload
    def requires(
        self, file: FileCondition, c1: Condition[X1, Any], c2: Condition[X2, Any], /
    ) -> PathExpr[C | Literal["file"] | X1 | X2, IsFile, Q]: ...
    @overload
    def requires(
        self,
        file: FileCondition,
        c1: Condition[X1, Any],
        c2: Condition[X2, Any],
        c3: Condition[X3, Any],
        /,
    ) -> PathExpr[C | Literal["file"] | X1 | X2 | X3, IsFile, Q]: ...
    @overload
    def requires(
        self,
        file: FileCondition,
        c1: Condition[X1, Any],
        c2: Condition[X2, Any],
        c3: Condition[X3, Any],
        c4: Condition[X4, Any],
        /,
    ) -> PathExpr[C | Literal["file"] | X1 | X2 | X3 | X4, IsFile, Q]: ...
    @overload
    def requires(
        self,
        file: FileCondition,
        c1: Condition[X1, Any],
        c2: Condition[X2, Any],
        c3: Condition[X3, Any],
        c4: Condition[X4, Any],
        c5: Condition[X5, Any],
        /,
    ) -> PathExpr[C | Literal["file"] | X1 | X2 | X3 | X4 | X5, IsFile, Q]: ...
    @overload
    def requires(self, c1: Condition[X1, Any], /) -> PathExpr[C | X1, K, Q]: ...
    @overload
    def requires(
        self, c1: Condition[X1, Any], c2: Condition[X2, Any], /
    ) -> PathExpr[C | X1 | X2, K, Q]: ...
    @overload
    def requires(
        self, c1: Condition[X1, Any], c2: Condition[X2, Any], c3: Condition[X3, Any], /
    ) -> PathExpr[C | X1 | X2 | X3, K, Q]: ...
    @overload
    def requires(
        self,
        c1: Condition[X1, Any],
        c2: Condition[X2, Any],
        c3: Condition[X3, Any],
        c4: Condition[X4, Any],
        /,
    ) -> PathExpr[C | X1 | X2 | X3 | X4, K, Q]: ...
    @overload
    def requires(
        self,
        c1: Condition[X1, Any],
        c2: Condition[X2, Any],
        c3: Condition[X3, Any],
        c4: Condition[X4, Any],
        c5: Condition[X5, Any],
        /,
    ) -> PathExpr[C | X1 | X2 | X3 | X4 | X5, K, Q]: ...
    @overload
    def requires(
        self,
        c1: Condition[X1, Any],
        c2: Condition[X2, Any],
        c3: Condition[X3, Any],
        c4: Condition[X4, Any],
        c5: Condition[X5, Any],
        c6: Condition[X6, Any],
        /,
    ) -> PathExpr[C | X1 | X2 | X3 | X4 | X5 | X6, K, Q]: ...
    @overload
    def requires(self, *conditions: Condition[Any, Any]) -> PathExpr[C, K, Q]: ...
    def requires(self, *conditions: Any) -> PathExpr[Any, Any, Any]:
        """This path, declaring conditions that must hold before it is used
        (checked by `check`): ``e.requires(File, Exists, Readable)``. See
        `wend.conditions`. The path, its equality and its derivation are
        unchanged."""
        from .conditions import declare

        return declare(self, conditions, ())

    @overload
    def ensures(self) -> PathExpr[C, K, Q]: ...
    @overload
    def ensures(
        self, file: FileCondition, /
    ) -> PathExpr[C, IsFile, Q | Literal["file"]]: ...
    @overload
    def ensures(
        self, file: FileCondition, c1: Condition[Any, X1], /
    ) -> PathExpr[C, IsFile, Q | Literal["file"] | X1]: ...
    @overload
    def ensures(
        self, file: FileCondition, c1: Condition[Any, X1], c2: Condition[Any, X2], /
    ) -> PathExpr[C, IsFile, Q | Literal["file"] | X1 | X2]: ...
    @overload
    def ensures(
        self,
        file: FileCondition,
        c1: Condition[Any, X1],
        c2: Condition[Any, X2],
        c3: Condition[Any, X3],
        /,
    ) -> PathExpr[C, IsFile, Q | Literal["file"] | X1 | X2 | X3]: ...
    @overload
    def ensures(
        self,
        file: FileCondition,
        c1: Condition[Any, X1],
        c2: Condition[Any, X2],
        c3: Condition[Any, X3],
        c4: Condition[Any, X4],
        /,
    ) -> PathExpr[C, IsFile, Q | Literal["file"] | X1 | X2 | X3 | X4]: ...
    @overload
    def ensures(
        self,
        file: FileCondition,
        c1: Condition[Any, X1],
        c2: Condition[Any, X2],
        c3: Condition[Any, X3],
        c4: Condition[Any, X4],
        c5: Condition[Any, X5],
        /,
    ) -> PathExpr[C, IsFile, Q | Literal["file"] | X1 | X2 | X3 | X4 | X5]: ...
    @overload
    def ensures(self, c1: Condition[Any, X1], /) -> PathExpr[C, K, Q | X1]: ...
    @overload
    def ensures(
        self, c1: Condition[Any, X1], c2: Condition[Any, X2], /
    ) -> PathExpr[C, K, Q | X1 | X2]: ...
    @overload
    def ensures(
        self, c1: Condition[Any, X1], c2: Condition[Any, X2], c3: Condition[Any, X3], /
    ) -> PathExpr[C, K, Q | X1 | X2 | X3]: ...
    @overload
    def ensures(
        self,
        c1: Condition[Any, X1],
        c2: Condition[Any, X2],
        c3: Condition[Any, X3],
        c4: Condition[Any, X4],
        /,
    ) -> PathExpr[C, K, Q | X1 | X2 | X3 | X4]: ...
    @overload
    def ensures(
        self,
        c1: Condition[Any, X1],
        c2: Condition[Any, X2],
        c3: Condition[Any, X3],
        c4: Condition[Any, X4],
        c5: Condition[Any, X5],
        /,
    ) -> PathExpr[C, K, Q | X1 | X2 | X3 | X4 | X5]: ...
    @overload
    def ensures(
        self,
        c1: Condition[Any, X1],
        c2: Condition[Any, X2],
        c3: Condition[Any, X3],
        c4: Condition[Any, X4],
        c5: Condition[Any, X5],
        c6: Condition[Any, X6],
        /,
    ) -> PathExpr[C, K, Q | X1 | X2 | X3 | X4 | X5 | X6]: ...
    @overload
    def ensures(self, *conditions: Condition[Any, Any]) -> PathExpr[C, K, Q]: ...
    def ensures(self, *conditions: Any) -> PathExpr[Any, Any, Any]:
        """This path, declaring conditions that must hold after it has been
        produced (checked by `confirm`): ``e.ensures(File, Exists)``."""
        from .conditions import declare

        return declare(self, (), conditions)

    @property
    def declares(self) -> Declarations:
        """What this expression declares, as atoms per phase and the bases it
        is declared `Under` (docs/SEMANTICS.md §10.1): an obligation the
        runtime checks, not a fact about the filesystem."""
        from .conditions import declarations

        return declarations(self.conditions)

    def tag(self, **tags: Any) -> PathExpr[C, K, Q]:
        """This path, tagged with metadata (``source="upload"``): what it is
        for or where it came from. Tags take no part in equality; `bind` and
        `rebase` keep them, other operations do not, and `wend.lineage`
        collects them through a path's derivation (§13)."""
        out = _carry(self, self)
        out.__dict__["tags"] = MappingProxyType({**self.tags, **tags})
        return cast("PathExpr[C, K, Q]", out)  # _carry keeps the declarations

    def check(self, mapping: Any = None, /, *, fs: Any = None, **kw: Any) -> Path:
        """Render, check every precondition against the filesystem now, and
        return the path. Raises a `ConditionError` for the first that fails:
        `IndeterminateError` when the filesystem cannot say. ``fs`` is a
        `wend.fs` filesystem (the local disk by default). The path carries
        no evidence of the check; `checked` returns the evidence."""
        from .conditions import _check_fs_option, realise

        env = _make_env(mapping, kw)
        _check_fs_option("check", self, env, fs)
        return realise(self, env, after=False, fs=fs)

    def confirm(self, mapping: Any = None, /, *, fs: Any = None, **kw: Any) -> Path:
        """Render, check every postcondition against the filesystem now, and
        return the path. Raises a `ConditionError` for the first that fails,
        as `check` does; `confirmed` returns the evidence."""
        from .conditions import _check_fs_option, realise

        env = _make_env(mapping, kw)
        _check_fs_option("confirm", self, env, fs)
        return realise(self, env, after=True, fs=fs)

    def checked(
        self, mapping: Any = None, /, *, fs: Any = None, **kw: Any
    ) -> Checked[C, K]:
        """`check`, returning the evidence instead of the path: a `Checked`
        whose type carries what this expression requires, which is what was
        checked, and nothing it ensures. The evidence is about this path at
        this moment; ``.path`` gives the path, and a path derived from it
        carries none."""
        return Checked(self.check(mapping, fs=fs, **kw), self.declares.requires)

    def confirmed(
        self, mapping: Any = None, /, *, fs: Any = None, **kw: Any
    ) -> Confirmed[Q, K]:
        """`confirm`, returning the evidence: a `Confirmed` whose type
        carries what this expression ensures, and nothing it requires."""
        return Confirmed(self.confirm(mapping, fs=fs, **kw), self.declares.ensures)

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

    @cached_property
    def _direct(self) -> bool:
        """No deferred head and no field whose text derives from a path, so
        binding a parameter removes that parameter and no other."""
        if isinstance(self.head, Deferred):
            return False
        for part in self.parts:
            if isinstance(part, Seg):
                for p in part.pieces:
                    if isinstance(p, Field) and not isinstance(
                        p.source, (Param, Const)
                    ):
                        return False
        return True

    def required_params(self) -> set[str]:
        """Names of the parameters rendering needs a binding for: every free
        parameter without a default (§3.1)."""
        return {n for n, p in self.params.items() if p.default is NO_DEFAULT}

    @property
    def defaults(self) -> dict[str, Any]:
        """The defaults of the free parameters that declare one, by name.
        Rendering uses them for names it is not given; ``e.bind(e.defaults)``
        applies them explicitly (§3.1)."""
        return {
            n: p.default for n, p in self.params.items() if p.default is not NO_DEFAULT
        }

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
        c = self.conditions
        if c is None and not self.tags:
            return f"PathExpr({self.pattern!r})"
        extra = "".join(
            f", {label}=({', '.join(map(repr, cs))})"
            for label, cs in (
                (("requires", c.requires), ("ensures", c.ensures)) if c else ()
            )
            if cs
        )
        if self.tags:
            extra += f", tags={dict(self.tags)!r}"
        return f"PathExpr({self.pattern!r}{extra})"

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
        return _derived(self._parent(), "parent", (self,))

    def _parent(self) -> PathExpr:
        if self._last_seg() is not None:
            return _new(self.head, self.parts[:-1])
        if self._empty_static():
            return self
        h = self.head
        if not self.parts and isinstance(h, Deferred) and h.op in _NAME_OPS:
            # with_name/with_suffix/with_stem replace only the last segment, so
            # the parent is the base's (§2 counts; the replaced segment is
            # discarded as §6 permits).
            return h.base.parent
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
        return None if seg is None else seg.suffix_split

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
        return _derived(self._with_name(name), "with_name", (self, name))

    def _with_name(self, name: Any) -> PathExpr:
        text = _to_text(name)
        new = _text_as_segment(text)
        if self._last_seg() is not None:
            return PathExpr(self.head, self.parts[:-1] + (new,))
        if self._empty_static():
            raise PathOperationError(f"{self.pattern!r} has an empty name")
        return PathExpr(Deferred("with_name", self, text))

    def with_suffix(self, suffix: str) -> PathExpr:
        return _derived(self._with_suffix(suffix), "with_suffix", (self, suffix))

    def _with_suffix(self, suffix: str) -> PathExpr:
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
            return _new(self.head, self.parts[:-1] + (Seg(_norm([*stem, suffix])),))
        if self._empty_static():
            raise PathOperationError(f"{self.pattern!r} has an empty name")
        return PathExpr(Deferred("with_suffix", self, suffix))

    def with_stem(self, stem: Any) -> PathExpr:
        return _derived(self._with_stem(stem), "with_stem", (self, stem))

    def _with_stem(self, stem: Any) -> PathExpr:
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
        return _derived(self._relative_to(other), "relative_to", (self, other))

    def _relative_to(self, other: Any) -> PathExpr:
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

    def bind(self, mapping: Any = None, /, **kw: Any) -> PathExpr[C, K, Q]:
        """Substitute some parameters, folding whatever becomes static.

        Values may be concrete (str, PathLike, ints for fields...) or symbolic:
        another PathExpr (rebasing), a Text, or a Param (renaming). Bindings
        come from a mapping, an object's fields (see `wend.bindings`) and
        keywords. Defaults are not applied: a parameter left unbound stays
        free, with its default (§3.1).
        """
        env = _make_env(mapping, kw)
        if not (self.param_names & env.keys()):
            return self
        out = _derived(_bind_expr(self, env), "bind", (self, env))
        if self.conditions is not None:
            from .conditions import attach, moved

            out = attach(out, moved(self.conditions, lambda b: b.bind(env)))
        if self.tags:
            out.__dict__["tags"] = self.tags
        return cast("PathExpr[C, K, Q]", out)  # the declarations, moved

    # rebase moves a declared Under base that lies under the old base, so a
    # literal base's identity does not survive it; only "under some base" does.
    # It is kept, as Under[str], in each phase that declared some Under; the
    # other atoms of that phase are dropped (sound, not precise).
    # (Never, not Any, for "whatever this phase declares": Any would make the
    # overloads overlap, and the later ones unreachable.)
    @overload
    def rebase(
        self: PathExpr[Under[Any], Any, Under[Any]], *args: Any
    ) -> PathExpr[Under[str], K, Under[str]]: ...
    @overload
    def rebase(
        self: PathExpr[Under[Any], Any, Never], *args: Any
    ) -> PathExpr[Under[str], K, Never]: ...
    @overload
    def rebase(
        self: PathExpr[Never, Any, Under[Any]], *args: Any
    ) -> PathExpr[C, K, Under[str]]: ...
    @overload
    def rebase(self, *args: Any) -> PathExpr[C, K, Q]: ...
    def rebase(self, *args: Any) -> PathExpr[Any, Any, Any]:
        """Move this path to a new base (§9).

        ``rebase(new)`` replaces the `base` this path was joined onto.
        ``rebase(old, new)`` replaces ``old`` wherever this path was built from
        it (a base, a path it is a sibling or cousin of, any expression in its
        derivation), re-applying the operations that built it; if this path
        was not built from ``old``, ``old`` must be a structural prefix.
        """
        if len(args) == 1:
            d = self.derivation
            if d is None or d.op != "join":
                raise ValueError(
                    f"{self.pattern!r} was not built by joining onto a base;"
                    " use rebase(old, new)"
                )
            old, new = d.args[0], _coerce(args[0], at_head=True)
            out = new / d.args[1]
        elif len(args) == 2:
            old = _coerce(args[0], at_head=True)
            new = _coerce(args[1], at_head=True)
            out = self._rebased(old, new)
        else:
            raise TypeError(f"rebase() takes 1 or 2 arguments ({len(args)} given)")
        if self.conditions is not None:
            from .conditions import attach, moved

            def move(b: PathExpr) -> PathExpr:
                r = _rederive(b, old, new, {})
                return b if r is None else r

            out = attach(out, moved(self.conditions, move))
        if self.tags:
            out = _carry(out, out)
            out.__dict__["tags"] = self.tags
        return out

    def _rebased(self, old: PathExpr, new: PathExpr) -> PathExpr:
        redone = _rederive(self, old, new, {})
        if redone is not None:
            return redone
        rel = self.relative_to(old)
        if isinstance(rel.head, Deferred):
            raise NotStaticError(
                f"{self.pattern!r} was not built from {old.pattern!r}, and"
                " it is not a structural prefix"
            )
        return new / rel

    def render(self, mapping: Any = None, /, **kw: Any) -> str:
        """Resolve to a canonical path string (equal to ``str(self.resolve(...))``).

        Bindings come from a mapping (keyed by name or `Param`), an object's
        fields (see `wend.bindings`) and keywords, which take precedence. A
        parameter given no binding takes its default, if it declares one
        (§3.1); otherwise it is a `MissingBindingError`.
        """
        env = _make_env(mapping, kw)
        if any(_is_symbolic(v) for v in env.values()):
            return self.bind(env).render()
        missing = self.param_names - env.keys()
        if missing:
            env = _with_defaults(self.params.values(), env, missing)
        s = _render_expr(self, env)
        if self.conditions is not None:
            from .conditions import guard

            return guard(self, s, env)
        return s

    def resolve(
        self,
        mapping: Any = None,
        /,
        *,
        cls: type = Path,
        **kw: Any,
    ) -> Any:
        """Resolve to a concrete path (``pathlib.Path`` unless ``cls`` is given).

        A parameter named ``cls`` is bound in ``mapping``; a ``cls=`` keyword
        is then the result type. Without it in ``mapping``, a ``cls=`` keyword
        on such an expression is ambiguous and raises `TypeError`.
        """
        if cls is not Path and "cls" in self.param_names:
            from .errors import _check_option_keywords

            env = _make_env(mapping, kw)
            _check_option_keywords("resolve", self, env, [("cls", cls, Path)])
        return cls(self.render(mapping, **kw))

    # -- matching, discovery, compilation (implemented in sibling modules) --

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

    def glob(self, mapping: Any = None, /, **kw: Any) -> Any:
        """Discover existing paths matching this expression (see `wend.glob`
        for the options, including ``ambiguous=``)."""
        from ._fs import glob

        return glob(self, mapping, **kw)

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


def _derived(result: PathExpr, op: str, args: tuple[Any, ...]) -> PathExpr:
    """``result``, recording that the public operation ``op`` built it from
    ``args`` (§9).

    A fresh result takes the derivation in place. One that already existed (an
    argument returned unchanged, or a result with its own derivation) is
    copied, keeping its cached state, so no shared expression is changed.
    """
    d = _new_tuple(Derivation, (op, args))
    if result.derivation is None:
        for a in args:
            if a is result:
                break
        else:
            result.__dict__["derivation"] = d
            return result
    if result.conditions is not None or result.tags:
        # Conditions and tags belong to the expression they were declared on
        # (§10, §13), and cached state (the compiled renderer) depends on them.
        out = PathExpr(result.head, result.parts)
    else:
        out = object.__new__(PathExpr)
        out.__dict__.update(result.__dict__)
    out.__dict__["derivation"] = d
    return out


_new_tuple = tuple.__new__


def _carry(e: PathExpr, meta: PathExpr) -> PathExpr:
    """A fresh copy of ``e`` with ``meta``'s derivation, conditions and tags."""
    out = PathExpr(e.head, e.parts)
    d = out.__dict__
    for k in ("derivation", "conditions", "tags"):
        v = meta.__dict__.get(k)
        if v is not None:
            d[k] = v
    return out


def _apply(op: str, args: tuple[Any, ...]) -> PathExpr:
    first = args[0]
    if op == "join":
        return first / args[1]
    if op == "parent":
        return first.parent
    if op == "bind":
        return first.bind(args[1])
    return getattr(first, op)(*args[1:])


def _rederive(e: Any, old: PathExpr, new: PathExpr, memo: dict[int, Any]) -> Any | None:
    """``e`` rebuilt with ``new`` in place of ``old`` throughout its
    derivation, or None when ``old`` is not among the expressions it was built
    from. Each operation is re-applied, so positions and structural decisions
    are those a fresh build would make."""
    key = id(e)
    if key in memo:
        return memo[key]
    out: Any = None
    if isinstance(e, PathExpr):
        if e == old:
            out = new
        elif e.derivation is not None:
            args = e.derivation.args
            redone = [_rederive(a, old, new, memo) for a in args]
            if any(r is not None for r in redone):
                out = _apply(
                    e.derivation.op,
                    tuple(
                        a if r is None else r for a, r in zip(args, redone, strict=True)
                    ),
                )
    elif isinstance(e, dict):
        redone = {k: _rederive(v, old, new, memo) for k, v in e.items()}
        if any(r is not None for r in redone.values()):
            out = {k: e[k] if r is None else r for k, r in redone.items()}
    memo[key] = out
    return out


def _check_literal(s: str) -> None:
    """Literal text is never NUL: no path can contain it (§1)."""
    if "\x00" in s:
        raise PathOperationError(f"{s!r} contains NUL, which no path can")


def _fstring_error() -> TypeError:
    return TypeError(
        "A Param was formatted into a plain string (an f-string or str.format); "
        "use a t-string instead, e.g. T(t'chunk_{idx:04d}')"
    )


def _new(
    head: Head, parts: tuple[Part, ...], params: dict[str, Param] | None = None
) -> PathExpr:
    """A PathExpr built without the dataclass ``__init__`` (construction is
    hot), with its parameter table when the caller already knows it."""
    e = object.__new__(PathExpr)
    d = e.__dict__
    d["head"] = head
    d["parts"] = parts
    if params is not None:
        d["params"] = params
        d["param_names"] = frozenset(params)
    return e


# Parsed literal paths: the anchor and the segments. Segments are immutable
# and their cached properties are pure, so expressions can share them.
_LITERALS: dict[str, tuple[str, tuple[Seg, ...]]] = {}


def _literal_expr(s: str) -> PathExpr:
    hit = _LITERALS.get(s)
    if hit is None:
        if has_marker(s):
            raise _fstring_error()
        _check_literal(s)
        p = PurePosixPath(s)
        anchor = p.anchor
        names = p.parts[1:] if anchor else p.parts
        hit = (anchor, tuple(Seg((n,)) for n in names))
        if len(_LITERALS) >= _CACHE_SIZE:
            _LITERALS.clear()
        _LITERALS[s] = hit
    anchor, segs = hit
    return _new(Root(anchor) if anchor else REL, segs, {})


_CACHE_SIZE = 4096


def _param_expr(p: Param, *, at_head: bool) -> PathExpr:
    kind = p.kind
    if kind is Kind.AUTO:
        kind = Kind.PATH if at_head else Kind.SEGMENT
    if kind in (Kind.PATH, Kind.ABSOLUTE):
        return _new(HeadParam(p), (), {p.name: p})
    if kind is Kind.SEGMENT:
        return _new(REL, (Seg((Field(p, role="segment"),)),), {p.name: p})
    return _new(REL, (Splice(p),), {p.name: p})


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
        out = _new(left.head, left.parts + right.parts)
    elif isinstance(left.head, _Rel) and not left.parts:
        return right  # "." is the identity for joins
    elif isinstance(h, Root):
        return right
    elif isinstance(h, HeadParam) and h.param.kind is Kind.AUTO:
        seg = Seg((Field(h.param, role="segment"),))
        out = _new(left.head, left.parts + (seg,) + right.parts)
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
    rp = right.params
    if not rp and not isinstance(h, HeadParam):
        out.__dict__["params"] = merged
        out.__dict__["param_names"] = left.param_names
        return out
    for name, p in rp.items():
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


# Set by ._union when it is imported (as wend's __init__ does): the types that
# offer alternatives, and the test for a t-string holding them (§11).
_ALTERNATIVES: tuple[type, ...] = ()
_has_alternatives: Any = None


def _is_alternation(x: Any) -> bool:
    """A union, or a t-string offering alternatives (§11)."""
    if isinstance(x, (str, PathExpr, Param)):
        return False
    if isinstance(x, Template):
        return _has_alternatives is not None and _has_alternatives(x)
    return isinstance(x, _ALTERNATIVES)


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
    if isinstance(v, _ALTERNATIVES):
        raise TypeError(
            f"{interp.expression!r} offers alternatives: build the union with"
            " U(t'...') or '|', not T() or a name"
        )
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


# Built templates by structure: a t-string's strings and, for each
# interpolation, the type and value (a Param, str or int only: values whose
# equality decides their formatting), conversion and spec. Specs that refer
# to a Param by marker are not cached: the marker names an object, not a value.
_TEMPLATES: dict[tuple[Any, ...], tuple[Head, tuple[Part, ...], dict[str, Param]]] = {}
_CACHEABLE = (Param, str, int)


def _template_key(t: Template) -> tuple[Any, ...] | None:
    key: list[Any] = [t.strings]
    for i in t.interpolations:
        v = i.value
        tv = type(v)
        if tv not in _CACHEABLE or "\x00" in i.format_spec:
            return None
        key.append((tv, v, i.conversion, i.format_spec))
    return tuple(key)


def _from_template(t: Template) -> PathExpr:
    key = _template_key(t)
    if key is not None:
        hit = _TEMPLATES.get(key)
        if hit is not None:
            head, parts, params = hit
            return _new(head, parts, dict(params))
    expr = _build_template(t)
    if key is not None and not isinstance(expr.head, Deferred):
        if len(_TEMPLATES) >= _CACHE_SIZE:
            _TEMPLATES.clear()
        _TEMPLATES[key] = (expr.head, expr.parts, expr.params)
    return expr


def _build_template(t: Template) -> PathExpr:
    segments: list[list[str | Interpolation]] = [[]]
    anchor = ""
    for idx, item in enumerate(t):
        if isinstance(item, str):
            if "\x00" in item:
                if has_marker(item):
                    raise _fstring_error()
                _check_literal(item)
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


@overload
def P[CA, KA: Unspecified, QA](x: PathExpr[CA, KA, QA]) -> PathExpr[CA, KA, QA]: ...
@overload
def P(x: str | os.PathLike[str] | Param | Template | Text = ".") -> PathExpr: ...
def P(x: Any = ".") -> PathExpr[Any, Any, Any]:
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
            raise InvalidBindingError(
                f"{name}={show(v)}: bytes paths are not supported"
            )
    else:
        raise InvalidBindingError(
            f"{name}={show(v)}: expected str or os.PathLike (format other values inside a t-string field)"
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
            f"{name}={show(v)}: decode bytes before using them in a path"
        )
    try:
        s = format(v, "")
    except FORMAT_ERRORS as e:
        raise InvalidBindingError(
            f"{name}={show(v)} cannot be formatted: {e}"
        ) from None
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
    except FORMAT_ERRORS as e:
        raise InvalidBindingError(
            f"Cannot format {show(v)} with {f.pattern}: {e}"
        ) from None
    if "/" in s or "\x00" in s:
        raise InvalidBindingError(
            f"{f.pattern} formats {show(v)} to {s!r}, which contains a separator"
        )
    dot_free, non_empty = f.facts
    if (dot_free and "." in s) or (non_empty and not s):
        raise InvalidBindingError(
            f"{f.pattern} formats {show(v)} to {s!r}, breaking its format type"
        )
    return s


def spec_text(p: Param, v: Any) -> str:
    """The text a value bound to ``p`` gives inside a format spec (``{x:{p}}``),
    formatted as an f-string formats a nested replacement field."""
    try:
        return format(v, "")
    except FORMAT_ERRORS as e:
        raise InvalidBindingError(
            f"{p.name}={show(v)} cannot be formatted into a format spec: {e}"
        ) from None


def check_seg(s: str) -> str:
    if s in ("", ".", ".."):
        raise InvalidBindingError(
            f"Segment renders to {s!r}, which is not a valid path segment"
        )
    return s


# ---------------------------------------------------------------------------
# Interpreter (the reference semantics)
# ---------------------------------------------------------------------------


def _make_env(mapping: Any, kw: dict[str, Any]) -> dict[str, Any]:
    """The bindings given as ``mapping`` (a mapping keyed by name or `Param`,
    or an object whose fields bind by name) and keywords, by name."""
    env: dict[str, Any] = {}
    if mapping is not None:
        if type(mapping) is not dict and not isinstance(mapping, Mapping):
            from ._bindings import object_bindings

            mapping = object_bindings(mapping)
        for k, v in mapping.items():
            env[k.name if isinstance(k, Param) else k] = v
    env.update(kw)
    return env


_SYMBOLIC = (PathExpr, Text, Param, Template)


def _is_symbolic(v: Any) -> bool:
    return isinstance(v, _SYMBOLIC)


def _with_defaults(
    params: Any, env: dict[str, Any], missing: frozenset[str]
) -> dict[str, Any]:
    """``env`` with each ``missing`` name bound to its parameter's default
    (§3.1). Raises `MissingBindingError` for those without one."""
    filled = dict(env)
    for p in params:
        if p.name in missing and p.default is not NO_DEFAULT:
            filled[p.name] = p.default
    if len(filled) - len(env) != len(missing):
        raise MissingBindingError(set(missing - filled.keys()))
    return filled


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
    """A dynamic format spec's text: each nested parameter, checked against its
    declaration, formatted as ``format(v, "")``."""
    out = []
    for s in spec:
        if isinstance(s, str):
            out.append(s)
        else:
            v = env[s.name]
            s.check(v)
            out.append(spec_text(s, v))
    return "".join(out)


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
            out.append(v if isinstance(v, Param) else spec_text(s, v))
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


def _bound_parts(part: Part, env: Mapping[str, Any]) -> tuple[Part, ...]:
    if isinstance(part, Seg):
        if not (part.param_names & env.keys()):
            return (part,)
        pieces = _bind_pieces(part.pieces, env)
        if len(pieces) == 1 and isinstance(pieces[0], str):
            check_seg(pieces[0])
            if "/" in pieces[0]:  # a Text bound into a segment
                raise InvalidBindingError(
                    f"Segment renders to {pieces[0]!r}, which contains a separator"
                )
        elif not pieces:
            check_seg("")
        return (Seg(pieces),)
    p = part.param
    if p.name not in env:
        return (part,)
    v = env[p.name]
    if isinstance(v, Param):
        return (Splice(v),)
    if isinstance(v, Template):
        v = _from_template(v)
    if isinstance(v, PathExpr):
        if not isinstance(v.head, _Rel):
            raise InvalidBindingError(
                f"{p.name!r} must be bound to a relative path, got {v!r}"
            )
        return v.parts
    return tuple(Seg((s,)) for s in splice_value(p, v))


def _bind_expr(e: PathExpr, env: Mapping[str, Any]) -> PathExpr:
    if not (e.param_names & env.keys()):
        return e
    out = _bind_head(e.head, env)
    # Every bound part is relative, so joining it is concatenation: collect
    # the parts and build once.
    parts = list(out.parts)
    keys = env.keys()
    for part in e.parts:
        if (
            part.param_names & keys
            if isinstance(part, Seg)
            else part.param.name in keys
        ):
            parts.extend(_bound_parts(part, env))
        else:
            parts.append(part)
    if e._direct:
        for v in env.values():
            if isinstance(v, _SYMBOLIC):
                break
        else:
            # Concrete values add no parameters, and in an expression without
            # derived text or deferred operations no other parameter can
            # fold away, so the table is the old one without them.
            params = {k: p for k, p in e.params.items() if k not in env}
            return _new(out.head, tuple(parts), params)
    result = _new(out.head, tuple(parts))
    result.params  # noqa: B018 - surface declaration conflicts now
    return result
