# The static half of wend._experimental.typed. Each signature mirrors what
# the runtime does to an expression's declared conditions (docs/SEMANTICS.md
# §10): derived expressions drop them; `bind` and `rebase` keep them;
# `requires` and `ensures` add them. A rule may claim less than the runtime
# declares, never more.

import os
from collections.abc import Mapping
from pathlib import Path
from string.templatelib import Template
from typing import (
    Any,
    Final,
    Generic,
    Literal,
    LiteralString,
    Never,
    Self,
    TypeVar,
    overload,
)
from warnings import deprecated

from wend import Absolute as Absolute
from wend import AnyPath as AnyPath
from wend import Param as Param
from wend import Segment as Segment
from wend import Step
from wend import SubPath as SubPath

__all__ = [
    "Absent",
    "Absolute",
    "AnyPath",
    "Checked",
    "Creatable",
    "Dir",
    "Exists",
    "Facts",
    "File",
    "IsFile",
    "Listable",
    "P",
    "Param",
    "PathExpr",
    "PathUnion",
    "Readable",
    "Resolved",
    "Segment",
    "StepSpec",
    "SubPath",
    "T",
    "Under",
    "Unspecified",
    "Uses",
    "Writable",
    "declared_by",
    "facts",
]

class Unspecified: ...
class IsFile(Unspecified): ...

C = TypeVar("C", contravariant=True, default=Never)
K = TypeVar("K", covariant=True, default=Unspecified)
# Invariant, so an argument binds its variable exactly: a covariant
# Condition lets call-site inference widen Literal["exists"] to
# Literal["exists", "read"] to fit an expected type.
Pre = TypeVar("Pre")
Post = TypeVar("Post")
B = TypeVar("B")  # invariant: one base's marker never stands for another's
L = TypeVar("L", bound=LiteralString)
# One variable per argument, each bound by exactly that argument: none is
# ever left for call-site inference to solve from the expected type.
X1 = TypeVar("X1")
X2 = TypeVar("X2")
X3 = TypeVar("X3")
X4 = TypeVar("X4")
X5 = TypeVar("X5")
X6 = TypeVar("X6")
CC = TypeVar("CC")
KX = TypeVar("KX")

class Condition(Generic[Pre, Post]):  # noqa: UP046 (variance is declared, not inferred)
    """Adds ``Pre`` when required, ``Post`` when ensured."""

class FileCondition(Condition[Literal["file"], Literal["post_file"]]):
    """``File``: adds its atom and, given first, the kind nothing joins below."""

Exists: Final[Condition[Literal["exists"], Literal["post_exists"]]]
Absent: Final[Condition[Literal["absent"], Literal["post_absent"]]]
Readable: Final[Condition[Literal["read"], Literal["post_read"]]]
Writable: Final[Condition[Literal["write"], Literal["post_write"]]]
Creatable: Final[Condition[Literal["create"], Literal["post_create"]]]
Listable: Final[Condition[Literal["list"], Literal["post_list"]]]
File: Final[FileCondition]
Dir: Final[Condition[Literal["dir"], Literal["post_dir"]]]

class Under(Condition["Under[B]", "Under[B]"], Generic[B]):  # noqa: UP046 (variance is declared, not inferred)
    @overload
    def __new__(cls, base: L) -> Under[L]: ...
    @overload
    def __new__(
        cls, base: str | os.PathLike[str] | Param | PathExpr[Any, Any]
    ) -> Under[str]: ...

class JoinBelowFile:
    """What joining below a declared File gives: not a path."""

class PathExpr(Generic[C, K]):  # noqa: UP046 (variance is declared, not inferred)
    @property
    def pattern(self) -> str: ...
    @property
    def params(self) -> Mapping[str, Param]: ...
    # -- what keeps declarations
    @overload
    def requires(self) -> PathExpr[C, K]: ...
    @overload
    def requires(
        self, file: FileCondition, /
    ) -> PathExpr[C | Literal["file"], IsFile]: ...
    @overload
    def requires(
        self, file: FileCondition, c1: Condition[X1, Any], /
    ) -> PathExpr[C | Literal["file"] | X1, IsFile]: ...
    @overload
    def requires(
        self, file: FileCondition, c1: Condition[X1, Any], c2: Condition[X2, Any], /
    ) -> PathExpr[C | Literal["file"] | X1 | X2, IsFile]: ...
    @overload
    def requires(
        self,
        file: FileCondition,
        c1: Condition[X1, Any],
        c2: Condition[X2, Any],
        c3: Condition[X3, Any],
        /,
    ) -> PathExpr[C | Literal["file"] | X1 | X2 | X3, IsFile]: ...
    @overload
    def requires(
        self,
        file: FileCondition,
        c1: Condition[X1, Any],
        c2: Condition[X2, Any],
        c3: Condition[X3, Any],
        c4: Condition[X4, Any],
        /,
    ) -> PathExpr[C | Literal["file"] | X1 | X2 | X3 | X4, IsFile]: ...
    @overload
    def requires(
        self,
        file: FileCondition,
        c1: Condition[X1, Any],
        c2: Condition[X2, Any],
        c3: Condition[X3, Any],
        c4: Condition[X4, Any],
        c5: Condition[X5, Any],
        /,
    ) -> PathExpr[C | Literal["file"] | X1 | X2 | X3 | X4 | X5, IsFile]: ...
    @overload
    def requires(self, c1: Condition[X1, Any], /) -> PathExpr[C | X1, K]: ...
    @overload
    def requires(
        self, c1: Condition[X1, Any], c2: Condition[X2, Any], /
    ) -> PathExpr[C | X1 | X2, K]: ...
    @overload
    def requires(
        self, c1: Condition[X1, Any], c2: Condition[X2, Any], c3: Condition[X3, Any], /
    ) -> PathExpr[C | X1 | X2 | X3, K]: ...
    @overload
    def requires(
        self,
        c1: Condition[X1, Any],
        c2: Condition[X2, Any],
        c3: Condition[X3, Any],
        c4: Condition[X4, Any],
        /,
    ) -> PathExpr[C | X1 | X2 | X3 | X4, K]: ...
    @overload
    def requires(
        self,
        c1: Condition[X1, Any],
        c2: Condition[X2, Any],
        c3: Condition[X3, Any],
        c4: Condition[X4, Any],
        c5: Condition[X5, Any],
        /,
    ) -> PathExpr[C | X1 | X2 | X3 | X4 | X5, K]: ...
    @overload
    def requires(
        self,
        c1: Condition[X1, Any],
        c2: Condition[X2, Any],
        c3: Condition[X3, Any],
        c4: Condition[X4, Any],
        c5: Condition[X5, Any],
        c6: Condition[X6, Any],
        /,
    ) -> PathExpr[C | X1 | X2 | X3 | X4 | X5 | X6, K]: ...
    @overload
    def requires(self, *conds: Condition[Any, Any]) -> PathExpr[C, K]:
        """More than 6 conditions: sound, the new ones are not tracked."""
    @overload
    def ensures(self) -> PathExpr[C, K]: ...
    @overload
    def ensures(
        self, file: FileCondition, /
    ) -> PathExpr[C | Literal["post_file"], IsFile]: ...
    @overload
    def ensures(
        self, file: FileCondition, c1: Condition[Any, X1], /
    ) -> PathExpr[C | Literal["post_file"] | X1, IsFile]: ...
    @overload
    def ensures(
        self, file: FileCondition, c1: Condition[Any, X1], c2: Condition[Any, X2], /
    ) -> PathExpr[C | Literal["post_file"] | X1 | X2, IsFile]: ...
    @overload
    def ensures(
        self,
        file: FileCondition,
        c1: Condition[Any, X1],
        c2: Condition[Any, X2],
        c3: Condition[Any, X3],
        /,
    ) -> PathExpr[C | Literal["post_file"] | X1 | X2 | X3, IsFile]: ...
    @overload
    def ensures(
        self,
        file: FileCondition,
        c1: Condition[Any, X1],
        c2: Condition[Any, X2],
        c3: Condition[Any, X3],
        c4: Condition[Any, X4],
        /,
    ) -> PathExpr[C | Literal["post_file"] | X1 | X2 | X3 | X4, IsFile]: ...
    @overload
    def ensures(
        self,
        file: FileCondition,
        c1: Condition[Any, X1],
        c2: Condition[Any, X2],
        c3: Condition[Any, X3],
        c4: Condition[Any, X4],
        c5: Condition[Any, X5],
        /,
    ) -> PathExpr[C | Literal["post_file"] | X1 | X2 | X3 | X4 | X5, IsFile]: ...
    @overload
    def ensures(self, c1: Condition[Any, X1], /) -> PathExpr[C | X1, K]: ...
    @overload
    def ensures(
        self, c1: Condition[Any, X1], c2: Condition[Any, X2], /
    ) -> PathExpr[C | X1 | X2, K]: ...
    @overload
    def ensures(
        self, c1: Condition[Any, X1], c2: Condition[Any, X2], c3: Condition[Any, X3], /
    ) -> PathExpr[C | X1 | X2 | X3, K]: ...
    @overload
    def ensures(
        self,
        c1: Condition[Any, X1],
        c2: Condition[Any, X2],
        c3: Condition[Any, X3],
        c4: Condition[Any, X4],
        /,
    ) -> PathExpr[C | X1 | X2 | X3 | X4, K]: ...
    @overload
    def ensures(
        self,
        c1: Condition[Any, X1],
        c2: Condition[Any, X2],
        c3: Condition[Any, X3],
        c4: Condition[Any, X4],
        c5: Condition[Any, X5],
        /,
    ) -> PathExpr[C | X1 | X2 | X3 | X4 | X5, K]: ...
    @overload
    def ensures(
        self,
        c1: Condition[Any, X1],
        c2: Condition[Any, X2],
        c3: Condition[Any, X3],
        c4: Condition[Any, X4],
        c5: Condition[Any, X5],
        c6: Condition[Any, X6],
        /,
    ) -> PathExpr[C | X1 | X2 | X3 | X4 | X5 | X6, K]: ...
    @overload
    def ensures(self, *conds: Condition[Any, Any]) -> PathExpr[C, K]:
        """More than 6 conditions: sound, the new ones are not tracked."""
    def bind(self, mapping: Any = None, /, **kw: Any) -> PathExpr[C, K]: ...
    # rebase moves a declared Under base that lies under the old base, so a
    # literal base's identity does not survive it; only "under some base" does.
    @overload
    def rebase(
        self: PathExpr[Under[Any], Any], *args: Any
    ) -> PathExpr[Under[str], K]: ...
    @overload
    def rebase(self, *args: Any) -> PathExpr[C, K]: ...
    def tag(self, **tags: Any) -> PathExpr[C, K]: ...
    # -- what drops them (a derived expression declares nothing)
    @overload
    @deprecated("nothing can be joined below a path declared a File")
    def __truediv__(self: PathExpr[Any, IsFile], other: Any) -> JoinBelowFile: ...
    @overload
    def __truediv__(self, other: PathUnion) -> PathUnion: ...
    @overload
    def __truediv__(
        self, other: str | os.PathLike[str] | Param | PathExpr[Any, Any] | Template
    ) -> PathExpr: ...
    def __rtruediv__(self, other: str | os.PathLike[str] | Param) -> PathExpr: ...
    def joinpath(self, *others: Any) -> PathExpr: ...
    @property
    def parent(self) -> PathExpr: ...
    def with_suffix(self, suffix: Any) -> PathExpr: ...
    def with_name(self, name: Any) -> PathExpr: ...
    def with_stem(self, stem: Any) -> PathExpr: ...
    def sibling(self, name: Any) -> PathExpr: ...
    def cousin(self, path: Any, *names: Any) -> PathExpr: ...
    def under(self, base: Any) -> PathExpr: ...
    def relative_to(self, base: Any) -> PathExpr: ...
    def __or__(self, other: Any) -> PathUnion: ...
    # -- realising
    def render(self, mapping: Any = None, /, **kw: Any) -> str: ...
    def resolve(self, mapping: Any = None, /, **kw: Any) -> Resolved[C, K]: ...
    def check(
        self, mapping: Any = None, /, *, fs: Any = None, **kw: Any
    ) -> Checked[C, K]: ...
    def match(self, path: Any) -> Any: ...
    def glob(self, *args: Any, **kw: Any) -> Any: ...

class PathUnion:
    def requires(self, *conds: Any) -> PathUnion: ...
    def ensures(self, *conds: Any) -> PathUnion: ...
    def __or__(self, other: Any) -> PathUnion: ...
    def render(self, mapping: Any = None, /, **kw: Any) -> str: ...
    def first(self, mapping: Any = None, /, *, fs: Any = None, **kw: Any) -> Path: ...

@overload
def P[CA, KA](arg: PathExpr[CA, KA], /) -> PathExpr[CA, KA]: ...
@overload
def P(arg: str | os.PathLike[str] | Param | Template, /) -> PathExpr: ...
def T(template: Template, /) -> PathExpr: ...

class Resolved(Path, Generic[C, K]):  # noqa: UP046 (variance is declared, not inferred)
    """Rendered from an expression declaring C and K."""

class Checked(Resolved[C, K]):
    """Its expression's preconditions held when it was realised."""

class Facts:
    atoms: frozenset[str]
    kind: type[Unspecified]

def facts(e: PathExpr[Any, Any]) -> Facts: ...
def declared_by(annotation: Any, e: PathExpr[Any, Any]) -> bool: ...

class Uses(Generic[CC, KX]):  # noqa: UP046 (variance is declared, not inferred)
    def __init__(self, expr: PathExpr[CC, KX]) -> None: ...
    @overload
    def __get__(
        self, obj: None, owner: type[Any] | None = None
    ) -> PathExpr[CC, KX]: ...
    @overload
    def __get__(
        self, obj: StepSpec, owner: type[Any] | None = None
    ) -> Checked[CC, KX]: ...

class StepSpec:
    def __init__(
        self, mapping: Any = None, /, *, fs: Any = None, **kw: Any
    ) -> None: ...
    def __enter__(self) -> Self: ...
    def __exit__(self, et: Any, ev: Any, tb: Any) -> None: ...
    @classmethod
    def step(cls) -> Step: ...
    @classmethod
    def effects(cls) -> list[Any]: ...
