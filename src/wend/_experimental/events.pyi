# The static half of wend._experimental.events: which of three guarantees
# each value carries. Checked and Confirmed are events (it was true), Held is
# an open object (which object), Sealed is a copy no one can change (it
# remains true). None is assignable to another.

from collections.abc import Mapping
from contextlib import AbstractContextManager
from typing import Any, Generic, Literal, Self, TypeVar, overload

from .._expr import PathExpr
from .._kinds import C, Checked, Confirmed, IsFile, K, Unspecified
from ..conditions import Step
from .confined import Confined
from .knowledge import Knowledge
from .publish import Derivation, Draft, Published, Version, VersionDraft

__all__ = [
    "Commits",
    "Held",
    "Holds",
    "Makes",
    "Run",
    "Sealed",
    "Spec",
    "Uses",
    "seal",
]

CC = TypeVar("CC")
KX = TypeVar("KX", bound=Unspecified)

class Held(Generic[C, K]):  # noqa: UP046
    """An open regular file: its object, kind and access are durable while it
    is open; its contents, size and names are not."""

    path: str  # the name it was opened by: reopening it may reach another object
    fd: int
    access: frozenset[str]
    used: list[str]  # a digest of what each read returned
    @property
    def ident(self) -> tuple[int, int]: ...
    @property
    def is_file(self) -> bool: ...
    def read(self) -> bytes: ...
    def close(self) -> None: ...
    def __enter__(self) -> Self: ...
    def __exit__(self, *exc: object) -> None: ...

class Sealed:
    """A copy of a held file's contents that no holder can change."""

    source: tuple[int, int]
    fd: int
    def __init__(self, data: bytes, source: tuple[int, int]) -> None: ...
    def read(self) -> bytes: ...
    def close(self) -> None: ...

def seal(h: Held[Literal["read"], IsFile]) -> Sealed: ...

class Uses(Generic[CC, KX]):  # noqa: UP046
    def __init__(self, expr: PathExpr[CC, KX]) -> None: ...
    @overload
    def __get__(
        self, obj: None, owner: type[Any] | None = None
    ) -> PathExpr[CC, KX]: ...
    @overload
    def __get__(self, obj: Spec, owner: type[Any] | None = None) -> Checked[CC, KX]: ...

class Holds:
    """Only an expression declaring an existing, readable File can be held."""

    def __init__(
        self, expr: PathExpr[Literal["file", "exists", "read"], IsFile]
    ) -> None: ...
    @overload
    def __get__(
        self, obj: None, owner: type[Any] | None = None
    ) -> PathExpr[Literal["file", "exists", "read"], IsFile]: ...
    @overload
    def __get__(
        self, obj: Spec, owner: type[Any] | None = None
    ) -> Held[Literal["read"], IsFile]: ...

class Makes:
    """Only an expression declaring a new file can be made."""

    def __init__(
        self,
        expr: PathExpr[Literal["absent", "create", "post_file", "post_exists"], IsFile],
    ) -> None: ...
    @overload
    def __get__(
        self, obj: None, owner: type[Any] | None = None
    ) -> PathExpr[Literal["absent", "create", "post_file", "post_exists"], IsFile]: ...
    @overload
    def __get__(self, obj: Spec, owner: type[Any] | None = None) -> Draft: ...

class Commits:
    """Only an expression declaring a directory, there once made, can hold
    versions."""

    immutable: bool
    def __init__(
        self,
        expr: PathExpr[Literal["dir", "post_dir", "post_exists"], Unspecified],
        *,
        immutable: bool = False,
    ) -> None: ...
    @overload
    def __get__(
        self, obj: None, owner: type[Any] | None = None
    ) -> PathExpr[Literal["dir", "post_dir", "post_exists"], Unspecified]: ...
    @overload
    def __get__(self, obj: Spec, owner: type[Any] | None = None) -> VersionDraft: ...

class Spec:
    def __init__(self, entered: Mapping[str, Any]) -> None: ...
    @classmethod
    def ports(cls) -> dict[str, Any]: ...
    @classmethod
    def step(cls) -> Step: ...

class Run:
    io: Confined
    knowledge: Knowledge
    epoch: int
    confirmed: dict[str, Confirmed[Any, Any]]  # by path below the root
    published: dict[str, Published | Version]  # by output (or store) path
    derivations: list[Derivation]
    lease: bool
    def __init__(self, root: str, *, lease: bool = False) -> None: ...
    def known(self, event: Checked[Any, Any] | Confirmed[Any, Any]) -> bool:
        """Not invalidated by this run's steps: conditional on no other writer."""
    def enter[S: Spec](
        self, spec: type[S], env: Mapping[str, Any]
    ) -> AbstractContextManager[S]: ...
