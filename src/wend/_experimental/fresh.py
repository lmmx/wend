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
"""

from __future__ import annotations

import ctypes
import hashlib
import os
import struct
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Literal

from ..errors import WendError
from .confined import Confined
from .events import Sealed


__all__ = ["Fingerprint", "Verdict", "Watch", "collect", "observe", "revalidate"]

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

Observer = Literal["meta", "digest", "meta+digest", "watch"]


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
    writer can act."""
    fds = [io._open(r, os.O_RDONLY) for r in rels]
    watch = Watch(fds) if observer == "watch" else None
    content = observer in ("digest", "meta+digest")
    try:
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
        return copies, coherent
    finally:
        if watch is not None:
            watch.close()
        for fd in fds:
            os.close(fd)
