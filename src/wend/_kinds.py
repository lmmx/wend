"""What the type of an expression says it declares, and the evidence a
check produces (research branch; see docs/journal/2026-10-22-typed-core.md
and docs/journal/2026-10-22-evidence.md).

`PathExpr` has three phantom type parameters, a Hoare triple's {C} e {Q}:

- ``C``, contravariant: the union of what the expression *requires*, as
  literal atoms (``Literal["read", "exists"]``) and `Under` markers. A
  union is a set, and contravariance turns "requires at least these" into
  subtyping. The default, ``Never``, requires nothing and accepts any
  expression.
- ``K``, covariant: `IsFile` once ``File`` is declared in either phase
  (nothing can be joined below it), `Unspecified` otherwise. `NotFile`,
  "known not to be declared a File", is never produced; it exists so that
  an expression of unknown kind joins as a path rather than as a File (see
  `PathExpr.__truediv__`).
- ``Q``, contravariant: the union of what it *ensures*, in the same atoms.
  Kept apart from ``C`` so that a check of the one never certifies the
  other.

A check does not make an atom true for ever, and is not a path: `Checked`
and `Confirmed` are *evidence*, the atoms a check found true of one path
at one moment, at a step's entry or exit. Each holds the path it is about
(``.path``); a path derived from it is an ordinary path, and carries no
evidence.
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
Q = TypeVar("Q", contravariant=True, default=Never)
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


class _Evidence:
    """What one check found, and nothing more.

    - ``path``: the path the check was about, as rendered; not an object.
    - ``atoms``: the conditions found true by lookups of ``path`` while the
      check ran (one ``stat`` and one ``lstat`` for the state atoms, one
      ``access`` per permission): each held at some instant of the check, not
      necessarily all at the same instant, nor of the same object.
    - ``bases``: the bases ``path`` was found contained in, lexically and
      after resolving symlinks.
    - ``epoch``: the step of a `Run` that made it, or ``None``.

    It is a record of the past. A later change to the filesystem does not
    update it, and nothing about it says the atoms still hold. It is not a
    path: ``.path`` gives the path, ordinary, and nothing derived from it
    carries the evidence. ``os.fspath`` (and so ``open``) takes it as the
    path it is about, unchanged. It cannot be altered once made; it can be
    constructed directly, as any type can be cast, and then certifies
    nothing."""

    __slots__ = ("_atoms", "_bases", "_epoch", "_path")

    def __init__(
        self,
        path: Path,
        atoms: frozenset[str] = frozenset(),
        epoch: int | None = None,
        bases: tuple[Path, ...] = (),
    ) -> None:
        object.__setattr__(self, "_path", path)
        object.__setattr__(self, "_atoms", frozenset(atoms))
        object.__setattr__(self, "_epoch", epoch)
        object.__setattr__(self, "_bases", tuple(bases))

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError(f"{type(self).__name__} cannot be altered")

    def __delattr__(self, name: str) -> None:
        raise AttributeError(f"{type(self).__name__} cannot be altered")

    @property
    def path(self) -> Path:
        return self._path

    @property
    def atoms(self) -> frozenset[str]:
        return self._atoms

    @property
    def bases(self) -> tuple[Path, ...]:
        return self._bases

    @property
    def epoch(self) -> int | None:
        return self._epoch

    def __fspath__(self) -> str:
        return str(self._path)

    def __repr__(self) -> str:
        return f"{type(self).__name__}({str(self._path)!r}, {sorted(self._atoms)})"


class Checked(_Evidence, Generic[C, K]):
    """Evidence that a path's preconditions held when it was checked (a
    step's entry): ``C`` is what was required, and so what was checked."""

    __slots__ = ()


class Confirmed(_Evidence, Generic[Q, K]):
    """Evidence that a path's postconditions held when it was confirmed (a
    step's exit): ``Q`` is what was ensured. Not a `Checked`."""

    __slots__ = ()
