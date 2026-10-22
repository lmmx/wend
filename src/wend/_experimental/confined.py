"""Running a pipeline confined to a root (research prototype; see
docs/journal/2026-10-22-confined-runs.md).

The analysis of path families (`families`) is sound under a closed world and
lexical identity. Run through `Confined`, the second holds by construction:
every path is rendered below the root, and every check and every access
resolves it with ``openat2`` beneath the root, refusing symlinks and mount
points (`identity.Beneath`). A check the analysis knows is elided; if
another writer has made the fact false, the access fails (``ENOENT``,
``EEXIST``, ``ELOOP``, ``EXDEV``, ``EISDIR``, ...) instead of reaching
another file.

`Plain` offers the same operations on ordinary paths, for comparison.
`run` executes a pipeline with either.
"""

from __future__ import annotations

import errno
import os
import shutil
import stat as st
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from ..conditions import Step, check_conditions, contained
from ..errors import (
    CapabilityError,
    ContainmentError,
    MissingPathError,
    PathExistsError,
    WendError,
    WrongKindError,
)
from .identity import Beneath, openat2
from .knowledge import CONDITION


__all__ = ["Confined", "Plain", "run"]

_OUTSIDE = (errno.ELOOP, errno.EXDEV)  # resolves through a symlink or a mount


class Confined:
    """Checks and file operations on paths below ``root``, each resolved by
    the kernel beneath the root, without symlinks or mount points."""

    def __init__(self, root: str) -> None:
        self.root = root.rstrip("/") or "/"
        self.b = Beneath(self.root)

    def rel(self, path: str) -> str:
        if not contained(path, self.root):
            raise ContainmentError(path, "root", f"is not under {self.root!r}")
        return path[len(self.root) :].lstrip("/")

    def _refused(self, rel: str, atom: str, e: OSError) -> ContainmentError:
        how = "a symlink" if e.errno == errno.ELOOP else "a mount point"
        return ContainmentError(
            rel, CONDITION.get(atom, atom), f"resolves through {how} below the root"
        )

    def _lookup(self, rel: str, atom: str) -> tuple[os.stat_result, int] | None:
        """The object at ``rel`` and an ``O_PATH`` descriptor for it, or None
        if nothing is there; ELOOP and EXDEV are refusals, not absence."""
        try:
            fd = self.b.open(rel, os.O_PATH)
        except OSError as e:
            if e.errno in (errno.ENOENT, errno.ENOTDIR):
                return None
            if e.errno in _OUTSIDE:
                raise self._refused(rel, atom, e) from e
            raise
        return os.fstat(fd), fd

    def check(self, rel: str, atoms: frozenset[str]) -> None:
        """Each atom (`knowledge.CONDITION`) of the path, as `wend.conditions`
        would check it, but resolved beneath the root."""
        for atom in sorted(atoms):
            found = self._lookup(rel, atom)
            s, fd = found if found else (None, -1)
            try:
                self._one(rel, atom, s, fd)
            finally:
                if fd >= 0:
                    os.close(fd)

    def _one(self, rel: str, atom: str, s: os.stat_result | None, fd: int) -> None:
        c = CONDITION[atom]
        if atom == "exists" and s is None:
            raise MissingPathError(rel, c, "does not exist")
        if atom == "absent" and s is not None:
            raise PathExistsError(rel, c, "already exists")
        if atom == "file" and s is not None and not st.S_ISREG(s.st_mode):
            raise WrongKindError(rel, c, "is not a regular file")
        if atom == "dir" and s is not None and not st.S_ISDIR(s.st_mode):
            raise WrongKindError(rel, c, "is not a directory")
        if atom in ("read", "list"):
            if s is None:
                raise MissingPathError(rel, c, "does not exist")
            if atom == "list" and not st.S_ISDIR(s.st_mode):
                raise WrongKindError(rel, c, "is not a directory")
            mode = os.R_OK | (os.X_OK if atom == "list" else 0)
            if not os.access(f"/proc/self/fd/{fd}", mode):
                raise CapabilityError(rel, c, "is not permitted")
        if atom in ("write", "create"):
            if s is None:
                self._creatable(rel, atom)
            elif atom == "write":
                mode = os.W_OK | (os.X_OK if st.S_ISDIR(s.st_mode) else 0)
                if not os.access(f"/proc/self/fd/{fd}", mode):
                    raise CapabilityError(rel, c, "is not writable")

    def _creatable(self, rel: str, atom: str) -> None:
        parts = rel.split("/")
        for i in range(len(parts) - 1, -1, -1):
            found = self._lookup("/".join(parts[:i]), atom)
            if found is None:
                continue
            s, fd = found
            try:
                if not st.S_ISDIR(s.st_mode):
                    raise CapabilityError(
                        rel, CONDITION[atom], "cannot be created: not below a directory"
                    )
                if not os.access(f"/proc/self/fd/{fd}", os.W_OK | os.X_OK):
                    raise CapabilityError(rel, CONDITION[atom], "cannot be created")
            finally:
                os.close(fd)
            return

    # -- operations ---------------------------------------------------------

    def _dir(self, rel: str) -> int:
        return self.b.open(rel, os.O_RDONLY | os.O_DIRECTORY)

    def _parent(self, rel: str, *, make: bool = False) -> tuple[int, str]:
        """A descriptor for ``rel``'s parent (made first if ``make``), and
        ``rel``'s last name."""
        head, _, name = rel.rpartition("/")
        fd = self._dir("")
        for part in head.split("/") if head else ():
            if make:
                try:
                    os.mkdir(part, dir_fd=fd)
                except FileExistsError:
                    pass
            try:
                nxt = self.b.open(part, os.O_RDONLY | os.O_DIRECTORY, at=fd)
            finally:
                os.close(fd)
            fd = nxt
        return fd, name

    def read_bytes(self, rel: str) -> bytes:
        with os.fdopen(self.b.open(rel, os.O_RDONLY), "rb") as f:
            return f.read()

    def write_bytes(self, rel: str, data: bytes) -> None:
        with os.fdopen(self.b.open(rel, os.O_WRONLY | os.O_TRUNC), "wb") as f:
            f.write(data)

    def create(self, rel: str, data: bytes) -> None:
        """Make ``rel`` and its parents, exclusively: one system call checks
        that nothing is at the name and makes the file."""
        fd, name = self._parent(rel, make=True)
        try:
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
            with os.fdopen(self.b.open(name, flags, at=fd), "wb") as f:
                f.write(data)
        finally:
            os.close(fd)

    def mkdir(self, rel: str) -> None:
        fd, name = self._parent(rel, make=True)
        try:
            os.mkdir(name, dir_fd=fd)
        finally:
            os.close(fd)

    def listdir(self, rel: str) -> list[str]:
        fd = self._dir(rel)
        try:
            return os.listdir(fd)
        finally:
            os.close(fd)

    def delete(self, rel: str) -> None:
        """Remove ``rel``, and everything below it, never following a symlink
        or entering a mount point (each subdirectory is opened beneath its
        parent under the same resolution)."""
        _not_the_root(rel)
        fd, name = self._parent(rel)
        try:
            s = os.stat(name, dir_fd=fd, follow_symlinks=False)
            if st.S_ISDIR(s.st_mode):
                sub = openat2(fd, name, os.O_RDONLY | os.O_DIRECTORY, Beneath.RESOLVE)
                try:
                    _rmtree(sub)
                finally:
                    os.close(sub)
                os.rmdir(name, dir_fd=fd)
            else:
                os.unlink(name, dir_fd=fd)
        finally:
            os.close(fd)

    def close(self) -> None:
        self.b.close()


def _not_the_root(rel: str) -> None:
    if not rel:
        raise ContainmentError(rel, "root", "is the root, which a run cannot remove")


def _rmtree(fd: int) -> None:
    for entry in os.scandir(fd):
        if entry.is_dir(follow_symlinks=False):
            sub = openat2(fd, entry.name, os.O_RDONLY | os.O_DIRECTORY, Beneath.RESOLVE)
            try:
                _rmtree(sub)
            finally:
                os.close(sub)
            os.rmdir(entry.name, dir_fd=fd)
        else:
            os.unlink(entry.name, dir_fd=fd)


class Plain:
    """`Confined`'s operations on ordinary paths (symlinks followed, mounts
    crossed), with checks by `wend.conditions`. Creation is exclusive, as in
    `Confined`, unless ``exclusive=False``: then it opens for writing as most
    code does (``open(p, "w")``), which writes through a symlink at the name."""

    def __init__(self, root: str, *, exclusive: bool = True) -> None:
        self.root = root.rstrip("/") or "/"
        self.exclusive = exclusive

    def rel(self, path: str) -> str:
        if not contained(path, self.root):
            raise ContainmentError(path, "root", f"is not under {self.root!r}")
        return path[len(self.root) :].lstrip("/")

    def _p(self, rel: str) -> Path:
        return Path(self.root, rel) if rel else Path(self.root)

    def check(self, rel: str, atoms: frozenset[str]) -> None:
        conds = tuple(CONDITION[a] for a in sorted(atoms))
        check_conditions(str(self._p(rel)), conds, {}, None)

    def read_bytes(self, rel: str) -> bytes:
        return self._p(rel).read_bytes()

    def write_bytes(self, rel: str, data: bytes) -> None:
        with open(self._p(rel), "r+b") as f:  # no create, as Confined
            f.truncate()
            f.write(data)

    def create(self, rel: str, data: bytes) -> None:
        p = self._p(rel)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "xb" if self.exclusive else "wb") as f:
            f.write(data)

    def mkdir(self, rel: str) -> None:
        self._p(rel).mkdir(parents=True)

    def listdir(self, rel: str) -> list[str]:
        return os.listdir(self._p(rel))

    def delete(self, rel: str) -> None:
        _not_the_root(rel)
        p = self._p(rel)
        if p.is_dir() and not p.is_symlink():
            shutil.rmtree(p)
        else:
            p.unlink()

    def close(self) -> None:
        pass


Body = Callable[[Any, str], Any]


def run(
    steps: Sequence[tuple[str, Step]],
    bodies: Sequence[Sequence[tuple[str, Body]]],
    env: Mapping[str, Any],
    io: Confined | Plain,
    *,
    elide: Mapping[tuple[str, str], frozenset[str]] | None = None,
    between: Callable[[str, int], None] | None = None,
) -> list[bool]:
    """Run each step: check each port's required atoms (less those in
    ``elide``, keyed by step and port), run its bodies with ``io`` and the
    port's path relative to the root, then check what it ensures. A step
    that raises has failed. ``between(point, i)`` is called before each
    step's checks (``"step"``) and between its checks and its bodies
    (``"use"``): where another writer can act.

    ``elide`` is a plan made assuming every earlier step completed
    (`families.analyse_families`), so after a failure nothing is elided."""
    elide = elide or {}
    done: list[bool] = []
    for i, (name, step) in enumerate(steps):
        if not all(done):
            elide = {}
        try:
            if between:
                between("step", i)
            rels = {port: io.rel(e.render(env)) for port, e in step.paths.items()}
            for port, e in step.paths.items():
                todo = e.declares.requires - elide.get((name, port), frozenset())
                io.check(rels[port], todo)
            if between:
                between("use", i)
            for port, body in bodies[i]:
                body(io, rels[port])
            for port, e in step.paths.items():
                io.check(rels[port], e.declares.ensures)
        except OSError, WendError:
            done.append(False)
            continue
        done.append(True)
    return done
