"""Outputs held for writing, and their publication (research prototype; see
docs/journal/2026-10-22-publication-and-consistency.md).

The counterpart of a held input. A `Draft` is a write capability for a new
object with no name: ``O_TMPFILE`` in a directory held beneath the run's
root. No reader that goes by names can open it while it is written, and
nothing is left behind if the writer fails or dies. A process that may
inspect the writer (its uid while it is dumpable, and root) can still reach
it through ``/proc``: read it, write it, name it (see `Draft`).
`Draft.publish` gives it a name in one system call, under a policy:

- ``"create"``: ``linkat``, which refuses an existing name (``EEXIST``);
- ``"replace"``: link under a fresh name, then ``renameat`` over the name;
  readers see the whole old object or the whole new one, never a mixture;
- ``"exchange"``: ``renameat2(RENAME_EXCHANGE)``, which swaps the two and
  so sees the object it replaced. With ``expect``, the object the caller
  last observed there, it is *exchange-and-validate*, an optimistic
  protocol and **not** a compare-and-swap: if another writer published in
  between, the exchange is undone and `Conflict` raised. Readers may see
  the withdrawn version meanwhile, and with three or more concurrent
  writers the undo, itself an unconditional exchange, can remove another
  writer's publication (docs/journal/2026-10-22-synthesis.md has the
  schedule). `Store` gives the conditional publication this cannot.

Publication spends the capability: the draft's descriptor is closed, so the
writer cannot change what it published (anyone else with write access to
the file still can). With ``durable=True`` the file is synced before it is
published and the directory after: the protocol for surviving a crash,
tested in one crash model (``tests/durability_test.py``, ext4 on a loop
device), not proven for any filesystem.

`Generation` publishes several outputs together: written into a new
directory no reader knows of, then published as one name. A reader that
holds that directory sees one generation of every output, so long as
nothing writes into a published generation, which nothing enforces: a
held directory pins names, not contents. `Store` is the versioned form
that enforces it (a manifest checked on every read, optionally immutable
members).
"""

from __future__ import annotations

import ctypes
import fcntl
import hashlib
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
    "InUse",
    "Inconsistent",
    "Modified",
    "Pinned",
    "Published",
    "Store",
    "Version",
    "VersionDraft",
    "invalidated",
    "renameat2",
]

Policy = Literal["create", "replace", "exchange"]
RENAME_NOREPLACE, RENAME_EXCHANGE = 1, 2


class Conflict(FileExistsError):
    """Another writer published at the name since the caller observed it."""


class Inconsistent(RuntimeError):
    """What a step used is not what its derivation would record: an input
    read differently from how it was observed at entry, or not the object
    the run itself published."""


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
    the capability to write it until it is published or abandoned. With
    ``held``, a descriptor of that directory, the draft is made there, not
    wherever ``directory`` leads by then.

    Nameless is not private. The object is reachable as ``/proc/<pid>/fd/N``
    by every process that may inspect the writer's (``ptrace``'s read check):
    processes of the writer's uid while it is dumpable, which is the default,
    and root always. Each of them can read it, write into it and give it a
    name, partial contents and all (docs/journal/2026-10-22-drafts.md). It is
    private against other unprivileged uids, and against the writer's own
    only if the writer's process is non-dumpable, a process-wide setting
    this library does not change."""

    io: Confined
    directory: str
    held: int | None = None
    dirfd: int = field(init=False)
    fd: int = field(init=False)
    spent: bool = field(init=False, default=False)

    def __post_init__(self) -> None:
        if self.held is None:
            self.dirfd = self.io._dir(self.directory)
        else:
            self.dirfd = os.dup(self.held)
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

    output: Published | Version
    inputs: dict[str, Fingerprint]

    def stale(self, io: Confined) -> dict[str, str]:
        from .fresh import revalidate

        out: dict[str, str] = {
            rel: v
            for rel, fp in self.inputs.items()
            if (v := revalidate(fp, io, rel)) != "unchanged"
        }
        if not self.output.current(io):
            # a name can be published over; a version can only be modified
            out[_rel(self.output)] = (
                "superseded" if isinstance(self.output, Published) else "modified"
            )
        return out


def _rel(p: Published | Version) -> str:
    if isinstance(p, Version):
        return p.rel
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
            ups = {
                i
                for i in d.inputs
                if i in doubt or any(i.startswith(f"{o}/") for o in doubt)
            }
            if not ups <= doubt.get(out, set()):
                doubt.setdefault(out, set()).update(ups)
                grew = True
    return doubt


# -- versioned generations ---------------------------------------------------


class Modified(ValueError):
    """A member of a pinned version does not hold what its manifest says."""


class InUse(BlockingIOError):
    """A reader holds the version: it cannot be reclaimed yet."""


@dataclass(frozen=True)
class Version:
    """A claimed version: the event of its commit, and the digest of its
    manifest, which is all a reader needs to verify every member later."""

    store: str
    n: int
    manifest: str

    @property
    def rel(self) -> str:
        return f"{self.store}/{Store.PREFIX}{self.n:06d}"

    def current(self, io: Confined) -> bool:
        """Whether every member still reads as committed (a version is never
        superseded, only modified or reclaimed)."""
        try:
            with Pinned(io, self.rel, self.manifest) as p:
                for name in p.manifest:
                    p.read(name)
        except Modified, OSError, WendError:
            return False
        return True


class Store:
    """Versions of a set of outputs, in one directory, never overwritten.
    Version ``n`` is claimed by renaming a filled hidden directory to
    ``v{n:06d}`` with ``RENAME_NOREPLACE``: if another writer claimed ``n``
    first the rename fails, and nothing of this version was ever visible
    under a version's name. With readers taking the highest version as
    current, a claim of ``n`` is "replace the current version if it is still
    ``n - 1``": the identity-conditioned compare-and-swap that exchange
    cannot give.

    What the kernel enforces is only that one directory holds each version's
    name. That the directory claimed is the one its writer filled, and that
    nobody writes into it, rests on the other processes: those of the
    writer's uid, and any other with write permission on the store's
    directory, can move, replace or claim a hidden draft. A commit detects
    each of these (`Inconsistent`) and returns no `Version`; it cannot
    prevent them (docs/journal/2026-10-22-drafts.md). A hidden draft is
    private (mode 0700) from other users while it is filled, though its name
    is listed to any who can read the store's directory.

    Each version holds a ``MANIFEST`` (one ``name sha256`` line per member);
    its commit returns a `Version` carrying the manifest's digest, for
    readers to check against (`pin`). The protocol, which writers must
    follow (docs/journal/2026-10-22-synthesis.md §3): claim only the version
    after the one read as latest; never write into a claimed version; never
    reclaim the latest; reclaim only through `reclaim`."""

    PREFIX = "v"

    def __init__(self, io: Confined, rel: str) -> None:
        self.io, self.rel = io, rel

    def versions(self) -> list[int]:
        return sorted(
            int(n[1:])
            for n in self.io.listdir(self.rel)
            if n.startswith(self.PREFIX) and n[1:].isdigit()
        )

    def latest(self) -> int | None:
        vs = self.versions()
        return vs[-1] if vs else None

    def begin(self, base: int | None) -> VersionDraft:
        """A new version derived from ``base`` (``None`` for the first): it
        will claim ``base + 1``."""
        return VersionDraft(self, 1 if base is None else base + 1)

    def pin(self, version: int, *, manifest: str | None = None) -> Pinned:
        """Hold version ``version`` (see `Pinned`)."""
        return Pinned(self.io, f"{self.rel}/{self.PREFIX}{version:06d}", manifest)

    def reclaim(self, version: int) -> None:
        """Remove a version no reader holds. Refused (`InUse`) while a
        `Pinned` reader holds its lease; a reader that pins afterwards finds
        no manifest and fails closed. Members made immutable are released
        first (which needs ``CAP_LINUX_IMMUTABLE``)."""
        if version == self.latest():
            raise ValueError(f"version {version} is the latest: it is current")
        name = f"{self.PREFIX}{version:06d}"
        parentfd = self.io._dir(self.rel)
        vfd = self.io._dir(f"{self.rel}/{name}")
        try:
            try:
                fcntl.flock(vfd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise InUse(f"version {version} is pinned by a reader") from None
            _set_immutable(vfd, False)
            names = os.listdir(vfd)
            # the manifest first: from here on a pin fails, not a read
            for m in sorted(names, key=lambda m: m != "MANIFEST"):
                mfd = openat2(vfd, m, os.O_RDONLY | os.O_NONBLOCK, Beneath.RESOLVE)
                try:
                    _set_immutable(mfd, False)
                finally:
                    os.close(mfd)
                os.unlink(m, dir_fd=vfd)
            os.rmdir(name, dir_fd=parentfd)
        finally:
            os.close(vfd)
            os.close(parentfd)


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _ident(fd: int) -> tuple[int, int]:
    s = os.fstat(fd)
    return (s.st_dev, s.st_ino)


def _ident_at(dirfd: int, name: str) -> tuple[int, int] | None:
    try:
        s = os.stat(name, dir_fd=dirfd, follow_symlinks=False)
    except FileNotFoundError:
        return None
    return (s.st_dev, s.st_ino)


class VersionDraft:
    """The next version of a `Store`, filled in a hidden directory, held by
    its descriptor: each member is a `Draft` made there, published under
    ``"create"``, whatever the hidden name leads to by then."""

    def __init__(self, store: Store, n: int) -> None:
        self.store, self.n = store, n
        self.parentfd = store.io._dir(store.rel)
        self.hidden = f".{store.PREFIX}{n:06d}.draft-{secrets.token_hex(6)}"
        try:
            # private while it is filled: other users may list its name, but
            # can neither enter it nor read what is in it
            os.mkdir(self.hidden, 0o700, dir_fd=self.parentfd)
            self.dirfd = openat2(
                self.parentfd,
                self.hidden,
                os.O_RDONLY | os.O_DIRECTORY,
                Beneath.RESOLVE,
            )
        except BaseException:
            os.close(self.parentfd)
            raise
        self.ident = _ident(self.dirfd)
        self.dir = f"{store.rel}/{self.hidden}"
        self.members: dict[str, str] = {}
        self.spent = False

    def add(self, name: str, data: bytes) -> None:
        if self.spent:
            raise ValueError("this version was committed or abandoned")
        if name == "MANIFEST":
            raise ValueError("MANIFEST is the version's own")
        d = Draft(self.store.io, self.dir, held=self.dirfd)
        d.write(data)
        d.publish(_name(name), policy="create")
        self.members[name] = _digest(data)

    def commit(self, *, immutable: bool = False) -> Version:
        """Claim the version. Raises `Conflict` if another writer claimed it;
        nothing of this version was visible under a version's name. Raises
        `Inconsistent` if the hidden directory was moved, replaced or claimed
        by another process: no `Version` is returned, and a version claimed
        by another is left as it is. With ``immutable`` (needs
        ``CAP_LINUX_IMMUTABLE``), every member is made immutable before the
        claim and the version directory after it (an immutable directory
        cannot be renamed): from then on no write, truncation, rename,
        unlink or link reaches them, through any descriptor or mapping,
        until the flag is cleared."""
        if self.spent:
            raise ValueError("this version was committed or abandoned")
        text = "".join(f"{n} {h}\n" for n, h in sorted(self.members.items())).encode()
        d = Draft(self.store.io, self.dir, held=self.dirfd)
        d.write(text)
        d.publish("MANIFEST", policy="create")
        name = f"{self.store.PREFIX}{self.n:06d}"
        outcome = "abandon"  # or "claimed", or "theirs": claimed, not by us
        try:
            if immutable:
                for m in [*self.members, "MANIFEST"]:
                    mfd = openat2(self.dirfd, m, os.O_RDONLY, Beneath.RESOLVE)
                    try:
                        _set_immutable(mfd)
                    finally:
                        os.close(mfd)
            os.fchmod(self.dirfd, 0o755)  # readable once claimed
            os.fsync(self.dirfd)
            if _ident_at(self.parentfd, self.hidden) != self.ident:
                if _ident_at(self.parentfd, name) == self.ident:
                    outcome = "theirs"
                    raise Inconsistent(
                        f"version {self.n} was claimed by another process, "
                        "with this draft's directory, before it was committed"
                    )
                raise Inconsistent(
                    f"version {self.n}'s hidden directory was moved or replaced "
                    "by another process"
                )
            try:
                renameat2(
                    self.parentfd, self.hidden, self.parentfd, name, RENAME_NOREPLACE
                )
            except FileExistsError:
                raise Conflict(
                    f"version {self.n} was claimed by another writer"
                ) from None
            except FileNotFoundError:
                if _ident_at(self.parentfd, name) == self.ident:
                    outcome = "theirs"
                    raise Inconsistent(
                        f"version {self.n} was claimed by another process, with "
                        "this draft's directory, as it was being claimed"
                    ) from None
                raise Inconsistent(
                    f"version {self.n}'s hidden directory was moved by another "
                    "process as it was claimed"
                ) from None
            if _ident_at(self.parentfd, name) != self.ident:
                raise Inconsistent(
                    f"version {self.n} was claimed with a directory another "
                    "process put in this draft's place: it is not this version"
                )
            outcome = "claimed"
            os.fsync(self.parentfd)
            if immutable:
                _set_immutable(self.dirfd)  # the same directory, now claimed
        finally:
            # Unclaimed, for any reason, it is removed: flagged members too,
            # which nothing else could delete. Claimed by another, it is a
            # version, and not this writer's to remove.
            self.abandon() if outcome == "abandon" else self._spend()
        return Version(self.store.rel, self.n, _digest(text))

    def abandon(self) -> None:
        """Give up the version: its members are removed through the held
        directory, and the directory too while its hidden name still leads
        to it (another process may have moved it)."""
        if self.spent:
            return
        try:
            for m in os.listdir(self.dirfd):
                try:
                    mfd = openat2(
                        self.dirfd, m, os.O_RDONLY | os.O_NONBLOCK, Beneath.RESOLVE
                    )
                    try:
                        _set_immutable(mfd, False)
                    finally:
                        os.close(mfd)
                    os.unlink(m, dir_fd=self.dirfd)
                except IsADirectoryError, PermissionError:
                    pass  # not a member this draft made
            if _ident_at(self.parentfd, self.hidden) == self.ident:
                os.rmdir(self.hidden, dir_fd=self.parentfd)
        finally:
            self._spend()

    def _spend(self) -> None:
        os.close(self.dirfd)
        os.close(self.parentfd)
        self.spent = True


FS_IOC_GETFLAGS, FS_IOC_SETFLAGS, FS_IMMUTABLE_FL = 0x80086601, 0x40086602, 0x10


def _set_immutable(fd: int, on: bool = True) -> None:
    flags = ctypes.c_long(0)
    fcntl.ioctl(fd, FS_IOC_GETFLAGS, flags)
    new = flags.value | FS_IMMUTABLE_FL if on else flags.value & ~FS_IMMUTABLE_FL
    if new != flags.value:  # clearing a flag never set needs no capability
        fcntl.ioctl(fd, FS_IOC_SETFLAGS, ctypes.c_long(new))


class Pinned:
    """A held version: its directory object, a shared lease on it, and its
    manifest as read once at pinning (checked against ``manifest``, the
    digest its commit returned, when the reader has it). Every member is
    read relative to the held directory, never by path again, and checked
    against the manifest before it is returned: a reader never uses bytes
    the version did not publish. A member changed since is refused
    (`Modified`), not read."""

    def __init__(self, io: Confined, rel: str, manifest: str | None) -> None:
        self.dirfd = io._dir(rel)
        try:
            fcntl.flock(self.dirfd, fcntl.LOCK_SH)  # the lease `reclaim` respects
            text = read_in(self.dirfd, "MANIFEST")
            if manifest is not None and _digest(text) != manifest:
                raise Modified(f"{rel}: its MANIFEST is not the one committed")
        except BaseException:
            os.close(self.dirfd)
            raise
        self.manifest: dict[str, str] = {}
        for line in text.decode().splitlines():
            name, _, digest = line.partition(" ")
            self.manifest[name] = digest

    def read(self, name: str) -> bytes:
        if name not in self.manifest:
            raise Modified(f"{name}: not a member of this version")
        data = read_in(self.dirfd, name)
        if _digest(data) != self.manifest[name]:
            raise Modified(f"{name}: not the contents its version published")
        return data

    def close(self) -> None:
        os.close(self.dirfd)  # and with it the lease

    def __enter__(self) -> Pinned:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
