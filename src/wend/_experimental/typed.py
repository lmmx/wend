"""A typed view of wend's declarations (research prototype).

Type checkers read ``typed.pyi``, which gives `PathExpr` two phantom type
parameters:

- ``C``, contravariant: the union of what the expression *declares*, as
  literal atoms (``Literal["read", "exists"]``) and `Under` markers. A union
  is a set, and contravariance turns "declares at least these" into
  subtyping: ``PathExpr[Literal["read", "exists"]]`` is assignable to
  ``PathExpr[Literal["read"]]`` and not the other way round. The default,
  ``Never``, declares nothing and accepts any expression.
- ``K``, covariant: `IsFile` when ``File`` is declared (nothing can be
  joined below it), the default `Unspecified` otherwise. Kinds as facts
  are atoms (``file``, ``dir``, ``post_file``, ``post_dir``): a step may
  require a file and ensure a directory.

At runtime this module re-exports wend's own objects, so code written
against it behaves exactly as code written against ``wend``. What it adds:

- `facts`: the same atoms, read from an expression's declared conditions
  (the abstraction the static type must never exceed);
- `Resolved` and `Checked`: `pathlib.Path` subclasses for a path rendered
  from a declaring expression, and one whose preconditions were checked;
- `StepSpec` and `Uses`: a step declared as a class, whose attributes are
  typed `Checked` paths inside ``with`` (descriptor typing, so both checkers
  infer them);
- `declared_by`: whether an annotation such as
  ``Checked[Literal["read"], IsFile]`` claims no more than an expression
  declares.

A static type certifies that a declaration is present. What the declaration
guarantees is the runtime's: ``Under`` holds for every rendered path (render
enforces it lexically); kind, existence and access hold when `check` or a
step's entry ran, and only then; ``post_*`` atoms are obligations checked
when a step exits. See docs/journal/2026-10-21-typed-path-families.md.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from types import GenericAlias, UnionType
from typing import (
    Any,
    Generic,
    Literal,
    NamedTuple,
    Never,
    TypeVar,
    Union,
    get_args,
    get_origin,
)

from .. import (
    Absent,
    Absolute,
    AnyPath,
    Creatable,
    Dir,
    Exists,
    File,
    Listable,
    P,
    Param,
    PathExpr,
    PathUnion,
    Readable,
    Segment,
    Step,
    SubPath,
    T,
    Writable,
)
from .. import conditions as _conditions
from .._expr import _coerce


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


class Unspecified:
    """``File`` not declared."""


class IsFile(Unspecified):
    """``File`` declared, in ``requires`` or ``ensures``: nothing can be joined
    below the path (the runtime raises)."""


class Under(_conditions.Under):
    """`wend.Under`, subscriptable so annotations can name a base:
    ``Under[Literal["/srv/static"]]``. A literal string base gives the marker
    its identity; any other base is ``Under[str]``, "under its own base"."""

    __class_getitem__ = classmethod(GenericAlias)


C = TypeVar("C", contravariant=True, default=Never)
K = TypeVar("K", covariant=True, default=Unspecified)


class Resolved(Path, Generic[C, K]):
    """A path rendered from an expression declaring ``C`` and ``K``. Only its
    ``Under`` atoms are guarantees about the path itself."""


class Checked(Resolved[C, K]):
    """A path whose expression's preconditions were checked when it was
    realised: true at that moment, not necessarily now."""


# ---------------------------------------------------------------------------
# The abstraction: what an expression declares
# ---------------------------------------------------------------------------

_PRE = {
    File: "file",
    Dir: "dir",
    Readable: "read",
    Writable: "write",
    Creatable: "create",
    Listable: "list",
    Exists: "exists",
    Absent: "absent",
}


class Facts(NamedTuple):
    """What an expression declares, as the atoms its static type may name."""

    atoms: frozenset[str]
    kind: type[Unspecified]


def _under_atoms(c: _conditions.Under) -> set[str]:
    out = {"Under[str]"}
    if c.base.is_static:
        out.add(f"Under[{c.base.pattern!r}]")
    return out


def facts(e: PathExpr) -> Facts:
    """The atoms ``e`` declares: ``read``, ``write``, ``create``, ``list``,
    ``exists``, ``absent``, ``file``, ``dir`` for preconditions, the same with
    ``post_`` for postconditions, ``Under[str]`` for any containment and
    ``Under['<base>']`` for a static base; and `IsFile` if ``File`` is
    declared on either side (what forbids joining below)."""
    conds = e.conditions
    atoms: set[str] = set()
    kind: type[Unspecified] = IsFile if _conditions.declares_file(e) else Unspecified
    if conds is not None:
        for prefix, cs in (("", conds.requires), ("post_", conds.ensures)):
            for c in cs:
                if isinstance(c, _conditions.Under):
                    atoms |= _under_atoms(c)
                elif c in _PRE:
                    atoms.add(prefix + _PRE[c])
    return Facts(frozenset(atoms), kind)


def _atoms_of(tp: Any) -> frozenset[str] | None:
    """The atoms an annotation's capability argument names, or None if it
    names something this prototype cannot read."""
    if tp is Any:
        return None
    if tp is Never:
        return frozenset()
    if get_origin(tp) in (Union, UnionType):
        out: set[str] = set()
        for a in get_args(tp):
            got = _atoms_of(a)
            if got is None:
                return None
            out |= got
        return frozenset(out)
    if get_origin(tp) is Literal:
        return frozenset(str(a) for a in get_args(tp))
    if get_origin(tp) is Under:
        (b,) = get_args(tp)
        if b is str:
            return frozenset({"Under[str]"})
        if get_origin(b) is Literal:
            return frozenset(f"Under[{a!r}]" for a in get_args(b))
        return None
    return None


def declared_by(annotation: Any, e: PathExpr) -> bool:
    """Whether ``annotation`` (``PathExpr[...]``, ``Resolved[...]`` or
    ``Checked[...]``) claims no more than ``e`` declares: every atom it names
    is among ``facts(e).atoms``, and its kind, if any, is ``e``'s."""
    args = get_args(annotation)
    if not args:
        return True
    atoms = _atoms_of(args[0])
    if atoms is None:
        return False
    f = facts(e)
    if not atoms <= f.atoms:
        return False
    kind = args[1] if len(args) > 1 else Unspecified
    return kind is Unspecified or kind is f.kind


# ---------------------------------------------------------------------------
# Steps declared as classes
# ---------------------------------------------------------------------------


class Uses(Generic[C, K]):
    """One path of a `StepSpec`: on the class, the declaring expression; on
    an entered instance, the realised `Checked` path."""

    def __init__(self, expr: Any) -> None:
        self.expr: PathExpr = _coerce(expr, at_head=True)
        self.name = ""

    def __set_name__(self, owner: type, name: str) -> None:
        self.name = name

    def __get__(self, obj: Any, owner: type | None = None) -> Any:
        if obj is None:
            return self.expr
        realised = obj.__dict__.get("_realised")
        if realised is None:
            raise AttributeError(
                f"{self.name!r} is realised only inside `with {type(obj).__name__}(...)`"
            )
        return realised[self.name]


class StepSpec:
    """A pipeline step declared as a class of `Uses` attributes::

        class Convert(StepSpec):
            src = Uses(raw.requires(File, Exists, Readable))
            dst = Uses(out.requires(Absent, Creatable).ensures(File, Exists))

        with Convert(root="/data", name="a") as s:
            write(transform(read(s.src)), s.dst)

    Entering checks every precondition (as `wend.Step` does) and gives each
    attribute its `Checked` path; leaving without an exception checks every
    postcondition. ``Convert.src`` is the declaring expression, so effects
    and graphs read the same declarations the types do.
    """

    _uses: Mapping[str, Uses[Any, Any]] = {}

    def __init_subclass__(cls, **kw: Any) -> None:
        super().__init_subclass__(**kw)
        uses: dict[str, Uses[Any, Any]] = {}
        for klass in reversed(cls.__mro__):
            for n, v in vars(klass).items():
                if isinstance(v, Uses):
                    uses[n] = v
        cls._uses = uses

    @classmethod
    def step(cls) -> Step:
        return Step({n: u.expr for n, u in cls._uses.items()})

    @classmethod
    def effects(cls) -> list[Any]:
        return cls.step().effects()

    def __init__(self, mapping: Any = None, /, *, fs: Any = None, **kw: Any) -> None:
        self._mapping, self._kw, self._fs = mapping, kw, fs

    def __enter__(self) -> StepSpec:
        paths = type(self).step().check(self._mapping, fs=self._fs, **self._kw)
        self.__dict__["_realised"] = {n: Checked(p) for n, p in paths.items()}
        return self

    def __exit__(self, et: Any, ev: Any, tb: Any) -> None:
        if et is None:
            type(self).step().confirm(self._mapping, fs=self._fs, **self._kw)
