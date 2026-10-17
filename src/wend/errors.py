"""Exception hierarchy.

Every error raised deliberately by wend derives from `WendError`. Errors that
signal an unacceptable value also derive from `ValueError`, so callers that
already handle pathlib's `ValueError` keep working.
"""

from __future__ import annotations

from typing import Any


class WendError(Exception):
    """Base class for all wend errors."""


class MissingBindingError(WendError, ValueError):
    """Resolution was attempted without values for some parameters."""

    def __init__(self, missing: set[str]) -> None:
        self.missing = frozenset(missing)
        super().__init__(f"Missing bindings: {sorted(self.missing)}")


class InvalidBindingError(WendError, ValueError):
    """A bound value is not acceptable at the position where it is used.

    Raised when a value would silently change the segment structure of the
    expression (a separator inside a segment, an empty segment, ``.``), escape
    upwards (``..``), or violate a declared type, kind or set of choices.
    """


class PathOperationError(WendError, ValueError):
    """A path operation is invalid for this expression (mirrors pathlib's ValueError)."""


class NotStaticError(WendError):
    """The requested information depends on parameter values that are not bound."""


class NotInvertibleError(WendError):
    """The expression contains a construct that `match` cannot invert."""


class AmbiguousMatchError(WendError, ValueError):
    """A concrete path matches the expression with more than one set of bindings."""

    def __init__(self, path: str, candidates: list[dict[str, Any]]) -> None:
        self.path = path
        self.candidates = candidates
        shown = ", ".join(repr(c) for c in candidates[:3])
        more = "" if len(candidates) <= 3 else f" (+{len(candidates) - 3} more)"
        super().__init__(
            f"{path!r} matches ambiguously: {shown}{more}. Bind a parameter, or"
            " constrain one with choices= or type=, to pick one reading"
        )


class ParamConflictError(WendError, ValueError):
    """Two different parameter declarations share a name within one expression."""
