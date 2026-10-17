"""Lenses: bidirectional mappings between two path layouts.

Two expressions that share parameters describe a relation between paths. A
`Lens` turns that relation into functions: match a path against one side and
render the bindings through the other.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

from ._expr import P, PathExpr, _make_env
from .errors import WendError


class NoMatchError(WendError, ValueError):
    """The path does not match the lens's source expression."""


class Lens:
    """Map paths matching ``source`` to the corresponding ``target`` paths.

    >>> src = P("src") / SubPath("rel") / T(t"{stem}.py")
    >>> lens = Lens(src, P("build") / SubPath("rel") / T(t"{stem}.pyc"))
    >>> lens("src/pkg/mod.py")
    PosixPath('build/pkg/mod.pyc')
    """

    def __init__(self, source: Any, target: Any) -> None:
        self.source: PathExpr = P(source)
        self.target: PathExpr = P(target)

    def __repr__(self) -> str:
        return f"Lens({self.source.pattern!r} -> {self.target.pattern!r})"

    @property
    def lossless(self) -> bool:
        """True if both directions need no extra bindings."""
        return self.source.param_names == self.target.param_names

    def bind(self, mapping: Any = None, /, **kw: Any) -> Lens:
        env = _make_env(mapping, kw)
        return Lens(self.source.bind(env), self.target.bind(env))

    def inverse(self) -> Lens:
        return Lens(self.target, self.source)

    def bindings(self, path: Any) -> dict[str, Any]:
        m = self.source.match(path)
        if m is None:
            raise NoMatchError(f"{str(path)!r} does not match {self.source.pattern!r}")
        return dict(m)

    def render(self, path: Any, **extra: Any) -> str:
        return self.target.render({**self.bindings(path), **extra})

    def __call__(self, path: Any, **extra: Any) -> Path:
        return Path(self.render(path, **extra))

    forward = __call__

    def backward(self, path: Any, **extra: Any) -> Path:
        return self.inverse()(path, **extra)

    def map(self, paths: Iterable[Any], **extra: Any) -> Iterator[tuple[Any, Path]]:
        """Pairs (path, mapped) for every path that matches the source; others are skipped."""
        for p in paths:
            m = self.source.match(p)
            if m is not None:
                yield p, Path(self.target.render({**m, **extra}))
