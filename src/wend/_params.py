"""Parameters: named, late-bound slots in path expressions."""

from __future__ import annotations

import enum
import re
import weakref
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from .errors import InvalidBindingError


if TYPE_CHECKING:
    from ._expr import PathExpr


class Kind(enum.Enum):
    """What a parameter may bind to when used as a path operand.

    AUTO      PATH at the head of an expression, SEGMENT anywhere else.
    PATH      Any path, absolute or relative (pathlib join semantics).
    ABSOLUTE  An absolute path; joining one replaces everything before it.
    SEGMENT   Exactly one segment: no separator, not "", "." or "..".
    SUBPATH   A relative path of zero or more segments, without "..".

    Inside a t-string field with a conversion or format spec, a parameter is a
    formatted value rather than a path operand, and its kind does not apply.
    """

    AUTO = "auto"
    PATH = "path"
    ABSOLUTE = "absolute"
    SEGMENT = "segment"
    SUBPATH = "subpath"


_REGISTRY: weakref.WeakValueDictionary[int, Param] = weakref.WeakValueDictionary()
MARKER_RE = re.compile("\x00wend:([0-9]+)\x00")


@dataclass(frozen=True)
class Param:
    """A named slot filled at resolution time.

    ``type`` constrains the bound value (``isinstance`` check) and tells
    `match` how to parse text back into a value. ``choices`` restricts the
    accepted values.
    """

    name: str
    kind: Kind = Kind.AUTO
    type: Any = None
    choices: frozenset[Any] | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name or "\x00" in self.name:
            raise ValueError(f"Invalid parameter name {self.name!r}")
        if not isinstance(self.kind, Kind):
            raise TypeError(f"kind must be a wend.Kind, not {self.kind!r}")
        if self.choices is not None and not isinstance(self.choices, frozenset):
            object.__setattr__(self, "choices", frozenset(self.choices))
        _REGISTRY[id(self)] = self

    def __format__(self, spec: str) -> str:
        # Called when a Param is evaluated inside a format spec of a t-string
        # (e.g. t"{idx:0{width}d}") or, by mistake, inside an f-string.
        if spec:
            raise ValueError(
                "A Param used inside a format spec cannot itself carry a spec"
            )
        _REGISTRY[id(self)] = self  # copies and unpickled Params skip __post_init__
        return f"\x00wend:{id(self)}\x00"

    def __truediv__(self, other: Any) -> PathExpr:
        from ._expr import P

        return P(self) / other

    def __rtruediv__(self, other: Any) -> PathExpr:
        from ._expr import P

        return P(other) / self

    def __repr__(self) -> str:
        extra = []
        if self.kind is not Kind.AUTO:
            extra.append(f"kind={self.kind}")
        if self.type is not None:
            extra.append(f"type={getattr(self.type, '__name__', self.type)}")
        if self.choices is not None:
            extra.append(f"choices={sorted(map(repr, self.choices))}")
        return f"Param({self.name!r}{''.join(', ' + e for e in extra)})"

    def check(self, value: Any) -> None:
        """Raise InvalidBindingError if ``value`` violates the declared type or choices."""
        if self.type is not None and not isinstance(value, self.type):
            raise InvalidBindingError(
                f"{self.name}={value!r}: expected {getattr(self.type, '__name__', self.type)}"
            )
        if self.choices is not None and value not in self.choices:
            raise InvalidBindingError(
                f"{self.name}={value!r}: not one of {sorted(map(repr, self.choices))}"
            )


def Segment(name: str, *, type: Any = None, choices: Any = None) -> Param:
    """A parameter binding exactly one path segment."""
    return Param(name, Kind.SEGMENT, type=type, choices=choices)


def SubPath(name: str, *, choices: Any = None) -> Param:
    """A parameter binding a relative path of zero or more segments."""
    return Param(name, Kind.SUBPATH, choices=choices)


def AnyPath(name: str, *, choices: Any = None) -> Param:
    """A parameter binding any path, with pathlib join semantics wherever it is used."""
    return Param(name, Kind.PATH, choices=choices)


def Absolute(name: str, *, choices: Any = None) -> Param:
    """A parameter binding an absolute path."""
    return Param(name, Kind.ABSOLUTE, choices=choices)


def lookup_marker(token: str) -> Param:
    param = _REGISTRY.get(int(token))
    if param is None:  # pragma: no cover - the Param was garbage collected
        raise ValueError("Format spec refers to a Param that no longer exists")
    return param


def has_marker(s: str) -> bool:
    return "\x00wend:" in s
