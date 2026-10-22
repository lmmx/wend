"""Outputs held for writing, and their publication (research prototype; see
docs/journal/2026-10-22-publication-and-consistency.md).

The counterpart of a held input. A `Draft` is a write capability for a new
object with no name: ``O_TMPFILE`` in a directory held beneath the run's
root. No reader can open it by any name while it is written, and nothing is
left behind if the writer fails or dies. `Draft.publish` gives it a name in
one system call, under a policy:

- ``"create"``: ``linkat``, which refuses an existing name (``EEXIST``);
- ``"replace"``: link under a fresh name, then ``renameat`` over the name;
  readers see the whole old object or the whole new one, never a mixture;
- ``"exchange"``: ``renameat2(RENAME_EXCHANGE)``, which swaps the two and
  so sees the object it replaced. With ``expect``, the object the caller
  last observed there, it is a compare-and-swap after the fact: if another
  writer published in between, the exchange is undone and `Conflict`
  raised. Readers may have seen the withdrawn version meanwhile.

Publication spends the capability: the draft's descriptor is closed, so the
writer cannot change what it published (anyone else with write access to
the file still can). With ``durable=True`` the file is synced before it is
published and the directory after: the protocol for surviving a crash,
which is argued, not tested here.

`Generation` publishes several outputs together: written into a new
directory no reader knows of, then published as one name. A reader that
holds that directory sees one generation of every output; a reader that
opens them one name at a time may see two.
"""

from __future__ import annotations

import ctypes
import os
import secrets
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal

from ..errors import WendError
from .confined import Confined
from .fresh import Fingerprint, fingerprint
from .identity import Beneath, openat2


__all__ = [
    "Conflict",
    "Derivation",
    "Draft",
    "Generation",
    "Published",
    "invalidated",
    "renameat2",
]

Policy = Literal["create", "replace", "exchange"]
RENAME_NOREPLACE, RENAME_EXCHANGE = 1, 2


class Conflict(FileExistsError):
    """Another writer published at the name since the caller observed it."""


def renameat2(olddirfd: int, old: str, newdirfd: int, new: str, flags: int) -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    if (
        libc.renameat2(olddirfd, os.fsencode(old), newdirfd, os.fsencode(new), flags)
        != 0
    ):
        e = ctypes.get_errno()
        raise OSError(e, os.strerror(e), new)


def _name(name: str) -> str:
    if not name or "/" in name or name in (".", ".."):
        raise ValueError(f"{name!r} is not one name in a directory")
    return name


@dataclass
class Published:
    """A publication event: at this moment, ``name`` in ``directory`` named
    the object ``ident``, with these contents. A fact about that moment;
    `current` says whether it is still so, as observed."""

    directory: str
    name: str
    fingerprint: Fingerprint  # taken once published: linking changes ctime
    policy: Policy
    durable: bool
    previous: tuple[int, int] | None = None  # the object it replaced
    # Whether the object published still held what the draft wrote when its
    # fingerprint was taken: once it has a name, another writer can reach it.
    intact: bool = True
    # Whether the directory it was published in was, just after, still the
    # one at ``directory`` beneath the root. Publication is into the held
    # directory object; another writer can move that directory at any time.
    at_path: bool = True

    def current(self, io: Confined) -> bool:
        from .fresh import revalidate

        rel = f"{self.directory}/{self.name}" if self.directory else self.name
        return revalidate(self.fingerprint, io, rel) == "unchanged"


@dataclass
class Draft:
    """A new, nameless object in ``directory`` (below ``io``'s root), and
    the capability to write it until it is published or abandoned."""

    io: Confined
    directory: str
    dirfd: int = field(init=False)
    fd: int = field(init=False)
    spent: bool = field(init=False, default=False)

    def __post_init__(self) -> None:
        self.dirfd = self.io._dir(self.directory)
        try:
            self.fd = os.open(
                ".", os.O_TMPFILE | os.O_WRONLY | os.O_CLOEXEC, 0o644, dir_fd=self.dirfd
            )
        except BaseException:
            os.close(self.dirfd)
            raise

    def _live(self) -> None:
        if self.spent:
            raise ValueError(
                "this draft was published or abandoned: its capability is spent"
            )

    def write(self, data: bytes) -> None:
        self._live()
        view = memoryview(data)
        while view:
            view = view[os.write(self.fd, view) :]

    def publish(
        self,
        name: str,
        *,
        policy: Policy = "create",
        durable: bool = True,
        expect: tuple[int, int] | None = None,
    ) -> Published:
        """Give the draft ``name`` in its directory, in one system call, and
        spend the capability. Raises ``FileExistsError`` for ``"create"`` if
        the name is taken, or `Conflict` for ``"exchange"`` if the object
        there is not ``expect``; the draft is then unpublished, and live."""
        self._live()
        name = _name(name)
        if durable:
            os.fsync(self.fd)
        written = self._fingerprint().digest
        src = f"/proc/self/fd/{self.fd}"
        previous = None
        if policy == "create":
            os.link(src, name, dst_dir_fd=self.dirfd, follow_symlinks=True)
        else:
            tmp = self._link_fresh(src, name)
            try:
                if policy == "replace":
                    previous = self._ident_of(name)
                    os.rename(tmp, name, src_dir_fd=self.dirfd, dst_dir_fd=self.dirfd)
                else:
                    renameat2(self.dirfd, tmp, self.dirfd, name, RENAME_EXCHANGE)
                    previous = self._ident_of(tmp)
                    if expect is not None and previous != expect:
                        renameat2(self.dirfd, tmp, self.dirfd, name, RENAME_EXCHANGE)
                        raise Conflict(f"{name!r} changed since it was observed")
                    os.unlink(tmp, dir_fd=self.dirfd)
            except BaseException:
                try:
                    os.unlink(tmp, dir_fd=self.dirfd)
                except FileNotFoundError:
                    pass
                raise
        if durable:
            os.fsync(self.dirfd)
        fp = self._fingerprint()
        at_path = self._at_path()
        self._spend()
        return Published(
            self.directory,
            name,
            fp,
            policy,
            durable,
            previous,
            fp.digest == written,
            at_path,
        )

    def abandon(self) -> None:
        """Give up the draft: its object has no name, so closing frees it."""
        if not self.spent:
            self._spend()

    def _spend(self) -> None:
        os.close(self.fd)
        os.close(self.dirfd)
        self.spent = True

    def _fingerprint(self) -> Fingerprint:
        # Of what was written: read through a second descriptor for the
        # same object (the draft is write-only).
        fd = os.open(f"/proc/self/fd/{self.fd}", os.O_RDONLY | os.O_CLOEXEC)
        try:
            return fingerprint(fd, content=True)
        finally:
            os.close(fd)

    def _link_fresh(self, src: str, near: str) -> str:
        while True:
            tmp = f".{near}.{secrets.token_hex(6)}"
            try:
                os.link(src, tmp, dst_dir_fd=self.dirfd, follow_symlinks=True)
                return tmp
            except FileExistsError:
                continue

    def _at_path(self) -> bool:
        try:
            fd = self.io._dir(self.directory)
        except OSError, WendError:
            return False
        try:
            a, b = os.fstat(fd), os.fstat(self.dirfd)
            return (a.st_dev, a.st_ino) == (b.st_dev, b.st_ino)
        finally:
            os.close(fd)

    def _ident_of(self, name: str) -> tuple[int, int] | None:
        try:
            s = os.stat(name, dir_fd=self.dirfd, follow_symlinks=False)
        except FileNotFoundError:
            return None
        return (s.st_dev, s.st_ino)


class Generation:
    """Several outputs published together: each is drafted into a fresh
    directory that no reader knows of, published there, and the directory is
    then published under ``name`` in ``parent`` with one rename (or an
    exchange with the generation it replaces)."""

    def __init__(self, io: Confined, parent: str, name: str) -> None:
        self.io, self.parent, self.name = io, parent, _name(name)
        self.parentfd = io._dir(parent)
        self.hidden = f".{name}.gen-{secrets.token_hex(6)}"
        os.mkdir(self.hidden, 0o755, dir_fd=self.parentfd)
        self.dir = f"{parent}/{self.hidden}" if parent else self.hidden
        self.outputs: dict[str, Published] = {}

    def draft(self) -> Draft:
        return Draft(self.io, self.dir)

    def add(self, filename: str, data: bytes) -> None:
        d = self.draft()
        d.write(data)
        self.outputs[filename] = d.publish(filename, policy="create", durable=True)

    def commit(
        self, *, policy: Literal["create", "exchange"] = "exchange"
    ) -> str | None:
        """Publish every output at once. Returns the hidden name the old
        generation now has (kept, for readers that still hold it), if any."""
        genfd = self.io._dir(self.dir)
        try:
            os.fsync(genfd)
        finally:
            os.close(genfd)
        old = None
        if policy == "exchange":
            try:
                renameat2(
                    self.parentfd,
                    self.hidden,
                    self.parentfd,
                    self.name,
                    RENAME_EXCHANGE,
                )
                old = self.hidden
            except FileNotFoundError:  # nothing to exchange with: the first generation
                renameat2(
                    self.parentfd,
                    self.hidden,
                    self.parentfd,
                    self.name,
                    RENAME_NOREPLACE,
                )
        else:
            renameat2(
                self.parentfd, self.hidden, self.parentfd, self.name, RENAME_NOREPLACE
            )
        os.fsync(self.parentfd)
        os.close(self.parentfd)
        return old


def hold_dir(io: Confined, rel: str) -> int:
    """A directory held beneath the root: names opened relative to it all
    come from that directory object, whatever is published at ``rel`` later."""
    return io._dir(rel)


def read_in(dirfd: int, name: str) -> bytes:
    fd = openat2(dirfd, _name(name), os.O_RDONLY | os.O_NONBLOCK, Beneath.RESOLVE)
    try:
        out, off = [], 0
        while chunk := os.pread(fd, 1 << 20, off):
            out.append(chunk)
            off += len(chunk)
        return b"".join(out)
    finally:
        os.close(fd)


@dataclass
class Derivation:
    """An output and the observations of the inputs it was made from: the
    edge along which a change invalidates a result. `stale` revalidates each
    input, and the output itself, and names what no longer matches. Like any
    observation it detects; it cannot see a change that was undone."""

    output: Published
    inputs: dict[str, Fingerprint]

    def stale(self, io: Confined) -> dict[str, str]:
        from .fresh import revalidate

        out: dict[str, str] = {
            rel: v
            for rel, fp in self.inputs.items()
            if (v := revalidate(fp, io, rel)) != "unchanged"
        }
        if not self.output.current(io):
            rel = (
                f"{self.output.directory}/{self.output.name}"
                if self.output.directory
                else self.output.name
            )
            out[rel] = "superseded"
        return out


def _rel(p: Published) -> str:
    return f"{p.directory}/{p.name}" if p.directory else p.name


def invalidated(derivations: Sequence[Derivation], io: Confined) -> dict[str, set[str]]:
    """Every output whose result is in doubt, and why: an input that changed
    as observed (or the output itself superseded), or an input that is the
    output of another derivation in doubt. The effects graph, read as a
    dependency graph whose edges carry observations."""
    by_output = {_rel(d.output): d for d in derivations}
    doubt = {out: set(d.stale(io)) for out, d in by_output.items()}
    doubt = {out: why for out, why in doubt.items() if why}
    grew = True
    while grew:
        grew = False
        for out, d in by_output.items():
            ups = {i for i in d.inputs if i in doubt}
            if not ups <= doubt.get(out, set()):
                doubt.setdefault(out, set()).update(ups)
                grew = True
    return doubt
