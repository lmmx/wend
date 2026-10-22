"""What a held descriptor keeps, and what it does not, on this kernel
(docs/journal/2026-10-22-confinement-is-not-consistency.md §3).

A descriptor keeps its object (through rename, unlink and replacement of
its name), not the object's contents or names. Kernel-backed mechanisms
that keep more are checked where this kernel and filesystem offer them."""

import ctypes
import errno
import fcntl
import os

import pytest

from wend._experimental.identity import Held


def _ident(fd: int) -> tuple[int, int]:
    s = os.fstat(fd)
    return (s.st_dev, s.st_ino)


@pytest.fixture
def held(tmp_path):
    (tmp_path / "x").write_bytes(b"mine")
    with Held(str(tmp_path / "x")) as h:
        yield h, _ident(h.fd)


@pytest.mark.parametrize("move", ["rename", "unlink", "replace"])
def test_a_held_file_keeps_its_object_whatever_happens_to_its_name(
    tmp_path, held, move
):
    h, before = held
    x = tmp_path / "x"
    if move == "rename":
        x.rename(tmp_path / "y")
    elif move == "unlink":
        x.unlink()
    else:  # the atomic-replace idiom: write a new file, rename it over the name
        (tmp_path / "new").write_bytes(b"theirs")
        (tmp_path / "new").rename(x)
        assert x.read_bytes() == b"theirs"  # the name now means another object
    assert _ident(h.fd) == before and h.read() == b"mine"
    assert os.fstat(h.fd).st_nlink == (1 if move == "rename" else 0)


@pytest.mark.parametrize("move", ["rewrite", "truncate", "hard_link"])
def test_a_held_file_does_not_keep_its_contents(tmp_path, held, move):
    h, _ = held
    x = tmp_path / "x"
    if move == "rewrite":
        x.write_bytes(b"theirs")
    elif move == "truncate":
        os.truncate(x, 0)
    else:
        os.link(x, tmp_path / "h")
        (tmp_path / "h").write_bytes(b"via a link")
    assert h.read() != b"mine"  # identity held, contents not


FS_IOC_GETFLAGS, FS_IOC_SETFLAGS, FS_IMMUTABLE_FL = 0x80086601, 0x40086602, 0x10


def test_an_immutable_file_refuses_writes_and_unlinks_even_for_root(tmp_path):
    x = tmp_path / "x"
    x.write_bytes(b"mine")
    fd = os.open(x, os.O_RDONLY)
    flags = ctypes.c_long(0)
    try:
        fcntl.ioctl(fd, FS_IOC_GETFLAGS, flags)
        fcntl.ioctl(fd, FS_IOC_SETFLAGS, ctypes.c_long(flags.value | FS_IMMUTABLE_FL))
    except OSError as e:
        os.close(fd)
        pytest.skip(f"cannot set the immutable flag here: {e}")
    try:
        with pytest.raises(PermissionError):
            x.write_bytes(b"theirs")
        with pytest.raises(PermissionError):
            x.unlink()
        assert os.pread(fd, 10, 0) == b"mine"
    finally:
        fcntl.ioctl(fd, FS_IOC_SETFLAGS, flags)
        os.close(fd)


F_ADD_SEALS = 1033
F_SEAL_SEAL, F_SEAL_SHRINK, F_SEAL_GROW, F_SEAL_WRITE = 1, 2, 4, 8


def test_a_sealed_copy_cannot_change_for_any_holder():
    m = os.memfd_create("snapshot", os.MFD_ALLOW_SEALING)
    try:
        os.write(m, b"snapshot")
        fcntl.fcntl(
            m, F_ADD_SEALS, F_SEAL_WRITE | F_SEAL_SHRINK | F_SEAL_GROW | F_SEAL_SEAL
        )
        with pytest.raises(PermissionError):
            os.pwrite(m, b"X", 0)
        with pytest.raises(PermissionError):
            os.ftruncate(m, 0)
        # another holder of the same object (through /proc) cannot write either
        other = os.open(f"/proc/self/fd/{m}", os.O_RDWR)
        try:
            with pytest.raises(PermissionError):
                os.pwrite(other, b"X", 0)
        finally:
            os.close(other)
        assert os.pread(m, 8, 0) == b"snapshot"
    finally:
        os.close(m)


def test_an_output_can_be_published_whole_and_without_clobbering(tmp_path):
    # O_TMPFILE: nameless until linked, so no reader sees it partly written.
    t = os.open(tmp_path, os.O_TMPFILE | os.O_WRONLY, 0o600)
    os.write(t, b"whole")
    os.link(f"/proc/self/fd/{t}", tmp_path / "out", follow_symlinks=True)
    os.close(t)
    assert (tmp_path / "out").read_bytes() == b"whole"
    # renameat2(RENAME_NOREPLACE): a rename that refuses an existing name.
    (tmp_path / "new").write_bytes(b"again")
    libc = ctypes.CDLL(None, use_errno=True)
    rc = libc.renameat2(-100, bytes(tmp_path / "new"), -100, bytes(tmp_path / "out"), 1)
    assert rc == -1 and ctypes.get_errno() == errno.EEXIST
    assert (tmp_path / "out").read_bytes() == b"whole"
