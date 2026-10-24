"""Option C: an expression carries its preconditions, ``Expr[Pre, K]``; one
that declares postconditions is a transition, ``Ensured[Pre, K, Post]``, a
subtype: the Hoare triple's {P} e {Q} as a type. Evidence objects hold a path."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Generic, Literal, Never, TypeVar, overload


class Unspecified: ...


class IsFile(Unspecified): ...


A = TypeVar("A")
X1 = TypeVar("X1")
X2 = TypeVar("X2")
X3 = TypeVar("X3")
Pre = TypeVar("Pre", contravariant=True, default=Never)
Post = TypeVar("Post", contravariant=True, default=Never)
K = TypeVar("K", bound=Unspecified, covariant=True, default=Unspecified)


class Cond(Generic[A]):  # noqa: UP046
    def __init__(self, name: str) -> None:
        self.name = name


class FileCond(Cond[Literal["file"]]): ...


File = FileCond("File")
Exists: Cond[Literal["exists"]] = Cond("Exists")
Absent: Cond[Literal["absent"]] = Cond("Absent")
Readable: Cond[Literal["read"]] = Cond("Readable")
Creatable: Cond[Literal["create"]] = Cond("Creatable")


class Checked(Generic[Pre, K]):  # noqa: UP046
    def __init__(self, path: Path) -> None:
        self.path = path


class Confirmed(Generic[Post, K]):  # noqa: UP046
    def __init__(self, path: Path) -> None:
        self.path = path


class Expr(Generic[Pre, K]):  # noqa: UP046
    @overload
    def requires(self, f: FileCond, /) -> Expr[Pre | Literal["file"], IsFile]: ...
    @overload
    def requires(
        self, f: FileCond, c1: Cond[X1], /
    ) -> Expr[Pre | Literal["file"] | X1, IsFile]: ...
    @overload
    def requires(
        self, f: FileCond, c1: Cond[X1], c2: Cond[X2], /
    ) -> Expr[Pre | Literal["file"] | X1 | X2, IsFile]: ...
    @overload
    def requires(self, c1: Cond[X1], /) -> Expr[Pre | X1, K]: ...
    @overload
    def requires(self, c1: Cond[X1], c2: Cond[X2], /) -> Expr[Pre | X1 | X2, K]: ...
    @overload
    def requires(
        self, c1: Cond[X1], c2: Cond[X2], c3: Cond[X3], /
    ) -> Expr[Pre | X1 | X2 | X3, K]: ...
    def requires(self, *c: Any) -> Any:
        return self

    @overload
    def ensures(self, f: FileCond, /) -> Ensured[Pre, IsFile, Literal["file"]]: ...
    @overload
    def ensures(
        self, f: FileCond, c1: Cond[X1], /
    ) -> Ensured[Pre, IsFile, Literal["file"] | X1]: ...
    @overload
    def ensures(self, c1: Cond[X1], /) -> Ensured[Pre, K, X1]: ...
    @overload
    def ensures(self, c1: Cond[X1], c2: Cond[X2], /) -> Ensured[Pre, K, X1 | X2]: ...
    def ensures(self, *c: Any) -> Any:
        return self

    def checked(self) -> Checked[Pre, K]:
        return Checked(Path("."))


class Ensured(Expr[Pre, K], Generic[Pre, K, Post]):  # noqa: UP046
    @overload
    def requires(
        self, f: FileCond, /
    ) -> Ensured[Pre | Literal["file"], IsFile, Post]: ...
    @overload
    def requires(
        self, f: FileCond, c1: Cond[X1], /
    ) -> Ensured[Pre | Literal["file"] | X1, IsFile, Post]: ...
    @overload
    def requires(
        self, f: FileCond, c1: Cond[X1], c2: Cond[X2], /
    ) -> Ensured[Pre | Literal["file"] | X1 | X2, IsFile, Post]: ...
    @overload
    def requires(self, c1: Cond[X1], /) -> Ensured[Pre | X1, K, Post]: ...
    @overload
    def requires(
        self, c1: Cond[X1], c2: Cond[X2], /
    ) -> Ensured[Pre | X1 | X2, K, Post]: ...
    @overload
    def requires(
        self, c1: Cond[X1], c2: Cond[X2], c3: Cond[X3], /
    ) -> Ensured[Pre | X1 | X2 | X3, K, Post]: ...
    def requires(self, *c: Any) -> Any:
        return self

    @overload
    def ensures(
        self, f: FileCond, /
    ) -> Ensured[Pre, IsFile, Post | Literal["file"]]: ...
    @overload
    def ensures(
        self, f: FileCond, c1: Cond[X1], /
    ) -> Ensured[Pre, IsFile, Post | Literal["file"] | X1]: ...
    @overload
    def ensures(self, c1: Cond[X1], /) -> Ensured[Pre, K, Post | X1]: ...
    @overload
    def ensures(
        self, c1: Cond[X1], c2: Cond[X2], /
    ) -> Ensured[Pre, K, Post | X1 | X2]: ...
    def ensures(self, *c: Any) -> Any:
        return self

    def confirmed(self) -> Confirmed[Post, K]:
        return Confirmed(Path("."))


def P(x: str) -> Expr:
    return Expr()
