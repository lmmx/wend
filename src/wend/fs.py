"""Filesystems for discovery: the local disk, fsspec, and object stores.

`glob` and `infer` read a tree through `FileSystem`, a small protocol:
- list a directory;
- say what a path is;
- identify a directory, to detect link cycles;
- walk a tree;
- give a view of one subtree for the duration of one walk.

`LocalFS`, the default, implements it with `os`. `FsspecFS` adapts an fsspec
filesystem, so the same expressions discover keys in memory or in S3, GCS or
Azure storage. `render`, `match` and `Lens` never touch a filesystem, so they
need nothing from here.

Paths stay in the filesystem's own namespace. fsspec strips a URL's protocol:
``memory://data/x`` is ``/data/x`` and ``s3://bucket/x`` is ``bucket/x``.
`url_to_fs` splits a URL into a filesystem and such a path, which is then
bound like any root::

    fs, root = url_to_fs("s3://bucket/data")
    expr.glob(root=root, fs=fs)

A URL is not an expression's head. pathlib reads ``s3://bucket`` as the path
``s3:/bucket``, so `glob` refuses one with a pointer to `url_to_fs`.
"""

from __future__ import annotations

import os
from collections.abc import Hashable, Iterator, Sequence
from operator import attrgetter
from stat import S_ISDIR, S_ISLNK, S_ISREG
from typing import Any, Literal, Protocol


type EntryKind = Literal["file", "dir", "link", "other"]

__all__ = [
    "DirEntry",
    "EntryKind",
    "FileSystem",
    "FsspecFS",
    "LocalFS",
    "url_to_fs",
]


class DirEntry(Protocol):
    """One entry of a directory listing, as `os.DirEntry` provides it."""

    @property
    def name(self) -> str: ...

    def is_dir(self, *, follow_symlinks: bool = True) -> bool: ...

    def is_file(self, *, follow_symlinks: bool = True) -> bool: ...

    def is_symlink(self) -> bool: ...


class FileSystem(Protocol):
    """What `glob` and `infer` need from a filesystem.

    Paths are strings in the filesystem's namespace, joined with ``/``; ``.``
    is the directory a relative path starts from.
    """

    def scandir(self, path: str) -> Sequence[DirEntry]:
        """The entries of directory ``path`` sorted by name.

        Empty if ``path`` is not a directory or cannot be listed.
        """
        ...

    def kind(self, path: str, *, follow_symlinks: bool = True) -> EntryKind | None:
        """What ``path`` is, or None if it does not exist.

        With ``follow_symlinks=False`` a symlink is ``"link"``; otherwise
        it is what it points to, and None if that does not exist. A path
        that cannot be examined (no permission, a symlink loop) is None, as
        ``os.path.isdir`` reads it; a failure that says nothing about the
        path, such as a dropped connection, raises.
        """
        ...

    def dir_key(self, path: str) -> Hashable | None:
        """An identity for directory ``path``, equal for the same directory
        reached by different paths.

        None on a filesystem without links, where no walk can cycle. Raises
        `OSError` if the directory cannot be identified.
        """
        ...

    def walk(self, top: str) -> Iterator[tuple[str, list[str], list[str]]]:
        """``(dirpath, dirnames, filenames)`` for ``top`` and every directory
        below it, as ``os.walk(top)`` gives them.

        The walk is top-down, does not descend symlinks, and visits only
        the ``dirnames`` left after the caller prunes the list in place.
        """
        ...

    def subtree(self, path: str) -> FileSystem:
        """A filesystem to read ``path`` and everything below it during one
        walk.

        `LocalFS` returns itself. `FsspecFS` returns a view that answers
        from what it has listed, and lists the whole subtree at once if
        ``listing="flat"``.
        """
        ...


def _child(d: str, name: str) -> str:
    if d == ".":
        return name
    if d.endswith("/"):
        return d + name
    return d + "/" + name


_by_name = attrgetter("name")


class LocalFS:
    """The local disk through `os`, the default for `glob` and `infer`."""

    __slots__ = ()

    def __repr__(self) -> str:
        return "LocalFS()"

    def scandir(self, path: str) -> list[os.DirEntry[str]]:
        try:
            with os.scandir(path) as it:
                return sorted(it, key=_by_name)
        except OSError:
            return []

    def kind(self, path: str, *, follow_symlinks: bool = True) -> EntryKind | None:
        try:
            mode = os.stat(path, follow_symlinks=follow_symlinks).st_mode
        except OSError, ValueError:
            return None
        if S_ISDIR(mode):
            return "dir"
        if S_ISREG(mode):
            return "file"
        if S_ISLNK(mode):
            return "link"
        return "other"

    def dir_key(self, path: str) -> tuple[int, int]:
        st = os.stat(path)
        return st.st_dev, st.st_ino

    def walk(self, top: str) -> Iterator[tuple[str, list[str], list[str]]]:
        return os.walk(top)

    def subtree(self, path: str) -> LocalFS:
        return self


LOCAL = LocalFS()


# ---------------------------------------------------------------------------
# fsspec
# ---------------------------------------------------------------------------


class _Entry:
    """A listed key or prefix of a store, which has no symlinks."""

    __slots__ = ("kind", "name")
    name: str
    kind: EntryKind

    def __init__(self, name: str, kind: EntryKind) -> None:
        self.name = name
        self.kind = kind

    def __repr__(self) -> str:
        return f"<{self.kind} {self.name!r}>"

    def is_dir(self, *, follow_symlinks: bool = True) -> bool:
        return self.kind == "dir"

    def is_file(self, *, follow_symlinks: bool = True) -> bool:
        return self.kind == "file"

    def is_symlink(self) -> bool:
        return False


def _protocols(fs: Any) -> frozenset[str]:
    p = fs.protocol
    return frozenset(p if isinstance(p, (tuple, list)) else (p,))


def _info_kind(name: str, info: dict[str, Any]) -> EntryKind:
    if name.endswith("/"):  # a directory marker, whatever type the store gives
        return "dir"
    # fsspec's find() reports a file given as the search root with an empty
    # info dict, so a missing type is a file.
    t = info.get("type", "file")
    if t == "directory":
        return "dir"
    return "file" if t == "file" else "other"


# Missing paths, and paths the store will not show: as for a local stat, these
# read as absent. Other failures (a dropped connection) propagate, so a failed
# request is never taken for an empty directory.
_ABSENT = (FileNotFoundError, NotADirectoryError, PermissionError)


def _merge(kinds: dict[str, EntryKind], name: str, kind: EntryKind) -> None:
    # A key that is also a prefix of other keys is a directory, as fsspec's
    # info() reports it.
    if kinds.get(name) != "dir":
        kinds[name] = kind


class FsspecFS:
    """An fsspec filesystem: object storage (S3, GCS, Azure), memory, HTTP...

    ``listing`` decides how `glob` and `infer` read a tree:

    - ``"flat"`` (default): one ``find`` for everything below the
      expression's literal prefix, which `glob` then walks in memory. On an
      object store that is a single prefix listing (one request per page of
      keys) however deep the layout, where a directory-by-directory walk
      makes one request per directory.
    - ``"tree"``: one ``ls`` for each directory the expression reaches, as
      on the local disk. Suited to filesystems with real directories (SFTP,
      HDFS), where ``find`` itself lists every directory, and to prefixes
      holding many keys that the expression never reaches.

    Results are the same either way. Within one walk, a path whose parent
    has been listed is classified without another request.

    Stores have no symlinks: no entry is a link, so `glob`'s symlink options
    change nothing, and `dir_key` is None. A directory is a prefix of some
    key or an explicit marker (a key ending in ``/``, or ``makedirs`` on the
    memory filesystem), so an empty directory exists only as a marker. A key
    that is also a prefix of other keys is a directory. Keys with an empty,
    ``.`` or ``..`` segment cannot be rendered by any expression and are
    never listed.

    fsspec's own local filesystem is refused: use `LocalFS`, which keeps
    `glob`'s symlink policy and cycle detection.
    """

    __slots__ = ("fs", "listing")

    def __init__(self, fs: Any, *, listing: Literal["flat", "tree"] = "flat") -> None:
        if listing not in ("flat", "tree"):
            raise ValueError(f"listing must be 'flat' or 'tree', not {listing!r}")
        if _protocols(fs) & {"file", "local"}:
            raise ValueError(
                "FsspecFS does not wrap fsspec's local filesystem; use"
                " wend.fs.LocalFS(), which keeps glob's symlink policy"
            )
        self.fs = fs
        self.listing = listing

    def __repr__(self) -> str:
        return f"FsspecFS({type(self.fs).__name__}, listing={self.listing!r})"

    @staticmethod
    def _path(path: str) -> str:
        return "" if path == "." else path

    def _strip(self, path: str) -> str:
        return self.fs._strip_protocol(self._path(path)).rstrip("/")

    def scandir(self, path: str) -> list[_Entry]:
        try:
            infos = self.fs.ls(self._path(path), detail=True)
        except _ABSENT:
            return []
        own = self._strip(path)
        kinds: dict[str, EntryKind] = {}
        for info in infos:
            name = info["name"].rstrip("/")
            if name == own:  # a file lists as itself, a store may list the marker
                continue
            base = name.rpartition("/")[2]
            if base not in ("", ".", ".."):
                _merge(kinds, base, _info_kind(info["name"], info))
        return [_Entry(n, k) for n, k in sorted(kinds.items())]

    def kind(self, path: str, *, follow_symlinks: bool = True) -> EntryKind | None:
        try:
            info = self.fs.info(self._path(path))
        except _ABSENT:
            return None
        return _info_kind(info.get("name", ""), info)

    def dir_key(self, path: str) -> None:
        return None

    def walk(self, top: str) -> Iterator[tuple[str, list[str], list[str]]]:
        return self.subtree(top).walk(top)

    def subtree(self, path: str) -> _Subtree:
        return _Subtree(self, path, flat=self.listing == "flat")


def _below(base: str, path: str) -> bool:
    if path == base:
        return True
    if base == ".":
        return not path.startswith("/")
    return path.startswith(base if base.endswith("/") else base + "/")


def _parent(path: str) -> str:
    head, sep, _ = path.rpartition("/")
    return (head or "/") if sep else "."


def _relative(prefix: str, key: str) -> str | None:
    """``key`` relative to ``prefix`` (both as fsspec spells them), or None."""
    if not prefix:  # the root: memory keys start with "/", bucket names do not
        return key.removeprefix("/")
    if key == prefix:
        return ""
    if key.startswith(prefix + "/"):
        return key[len(prefix) + 1 :]
    return None


class _Subtree:
    """One walk's view of an `FsspecFS` below ``base``.

    Paths are spelled as the walk builds them from ``base``, whatever
    spelling the store's keys use (``data/x`` and ``/data/x`` are one path on
    the memory filesystem). A flat view is filled by one ``find``; a tree
    view records each ``ls``. Either way, a path is classified from its
    parent's listing when there is one.
    """

    __slots__ = ("_base", "_complete", "_fs", "_kinds", "_listed")

    def __init__(self, fs: FsspecFS, base: str, *, flat: bool) -> None:
        self._fs = fs
        self._base = base
        self._complete = flat
        self._kinds: dict[str, EntryKind | None] = {}
        self._listed: dict[str, list[_Entry]] = {}
        if flat:
            try:
                self._fill()
            except ValueError:
                # s3fs refuses to list a whole store ("Cannot traverse all
                # of S3"): below a templated bucket, list level by level.
                if fs._strip(base):
                    raise
                self._complete = False

    def _fill(self) -> None:
        fs, base = self._fs, self._base
        prefix = fs._strip(base)
        found = fs.fs.find(fs._path(base), withdirs=True, detail=True)
        kinds: dict[str, EntryKind] = {}
        names: dict[str, dict[str, EntryKind]] = {}
        for key, info in found.items():
            rel = _relative(prefix, key.rstrip("/"))
            if rel is None:
                continue
            kind = _info_kind(key, info)
            if not rel:
                _merge(kinds, base, kind)
                continue
            parts = rel.split("/")
            if any(p in ("", ".", "..") for p in parts):
                continue
            kinds[base] = "dir"
            d = base
            for j, part in enumerate(parts):
                k = kind if j == len(parts) - 1 else "dir"
                _merge(names.setdefault(d, {}), part, k)
                d = _child(d, part)
                _merge(kinds, d, k)
        self._kinds.update(kinds)
        for d, k in kinds.items():
            if k == "dir":
                found_here = names.get(d, {})
                self._listed[d] = [_Entry(n, found_here[n]) for n in sorted(found_here)]

    def scandir(self, path: str) -> list[_Entry]:
        entries = self._listed.get(path)
        if entries is not None:
            return entries
        if self._complete and _below(self._base, path):
            return []
        entries = self._listed[path] = self._fs.scandir(path)
        for e in entries:
            self._kinds[_child(path, e.name)] = e.kind
        return entries

    def kind(self, path: str, *, follow_symlinks: bool = True) -> EntryKind | None:
        if path in self._kinds:
            return self._kinds[path]
        if (self._complete and _below(self._base, path)) or _parent(
            path
        ) in self._listed:
            return None
        k = self._kinds[path] = self._fs.kind(path)
        return k

    def dir_key(self, path: str) -> None:
        return None

    def walk(self, top: str) -> Iterator[tuple[str, list[str], list[str]]]:
        if self.kind(top) != "dir":
            return
        stack = [top]
        while stack:
            d = stack.pop()
            entries = self.scandir(d)
            dirs = [e.name for e in entries if e.kind == "dir"]
            yield d, dirs, [e.name for e in entries if e.kind != "dir"]
            stack.extend(_child(d, name) for name in reversed(dirs))

    def subtree(self, path: str) -> FileSystem:
        return self if _below(self._base, path) else self._fs.subtree(path)


def url_to_fs(url: str, **storage_options: Any) -> tuple[FileSystem, str]:
    """Split a URL into a filesystem and a path in that filesystem's namespace.

    ``url_to_fs("s3://bucket/data")`` is ``(FsspecFS(S3FileSystem),
    "bucket/data")``; ``url_to_fs("memory://data")`` is ``(FsspecFS(...),
    "/data")``; a local path or ``file://`` URL gives `LocalFS`. Bind the
    path as an expression's root and pass the filesystem to `glob` or
    `infer`. ``storage_options`` go to fsspec (credentials, ``anon=True``,
    and so on). Needs fsspec (``pip install "wend[fsspec]"``).
    """
    try:
        from fsspec.core import url_to_fs as split
    except ImportError:
        raise ImportError(
            'wend.fs.url_to_fs needs fsspec: pip install "wend[fsspec]"'
        ) from None
    fs, path = split(url, **storage_options)
    if _protocols(fs) & {"file", "local"}:
        return LOCAL, path
    return FsspecFS(fs), path


def _check_root(fs: FileSystem, path: str) -> None:
    """Refuse a path that is a URL with its ``//`` collapsed (``s3:/bucket``)."""
    if isinstance(fs, FsspecFS):
        first = path.split("/", 1)[0]
        if first.endswith(":") and first[:-1] in _protocols(fs.fs):
            raise ValueError(
                f"{path!r} is a URL read as a path, with its '//' collapsed."
                " Split it with wend.fs.url_to_fs(url), which gives the"
                " filesystem and the path to bind as the root"
            )
