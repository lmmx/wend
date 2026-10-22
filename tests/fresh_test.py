"""wend._experimental.fresh: which observer sees which move of another writer
between two observations of a file. Each cell of the table is a test; the
last row is a move no observer sees."""

import mmap
import os
import time
from pathlib import Path

import pytest

from wend._experimental.confined import Confined
from wend._experimental.fresh import Watch, fingerprint, observe, revalidate


SIZE = 4096  # one page


def rewrite(p: Path) -> None:
    fd = os.open(p, os.O_WRONLY)
    os.pwrite(fd, b"b" * SIZE, 0)
    os.close(fd)


def rewrite_restoring_mtime(p: Path) -> None:
    s = os.stat(p)
    rewrite(p)
    os.utime(p, ns=(s.st_atime_ns, s.st_mtime_ns))


def change_and_back(p: Path) -> None:
    rewrite(p)
    p.write_bytes(b"a" * SIZE)


def replace_name(p: Path) -> None:
    (p.parent / "new").write_bytes(b"a" * SIZE)
    (p.parent / "new").rename(p)


def through_hard_link(p: Path) -> None:
    os.link(p, p.parent / "other")
    fd = os.open(p.parent / "other", os.O_WRONLY)
    os.pwrite(fd, b"b", 0)
    os.close(fd)


class Mapped:
    """A writer through a shared mapping; with ``dirty``, its page is made
    dirty (with the byte already there) before the first observation."""

    def __init__(self, p: Path, dirty: bool) -> None:
        self.fd = os.open(p, os.O_RDWR)
        self.m = mmap.mmap(self.fd, SIZE)
        if dirty:
            self.m[0:1] = b"a"
            time.sleep(0.01)

    def close(self) -> None:
        self.m.close()
        os.close(self.fd)


MOVES = {
    "same-size rewrite": rewrite,
    "rewrite, mtime restored": rewrite_restoring_mtime,
    "change, then change back": change_and_back,
    "a new file renamed over the name": replace_name,
    "a write through a hard link": through_hard_link,
    "mmap, first write to a clean page": "mmap-clean",
    "mmap, write to a dirty page": "mmap-dirty",
    "mmap, dirty page changed and changed back": "mmap-dirty-aba",
}
OBSERVERS = ["meta", "digest", "meta+digest", "watch"]
# Which observer sees which move, on this kernel (ext4, fine timestamps).
SEES = {
    "same-size rewrite": {"meta", "digest", "meta+digest", "watch"},
    "rewrite, mtime restored": {
        "meta",
        "digest",
        "meta+digest",
        "watch",
    },  # ctime moved
    "change, then change back": {"meta", "meta+digest", "watch"},
    "a new file renamed over the name": {"meta", "digest", "meta+digest", "watch"},
    "a write through a hard link": {"meta", "digest", "meta+digest", "watch"},
    "mmap, first write to a clean page": {"meta", "digest", "meta+digest"},
    "mmap, write to a dirty page": {"digest", "meta+digest"},
    "mmap, dirty page changed and changed back": set(),
}


def saw(observer: str, move: str, root: Path) -> bool:
    p = root / "x"
    p.write_bytes(b"a" * SIZE)
    act = MOVES[move]
    mapped = None
    if isinstance(act, str):
        mapped = Mapped(p, dirty=act != "mmap-clean")
    io = Confined(str(root))
    held = os.open(p, os.O_RDONLY)
    try:
        if observer == "watch":
            w = Watch([held])
            w.drain()
            w.events, w.overflowed = 0, False
        else:
            fp = observe(io, "x", content=observer != "meta")
        if mapped is not None:
            if act == "mmap-dirty-aba":
                mapped.m[0:1] = b"Z"
                mapped.m[0:1] = b"a"
            else:
                mapped.m[1:2] = b"c"
        else:
            act(p)
        time.sleep(0.01)
        if observer == "watch":
            seen = w.changed()
            w.close()
            return seen
        if observer == "meta+digest":
            return revalidate(fp, io, "x") != "unchanged"
        verdict = revalidate(fp, io, "x")
        if observer == "meta":
            return verdict != "unchanged"
        # digest alone: the contents and which object, not the times
        if verdict in ("replaced", "gone", "refused"):
            return True
        return observe(io, "x", content=True).digest != fp.digest
    finally:
        os.close(held)
        io.close()
        if mapped is not None:
            mapped.close()


@pytest.mark.parametrize("observer", OBSERVERS)
@pytest.mark.parametrize("move", list(MOVES))
def test_what_each_observer_sees(tmp_path, move, observer):
    assert saw(observer, move, tmp_path) is (observer in SEES[move])


def test_some_moves_leave_no_trace_for_any_observer():
    # The witness for the limit of observation: through a page already dirty
    # in a shared mapping, a writer can change a file and change it back with
    # no change of time, size or contents at either moment, and no event.
    assert SEES["mmap, dirty page changed and changed back"] == set()


def test_a_fingerprint_of_a_held_file_is_of_the_object_not_the_name(tmp_path):
    p = tmp_path / "x"
    p.write_bytes(b"mine")
    fd = os.open(p, os.O_RDONLY)
    before = fingerprint(fd, content=True)
    replace_name(p)
    after = fingerprint(fd, content=True)
    # The held object keeps its identity and contents; losing its name
    # changed its link count, and so its ctime.
    assert (after.ident, after.digest) == (before.ident, before.digest)
    assert after.ctime_ns != before.ctime_ns
    io = Confined(str(tmp_path))
    try:
        assert revalidate(before, io, "x") == "replaced"  # the name did
    finally:
        io.close()
        os.close(fd)
