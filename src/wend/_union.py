"""Unions: one pattern among several alternatives (docs/SEMANTICS.md §11).

A union is an ordered set of path expressions. It is built with ``|``, with
`U`, or from a t-string whose interpolations offer alternatives with `Alt`::

    k = Param("k", type=int)
    logs = U(t"{d}/app.log{Alt('', t'.{k}')}{Alt('', '.gz')}")

Each alternative is an ordinary, branch-free expression: alternation lives
outside the normal form, so everything that holds for an expression holds for
each alternative. Path operations distribute over the alternatives; `match`
and `glob` take every alternative's readings, and a path that two of them
read is ambiguous; `render` needs exactly one alternative, and `first` is the
explicit, effectful fallback: the first alternative that exists.
"""

from __future__ import annotations

import heapq
import itertools
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from string.templatelib import Interpolation, Template
from typing import TYPE_CHECKING, Any

from . import _expr
from ._expr import PathExpr, _coerce, _from_template, _make_env
from ._match import Match, _canonical
from .errors import (
    AmbiguousMatchError,
    ConditionError,
    NoAlternativeError,
    PathOperationError,
)


if TYPE_CHECKING:
    from .query import Query


MAX_ALTERNATIVES = 4096


class Alt:
    """Alternatives for one interpolation of a t-string given to `U`.

    Each option is text (a str), a t-string (which may hold parameters and
    nested alternatives) or a `Param`. It is spliced into the template as if
    written there, so an option may hold separators. ``Alt("", x)`` makes
    ``x`` optional.
    """

    __slots__ = ("options",)

    def __init__(self, *options: Any) -> None:
        from ._params import Param

        if not options:
            raise ValueError("Alt() needs at least one option")
        for o in options:
            if not isinstance(o, (str, Template, Param)):
                raise TypeError(
                    f"An Alt option is a str, a t-string or a Param, not {o!r}"
                )
        self.options = options

    def __repr__(self) -> str:
        return f"Alt({', '.join(map(repr, self.options))})"

    def __format__(self, spec: str) -> str:
        raise TypeError("Alt(...) is for t-strings given to U(), not f-strings")


def _as_template(o: Any) -> Template:
    if isinstance(o, Template):
        return o
    if isinstance(o, str):
        return Template(o)
    return Template(Interpolation(o, getattr(o, "name", "")))


def has_alternatives(t: Template) -> bool:
    for i in t.interpolations:
        v = i.value
        if isinstance(v, (Alt, PathUnion)) or (
            isinstance(v, Template) and has_alternatives(v)
        ):
            return True
    return False


def expand(t: Template) -> list[Template]:
    """The plain templates ``t`` stands for, in order: the product of its
    alternatives, the leftmost varying slowest."""
    choices: list[list[list[str | Interpolation]]] = []
    for item in t:
        if isinstance(item, str):
            choices.append([[item]])
            continue
        v = item.value
        if isinstance(v, Alt):
            if item.conversion is not None or item.format_spec:
                raise TypeError(
                    f"{item.expression or 'Alt'}: an Alt takes no conversion or format spec"
                )
            choices.append(
                [list(s) for o in v.options for s in expand(_as_template(o))]
            )
        elif isinstance(v, PathUnion):
            choices.append([[_with_value(item, a)] for a in v.alternatives])
        elif isinstance(v, Template) and has_alternatives(v):
            choices.append([[_with_value(item, s)] for s in expand(v)])
        else:
            choices.append([[item]])
    n = 1
    for c in choices:
        n *= len(c)
    if n > MAX_ALTERNATIVES:
        raise ValueError(f"{n} alternatives is more than {MAX_ALTERNATIVES}")
    return [
        Template(*(x for part in combo for x in part))
        for combo in itertools.product(*choices)
    ]


def _with_value(item: Interpolation, value: Any) -> Interpolation:
    return Interpolation(value, item.expression, item.conversion, item.format_spec)


def _alternatives(x: Any) -> tuple[PathExpr, ...]:
    if isinstance(x, PathUnion):
        return x.alternatives
    if isinstance(x, Template) and has_alternatives(x):
        return tuple(_from_template(t) for t in expand(x))
    return (_coerce(x, at_head=True),)


def union(items: Any) -> PathUnion:
    """The union of ``items`` (expressions, unions, anything `P` takes),
    flattened, without repeated alternatives (the first is kept)."""
    out: list[PathExpr] = []
    seen: set[PathExpr] = set()
    for x in items:
        for a in _alternatives(x):
            if a not in seen:
                seen.add(a)
                out.append(a)
    if not out:
        raise ValueError("A union needs at least one alternative")
    return PathUnion(tuple(out))


def U(*items: Any) -> PathUnion:
    """A union: ``U(a, b, c)`` is ``a | b | c``; ``U(t"...{Alt(x, y)}...")``
    expands a t-string's alternatives."""
    return union(items)


class AltMatch(Match):
    """A `Match` of a union: also says which alternative matched."""

    __slots__ = ("alternative", "expr")

    def __init__(
        self, path: str, bindings: dict[str, Any], alternative: int, expr: PathExpr
    ) -> None:
        super().__init__(path, bindings)
        self.alternative = alternative
        self.expr = expr

    def __repr__(self) -> str:
        return (
            f"Match({self.path!r}, {self.bindings!r}, alternative={self.alternative})"
        )


@dataclass(frozen=True, repr=False)
class PathUnion:
    """An ordered union of path expressions (docs/SEMANTICS.md §11)."""

    alternatives: tuple[PathExpr, ...]

    # -- building -------------------------------------------------------------

    def __or__(self, other: Any) -> PathUnion:
        return union((self, other))

    def __ror__(self, other: Any) -> PathUnion:
        return union((other, self))

    def _map(self, fn: Any) -> PathUnion:
        return union(fn(a) for a in self.alternatives)

    def __truediv__(self, other: Any) -> PathUnion:
        rights = _alternatives_operand(other)
        return union(a / r for a in self.alternatives for r in rights)

    def __rtruediv__(self, other: Any) -> PathUnion:
        return union(
            left / a for left in _alternatives(other) for a in self.alternatives
        )

    def joinpath(self, *others: Any) -> PathUnion:
        out = self
        for o in others:
            out = out / o
        return out

    def child(self, *parts: Any) -> PathUnion:
        return self.joinpath(*parts)

    def under(self, base: Any) -> PathUnion:
        return union(b / a for b in _alternatives(base) for a in self.alternatives)

    @property
    def parent(self) -> PathUnion:
        return self._map(lambda a: a.parent)

    def with_name(self, name: Any) -> PathUnion:
        return self._map(lambda a: a.with_name(name))

    def with_suffix(self, suffix: str) -> PathUnion:
        return self._map(lambda a: a.with_suffix(suffix))

    def with_stem(self, stem: Any) -> PathUnion:
        return self._map(lambda a: a.with_stem(stem))

    def relative_to(self, other: Any) -> PathUnion:
        return self._map(lambda a: a.relative_to(other))

    def bind(self, mapping: Any = None, /, **kw: Any) -> PathUnion:
        env = _make_env(mapping, kw)
        return self._map(lambda a: a.bind(env))

    def requires(self, *conditions: Any) -> PathUnion:
        return self._map(lambda a: a.requires(*conditions))

    def ensures(self, *conditions: Any) -> PathUnion:
        return self._map(lambda a: a.ensures(*conditions))

    # -- introspection --------------------------------------------------------

    def __iter__(self) -> Iterator[PathExpr]:
        return iter(self.alternatives)

    def __len__(self) -> int:
        return len(self.alternatives)

    @property
    def param_names(self) -> frozenset[str]:
        return frozenset().union(*(a.param_names for a in self.alternatives))

    @property
    def pattern(self) -> str:
        return " | ".join(a.pattern for a in self.alternatives)

    def __repr__(self) -> str:
        return f"U({', '.join(repr(a.pattern) for a in self.alternatives)})"

    __str__ = __repr__

    # -- rendering ------------------------------------------------------------

    def render(self, mapping: Any = None, /, **kw: Any) -> str:
        """The rendering of the only alternative. A union of several has no
        single rendering: use `renderings`, or `first` to pick by existence."""
        if len(self.alternatives) != 1:
            raise PathOperationError(
                f"{self.pattern!r} has {len(self.alternatives)} alternatives;"
                " use renderings() for all of them, or first() for the first"
                " that exists"
            )
        return self.alternatives[0].render(mapping, **kw)

    def resolve(
        self,
        mapping: Any = None,
        /,
        *,
        cls: type = Path,
        **kw: Any,
    ) -> Any:
        return cls(self.render(mapping, **kw))

    def renderings(self, mapping: Any = None, /, **kw: Any) -> tuple[str, ...]:
        """Every alternative rendered with the same bindings, in order."""
        env = _make_env(mapping, kw)
        return tuple(a.render(env) for a in self.alternatives)

    def first(self, mapping: Any = None, /, **kw: Any) -> Path:
        """The first alternative that exists and meets its own preconditions,
        checked now against the filesystem (an effect, unlike `render`).

        Every alternative must render: a missing or invalid binding is an
        error, not a reason to skip it. Raises `NoAlternativeError` (a
        `FileNotFoundError`) listing what was tried when none qualifies.
        """
        from .conditions import Exists, check_conditions

        env = _make_env(mapping, kw)
        tried: list[tuple[str, ConditionError]] = []
        for a in self.alternatives:
            s = a.render(env)
            conds = a.conditions
            try:
                check_conditions(s, (Exists, *(conds.requires if conds else ())), env)
            except ConditionError as e:
                tried.append((s, e))
                continue
            return Path(s)
        raise NoAlternativeError(tried)

    # -- matching and discovery -----------------------------------------------

    def match_all(self, path: Any, *, limit: int = 1000) -> list[AltMatch]:
        """Every verified reading of ``path``, by each alternative in order."""
        s = _canonical(path)
        out: list[AltMatch] = []
        for i, a in enumerate(self.alternatives):
            for env in a.match_all(s, limit=limit - len(out)):
                out.append(AltMatch(s, env, i, a))
            if len(out) >= limit:
                break
        return out

    def match(self, path: Any) -> AltMatch | None:
        """The one reading of ``path``: None if no alternative reads it, and
        `AmbiguousMatchError` if two readings exist, by one alternative or by
        two."""
        found = self.match_all(path, limit=2)
        if not found:
            return None
        if len(found) > 1:
            s = _canonical(path)
            raise AmbiguousMatchError(s, list(self.match_all(s)))
        return found[0]

    def glob(self, mapping: Any = None, /, **kw: Any) -> Iterator[AltMatch]:
        """Discover existing paths that any alternative matches, in path order
        (see `wend.glob` for the options). A path two alternatives find is
        ambiguous."""
        streams = [
            _tagged(a.glob(mapping, **kw), i, a)
            for i, a in enumerate(self.alternatives)
        ]
        merged = heapq.merge(*streams, key=lambda m: m.path)
        for path, group in itertools.groupby(merged, key=lambda m: m.path):
            found = list(group)
            if len(found) > 1:
                raise AmbiguousMatchError(path, list(found))
            yield found[0]

    # -- queries ----------------------------------------------------------------

    def __sub__(self, other: Any) -> Query:
        from .query import Query

        return Query(self) - other

    def __and__(self, other: Any) -> Query:
        from .query import Query

        return Query(self) & other

    def where(self, *predicates: Any) -> Query:
        from .query import Query

        return Query(self).where(*predicates)


def _tagged(found: Iterator[Match], i: int, a: PathExpr) -> Iterator[AltMatch]:
    for m in found:
        yield AltMatch(m.path, dict(m.bindings), i, a)


def _alternatives_operand(x: Any) -> tuple[Any, ...]:
    """A right operand of ``/``: a union's alternatives, or one operand as
    `PathExpr.__truediv__` takes it (a str or Param stays a segment)."""
    if isinstance(x, PathUnion):
        return x.alternatives
    if isinstance(x, Template) and has_alternatives(x):
        return tuple(_from_template(t) for t in expand(x))
    return (x,)


_expr._ALTERNATIVES = (Alt, PathUnion)
_expr._has_alternatives = has_alternatives
