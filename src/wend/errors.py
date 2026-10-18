"""Exception hierarchy.

Every error raised deliberately by wend derives from `WendError`. Errors that
signal an unacceptable value also derive from `ValueError`, so callers that
already handle pathlib's `ValueError` keep working. Misused arguments raise
`TypeError` or `ValueError`, as Python's own functions do; the private helpers
at the end hold the argument rules that several entry points share.
"""

from __future__ import annotations

from collections.abc import Callable, Container, Iterable, Mapping, Sequence
from typing import Any, Literal


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

    def __init__(self, path: str, candidates: Sequence[Mapping[str, Any]]) -> None:
        self.path = path
        self.candidates = list(candidates)
        shown = ", ".join(repr(c) for c in candidates[:3])
        more = "" if len(candidates) <= 3 else f" (+{len(candidates) - 3} more)"
        super().__init__(
            f"{path!r} matches ambiguously: {shown}{more}. Bind a parameter, or"
            " constrain one with choices= or type=, to pick one reading"
        )


class ParamConflictError(WendError, ValueError):
    """Two different parameter declarations share a name within one expression."""


# -- Helpers shared by the public entry points ---------------------------------


def _check_option_keywords(
    method: str,
    expr: Any,
    env: Container[str],
    options: Iterable[tuple[str, Any, Any]],
    *,
    before: str = "",
) -> None:
    """Refuse an option keyword that also names a parameter left unbound.

    The rule, shared by every method that takes both options and keyword
    bindings: ``options`` lists ``(name, value, default)``; an option whose
    value is not its default was passed by keyword. A keyword binding can
    never carry an option's name (Python gives that keyword to the option),
    so a name found in ``env`` was bound through the positional mapping and
    the keyword is unambiguously the option. If ``env`` lacks it and ``expr``
    has a parameter of that name, the caller may have meant either.
    ``before`` names the positional arguments ahead of the mapping, for the
    message.
    """
    for name, value, default in options:
        if value is not default and name in expr.param_names and name not in env:
            raise TypeError(
                f"{method}() got {name}={value!r}, but {name!r} is both an option"
                f" of {method}() and a parameter of {expr.pattern!r}. Bind the"
                f" parameter in the mapping, as {method}({before}{{{name!r}: ...}});"
                f" a {name}= keyword is then read as the option"
            )


def _ambiguity_handler(
    ambiguous: Literal["raise", "skip"] | Callable[[AmbiguousMatchError], object],
) -> Callable[[AmbiguousMatchError], object] | None:
    """The callback for an ``ambiguous=`` argument; None means raise."""
    if isinstance(ambiguous, str):
        if ambiguous == "raise":
            return None
        if ambiguous == "skip":
            return _ignore
    elif callable(ambiguous):
        return ambiguous
    raise ValueError(
        f"ambiguous must be 'raise', 'skip' or a callable, not {ambiguous!r}"
    )


def _ignore(error: AmbiguousMatchError) -> None:
    return None


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


class NoAlternativeError(ConditionError, FileNotFoundError):
    """No alternative of a union exists (or meets its preconditions).

    ``tried`` lists each rendered alternative with the condition error that
    ruled it out, in order.
    """

    def __init__(self, tried: list[tuple[str, ConditionError]]) -> None:
        self.tried = tried
        self.path = tried[0][0] if tried else ""
        self.condition = None
        shown = ", ".join(f"{s!r} ({e.condition!r})" for s, e in tried)
        super(ConditionError, self).__init__(f"No alternative qualifies: tried {shown}")
