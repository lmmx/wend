"""Three guarantees, as three types (research prototype; see
docs/journal/2026-10-22-typed-core.md).

- **It was true.** `Checked` and `Confirmed` (`wend._kinds`) are evidence:
  the atoms a check found true of one path, at a step's entry (what the
  path requires) or exit (what it ensures). They are not paths: a path
  derived from one carries no evidence. A run stamps each with its epoch,
  and `known` says whether no effect *of this run* has invalidated it
  since. Another writer is invisible to it.
- **Which object.** `Held` is an open regular file, opened beneath the
  run's root and judged on its descriptor (`confined.Confined`). Its type
  claims only what the descriptor keeps: its kind, and the access it was
  opened with. Not its contents, its size or its names.
- **It remains true.** `Sealed` is a copy of a held file's contents in a
  sealed memfd: no holder can change it, the kernel refuses (``EPERM``).

`Run` executes steps declared as classes (`Spec`, with `Uses`, `Holds`,
`Makes` and `Commits` attributes), confined to a root, and keeps knowledge keyed by rendered
strings (`knowledge.Knowledge`). Confinement removes one source of error,
aliasing (docs/journal/2026-10-22-aliasing.md §5), and nothing else: another
writer can still change, create or delete an ordinary file inside the root.
So `known` is knowledge *conditional on a closed world*, that no one but the
run's own steps writes below the root; it is never a fact about the
filesystem now.
"""

from __future__ import annotations

import fcntl
import hashlib
import os
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Generic, Literal, cast

from .._kinds import C, Checked, Confirmed, IsFile, K
from ..conditions import Step
from .confined import Confined
from .identity import Held as _Held
from .knowledge import MUTATING, Knowledge


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


class Held(_Held, Generic[C, K]):  # noqa: UP046 (variance is declared, not inferred)
    """An open regular file, judged confined when it was opened. Durable
    while open: which object it is, its kind, the access it was opened with
    (``read`` or ``write``). Not durable: contents, size, names."""

    access: frozenset[str]

    def __init__(self, path: str, fd: int, access: frozenset[str]) -> None:
        super().__init__(path, fd)
        self.access = access
        self.used: list[str] = []  # a digest of what each read returned

    def read(self) -> bytes:
        data = super().read()
        self.used.append(hashlib.sha256(data).hexdigest())
        return data

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


class Makes(Generic[C, K]):  # noqa: UP046
    """One output of a `Spec`: on an entered instance, a `publish.Draft` in the
    output's directory, which no reader can see. When the step finishes the
    run publishes it under the output's name (``"create"``: never over
    another file), confirms it, and records what it was made from. If the
    step fails the draft is abandoned and nothing appears. The expression
    must declare a new file (absent and creatable, a file once made)."""

    def __init__(self, expr: Any) -> None:
        d = expr.declares
        if not ({"absent", "create"} <= d.requires and {"file", "exists"} <= d.ensures):
            raise TypeError(
                f"{expr.pattern!r} must require Absent, Creatable and ensure File, Exists to be made"
            )
        self.expr = expr
        self.name = ""

    def __set_name__(self, owner: type, name: str) -> None:
        self.name = name

    def __get__(self, obj: Any, owner: type | None = None) -> Any:
        if obj is None:
            return self.expr
        return obj._entered(self.name).draft


class Commits(Generic[C, K]):  # noqa: UP046
    """A new version of a `publish.Store` (several outputs published as
    one): on an entered instance, a `publish.VersionDraft` that no reader
    can see. When the step finishes the run claims it as the version after
    the latest one seen at entry, or fails the step if another writer
    claimed that version first; if the step fails it is abandoned. The
    expression must declare a directory, made if missing."""

    def __init__(self, expr: Any, *, immutable: bool = False) -> None:
        d = expr.declares
        if not ("dir" in d.requires and {"dir", "exists"} <= d.ensures):
            raise TypeError(
                f"{expr.pattern!r} must require Dir and ensure Dir, Exists to hold versions"
            )
        self.expr = expr
        self.immutable = immutable
        self.name = ""

    def __set_name__(self, owner: type, name: str) -> None:
        self.name = name

    def __get__(self, obj: Any, owner: type | None = None) -> Any:
        if obj is None:
            return self.expr
        return obj._entered(self.name).draft


class Spec:
    """A step declared as a class of `Uses`, `Holds`, `Makes` and `Commits`
    attributes, entered with `Run.enter`."""

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
                if isinstance(v, (Uses, Holds, Makes, Commits)):
                    out[n] = v
        return out

    @classmethod
    def step(cls) -> Step:
        return Step({n: p.expr for n, p in cls.ports().items()})


class _Port:
    def __init__(
        self, checked: Checked[Any, Any], held: Held[Any, Any] | None, draft: Any = None
    ) -> None:
        self.checked = checked
        self.held = held
        self.draft = draft


class Run:
    """Steps run confined to ``root``, with what the run knows: each check
    is an event stamped with an epoch, and an event is `known` while no
    mutation of this run has invalidated its atoms."""

    def __init__(self, root: str, *, lease: bool = False) -> None:
        self.io = Confined(root)
        # Lease each held input (`fresh.Leases`): while a step runs, no
        # process can have it open for writing. Needs the inputs' owner or
        # CAP_LEASE; a step whose input has a writer fails at entry (`Busy`).
        self.lease = lease
        self.knowledge = Knowledge()
        self.epoch = 0
        # by path below the root: a port name recurs across steps
        self.confirmed: dict[str, Confirmed[Any, Any]] = {}
        # publish.Published by output path, publish.Version by store path
        self.published: dict[str, Any] = {}
        self.derivations: list[Any] = []  # publish.Derivation, in order

    def known(self, event: Checked[Any, Any] | Confirmed[Any, Any]) -> bool:
        """Whether no step of this run has invalidated ``event`` since: every
        atom it checked would still hold *if no one else wrote below the
        root*. Not whether it holds now; another writer is invisible here."""
        return all(self.knowledge.knows(a, str(event.path)) for a in event.atoms)

    def _event(self, cls: type, path: str, atoms: frozenset[str]) -> Any:
        return cls(Path(path), atoms, self.epoch)

    @contextmanager
    def enter[S: Spec](self, spec: type[S], env: Mapping[str, Any]) -> Iterator[S]:
        """Check each port's preconditions beneath the root, hold each `Holds`
        input, run the body, forget what its mutations may change, publish
        its outputs, check the postconditions and learn them, as `Confirmed`
        events in ``self.confirmed``.

        Two checks keep a derivation true to what the step did. An input this
        run published must still be that object with those contents when a
        later step holds it; and every read of an input during the step must
        return what was observed at entry. Otherwise the step's outputs are
        abandoned and `publish.Inconsistent` raised."""
        from .fresh import Leases, fingerprint
        from .publish import (
            Derivation,
            Draft,
            Inconsistent,
            Published,
            Store,
            VersionDraft,
        )

        self.epoch += 1
        ports = spec.ports()
        held: dict[str, Held[Any, Any]] = {}
        leases: list[Leases] = []
        drafts: dict[str, Draft | VersionDraft] = {}
        observed = {}
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
                h = d = None
                if isinstance(p, Holds):
                    fd = self.io._open(rels[n], os.O_RDONLY)
                    h = held[n] = Held(paths[n], fd, frozenset({"read"}))
                    if self.lease:  # before observing: frozen from here on
                        leases.append(Leases([fd]))
                    fp = observed[rels[n]] = fingerprint(fd, content=True)
                    mine = self.published.get(rels[n])
                    if isinstance(mine, Published) and (
                        (mine.fingerprint.ident, mine.fingerprint.digest)
                        != (fp.ident, fp.digest)
                    ):
                        raise Inconsistent(
                            f"{rels[n]} is not the file this run published there"
                        )
                elif isinstance(p, Makes):
                    # the output's directory, made if missing (directories
                    # become visible early; the file does not)
                    pfd, _ = self.io._parent(rels[n], make=True)
                    os.close(pfd)
                    d = drafts[n] = Draft(self.io, rels[n].rpartition("/")[0])
                elif isinstance(p, Commits):
                    try:
                        self.io.mkdir(rels[n])
                    except FileExistsError:
                        pass
                    store = Store(self.io, rels[n])
                    d = drafts[n] = store.begin(store.latest())
                entered[n] = _Port(self._event(Checked, paths[n], req), h, d)
            try:
                yield cast("S", spec(entered))
                if not all(lease.unbroken() for lease in leases):
                    raise Inconsistent(
                        "an input was asked for, for writing, during the step"
                    )
                for n, h in held.items():
                    if any(u != observed[rels[n]].digest for u in h.used):
                        raise Inconsistent(
                            f"{rels[n]} changed while the step read it: what it "
                            "used is not what was observed at entry"
                        )
            except BaseException:
                for d in drafts.values():
                    d.abandon()
                raise
            finally:
                for n, p in ports.items():
                    if p.expr.declares.verbs & MUTATING:
                        self.knowledge.forget(paths[n])
            # Each output is published whole, one after another: a failure
            # here leaves the earlier ones published (a `Commits` output
            # publishes several together).
            try:
                for n, d in drafts.items():
                    if isinstance(d, VersionDraft):
                        out = d.commit(immutable=ports[n].immutable)
                    else:
                        out = d.publish(rels[n].rpartition("/")[2], policy="create")
                    self.published[rels[n]] = out
                    self.derivations.append(Derivation(out, dict(observed)))
            finally:
                for d in drafts.values():
                    d.abandon()
            self.epoch += 1
            for n, p in ports.items():
                post = p.expr.declares.ensures
                self.io.check(rels[n], post)
                self.knowledge.learn(post, paths[n])
                self.confirmed[rels[n]] = self._event(Confirmed, paths[n], post)
        finally:
            for lease in leases:
                lease.release()
            for h in held.values():
                h.close()
