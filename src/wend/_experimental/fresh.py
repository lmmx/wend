"""Freshness: what can be observed of a file between two moments (research
prototype; see docs/journal/2026-10-22-publication-and-consistency.md).

Three observers, none of which sees every change:

- `Fingerprint` with ``content=False``: the object and its metadata
  (device, inode, size, ``mtime``, ``ctime``). Misses a write into an
  already dirty page of a shared mapping, which updates neither time.
- `Fingerprint` with ``content=True``: also a digest of the contents. Sees
  any difference between the two moments, never a change that was undone
  in between.
- `Watch`: inotify on the held object, from one moment to the other. Sees
  a change that was undone, never a write through a shared mapping, and can
  overflow.

`revalidate` compares two observations; it detects, it never guarantees.
"unchanged" means *unchanged as observed at the two moments*. `collect`
is the double collect of the shared-memory snapshot literature, over
files: sound only if the observer sees every change, which none here does.

`Leases` is not an observer but an exclusion: a read lease is granted only
while no process has the file open for writing (through a descriptor or a
shared writable mapping), and any later open for writing breaks it; one
truncation does not, and a size recorded with the leases catches it. With
``observer="lease"``, `collect` copies inside an interval in which no
writer exists, which no observer can establish. The leases are taken by a
helper process, so that the signal announcing a break is never this
process's (docs/journal/2026-10-22-leases.md).
"""

from __future__ import annotations

import ctypes
import errno
import fcntl
import hashlib
import os
import struct
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Literal

from ..errors import WendError
from .confined import Confined
from .events import Sealed


__all__ = [
    "Busy",
    "Fingerprint",
    "LEASABLE",
    "Leases",
    "Unleasable",
    "Verdict",
    "Watch",
    "collect",
    "observe",
    "revalidate",
]

Verdict = Literal["unchanged", "changed", "replaced", "gone", "refused"]


@dataclass(frozen=True)
class Fingerprint:
    ident: tuple[int, int]  # (device, inode): which object
    size: int
    mtime_ns: int
    ctime_ns: int
    digest: str | None = None  # SHA-256 of the contents, if taken

    @property
    def meta(self) -> tuple[object, ...]:
        return (self.ident, self.size, self.mtime_ns, self.ctime_ns)


def fingerprint(fd: int, *, content: bool) -> Fingerprint:
    s = os.fstat(fd)
    digest = None
    if content:
        h, off = hashlib.sha256(), 0
        while chunk := os.pread(fd, 1 << 20, off):
            h.update(chunk)
            off += len(chunk)
        digest = h.hexdigest()
    return Fingerprint(
        (s.st_dev, s.st_ino), s.st_size, s.st_mtime_ns, s.st_ctime_ns, digest
    )


def observe(io: Confined, rel: str, *, content: bool = True) -> Fingerprint:
    """The object at ``rel`` now, opened beneath the root and judged."""
    fd = io._open(rel, os.O_RDONLY)
    try:
        return fingerprint(fd, content=content)
    finally:
        os.close(fd)


def revalidate(fp: Fingerprint, io: Confined, rel: str) -> Verdict:
    """``rel`` against an earlier observation, with the same observer: gone,
    no longer confined (another name was linked to it, a link replaced it:
    ``"refused"``), another object, changed as far as the observer sees, or
    unchanged *as observed* (not: unchanged in between)."""
    try:
        now = observe(io, rel, content=fp.digest is not None)
    except FileNotFoundError:
        return "gone"
    except WendError:
        return "refused"
    if now.ident != fp.ident:
        return "replaced"
    if now.meta != fp.meta or now.digest != fp.digest:
        return "changed"
    return "unchanged"


# -- inotify -----------------------------------------------------------------

IN_MODIFY, IN_ATTRIB, IN_CLOSE_WRITE = 0x2, 0x4, 0x8
IN_DELETE_SELF, IN_MOVE_SELF, IN_Q_OVERFLOW = 0x400, 0x800, 0x4000
_EVENT = struct.Struct("iIII")


class Watch:
    """inotify on open objects (each watched through its descriptor, so the
    watch is on the object, whatever its names): `changed` says whether any
    event, or an overflow, arrived since the watch began."""

    MASK = IN_MODIFY | IN_ATTRIB | IN_CLOSE_WRITE | IN_DELETE_SELF | IN_MOVE_SELF

    def __init__(self, fds: Sequence[int]) -> None:
        self._libc = ctypes.CDLL(None, use_errno=True)
        self.fd = self._libc.inotify_init1(os.O_NONBLOCK | os.O_CLOEXEC)
        if self.fd < 0:
            raise OSError(ctypes.get_errno(), "inotify_init1")
        for fd in fds:
            if (
                self._libc.inotify_add_watch(
                    self.fd, f"/proc/self/fd/{fd}".encode(), self.MASK
                )
                < 0
            ):
                raise OSError(ctypes.get_errno(), "inotify_add_watch")
        self.events = 0
        self.overflowed = False

    def drain(self) -> None:
        while True:
            try:
                buf = os.read(self.fd, 1 << 16)
            except BlockingIOError:
                return
            off = 0
            while off < len(buf):
                _, mask, _, ln = _EVENT.unpack_from(buf, off)
                self.events += 1
                self.overflowed |= bool(mask & IN_Q_OVERFLOW)
                off += _EVENT.size + ln

    def changed(self) -> bool:
        self.drain()
        return self.events > 0 or self.overflowed

    def close(self) -> None:
        os.close(self.fd)


# -- several inputs at once ----------------------------------------------------

Observer = Literal["meta", "digest", "meta+digest", "watch", "lease"]

F_SETSIG, F_SETLEASE, F_GETLEASE = 10, 1024, 1025


class Busy(BlockingIOError):
    """A process has the file open for writing: no lease, so no snapshot now."""


class Unleasable(OSError):
    """No lease can be had: not the file's owner and without ``CAP_LEASE``
    (``EACCES``), a file or filesystem without leases (``EINVAL``), or no
    helper process to take them."""


# The leases are taken by a helper process, never by this one. F_SETLEASE
# makes its caller the owner of the open file description (fs/locks.c,
# lease_setup), and a break is announced to the owner by a signal, SIGIO
# unless F_SETSIG says otherwise; whatever a process does with that signal,
# taking a lease in-process makes it the library's to manage. The helper
# ignores SIGIO, takes every lease on the descriptions it shares with this
# process (passed, not reopened), reports, and exits. The leases stay on
# the descriptions, held for as long as this process keeps them open, and
# their owner is a process that no longer exists: a later break signals no
# one. This process sees a break by asking (F_GETLEASE).
_TAKE = """
import fcntl, signal, sys
signal.signal(signal.SIGIO, signal.SIG_IGN)
taken = []
for fd in map(int, sys.argv[1:]):
    try:
        fcntl.fcntl(fd, 10, 0)
        fcntl.fcntl(fd, 1024, fcntl.F_RDLCK)
    except OSError as e:
        for t in taken:
            fcntl.fcntl(t, 1024, fcntl.F_UNLCK)
        print(fd, e.errno, flush=True)
        sys.exit(0)
    taken.append(fd)
print("ok", flush=True)
"""


# Filesystems on which a lease is known to exclude every change: a file's
# contents change only through its open file descriptions (and truncation),
# and both were tested (tests/leases_test.py). The kernel grants leases on
# others whose contents change with no writer at all: /proc and /sys files,
# a FUSE or network filesystem's server, an overlay's lower layers.
LEASABLE = {0xEF53: "ext2/3/4", 0x01021994: "tmpfs"}


def filesystem(fd: int) -> int:
    """The type of the filesystem ``fd`` is on (``statfs.f_type``)."""
    buf = ctypes.create_string_buffer(256)  # larger than any struct statfs
    if ctypes.CDLL(None, use_errno=True).fstatfs(fd, buf) != 0:
        raise OSError(ctypes.get_errno(), "fstatfs")
    return ctypes.c_long.from_buffer(buf).value & 0xFFFFFFFF


class Leases:
    """Read leases on open files, all or none, and whether they still hold.

    A read lease is granted only while no open file description of the file
    has write access (a descriptor, or a shared writable mapping whose
    descriptor was closed), and any later open with write access, or
    ``truncate(2)``, breaks it. One way to change a leased file does not
    break the lease: an ``open`` with ``O_RDONLY | O_TRUNC``, which needs
    only write permission, empties the file and leaves the lease as it was
    (Linux 6.18; the open breaks leases by its access mode, the truncation
    after it does not ask). After a lease is granted the size can therefore
    only fall, to zero. So `unbroken` asks two things: every lease is still
    a read lease, and every size is what it was when the leases were taken.
    If both hold at some moment, no file changed between the leases and that
    moment (docs/journal/2026-10-22-leases.md, proposition L).

    Needs the files' owner or ``CAP_LEASE``, a filesystem in `LEASABLE`,
    and a Python interpreter for the helper.
    A writer is delayed, not refused: its ``open`` waits until the leases
    are given up, or for ``/proc/sys/fs/lease-break-time`` seconds, after
    which the kernel removes them. The leases are released by `release`,
    or when the last descriptor of each file description is closed."""

    def __init__(self, fds: Sequence[int], *, timeout: float = 10.0) -> None:
        self.fds = list(fds)
        self.sizes: list[int] = []
        self.taken = False
        for fd in self.fds:
            if (kind := filesystem(fd)) not in LEASABLE:
                raise Unleasable(
                    errno.EINVAL,
                    f"a lease on this filesystem ({kind:#x}) need not exclude "
                    "every change",
                    f"/proc/self/fd/{fd}",
                )
        try:
            report = _take(self.fds, timeout)
            if report != "ok":
                fd, err = (int(x) for x in report.split())
                if err == errno.EAGAIN:
                    raise Busy(err, "a process has it open for writing")
                raise Unleasable(err, os.strerror(err), f"/proc/self/fd/{fd}")
            self.sizes = [os.fstat(fd).st_size for fd in self.fds]
            self.taken = True
        except BaseException:
            self.release()
            raise

    def unbroken(self) -> bool:
        """No process has had any of the files open for writing since the
        leases were taken, and none was emptied by ``O_TRUNC``."""
        return self.taken and all(
            fcntl.fcntl(fd, F_GETLEASE) == fcntl.F_RDLCK
            and os.fstat(fd).st_size == size
            for fd, size in zip(self.fds, self.sizes, strict=True)
        )

    def release(self) -> None:
        """Give up every lease; a writer waiting for one goes on. Call it
        before closing the descriptors: a closed number may be reused."""
        for fd in self.fds:
            try:
                fcntl.fcntl(fd, F_SETLEASE, fcntl.F_UNLCK)
            except OSError:  # none to give up: never taken, or broken
                pass
        self.fds, self.sizes, self.taken = [], [], False

    def __enter__(self) -> Leases:
        return self

    def __exit__(self, *exc: object) -> None:
        self.release()


def _take(fds: Sequence[int], timeout: float) -> str:
    """The helper's report: ``ok``, or the descriptor it was refused and the
    error. Its exit status is not read: a host that reaps every child (a
    SIGCHLD handler calling ``waitpid(-1)``) may have taken it."""
    if not sys.executable:
        raise Unleasable(errno.ENOENT, "no interpreter for the lease helper")
    try:
        done = subprocess.run(
            [sys.executable, "-I", "-S", "-c", _TAKE, *map(str, fds)],
            pass_fds=fds,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=timeout,
            start_new_session=True,  # a terminal's signals are the host's
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        raise Unleasable(errno.ECHILD, f"the lease helper failed: {e}") from e
    lines = done.stdout.split("\n")
    if not lines[0]:
        raise Unleasable(errno.ECHILD, f"the lease helper did not report: {done}")
    return lines[0]


def collect(
    io: Confined,
    rels: Sequence[str],
    *,
    observer: Observer,
    between: Callable[[str, int], None] | None = None,
) -> tuple[dict[str, Sealed], bool]:
    """A copy of each input (sealed) and whether the copies were *observed*
    coherent: observed once while copying, then once more, and unchanged
    between the two (a double collect). Were the observer to see every
    change, the copies would be the state of every input at one instant;
    ``between(phase, i)`` runs after each input in each phase, where another
    writer can act.

    With ``observer="lease"`` nothing is inferred from observation: every
    input is leased before the first copy (`Busy` if any has a writer), and
    the copies are coherent if the leases are unbroken after the last check
    (no open for writing, no size fallen) and each name still means the
    object copied."""
    fds = [io._open(r, os.O_RDONLY) for r in rels]
    watch = leases = None
    try:
        if observer == "watch":
            watch = Watch(fds)
        if observer == "lease":
            leases = Leases(fds)  # raises Busy while any writer exists
        content = observer in ("digest", "meta+digest")
        first, copies = [], {}
        for i, (r, fd) in enumerate(zip(rels, fds, strict=True)):
            fp = fingerprint(fd, content=True)
            first.append(fp)
            data = os.pread(fd, fp.size, 0)
            copies[r] = Sealed(data, fp.ident)
            if between:
                between("first", i)
        coherent = True
        for i, (r, fd) in enumerate(zip(rels, fds, strict=True)):
            again = fingerprint(fd, content=content)
            before = first[i]
            if observer in ("meta", "meta+digest") and again.meta != before.meta:
                coherent = False
            if content and again.digest != before.digest:
                coherent = False
            try:  # and the name still means the object copied
                if observe(io, r, content=False).ident != before.ident:
                    coherent = False
            except OSError, WendError:  # gone, or no longer confined
                coherent = False
            if between:
                between("second", i)
        if watch is not None and watch.changed():
            coherent = False
        if leases is not None and not leases.unbroken():
            coherent = False  # a writer asked for the file during the copies
        return copies, coherent
    finally:
        if watch is not None:
            watch.close()
        if leases is not None:
            leases.release()
        for fd in fds:
            os.close(fd)
