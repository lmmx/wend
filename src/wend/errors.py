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


class ConditionError(WendError):
    """A declared condition does not hold for a rendered path (§10).

    ``path`` is the rendered path and ``condition`` the condition that failed.
    Subclasses also derive from the builtin exception that describes the same
    failure, so ``except FileNotFoundError`` keeps working.
    """

    def __init__(self, path: str, condition: Any, message: str) -> None:
        self.path = path
        self.condition = condition
        super().__init__(f"{path!r} {message} (required: {condition!r})")


class MissingPathError(ConditionError, FileNotFoundError):
    """A path required to exist does not."""


class PathExistsError(ConditionError, FileExistsError):
    """A path required to be absent exists (possibly as a broken symlink)."""


class WrongKindError(ConditionError):
    """A path exists but is not the declared kind (a file, or a directory)."""


class CapabilityError(ConditionError, PermissionError):
    """A path cannot be used as declared: read, written, created or listed."""


class ContainmentError(ConditionError, InvalidBindingError):
    """A path is not under the base it was declared to be under.

    Raised by `render` when the bindings take the path lexically outside the
    base, and by `check` when it resolves outside it through symlinks.
    """
