"""Parameters: named, late-bound slots in path expressions."""

from __future__ import annotations

import enum
import re
import weakref
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Final

from .errors import InvalidBindingError, show


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


class _NoDefault:
    """The `Param.default` of a parameter declared without one."""

    __slots__ = ()

    def __repr__(self) -> str:
        return "NO_DEFAULT"

    def __reduce__(self) -> str:
        return "NO_DEFAULT"  # the module-level singleton


NO_DEFAULT: Final = _NoDefault()


@dataclass(frozen=True, eq=False)
class Param:
    """A named slot filled at resolution time.

    ``type`` constrains the bound value (``isinstance`` check) and tells
    `match` how to parse text back into a value. ``choices`` restricts the
    accepted values. ``default`` is the value rendering uses when no binding
    is given for the name (docs/SEMANTICS.md §3.1); `bind` and `match` leave
    it alone.
    """

    name: str
    kind: Kind = Kind.AUTO
    type: Any = None
    choices: frozenset[Any] | None = None
    default: Any = field(default=NO_DEFAULT, kw_only=True)

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name or "\x00" in self.name:
            raise ValueError(f"Invalid parameter name {self.name!r}")
        if not isinstance(self.kind, Kind):
            raise TypeError(f"kind must be a wend.Kind, not {self.kind!r}")
        if self.choices is not None and not isinstance(self.choices, frozenset):
            object.__setattr__(self, "choices", frozenset(self.choices))
        if self.default is not NO_DEFAULT:
            _check_default(self)
        _REGISTRY[id(self)] = self

    # A default is part of the declaration, so Params with different defaults
    # are different (and conflict under one name). Defaults and choices compare
    # by type and repr as well as by value: 1, True and 1.0 are equal but
    # render apart, and equal Params must be interchangeable (the template
    # cache relies on it).
    def __eq__(self, other: object) -> bool:
        if self is other:
            return True
        if other.__class__ is not self.__class__:
            return NotImplemented
        o: Param = other  # type: ignore[assignment]
        if self.name != o.name or self.kind is not o.kind or self.type != o.type:
            return False
        if self.choices is not o.choices and not _same_choices(self.choices, o.choices):
            return False
        a, b = self.default, o.default
        return a is b or (type(a) is type(b) and a == b and repr(a) == repr(b))

    def __hash__(self) -> int:
        return hash((self.name, self.kind, self.type, self.choices, self.default))

    @property
    def has_default(self) -> bool:
        """Whether the parameter declares a default."""
        return self.default is not NO_DEFAULT

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
        if self.default is not NO_DEFAULT:
            extra.append(f"default={self.default!r}")
        return f"Param({self.name!r}{''.join(', ' + e for e in extra)})"

    def check(self, value: Any) -> None:
        """Raise InvalidBindingError if ``value`` violates the declared type or choices."""
        if self.type is not None and not isinstance(value, self.type):
            raise InvalidBindingError(
                f"{self.name}={show(value)}: expected {getattr(self.type, '__name__', self.type)}"
            )
        if self.choices is not None and not _is_choice(value, self.choices):
            raise InvalidBindingError(
                f"{self.name}={show(value)}: not one of {sorted(map(repr, self.choices))}"
            )


def _check_default(p: Param) -> None:
    """Reject a default that no binding of ``p`` could accept: it must meet
    the declared type and choices, be hashable (a declaration is), and meet
    the kind's rule (§3). An AUTO parameter's kind depends on where it is
    used, so its default is only required to be usable somewhere: a path, or
    a value a segment can format. Where it is used, it is checked again at
    render, like any binding."""
    from ._expr import _segment_text, head_value, seg_value, splice_value

    d = p.default
    try:
        hash(d)
    except TypeError:
        raise TypeError(
            f"The default of {p.name!r} must be hashable, not {d!r}"
        ) from None
    try:
        if p.kind is Kind.SEGMENT:
            seg_value(p, d)
        elif p.kind is Kind.SUBPATH:
            splice_value(p, d)
        elif p.kind in (Kind.PATH, Kind.ABSOLUTE):
            head_value(p, d)
        else:
            p.check(d)
            _segment_text(p.name, d)
    except InvalidBindingError as e:
        raise InvalidBindingError(f"Invalid default for {p.name!r}: {e}") from None


def _same_choices(a: frozenset[Any] | None, b: frozenset[Any] | None) -> bool:
    """Whether two declarations' choices are the same, member by member as
    defaults are (§3.1: one type, equal, one repr): ``{1}``, ``{True}`` and
    ``{1.0}`` are equal sets but different choices."""
    if a is b:
        return True
    if a is None or b is None or a != b:
        return False
    # Equal sets pair each member with the one member of the other it equals.
    partner = {m: m for m in b}
    for m in a:
        n = partner[m]
        if m is not n and (type(m) is not type(n) or repr(m) != repr(n)):
            return False
    return True


def _is_choice(value: Any, choices: frozenset[Any]) -> bool:
    try:
        return value in choices
    except TypeError:  # unhashable, so not among the (hashable) choices
        return False


def Segment(
    name: str, *, type: Any = None, choices: Any = None, default: Any = NO_DEFAULT
) -> Param:
    """A parameter binding exactly one path segment."""
    return Param(name, Kind.SEGMENT, type=type, choices=choices, default=default)


def SubPath(name: str, *, choices: Any = None, default: Any = NO_DEFAULT) -> Param:
    """A parameter binding a relative path of zero or more segments."""
    return Param(name, Kind.SUBPATH, choices=choices, default=default)


def AnyPath(name: str, *, choices: Any = None, default: Any = NO_DEFAULT) -> Param:
    """A parameter binding any path, with pathlib join semantics wherever it is used."""
    return Param(name, Kind.PATH, choices=choices, default=default)


def Absolute(name: str, *, choices: Any = None, default: Any = NO_DEFAULT) -> Param:
    """A parameter binding an absolute path."""
    return Param(name, Kind.ABSOLUTE, choices=choices, default=default)


def lookup_marker(token: str) -> Param:
    param = _REGISTRY.get(int(token))
    if param is None:  # pragma: no cover - the Param was garbage collected
        raise ValueError("Format spec refers to a Param that no longer exists")
    return param


def has_marker(s: str) -> bool:
    return "\x00wend:" in s
