"""Knowledge about directory entries, not strings (research prototype; see
docs/journal/2026-10-22-aliasing.md).

`wend._experimental.knowledge` identifies a path by its rendered string, so
it is unsound wherever two strings name one file: a symlink (`link/x` and
`d/x`), a ``..`` spelling (`d/../a` and `a`), a bind mount. Here a fact
carries the *resolution trace* of its path:

- ``entries``: every directory entry looked up while resolving it, each as
  the (device, inode) of the directory it lives in and its name, including
  symlinks followed (and the entries of their targets) and the first
  missing entry;
- ``dirs``: the (device, inode) of every directory passed through;
- ``final``: the entry the path names, or for a missing path its first
  missing entry.

A fact is keyed by what its atom's check reads, so two spellings share
knowledge exactly when their checks read the same thing (`_key`): ``absent``
reads the last entry without following a final symlink (``lstat``); the
creation checks of a missing path read its nearest existing ancestor, as
`wend.conditions` finds it; every other atom reads the object the path
resolves to, or the entry at which resolution failed.

A mutation of a path ``m`` can change only its own entry (followed or not),
what lies below it, and the missing entries along its way (making it can
make its parents). So it forgets a fact whose trace looked up ``m``'s
final entry (which covers the parents it may make), passed through ``m``'s
directory, or resolved to ``m``'s object.
Spelling no longer matters; what remains assumed is listed in the journal.

Resolving a trace costs the lookups a check makes, so this is a reference
semantics and an oracle, not a way to skip checks. Two cheaper routes to
sound knowledge keyed by strings: `IdentityTracker.alias_free` says when a
run read every path as written, and `Beneath` has the kernel refuse any
other reading at the moment of use. `Held` keeps an open file, of which
facts survive changes to the namespace.
"""

from __future__ import annotations

import ctypes
import os
import posixpath
import stat as st
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..conditions import Step, _ancestor, check_conditions
from .knowledge import CONDITION, MUTATING, Entry


__all__ = [
    "Beneath",
    "DirEntry",
    "Held",
    "IdentityKnowledge",
    "IdentityTracker",
    "Trace",
    "openat2",
    "resolve",
]

Ident = tuple[int, int]


@dataclass(frozen=True)
class DirEntry:
    dir: Ident
    name: str


@dataclass(frozen=True)
class Trace:
    path: str
    entries: frozenset[DirEntry]
    missing: frozenset[DirEntry]
    dirs: frozenset[Ident]
    final: DirEntry | None  # where resolution ended, following symlinks
    is_dir: Ident | None  # the path's own identity, when it is a directory
    rest: tuple[str, ...] = ()  # components past a missing one or a file
    # Where resolution departed from reading the string, as physical paths:
    # each symlink followed and each directory a ``..`` left; and each
    # directory resolved (to find the mount points crossed).
    links: tuple[str, ...] = ()
    ups: tuple[str, ...] = ()
    walked: tuple[str, ...] = ()
    # The object an existing path resolves to: two names of one object (a
    # hard link, or a case-insensitive filesystem's two spellings) share it.
    obj: Ident | None = None
    # The entry ``lstat`` reads (a final symlink not followed), and for a
    # missing path the directory its creation checks consult.
    lfinal: DirEntry | None = None
    anc: Ident | None = None

    def alias_free(self, root: str) -> bool:
        """Whether, below ``root``, this resolution read the string as
        written: no symlink, no ``..`` and no mount point crossed (what
        resolution above the root does is shared by every path below it).
        Two alias-free strings below one root name the same entry, or lie
        above or below each other, exactly when the strings do (on a
        case-sensitive filesystem)."""
        r = os.path.realpath(root)
        below = r.rstrip("/") + "/"
        if any(x.startswith(below) for x in self.links):
            return False
        if any(x == r or x.startswith(below) for x in self.ups):
            return False
        mounts = _mount_points()
        return "*" not in mounts and not any(
            w.startswith(below) and w in mounts for w in self.walked
        )


def _mount_points() -> frozenset[str]:
    try:
        with open("/proc/self/mountinfo") as f:
            return frozenset(line.split()[4] for line in f)
    except OSError:  # no mountinfo: nothing can be ruled out
        return frozenset({"*"})


def _ident(s: os.stat_result) -> Ident:
    return (s.st_dev, s.st_ino)


def resolve(path: str, *, max_links: int = 40) -> Trace:
    """Resolve ``path`` component by component, as the kernel does, without
    trusting its spelling: ``..`` moves to the physical parent, symlinks
    (also a final one) are followed, and a missing component ends the walk."""
    if not path.startswith("/"):
        path = os.getcwd().rstrip("/") + "/" + path
    real = "/"
    dirs = {_ident(os.stat("/"))}
    entries: set[DirEntry] = set()
    missing: set[DirEntry] = set()
    final: DirEntry | None = None
    todo = [c for c in path.split("/") if c not in ("", ".")]
    own = len(todo)  # how many of todo's last components are the path's own
    n_links = 0
    links: list[str] = []
    ups: list[str] = []
    walked: list[str] = []
    last: list[DirEntry | None] = []  # the path's own last entry, unfollowed

    def trace(final, is_dir, rest=(), obj=None):
        lfinal = last[0] if last else final
        anc = None
        if obj is None:
            try:
                anc = _ident(os.stat(_ancestor(path)))
            except OSError:
                pass
        return Trace(
            path,
            frozenset(entries),
            frozenset(missing),
            frozenset(dirs),
            final,
            is_dir,
            tuple(rest),
            tuple(links),
            tuple(ups),
            tuple(walked),
            obj,
            lfinal,
            anc,
        )

    is_dir: Ident | None = _ident(os.stat("/"))
    while todo:
        mine = len(todo) == own
        c = todo.pop(0)
        if mine:
            own -= 1
        if c == "..":
            ups.append(real)
            real = posixpath.dirname(real) or "/"
            dirs.add(_ident(os.stat(real)))
            final, is_dir = None, _ident(os.stat(real))
            if mine and not own:
                last.append(None)
            continue
        here = DirEntry(_ident(os.stat(real)), c)
        entries.add(here)
        final, is_dir = here, None
        if mine and not own:
            last.append(here)
        cand = real.rstrip("/") + "/" + c
        try:
            s = os.lstat(cand)
        except FileNotFoundError, NotADirectoryError:
            missing.add(here)
            return trace(final, None, todo)
        if st.S_ISLNK(s.st_mode):
            links.append(cand)
            n_links += 1
            if n_links > max_links:
                break
            target = os.readlink(cand)
            if target.startswith("/"):
                real = "/"
            todo = [x for x in target.split("/") if x not in ("", ".")] + todo
            continue
        if st.S_ISDIR(s.st_mode):
            real = cand
            walked.append(real)
            dirs.add(_ident(s))
            is_dir = _ident(s)
        elif todo:
            # Below a non-directory nothing can be: the next lookup fails
            # (ENOTDIR), at an entry of its own, never the file's.
            below = DirEntry(_ident(os.stat(cand)), todo[0])
            entries.add(below)
            missing.add(below)
            return trace(below, None, todo[1:])
    try:
        obj: Ident | None = _ident(os.stat(path))
    except OSError:
        obj = None
    return trace(final, is_dir, obj=obj)


def affects(m: Trace, f: Trace) -> bool:
    """Whether mutating ``m``'s path can change a fact about ``f``'s path."""
    # Mutating a symlink's path may change the link itself (unlink) as well
    # as its target, but every trace that looked the link up followed it to
    # the same final entry, so that entry alone decides.
    if m.final is not None and m.final in f.entries:
        return True  # f is m, below m, or resolved through m
    if m.obj is not None and m.obj == f.obj:
        return True  # another name of m's object
    # f is below m's directory, however it was spelled (a bind mount reaches
    # it through another entry). Making m's missing parents needs no clause
    # of its own: a missing path's final entry is its first missing entry.
    return m.is_dir is not None and m.is_dir in f.dirs


@dataclass(frozen=True)
class IFact:
    atom: str
    trace: Trace


@dataclass
class IdentityKnowledge:
    facts: list[IFact] = field(default_factory=list)

    def knows(self, atom: str, t: Trace) -> bool:
        k = _key(atom, t)
        return any(f.atom == atom and _key(atom, f.trace) == k for f in self.facts)

    def learn(self, atoms: frozenset[str], t: Trace) -> None:
        for a in sorted(atoms):
            if not self.knows(a, t):
                self.facts.append(IFact(a, t))

    def forget(self, m: Trace) -> None:
        self.facts = [f for f in self.facts if not affects(m, f.trace)]


def _key(atom: str, t: Trace) -> tuple:
    """What ``atom``'s check of ``t``'s path reads (`wend.conditions`): two
    traces with one key give one outcome while nothing in the key changes."""
    if atom == "absent":  # lstat: a final symlink is itself an entry
        return ("l", t.lfinal) if t.lfinal is not None else ("d", t.is_dir)
    if atom in ("create", "write") and t.obj is None:
        # A missing path's creation checks read only the nearest existing
        # ancestor, found from the spelling (so not always the parent of the
        # first missing entry: a dangling symlink on the way moves it).
        return ("m", t.anc)
    # stat: the object at the final entry, or the entry where resolution
    # failed (a missing path's components past it are never read).
    return ("f", t.final) if t.final is not None else ("d", t.is_dir)


class IdentityTracker:
    """`wend._experimental.knowledge.Tracker`, with facts keyed by resolution
    traces: a fact about ``link/x`` is a fact about ``d/x``."""

    def __init__(self, *, elide: bool = False, fs: Any = None) -> None:
        self.knowledge = IdentityKnowledge()
        self.entries: list[Entry] = []
        self.traces: list[Trace] = []
        self.elide = elide
        self.fs = fs

    @contextmanager
    def run(
        self, name: str, step: Step, env: Mapping[str, Any]
    ) -> Iterator[dict[str, Path]]:
        k = self.knowledge
        paths = {port: e.render(env) for port, e in step.paths.items()}
        traces = {port: resolve(p) for port, p in paths.items()}
        self.traces.extend(traces.values())
        entries = []
        for port, e in step.paths.items():
            p, req = paths[port], e.declares.requires
            known = frozenset(a for a in req if k.knows(a, traces[port]))
            todo = req - known if self.elide else req
            check_conditions(p, tuple(CONDITION[a] for a in sorted(todo)), env, self.fs)
            entries.append(Entry(name, port, p, known, frozenset(todo)))
        for port, e in step.paths.items():
            k.learn(e.declares.requires, traces[port])
        self.entries.extend(entries)
        try:
            yield {port: Path(p) for port, p in paths.items()}
        finally:
            for port, e in step.paths.items():
                if e.declares.verbs & MUTATING:
                    k.forget(traces[port])
        for port, e in step.paths.items():
            post = e.declares.ensures
            check_conditions(
                paths[port], tuple(CONDITION[a] for a in sorted(post)), env, self.fs
            )
            after = resolve(paths[port])
            self.traces.append(after)
            k.learn(post, after)

    def alias_free(self, root: str) -> bool:
        """Whether every path this run resolved was alias-free below
        ``root``: the condition under which string-keyed knowledge, and so
        the analysis of path families, is exact."""
        return all(t.alias_free(root) for t in self.traces)


class Held:
    """An open file and what was found of it when it was opened. Unlike a
    fact about a name, a fact about an open file description survives any
    later change to the namespace: unlinking the name, renaming over it, or
    swapping it for a symlink leaves this file, its kind and the access it
    was opened with as they were (its content can still change, through
    another writer of the same file)."""

    def __init__(self, path: str, fd: int | None = None) -> None:
        self.path = path
        self.fd = os.open(path, os.O_RDONLY) if fd is None else fd
        self.stat = os.fstat(self.fd)

    @property
    def is_file(self) -> bool:
        return st.S_ISREG(self.stat.st_mode)

    def read(self) -> bytes:
        return os.pread(self.fd, max(os.fstat(self.fd).st_size, 0), 0)

    def close(self) -> None:
        os.close(self.fd)

    def __enter__(self) -> Held:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


# -- Resolution the kernel holds to the string ---------------------------------

RESOLVE_NO_XDEV, RESOLVE_NO_SYMLINKS, RESOLVE_BENEATH = 0x01, 0x04, 0x08
_SYS_OPENAT2 = 437  # the same number on every architecture


class _OpenHow(ctypes.Structure):
    _fields_ = [
        ("flags", ctypes.c_uint64),
        ("mode", ctypes.c_uint64),
        ("resolve", ctypes.c_uint64),
    ]


_syscall = ctypes.CDLL(None, use_errno=True).syscall


def openat2(dirfd: int, path: str, flags: int, resolve: int, mode: int = 0o666) -> int:
    """``openat2(2)``: ``path`` opened relative to ``dirfd`` under ``resolve``."""
    how = _OpenHow(flags | os.O_CLOEXEC, mode if flags & os.O_CREAT else 0, resolve)
    fd = _syscall(
        _SYS_OPENAT2, dirfd, os.fsencode(path), ctypes.byref(how), ctypes.sizeof(how)
    )
    if fd < 0:
        e = ctypes.get_errno()
        raise OSError(e, os.strerror(e), path)
    return fd


class Beneath:
    """A directory, and paths below it opened as ``openat2`` (Linux 5.6)
    resolves them with ``RESOLVE_BENEATH | RESOLVE_NO_SYMLINKS |
    RESOLVE_NO_XDEV``: never above the directory, through a symlink or
    across a mount point. With ``..`` refused as well, every resolution that
    succeeds is alias-free (`Trace.alias_free`), and the kernel decides it
    at the moment of use, not of a check: a spelling swapped for a symlink
    afterwards fails (ELOOP) rather than resolving elsewhere."""

    RESOLVE = RESOLVE_BENEATH | RESOLVE_NO_SYMLINKS | RESOLVE_NO_XDEV

    def __init__(self, root: str) -> None:
        self.root = root
        self.fd = os.open(root, os.O_PATH | os.O_DIRECTORY)

    def open(
        self,
        rel: str,
        flags: int = os.O_RDONLY,
        mode: int = 0o666,
        *,
        at: int | None = None,
    ) -> int:
        """``rel`` below the root (or below the directory ``at``, itself
        opened beneath the root)."""
        if rel.startswith("/") or ".." in rel.split("/"):
            raise ValueError(f"{rel!r} is not a path below the root")
        dirfd = self.fd if at is None else at
        return openat2(dirfd, rel or ".", flags, self.RESOLVE, mode)

    def stat(self, rel: str) -> os.stat_result:
        fd = self.open(rel, os.O_PATH)
        try:
            return os.fstat(fd)
        finally:
            os.close(fd)

    def hold(self, rel: str) -> Held:
        """``rel`` opened for reading, kept open: checks made on it (`Held`)
        are checks of the file the body then reads."""
        return Held(os.path.join(self.root, rel), self.open(rel))

    def create(self, rel: str, mode: int = 0o666) -> int:
        """``rel`` made and opened for writing in one step: ``Absent`` and its
        creation are a single system call (``O_CREAT | O_EXCL``)."""
        return self.open(rel, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)

    def close(self) -> None:
        os.close(self.fd)

    def __enter__(self) -> Beneath:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
