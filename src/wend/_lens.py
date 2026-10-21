"""Lenses: bidirectional mappings between two path layouts.

Two expressions that share parameters describe a relation between paths. A
`Lens` turns that relation into functions: match a path against one side and
render the bindings through the other.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator
from pathlib import Path
from typing import Any, Literal

from ._expr import P, PathExpr, _make_env
from .errors import (
    AmbiguousMatchError,
    NotInvertibleError,
    WendError,
    _ambiguity_handler,
    _check_option_keywords,
)


class NoMatchError(WendError, ValueError):
    """The path does not match the lens's source expression."""


class Lens:
    """Map paths matching ``source`` to the corresponding ``target`` paths.

    >>> src = P("src") / SubPath("rel") / T(t"{stem}.py")
    >>> lens = Lens(src, P("build") / SubPath("rel") / T(t"{stem}.pyc"))
    >>> lens("src/pkg/mod.py")
    PosixPath('build/pkg/mod.pyc')

    Target parameters that the source does not provide are bound per call,
    by keyword or after the path, in a mapping or an object whose fields
    bind by name (see `wend.bindings`): ``lens(path, run="r1")``,
    ``lens(path, {"run": "r1"})`` or ``lens(path, job)``. The path is
    positional-only, so a parameter may have any name.
    """

    def __init__(self, source: Any, target: Any) -> None:
        self.source: PathExpr = P(source)
        self.target: PathExpr = P(target)

    def __repr__(self) -> str:
        return f"Lens({self.source.pattern!r} -> {self.target.pattern!r})"

    @property
    def lossless(self) -> bool:
        """True if both sides have the same parameters, so neither direction
        needs extra bindings.

        Mapping forward through a lossless lens also checks that the result
        maps back uniquely: where two source paths would share a target
        (``{a}/{b}`` to ``{a}-{b}``), it raises `AmbiguousMatchError`.
        """
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

    def render(self, path: Any, mapping: Any = None, /, **extra: Any) -> str:
        return self._target(self.bindings(path), _make_env(mapping, extra))

    def _target(self, env: dict[str, Any], extra: dict[str, Any]) -> str:
        out = self.target.render({**env, **extra})
        if self.lossless:
            try:
                readings = self.target.match_all(out, limit=2)
            except NotInvertibleError:
                return out
            if len(readings) > 1:
                raise AmbiguousMatchError(out, self.target.match_all(out))
        return out

    def __call__(self, path: Any, mapping: Any = None, /, **extra: Any) -> Path:
        return Path(self.render(path, mapping, **extra))

    forward = __call__

    def backward(self, path: Any, mapping: Any = None, /, **extra: Any) -> Path:
        return self.inverse()(path, mapping, **extra)

    def map(
        self,
        paths: Iterable[Any],
        mapping: Any = None,
        /,
        *,
        ambiguous: Literal["raise", "skip"]
        | Callable[[AmbiguousMatchError], object] = "raise",
        **extra: Any,
    ) -> Iterator[tuple[Any, Path]]:
        """Pairs ``(path, mapped)``, in order, for each path that matches the
        source; other paths are skipped.

        ``mapping`` and keyword arguments bind target parameters, as for
        `render`. A target parameter named ``ambiguous`` is bound through
        ``mapping``; as a keyword it raises `TypeError` (see `wend.glob`).

        ``ambiguous`` decides what happens to a path that cannot be mapped
        uniquely: one that matches the source more than one way, or, through
        a lossless lens, one whose target reads back more than one way
        (another source path would map to the same target). ``"raise"``
        (default) raises `AmbiguousMatchError` when that path is reached;
        ``"skip"`` leaves it out; a callable is called with the
        `AmbiguousMatchError` and the path is left out, so
        ``ambiguous=report.append`` collects them. The error names the path
        that reads more than one way (the source path, or the target path
        for a collision) and every verified reading of it. As with
        `wend.glob`, a callback keeps ``map`` an iterator of pairs.
        """
        env = _make_env(mapping, extra)
        options = [("ambiguous", ambiguous, "raise")]
        _check_option_keywords("map", self.target, env, options, before="paths, ")
        return self._map(paths, env, _ambiguity_handler(ambiguous))

    def _map(
        self,
        paths: Iterable[Any],
        extra: dict[str, Any],
        on_ambiguous: Callable[[AmbiguousMatchError], object] | None,
    ) -> Iterator[tuple[Any, Path]]:
        for p in paths:
            try:
                m = self.source.match(p)
                out = None if m is None else self._target(dict(m), extra)
            except AmbiguousMatchError as error:
                if on_ambiguous is None:
                    raise
                on_ambiguous(error)
                continue
            if out is not None:
                yield p, Path(out)
