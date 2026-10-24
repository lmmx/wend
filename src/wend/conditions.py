"""Conditions: what a path must be, and may be used for, when it is realised.

An expression can declare conditions about the filesystem (``Exists``,
``Absent``), about the kind of thing it names (``File``, ``Dir``), about how it
will be used (``Readable``, ``Writable``, ``Creatable``, ``Listable``) and
about where it may lead (``Under(base)``)::

    src = (P(root) / "raw" / T(t"{name}.csv")).requires(File, Exists, Readable)
    dst = (P(root) / "out" / T(t"{name}.parquet")).requires(Absent, Creatable)
    dst = dst.ensures(File, Exists)

`PathExpr.render` stays pure: the only condition it enforces is the lexical
part of ``Under``, which needs no filesystem. Everything else is checked by an
explicit step, `PathExpr.check` (preconditions) and `PathExpr.confirm`
(postconditions), or by a `Step` that groups the paths of one pipeline step.

Checks are point in time. A path that exists when it is checked may be gone
when it is opened, and a symlink may be swapped between the two: checks
describe and catch mistakes, they are not a sandbox and do not prevent races.
See docs/SEMANTICS.md §10.
"""

from __future__ import annotations

import os
import stat
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, NamedTuple

from .errors import (
    CapabilityError,
    ContainmentError,
    IndeterminateError,
    MissingPathError,
    PathExistsError,
    PathOperationError,
    WrongKindError,
)


if TYPE_CHECKING:
    from ._expr import PathExpr
    from .schema import Entry


__all__ = [
    "Absent",
    "Condition",
    "Creatable",
    "Declarations",
    "Dir",
    "Effect",
    "Exists",
    "File",
    "Listable",
    "Readable",
    "Step",
    "Under",
    "Writable",
]


class Condition:
    """A property of a path, checked when the path is realised."""

    __slots__ = ("name",)

    def __init__(self, name: str) -> None:
        self.name = name

    def __repr__(self) -> str:
        return self.name

    def __reduce__(self) -> str:
        return self.name  # the module-level singleton of that name

    def __call__(
        self,
        path: Any,
        /,
        *,
        optional: bool = False,
        many: bool = False,
        open: bool = False,
    ) -> Entry:
        """``File(path, ...)`` and ``Dir(path, ...)`` declare a schema entry
        (see `wend.schema`): a relative path that names a file or directory,
        with its cardinality. Other conditions are not callable."""
        if self.name not in ("File", "Dir"):
            raise TypeError(f"{self.name} is a condition, not a schema entry")
        from .schema import Entry

        kind = "file" if self.name == "File" else "dir"
        return Entry(path, kind, optional=optional, many=many, open=open)

    def __get_pydantic_core_schema__(self, source: Any, handler: Any) -> Any:
        """Pydantic's hook: ``Annotated[Path, File, Exists]`` checks each
        condition when a model is validated (see `wend.pydantic`, which needs
        ``wend[pydantic]``)."""
        from .pydantic import condition_schema

        return condition_schema(self, source, handler)


Exists = Condition("Exists")
"""Something exists at the path (symlinks are followed)."""

Absent = Condition("Absent")
"""Nothing occupies the path's name, not even a broken symlink."""

File = Condition("File")
"""The path names a regular file: if it exists it is one, and nothing can be
joined below it. Add ``Exists`` to require that it exists."""

Dir = Condition("Dir")
"""The path names a directory: if it exists it is one."""

Readable = Condition("Readable")
"""The path exists and the process may read it."""

Writable = Condition("Writable")
"""The process may write the path: it exists and is writable, or it is
`Creatable`."""

Creatable = Condition("Creatable")
"""The path exists, or could be created now: its nearest existing ancestor is
a directory the process may write to and search."""

Listable = Condition("Listable")
"""The path is an existing directory the process may list."""

_SIMPLE = (Exists, Absent, File, Dir, Readable, Writable, Creatable, Listable)

# The effect each capability declares, for `Step.effects`.
# Pairs that cannot hold together in one phase.
_CONTRADICTIONS = (
    (Exists, Absent),
    (File, Dir),
    (Absent, Readable),
    (Absent, Listable),
    (File, Listable),
)


@dataclass(frozen=True)
class Under(Condition):
    """The path stays under ``base``: lexically when it is rendered, and after
    resolving symlinks when it is checked.

    ``base`` is rendered with the same bindings as the path, so its parameters
    must be among the path's. Lexically, the path must start with the base's
    components and have no ``..`` after them.
    """

    base: PathExpr

    def __init__(self, base: Any) -> None:
        from ._expr import _coerce

        object.__setattr__(self, "base", _coerce(base, at_head=True))

    @property  # type: ignore[override]
    def name(self) -> str:
        return f"Under({self.base.pattern!r})"

    def __repr__(self) -> str:
        return self.name

    def __reduce__(self) -> Any:  # type: ignore[override]
        return Under, (self.base,)


class Conditions(NamedTuple):
    """The conditions declared on an expression."""

    requires: tuple[Condition, ...]
    ensures: tuple[Condition, ...]

    @property
    def bases(self) -> tuple[PathExpr, ...]:
        return tuple(
            c.base for c in (*self.requires, *self.ensures) if isinstance(c, Under)
        )


# The atom each condition other than ``Under`` declares (§10.1).
ATOMS: dict[Condition, str] = {
    Exists: "exists",
    Absent: "absent",
    File: "file",
    Dir: "dir",
    Readable: "read",
    Writable: "write",
    Creatable: "create",
    Listable: "list",
}
_PERMISSIONS = ("read", "write", "create", "list")


class Declarations(NamedTuple):
    """What an expression declares (docs/SEMANTICS.md §10.1): the atoms it
    requires before it is used, the atoms it ensures after it is produced,
    and the bases it is declared `Under`.

    A declaration is an obligation, not a fact about the filesystem. Only
    containment holds of every path the expression renders (`render` checks
    it); every other atom holds when a check finds it, at that moment.
    """

    requires: frozenset[str]
    ensures: frozenset[str]
    under: tuple[PathExpr, ...]

    @property
    def verbs(self) -> frozenset[str]:
        """The effects declared (what `Step.effects` reports): each permission
        in either phase, ``create`` for ``exists`` ensured but not required,
        and ``delete`` for ``absent`` ensured but not required."""
        pre, post = self.requires, self.ensures
        out = {v for v in _PERMISSIONS if v in pre or v in post}
        if "exists" in post and "exists" not in pre:
            out.add("create")
        if "absent" in post and "absent" not in pre:
            out.add("delete")
        return frozenset(out)

    def __and__(self, other: object) -> Declarations:
        """What both declare: the atoms of each phase in both, and the bases
        both are declared under."""
        if not isinstance(other, Declarations):
            return NotImplemented
        return Declarations(
            self.requires & other.requires,
            self.ensures & other.ensures,
            tuple(b for b in self.under if b in other.under),
        )


NONE = Declarations(frozenset(), frozenset(), ())


def declarations(conds: Conditions | None) -> Declarations:
    """The `Declarations` of an expression carrying ``conds``."""
    if conds is None:
        return NONE
    under: list[PathExpr] = []
    for c in (*conds.requires, *conds.ensures):
        if isinstance(c, Under) and c.base not in under:
            under.append(c.base)
    return Declarations(
        frozenset(ATOMS[c] for c in conds.requires if c in ATOMS),
        frozenset(ATOMS[c] for c in conds.ensures if c in ATOMS),
        tuple(under),
    )


# ---------------------------------------------------------------------------
# Declaring
# ---------------------------------------------------------------------------


def declare(
    e: PathExpr, requires: tuple[Any, ...], ensures: tuple[Any, ...]
) -> PathExpr:
    """``e`` with ``requires`` and ``ensures`` added to its conditions."""
    old = e.conditions
    pre = _merge(old.requires if old else (), requires, e)
    post = _merge(old.ensures if old else (), ensures, e)
    return attach(e, Conditions(pre, post))


def attach(e: PathExpr, conds: Conditions | None) -> PathExpr:
    """A copy of ``e`` (same path and derivation) carrying ``conds``."""
    from ._expr import PathExpr

    out = PathExpr(e.head, e.parts)
    if e.derivation is not None:
        out.__dict__["derivation"] = e.derivation
    if e.tags:
        out.__dict__["tags"] = e.tags
    if conds is not None and (conds.requires or conds.ensures):
        out.__dict__["conditions"] = conds
    return out


def _merge(
    have: tuple[Condition, ...], new: tuple[Any, ...], e: PathExpr
) -> tuple[Condition, ...]:
    out = list(have)
    for c in new:
        if not isinstance(c, Condition):
            raise TypeError(f"Expected a wend condition, not {c!r}")
        if isinstance(c, Under):
            extra = c.base.param_names - e.param_names
            if extra:
                raise PathOperationError(
                    f"{c!r} uses parameters {sorted(extra)} that"
                    f" {e.pattern!r} does not have"
                )
        if c not in out:
            out.append(c)
    for a, b in _CONTRADICTIONS:
        if a in out and b in out:
            raise PathOperationError(f"{e.pattern!r} cannot be both {a!r} and {b!r}")
    return tuple(out)


def declares_file(e: PathExpr) -> bool:
    c = e.conditions
    return c is not None and (File in c.requires or File in c.ensures)


def moved(conds: Conditions | None, move: Any) -> Conditions | None:
    """``conds`` with each ``Under`` base passed through ``move``."""
    if conds is None or not conds.bases:
        return conds

    def one(c: Condition) -> Condition:
        return Under(move(c.base)) if isinstance(c, Under) else c

    return Conditions(tuple(map(one, conds.requires)), tuple(map(one, conds.ensures)))


# ---------------------------------------------------------------------------
# Containment
# ---------------------------------------------------------------------------


def contained(path: str, base: str) -> bool:
    """Whether ``path`` is lexically ``base`` or below it: same anchor, the
    base's components first, and no ``..`` after them.

    Both are canonical path strings (as `render` returns them): no empty or
    ``.`` components, no trailing separator, and a leading ``//`` only as the
    anchor.
    """
    if path == base:
        return True
    if _anchor(path) != _anchor(base):
        return False
    if base == ".":
        rest = path
    elif path.startswith(base if base.endswith("/") else base + "/"):
        rest = path[len(base) :].lstrip("/")
    else:
        return False
    return not (
        rest == ".." or rest.startswith("../") or rest.endswith("/..") or "/../" in rest
    )


def _anchor(s: str) -> str:
    if s.startswith("/"):
        return "//" if s.startswith("//") and not s.startswith("///") else "/"
    return ""


def guard(e: PathExpr, s: str, env: Mapping[str, Any]) -> str:
    """``s`` (``e`` rendered with ``env``) if it is under each declared base."""
    conds = e.conditions
    assert conds is not None
    for base in conds.bases:
        b = base._compiled.render(env)
        if not contained(s, b):
            raise ContainmentError(s, Under(base), f"is not under {b!r}")
    return s


def guarded(e: PathExpr, fn: Any) -> Any:
    """``fn`` (a compiled renderer of ``e``) checking ``e``'s ``Under`` bases."""
    conds = e.conditions
    assert conds is not None
    checks = tuple((b._compiled._fn, Under(b)) for b in conds.bases)

    def render(env: Any) -> str:
        s = fn(env)
        for base_fn, c in checks:
            b = base_fn(env)
            if not contained(s, b):
                raise ContainmentError(s, c, f"is not under {b!r}")
        return s

    return render


def _resolves_under(path: str, base: str) -> bool:
    rp, rb = os.path.realpath(path), os.path.realpath(base)
    return rp == rb or rp.startswith(rb.rstrip("/") + "/")


# ---------------------------------------------------------------------------
# Checking
# ---------------------------------------------------------------------------


class _Probe:
    """One path's filesystem state, looked up once per check."""

    def __init__(self, path: str) -> None:
        self.path = path
        self._st: Any = ...
        self._lst: Any = ...

    def _get(self, fn: Any) -> os.stat_result | None:
        try:
            return fn(self.path)
        except FileNotFoundError, NotADirectoryError:
            return None
        except OSError as e:
            raise IndeterminateError(
                self.path, None, f"could not be checked: {e}"
            ) from e

    @property
    def st(self) -> os.stat_result | None:
        if self._st is ...:
            self._st = self._get(os.stat)
        return self._st

    @property
    def lst(self) -> os.stat_result | None:
        if self._lst is ...:
            self._lst = self._get(os.lstat)
        return self._lst


def _ancestor(path: str) -> str:
    """The nearest existing ancestor of ``path``."""
    d = path
    while True:
        parent = os.path.dirname(d) or "."
        if parent == d or os.path.exists(parent):
            return parent
        d = parent


def _creatable(p: _Probe, c: Condition) -> None:
    if p.st is not None:
        return
    anc = _ancestor(p.path)
    if not os.path.isdir(anc):
        raise CapabilityError(
            p.path, c, f"cannot be created: {anc!r} is not a directory"
        )
    if not os.access(anc, os.W_OK | os.X_OK):
        raise CapabilityError(p.path, c, f"cannot be created in {anc!r}")


def _check_one(p: _Probe, c: Condition, env: Mapping[str, Any]) -> None:
    s = p.path
    if isinstance(c, Under):
        b = c.base._compiled.render(env)
        if not contained(s, b):
            raise ContainmentError(s, c, f"is not under {b!r}")
        if not _resolves_under(s, b):
            raise ContainmentError(s, c, f"resolves outside {b!r}")
    elif c is Exists:
        if p.st is None:
            raise MissingPathError(s, c, "does not exist")
    elif c is Absent:
        if p.lst is not None:
            raise PathExistsError(s, c, "already exists")
    elif c is File:
        if p.st is not None and not stat.S_ISREG(p.st.st_mode):
            raise WrongKindError(s, c, "is not a regular file")
    elif c is Dir:
        if p.st is not None and not stat.S_ISDIR(p.st.st_mode):
            raise WrongKindError(s, c, "is not a directory")
    elif c is Readable:
        if p.st is None:
            raise MissingPathError(s, c, "does not exist")
        if not os.access(s, os.R_OK):
            raise CapabilityError(s, c, "is not readable")
    elif c is Listable:
        if p.st is None:
            raise MissingPathError(s, c, "does not exist")
        if not stat.S_ISDIR(p.st.st_mode):
            raise WrongKindError(s, c, "is not a directory")
        if not os.access(s, os.R_OK | os.X_OK):
            raise CapabilityError(s, c, "is not listable")
    elif c is Writable:
        if p.st is None:
            _creatable(p, c)
        else:
            mode = os.W_OK | (os.X_OK if stat.S_ISDIR(p.st.st_mode) else 0)
            if not os.access(s, mode):
                raise CapabilityError(s, c, "is not writable")
    elif c is Creatable:
        _creatable(p, c)
    else:  # pragma: no cover - every condition is handled above
        raise TypeError(f"Unknown condition {c!r}")


# -- Other filesystems --------------------------------------------------------
#
# A store has no permission bits, so each capability is what the store can
# report: True (holds), False (known not to), or None (cannot be determined
# without exercising it). A condition that cannot be determined raises
# IndeterminateError; it is never reported as false.

# Stores whose object metadata takes the same permission as the object's
# content: S3 HEAD needs s3:GetObject, GCS storage.objects.get, Azure blob
# read. A successful lookup of an object there shows it can be read.
_METADATA_IS_READ = frozenset(
    {"s3", "s3a", "gs", "gcs", "abfs", "abfss", "az", "adl", "memory"}
)
# Filesystems that never accept writes.
_READ_ONLY = frozenset({"http", "https", "github", "zip", "tar", "libarchive"})
# Filesystems that accept every write (nothing to authorise).
_ALWAYS_WRITABLE = frozenset({"memory"})


class _StoreProbe:
    """One path's state on an fsspec filesystem, looked up once per check.

    Unlike discovery, which reads a path it may not see as absent, a check
    tells a missing path (None) from one it cannot look at, which raises
    `IndeterminateError`.
    """

    def __init__(self, fs: Any, path: str) -> None:
        from .fs import _protocols

        self.fs = fs
        self.path = path
        self.protocols = _protocols(fs.fs)
        self._kind: Any = ...

    def _unknown(self, c: Any, e: BaseException) -> IndeterminateError:
        return IndeterminateError(self.path, c, f"could not be checked: {e}")

    @property
    def kind(self) -> str | None:
        if self._kind is ...:
            from .fs import _info_kind

            try:
                info = self.fs.fs.info(self.fs._path(self.path))
            except FileNotFoundError, NotADirectoryError:
                self._kind = None
            except OSError as e:  # PermissionError among them: not absent
                raise self._unknown(None, e) from e
            else:
                self._kind = _info_kind(info.get("name", ""), info)
        return self._kind

    def listable(self, c: Condition) -> bool:
        try:
            self.fs.fs.ls(self.fs._path(self.path), detail=False)
        except PermissionError:
            return False
        except OSError as e:
            raise self._unknown(c, e) from e
        return True

    def readable(self, c: Condition) -> bool | None:
        if self.kind == "dir":
            return self.listable(c)
        return True if self.protocols & _METADATA_IS_READ else None

    def writable(self) -> bool | None:
        if self.protocols & _READ_ONLY:
            return False
        if self.protocols & _ALWAYS_WRITABLE:
            return True
        return None


def _capability(
    p: _StoreProbe, c: Condition, ok: bool | None, fails: str, why: str
) -> None:
    if ok is None:
        raise IndeterminateError(p.path, c, f"could not be checked: {why}")
    if not ok:
        raise CapabilityError(p.path, c, fails)


def _check_store(p: _StoreProbe, c: Condition, env: Mapping[str, Any]) -> None:
    s = p.path
    protocol = "/".join(sorted(p.protocols))
    if isinstance(c, Under):
        b = c.base._compiled.render(env)
        if not contained(s, b):  # a store has no symlinks: s resolves to itself
            raise ContainmentError(s, c, f"is not under {b!r}")
    elif c is Exists:
        if p.kind is None:
            raise MissingPathError(s, c, "does not exist")
    elif c is Absent:
        if p.kind is not None:
            raise PathExistsError(s, c, "already exists")
    elif c is File:
        if p.kind not in (None, "file"):
            raise WrongKindError(s, c, "is not a regular file")
    elif c is Dir:
        if p.kind not in (None, "dir"):
            raise WrongKindError(s, c, "is not a directory")
    elif c is Readable:
        if p.kind is None:
            raise MissingPathError(s, c, "does not exist")
        why = f"{protocol} metadata does not show whether the content can be read"
        _capability(p, c, p.readable(c), "is not readable", why)
    elif c is Listable:
        if p.kind is None:
            raise MissingPathError(s, c, "does not exist")
        if p.kind != "dir":
            raise WrongKindError(s, c, "is not a directory")
        _capability(p, c, p.listable(c), "is not listable", "")
    elif c is Writable or c is Creatable:
        if c is Creatable and p.kind is not None:
            return
        fails = "is not writable" if c is Writable else "cannot be created"
        why = f"{protocol} storage cannot report whether a write would succeed without writing"
        _capability(p, c, p.writable(), f"{fails}: {protocol} is read-only", why)
    else:  # pragma: no cover - every condition is handled above
        raise TypeError(f"Unknown condition {c!r}")


def _order(c: Condition) -> int:
    # Containment first: no other check should touch a path outside its base.
    return -1 if isinstance(c, Under) else _SIMPLE.index(c)


def check_conditions(
    s: str, conds: tuple[Condition, ...], env: Mapping[str, Any], fs: Any = None
) -> None:
    """Raise the first `ConditionError` among ``conds`` for the path ``s`` on
    ``fs`` (a `wend.fs` filesystem; the local disk by default)."""
    from .fs import FsspecFS, LocalFS

    ordered = sorted(conds, key=_order)
    if fs is None or isinstance(fs, LocalFS):
        p = _Probe(s)
        for c in ordered:
            _check_one(p, c, env)
    elif isinstance(fs, FsspecFS):
        q = _StoreProbe(fs, s)
        for c in ordered:
            _check_store(q, c, env)
    else:
        raise TypeError(
            f"conditions are checked on the local disk or a wend.fs.FsspecFS, not {fs!r}"
        )


def realise(
    e: PathExpr, env: Mapping[str, Any], *, after: bool, fs: Any = None
) -> Path:
    """Render ``e`` and check its preconditions (or, ``after``, postconditions)
    on ``fs``."""
    s = e.render(env)
    conds = e.conditions
    if conds is not None:
        check_conditions(s, conds.ensures if after else conds.requires, env, fs)
    return Path(s)


def _check_fs_option(method: str, owner: Any, env: Mapping[str, Any], fs: Any) -> None:
    """The ``fs=`` option, kept apart from a parameter named ``fs``."""
    from .errors import _check_option_keywords

    _check_option_keywords(method, owner, env, [("fs", fs, None)])


# ---------------------------------------------------------------------------
# Steps and effects
# ---------------------------------------------------------------------------


class Effect(NamedTuple):
    """What a step may do to one of its paths, as declared."""

    name: str
    expr: PathExpr
    verbs: frozenset[str]

    def __repr__(self) -> str:
        verbs = ", ".join(sorted(self.verbs)) or "uses"
        return f"<{self.name}: {verbs} {self.expr.pattern}>"


class Step:
    """The paths one step of a pipeline uses, with their conditions.

    A single declaration of what must hold before the step runs (each path's
    `requires`) and after it finishes (each path's `ensures`)::

        convert = Step(src=src, dst=dst)
        with convert(root="/data", name="a") as p:
            write(transform(read(p["src"])), p["dst"])

    Entering checks every precondition and yields the rendered paths; leaving
    without an exception checks every postcondition. The bindings are shared:
    each path takes the parameters it uses.
    """

    def __init__(self, paths: Mapping[str, Any] | None = None, /, **named: Any) -> None:
        from ._expr import _coerce

        self.paths: dict[str, PathExpr] = {
            k: _coerce(v, at_head=True) for k, v in {**(paths or {}), **named}.items()
        }

    def __repr__(self) -> str:
        return f"Step({', '.join(f'{k}={v.pattern!r}' for k, v in self.paths.items())})"

    @property
    def param_names(self) -> frozenset[str]:
        return frozenset().union(*(e.param_names for e in self.paths.values()))

    @property
    def pattern(self) -> str:
        return repr(self)

    def _realise(
        self, mapping: Any, kw: dict[str, Any], after: bool, fs: Any
    ) -> dict[str, Path]:
        from ._expr import _make_env

        env = _make_env(mapping, kw)
        _check_fs_option("confirm" if after else "check", self, env, fs)
        return {k: realise(e, env, after=after, fs=fs) for k, e in self.paths.items()}

    def check(
        self, mapping: Any = None, /, *, fs: Any = None, **kw: Any
    ) -> dict[str, Path]:
        """Render every path and check its preconditions, in declaration order,
        on ``fs`` (a `wend.fs` filesystem; the local disk by default)."""
        return self._realise(mapping, kw, False, fs)

    def confirm(
        self, mapping: Any = None, /, *, fs: Any = None, **kw: Any
    ) -> dict[str, Path]:
        """Render every path and check its postconditions, in declaration order,
        on ``fs``."""
        return self._realise(mapping, kw, True, fs)

    @contextmanager
    def __call__(
        self, mapping: Any = None, /, *, fs: Any = None, **kw: Any
    ) -> Iterator[dict[str, Path]]:
        paths = self.check(mapping, fs=fs, **kw)
        yield paths
        self.confirm(mapping, fs=fs, **kw)

    def effects(self) -> list[Effect]:
        """The filesystem effects each path declares: ``read``, ``write``,
        ``create``, ``list`` (capabilities), plus ``create`` for a path that
        must exist afterwards but need not before, and ``delete`` for one that
        must be absent afterwards but need not be before. Paths declaring none
        are listed with no verbs. This reports declarations, not behaviour."""
        return [Effect(k, e, e.declares.verbs) for k, e in self.paths.items()]
