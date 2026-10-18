"""Queries: discovery plans that filter what a pattern finds (SEMANTICS.md §11).

A query starts from an expression or a union and adds filters::

    src = P("src") / SubPath("rel") / T(t"{stem}.py")
    tests = P("src") / SubPath("rel") / T(t"{stem}_test.py")
    recent = (src - tests).where(File, modified_after(yesterday))
    for m in recent.glob():
        ...

- ``q - pattern`` drops paths that ``pattern`` matches;
- ``q & pattern`` keeps paths that ``pattern`` also matches, adding its
  bindings (a parameter both patterns bind must agree);
- ``q.where(*predicates)`` keeps paths for which every predicate holds. A
  predicate is a condition (``File``, ``Readable``, ``Under(base)``...), a
  filesystem test such as `modified_after`, or any callable taking the `Match`.

Nothing runs until `glob` (or `match`) is called, and results stream as they
are found. Filters are a conjunction: wend runs the pattern filters first,
then pure callables, then the predicates that touch the filesystem, which is
the cheapest order and gives the same results.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator
from datetime import datetime
from typing import Any

from ._expr import PathExpr, _coerce
from ._match import Match, _canonical
from .conditions import Condition, check_conditions
from .errors import (
    AmbiguousMatchError,
    ConditionError,
    InvalidBindingError,
    MissingBindingError,
)


__all__ = [
    "FsPredicate",
    "Query",
    "larger_than",
    "modified_after",
    "modified_before",
    "smaller_than",
]


class FsPredicate:
    """A test on the filesystem entry at a matched path (an effect)."""

    __slots__ = ("description", "test")

    def __init__(
        self, description: str, test: Callable[[os.stat_result], bool]
    ) -> None:
        self.description = description
        self.test = test

    def __repr__(self) -> str:
        return self.description

    def __call__(self, m: Match) -> bool:
        try:
            st = os.stat(m.path)
        except OSError:
            return False
        return self.test(st)


def _timestamp(when: datetime | float) -> float:
    return when.timestamp() if isinstance(when, datetime) else float(when)


def modified_after(when: datetime | float) -> FsPredicate:
    """The path was modified after ``when`` (a datetime or a POSIX timestamp)."""
    t = _timestamp(when)
    return FsPredicate(f"modified_after({when!r})", lambda st: st.st_mtime > t)


def modified_before(when: datetime | float) -> FsPredicate:
    """The path was modified before ``when``."""
    t = _timestamp(when)
    return FsPredicate(f"modified_before({when!r})", lambda st: st.st_mtime < t)


def larger_than(size: int) -> FsPredicate:
    """The path's size in bytes is more than ``size``."""
    return FsPredicate(f"larger_than({size})", lambda st: st.st_size > size)


def smaller_than(size: int) -> FsPredicate:
    """The path's size in bytes is less than ``size``."""
    return FsPredicate(f"smaller_than({size})", lambda st: st.st_size < size)


def _pattern(x: Any) -> Any:
    from ._union import PathUnion, U

    if isinstance(x, (PathExpr, PathUnion)):
        return x
    from string.templatelib import Template

    if isinstance(x, Template):
        return U(x)
    return _coerce(x, at_head=True)


class Query:
    """A lazy discovery plan: a source pattern and filters (see the module)."""

    def __init__(
        self,
        source: Any,
        drop: tuple[Any, ...] = (),
        keep: tuple[Any, ...] = (),
        where: tuple[Any, ...] = (),
    ) -> None:
        self.source = _pattern(source)
        self.drop = drop
        self.keep = keep
        self.predicates = where

    def _with(self, **changes: Any) -> Query:
        args = {
            "drop": self.drop,
            "keep": self.keep,
            "where": self.predicates,
        } | changes
        return Query(self.source, **args)

    def __sub__(self, other: Any) -> Query:
        return self._with(drop=(*self.drop, _pattern(other)))

    def __and__(self, other: Any) -> Query:
        return self._with(keep=(*self.keep, _pattern(other)))

    def where(self, *predicates: Any) -> Query:
        for p in predicates:
            if not (isinstance(p, Condition) or callable(p)):
                raise TypeError(f"A predicate is a condition or a callable, not {p!r}")
        return self._with(where=(*self.predicates, *predicates))

    def __repr__(self) -> str:
        parts = [repr(self.source)]
        parts += [f"- {d!r}" for d in self.drop]
        parts += [f"& {k!r}" for k in self.keep]
        if self.predicates:
            parts.append(f".where({', '.join(map(repr, self.predicates))})")
        return f"Query({' '.join(parts)})"

    # -- evaluation -----------------------------------------------------------

    def _order(self) -> list[Any]:
        """Predicates, pure ones first (their relative order is kept)."""
        pure = [
            p for p in self.predicates if not isinstance(p, (Condition, FsPredicate))
        ]
        return pure + [p for p in self.predicates if p not in pure]

    def _admit(self, m: Match, preds: list[Any]) -> Match | None:
        for d in self.drop:
            if d.match_all(m.path, limit=1):
                return None
        bindings = dict(m.bindings)
        for k in self.keep:
            merged: list[dict[str, Any]] = []
            for r in k.match_all(m.path):
                env = {**bindings, **r}
                if (
                    all(bindings.get(n, v) == v for n, v in r.items())
                    and env not in merged
                ):
                    merged.append(env)
            if not merged:
                return None
            if len(merged) > 1:
                raise AmbiguousMatchError(m.path, merged)
            bindings = merged[0]
        out = m if bindings == m.bindings else _rebind(m, bindings)
        for p in preds:
            if isinstance(p, Condition):
                try:
                    check_conditions(out.path, (p,), out.bindings)
                except ConditionError, MissingBindingError, InvalidBindingError:
                    return None
            elif not p(out):
                return None
        return out

    def glob(self, mapping: Any = None, /, **kw: Any) -> Iterator[Match]:
        """Discover the source's paths and yield those every filter admits,
        as they are found (see `wend.glob` for the options)."""
        preds = self._order()
        for m in self.source.glob(mapping, **kw):
            out = self._admit(m, preds)
            if out is not None:
                yield out

    def match(self, path: Any) -> Match | None:
        """The source's reading of ``path``, if every filter admits it. The
        filesystem predicates look at ``path`` now."""
        m = self.source.match(_canonical(path))
        if m is None:
            return None
        return self._admit(m, self._order())


def _rebind(m: Match, bindings: dict[str, Any]) -> Match:
    from ._union import AltMatch

    if isinstance(m, AltMatch):
        return AltMatch(m.path, bindings, m.alternative, m.expr)
    return Match(m.path, bindings)
