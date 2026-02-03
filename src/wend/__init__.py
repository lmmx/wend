"""
Deferred path expressions with late binding.

Build path expressions symbolically, resolve them later with concrete bindings.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from string.templatelib import Template
from typing import Any


# Parameters (late binding slots)


@dataclass(frozen=True)
class Param:
    """A named slot to be filled at resolution time."""

    name: str

    def __truediv__(self, other: PathExpr | str | Param) -> PathExpr:
        if isinstance(other, Param):
            return ParamExpr(self) / ParamExpr(other)
        return ParamExpr(self) / other

    def __rtruediv__(self, other: str) -> PathExpr:
        return LiteralExpr(other) / ParamExpr(self)

    def __repr__(self) -> str:
        return f"Param({self.name!r})"


# Path Expressions (composable, deferred)


class PathExpr:
    """Base class for path expressions. Everything is deferred."""

    def __truediv__(self, other: PathExpr | str | Param) -> PathExpr:
        if isinstance(other, Param):
            right = ParamExpr(other)
        elif isinstance(other, PathExpr):
            right = other
        else:
            right = LiteralExpr(other)
        return JoinExpr.create(self, right)

    def __rtruediv__(self, other: str) -> PathExpr:
        return JoinExpr.create(LiteralExpr(other), self)

    @property
    def parent(self) -> PathExpr:
        return ParentExpr.create(self)

    def with_name(self, name: str) -> PathExpr:
        return WithNameExpr(self, name)

    def with_suffix(self, suffix: str) -> PathExpr:
        return WithSuffixExpr.create(self, suffix)

    def required_params(self) -> set[str]:
        """Return all parameter names needed to resolve this expression."""
        raise NotImplementedError

    def resolve(self, bindings: dict[str, Any] | None = None) -> Path:
        """Resolve to a concrete Path with the given bindings."""
        bindings = bindings or {}
        missing = self.required_params() - set(bindings.keys())
        if missing:
            raise ValueError(f"Missing bindings: {missing}")
        cache: dict[int, Path] = {}
        return self._resolve(bindings, cache)

    def _resolve(self, bindings: dict[str, Any], cache: dict[int, Path]) -> Path:
        """Internal resolve with memoization cache."""
        raise NotImplementedError


@dataclass(frozen=True)
class LiteralExpr(PathExpr):
    """A concrete string/path segment."""

    value: str | Path

    def required_params(self) -> set[str]:
        return set()

    def _resolve(self, bindings: dict[str, Any], cache: dict[int, Path]) -> Path:
        if id(self) in cache:
            return cache[id(self)]
        result = Path(self.value)
        cache[id(self)] = result
        return result


@dataclass(frozen=True)
class ParamExpr(PathExpr):
    """A parameter reference—resolved from bindings."""

    param: Param

    def required_params(self) -> set[str]:
        return {self.param.name}

    def _resolve(self, bindings: dict[str, Any], cache: dict[int, Path]) -> Path:
        if id(self) in cache:
            return cache[id(self)]
        result = Path(bindings[self.param.name])
        cache[id(self)] = result
        return result


@dataclass(frozen=True)
class TemplateExpr(PathExpr):
    """A t-string template with interpolations."""

    template: Template
    _params: frozenset[str] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        params = set()
        for interp in self.template.interpolations:
            if isinstance(interp.value, Param):
                params.add(interp.value.name)
        object.__setattr__(self, "_params", frozenset(params))

    def required_params(self) -> set[str]:
        return set(self._params)

    def _resolve(self, bindings: dict[str, Any], cache: dict[int, Path]) -> Path:
        if id(self) in cache:
            return cache[id(self)]
        parts = []
        for item in self.template:
            if isinstance(item, str):
                parts.append(item)
            else:
                value = item.value
                if isinstance(value, Param):
                    value = bindings[value.name]
                parts.append(format(value, item.format_spec))
        result = Path("".join(parts))
        cache[id(self)] = result
        return result


@dataclass(frozen=True)
class JoinExpr(PathExpr):
    """Path join: left / right"""

    left: PathExpr
    right: PathExpr

    @staticmethod
    def create(left: PathExpr, right: PathExpr) -> PathExpr:
        """Construct with constant folding."""
        # Fold Literal / Literal -> Literal
        if isinstance(left, LiteralExpr) and isinstance(right, LiteralExpr):
            return LiteralExpr(Path(left.value) / right.value)
        return JoinExpr(left, right)

    def required_params(self) -> set[str]:
        return self.left.required_params() | self.right.required_params()

    def _resolve(self, bindings: dict[str, Any], cache: dict[int, Path]) -> Path:
        if id(self) in cache:
            return cache[id(self)]
        result = self.left._resolve(bindings, cache) / self.right._resolve(
            bindings, cache
        )
        cache[id(self)] = result
        return result


@dataclass(frozen=True)
class ParentExpr(PathExpr):
    """Parent of a path expression."""

    child: PathExpr

    @staticmethod
    def create(child: PathExpr) -> PathExpr:
        """Construct with algebraic simplification."""
        # parent(a / b) = a (when b is single component)
        if isinstance(child, JoinExpr):
            # Check if right side is a single component (no further joins)
            if isinstance(child.right, (LiteralExpr, ParamExpr, TemplateExpr)):
                return child.left
        # parent(Literal) can be folded
        if isinstance(child, LiteralExpr):
            return LiteralExpr(Path(child.value).parent)
        return ParentExpr(child)

    def required_params(self) -> set[str]:
        return self.child.required_params()

    def _resolve(self, bindings: dict[str, Any], cache: dict[int, Path]) -> Path:
        if id(self) in cache:
            return cache[id(self)]
        result = self.child._resolve(bindings, cache).parent
        cache[id(self)] = result
        return result


@dataclass(frozen=True)
class WithNameExpr(PathExpr):
    """Replace the final component name."""

    base: PathExpr
    name: str

    def required_params(self) -> set[str]:
        return self.base.required_params()

    def _resolve(self, bindings: dict[str, Any], cache: dict[int, Path]) -> Path:
        if id(self) in cache:
            return cache[id(self)]
        result = self.base._resolve(bindings, cache).with_name(self.name)
        cache[id(self)] = result
        return result


@dataclass(frozen=True)
class WithSuffixExpr(PathExpr):
    """Change suffix of a path."""

    base: PathExpr
    suffix: str

    @staticmethod
    def create(base: PathExpr, suffix: str) -> PathExpr:
        """Construct with suffix chain collapse."""
        # path.with_suffix(".a").with_suffix(".b") -> path.with_suffix(".b")
        if isinstance(base, WithSuffixExpr):
            return WithSuffixExpr(base.base, suffix)
        # Literal can be folded
        if isinstance(base, LiteralExpr):
            return LiteralExpr(Path(base.value).with_suffix(suffix))
        return WithSuffixExpr(base, suffix)

    def required_params(self) -> set[str]:
        return self.base.required_params()

    def _resolve(self, bindings: dict[str, Any], cache: dict[int, Path]) -> Path:
        if id(self) in cache:
            return cache[id(self)]
        result = self.base._resolve(bindings, cache).with_suffix(self.suffix)
        cache[id(self)] = result
        return result


# Convenience constructors


def P(path: str | Path) -> LiteralExpr:
    """Literal path expression."""
    return LiteralExpr(path)


def T(template: Template) -> TemplateExpr:
    """Template path expression from a t-string."""
    return TemplateExpr(template)


# Connectivity (rebasing)


@dataclass(frozen=True)
class RelativePath:
    """A path defined relative to a base, preserving the relation."""

    base: PathExpr
    relative: PathExpr

    @property
    def expr(self) -> PathExpr:
        """The full path expression."""
        return self.base / self.relative

    def rebase(self, new_base: PathExpr) -> RelativePath:
        """Create equivalent path under a different base."""
        return RelativePath(new_base, self.relative)

    def resolve(self, bindings: dict[str, Any] | None = None) -> Path:
        return self.expr.resolve(bindings)

    def required_params(self) -> set[str]:
        return self.expr.required_params()
