"""Three guarantees, as three types (research prototype; see
docs/journal/2026-10-22-typed-core.md).

- **It was true.** `Checked` and `Confirmed` (`wend._kinds`) are events: the
  atoms a check found true of a path, at a step's entry or exit. A run
  stamps each with its epoch, and `known` says whether no effect *of this
  run* has invalidated it since. Another writer is invisible to it.
- **Which object.** `Held` is an open regular file, opened beneath the
  run's root and judged on its descriptor (`confined.Confined`). Its type
  claims only what the descriptor keeps: its kind, and the access it was
  opened with. Not its contents, its size or its names.
- **It remains true.** `Sealed` is a copy of a held file's contents in a
  sealed memfd: no holder can change it, the kernel refuses (``EPERM``).

`Run` executes steps declared as classes (`Spec`, with `Uses` and `Holds`
attributes), confined to a root, and keeps knowledge keyed by rendered
strings (`knowledge.Knowledge`). Confinement removes one source of error,
aliasing (docs/journal/2026-10-22-aliasing.md §5), and nothing else: another
writer can still change, create or delete an ordinary file inside the root.
So `known` is knowledge *conditional on a closed world*, that no one but the
run's own steps writes below the root; it is never a fact about the
filesystem now.
"""

from __future__ import annotations

import fcntl
import os
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import Any, Generic, Literal, cast

from .._kinds import C, Checked, Confirmed, IsFile, K
from ..conditions import Step
from .confined import Confined
from .identity import Held as _Held
from .knowledge import MUTATING, Knowledge


__all__ = ["Held", "Holds", "Run", "Sealed", "Spec", "Uses", "seal"]


class Held(_Held, Generic[C, K]):  # noqa: UP046 (variance is declared, not inferred)
    """An open regular file, judged confined when it was opened. Durable
    while open: which object it is, its kind, the access it was opened with
    (``read`` or ``write``). Not durable: contents, size, names."""

    access: frozenset[str]

    def __init__(self, path: str, fd: int, access: frozenset[str]) -> None:
        super().__init__(path, fd)
        self.access = access

    @property
    def ident(self) -> tuple[int, int]:
        """The object, as (device, inode): fixed for as long as it is held."""
        return (self.stat.st_dev, self.stat.st_ino)


F_ADD_SEALS = 1033
F_SEAL_SEAL, F_SEAL_SHRINK, F_SEAL_GROW, F_SEAL_WRITE = 1, 2, 4, 8


class Sealed:
    """A copy of a held file's contents that nothing can change: a memfd with
    every write, shrink and grow sealed. ``source`` is the object it was
    copied from, and ``read`` gives the contents as they were then."""

    def __init__(self, data: bytes, source: tuple[int, int]) -> None:
        self.source = source
        self.fd = os.memfd_create("wend-sealed", os.MFD_ALLOW_SEALING | os.MFD_CLOEXEC)
        os.write(self.fd, data)
        fcntl.fcntl(
            self.fd,
            F_ADD_SEALS,
            F_SEAL_WRITE | F_SEAL_SHRINK | F_SEAL_GROW | F_SEAL_SEAL,
        )

    def read(self) -> bytes:
        return os.pread(self.fd, os.fstat(self.fd).st_size, 0)

    def close(self) -> None:
        os.close(self.fd)


def seal(h: Held[Literal["read"], IsFile]) -> Sealed:
    """The contents of ``h`` now, sealed. Another writer can still change the
    held file afterwards; it cannot change this copy."""
    return Sealed(h.read(), h.ident)


class Uses(Generic[C, K]):  # noqa: UP046
    """One path of a `Spec`: on the class, the declaring expression; on an
    entered instance, the `Checked` event of its entry."""

    def __init__(self, expr: Any) -> None:
        self.expr = expr
        self.name = ""

    def __set_name__(self, owner: type, name: str) -> None:
        self.name = name

    def __get__(self, obj: Any, owner: type | None = None) -> Any:
        if obj is None:
            return self.expr
        return obj._entered(self.name).checked


class Holds(Generic[C, K]):  # noqa: UP046
    """One input of a `Spec`, held open for reading on an entered instance: a
    `Held` file, judged confined when opened. The expression must declare
    that it is an existing, readable file (the stub says which)."""

    def __init__(self, expr: Any) -> None:
        d = expr.declares
        if not {"file", "exists", "read"} <= d.requires:
            raise TypeError(
                f"{expr.pattern!r} must require File, Exists and Readable to be held"
            )
        self.expr = expr
        self.name = ""

    def __set_name__(self, owner: type, name: str) -> None:
        self.name = name

    def __get__(self, obj: Any, owner: type | None = None) -> Any:
        if obj is None:
            return self.expr
        return obj._entered(self.name).held


class Spec:
    """A step declared as a class of `Uses` and `Holds` attributes, entered
    with `Run.enter`."""

    def __init__(self, entered: Mapping[str, _Port]) -> None:
        self.__dict__["_ports"] = entered

    def _entered(self, name: str) -> _Port:
        try:
            return self.__dict__["_ports"][name]
        except KeyError:
            raise AttributeError(f"{name!r} exists only inside `Run.enter`") from None

    @classmethod
    def ports(cls) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for klass in reversed(cls.__mro__):
            for n, v in vars(klass).items():
                if isinstance(v, (Uses, Holds)):
                    out[n] = v
        return out

    @classmethod
    def step(cls) -> Step:
        return Step({n: p.expr for n, p in cls.ports().items()})


class _Port:
    def __init__(self, checked: Checked[Any, Any], held: Held[Any, Any] | None) -> None:
        self.checked = checked
        self.held = held


class Run:
    """Steps run confined to ``root``, with what the run knows: each check
    is an event stamped with an epoch, and an event is `known` while no
    mutation of this run has invalidated its atoms."""

    def __init__(self, root: str) -> None:
        self.io = Confined(root)
        self.knowledge = Knowledge()
        self.epoch = 0
        self.confirmed: dict[str, Confirmed[Any, Any]] = {}

    def known(self, event: Checked[Any, Any] | Confirmed[Any, Any]) -> bool:
        """Whether no step of this run has invalidated ``event`` since: every
        atom it checked would still hold *if no one else wrote below the
        root*. Not whether it holds now; another writer is invisible here."""
        atoms: frozenset[str] = event.__dict__["atoms"]
        return all(self.knowledge.knows(a, str(event)) for a in atoms)

    def _event(self, cls: type, path: str, atoms: frozenset[str]) -> Any:
        e = cls(path)
        e.__dict__.update(atoms=atoms, epoch=self.epoch)
        return e

    @contextmanager
    def enter[S: Spec](self, spec: type[S], env: Mapping[str, Any]) -> Iterator[S]:
        """Check each port's preconditions beneath the root, hold each `Holds`
        input, run the body, forget what its mutations may change, check the
        postconditions and learn them, as `Confirmed` events in
        ``self.confirmed``."""
        self.epoch += 1
        ports, held = spec.ports(), []
        paths = {n: p.expr.render(env) for n, p in ports.items()}
        rels = {n: self.io.rel(paths[n]) for n in ports}
        entered: dict[str, _Port] = {}
        try:
            for n, p in ports.items():
                req = p.expr.declares.requires
                self.io.check(rels[n], req)
            for n, p in ports.items():
                req = p.expr.declares.requires
                self.knowledge.learn(req, paths[n])
                h = None
                if isinstance(p, Holds):
                    fd = self.io._open(rels[n], os.O_RDONLY)
                    h = Held(paths[n], fd, frozenset({"read"}))
                    held.append(h)
                entered[n] = _Port(self._event(Checked, paths[n], req), h)
            try:
                yield cast("S", spec(entered))
            finally:
                for n, p in ports.items():
                    if p.expr.declares.verbs & MUTATING:
                        self.knowledge.forget(paths[n])
            self.epoch += 1
            for n, p in ports.items():
                post = p.expr.declares.ensures
                self.io.check(rels[n], post)
                self.knowledge.learn(post, paths[n])
                self.confirmed[n] = self._event(Confirmed, paths[n], post)
        finally:
            for h in held:
                h.close()
