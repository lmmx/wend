"""What the type of an expression says it declares, and the events a check
produces (research branch; see docs/journal/2026-10-22-typed-core.md).

`PathExpr` has two phantom type parameters:

- ``C``, contravariant: the union of what the expression declares, as
  literal atoms (``Literal["read", "exists"]``, ``post_*`` for what it
  ensures) and `Under` markers. A union is a set, and contravariance turns
  "declares at least these" into subtyping. The default, ``Never``,
  declares nothing and accepts any expression.
- ``K``, covariant: `IsFile` once ``File`` is declared (nothing can be
  joined below it), `Unspecified` otherwise. `NotFile`, "known not to be
  declared a File", is never produced; it exists so that an expression of
  unknown kind joins as a path rather than as a File (see `PathExpr.__truediv__`).

A check does not make an atom true for ever: `Checked` and `Confirmed` are
*events*, the atoms that held of a path when it was checked at a step's
entry or exit. Neither is a guarantee that they still hold.
"""

from __future__ import annotations

from pathlib import Path
from typing import Generic, LiteralString, Never, TypeVar


__all__ = ["Checked", "Confirmed", "IsFile", "JoinBelowFile", "NotFile", "Unspecified"]


class Unspecified:
    """``File`` not declared, or not known to be."""


class NotFile(Unspecified):
    """``File`` known not to be declared: disjoint from `IsFile`."""


class IsFile(Unspecified):
    """``File`` declared, in ``requires`` or ``ensures``: nothing can be joined
    below the path (the runtime raises)."""


class JoinBelowFile:
    """What joining below a declared File gives, for a type checker: not a
    path (the runtime raises `PathOperationError`)."""


C = TypeVar("C", contravariant=True, default=Never)
K = TypeVar("K", bound=Unspecified, covariant=True, default=Unspecified)
# Invariant, so an argument binds its variable exactly: a covariant
# condition lets call-site inference widen Literal["exists"] to a union.
Pre = TypeVar("Pre")
Post = TypeVar("Post")
B = TypeVar("B")
L = TypeVar("L", bound=LiteralString)
# One variable per argument, each bound by exactly that argument.
X1 = TypeVar("X1")
X2 = TypeVar("X2")
X3 = TypeVar("X3")
X4 = TypeVar("X4")
X5 = TypeVar("X5")
X6 = TypeVar("X6")


class Checked(Path, Generic[C, K]):
    """A path whose expression's preconditions were checked when it was
    realised: an event, true at that moment, not necessarily now."""


class Confirmed(Path, Generic[C, K]):
    """A path whose expression's postconditions were checked when it was
    confirmed (a step's exit): an event too, and not a `Checked`."""
