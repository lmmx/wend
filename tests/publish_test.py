"""wend._experimental.publish against another writer and against failure:
writing the final name directly, writing a temporary name and renaming it,
and a nameless draft published in one system call."""

import errno
import os
import shutil
import signal
import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path

import pytest

from wend._experimental import publish as pub
from wend._experimental.confined import Confined
from wend._experimental.publish import Conflict, Draft


pytestmark = pytest.mark.linux


CHUNKS, CHUNK = 40, b"x" * 1024
WHOLE = CHUNK * CHUNKS


def direct(root: Path, pause: float = 0.001) -> None:
    with open(root / "out" / "final.csv", "wb") as f:
        for _ in range(CHUNKS):
            f.write(CHUNK)
            f.flush()
            time.sleep(pause)


def temp_name(root: Path, pause: float = 0.001) -> None:
    tmp = root / "out" / ".final.csv.tmp"
    with open(tmp, "xb") as f:
        for _ in range(CHUNKS):
            f.write(CHUNK)
            f.flush()
            time.sleep(pause)
    os.rename(tmp, root / "out" / "final.csv")


def draft(root: Path, pause: float = 0.001) -> None:
    io = Confined(str(root))
    try:
        d = Draft(io, "out")
        for _ in range(CHUNKS):
            d.write(CHUNK)
            time.sleep(pause)
        d.publish("final.csv")
    finally:
        io.close()


STRATEGIES = {"direct": direct, "temp name": temp_name, "draft": draft}


@pytest.fixture
def root(tmp_path):
    (tmp_path / "out").mkdir()
    return tmp_path


@pytest.mark.parametrize("strategy", list(STRATEGIES))
def test_whether_a_reader_can_see_a_partial_output(root, strategy):
    partial, stop = [], threading.Event()

    def reader():
        while not stop.is_set():
            try:
                data = (root / "out" / "final.csv").read_bytes()
            except FileNotFoundError:
                continue
            if data != WHOLE:
                partial.append(len(data))

    t = threading.Thread(target=reader)
    t.start()
    STRATEGIES[strategy](root)
    stop.set()
    t.join()
    assert bool(partial) is (strategy == "direct")


CHILD = textwrap.dedent(
    """
    import sys, time
    sys.path.insert(0, {src!r})
    sys.path.insert(0, {tests!r})
    from pathlib import Path
    import publish_test as t
    t.{fn}(Path({root!r}), pause=0.05)
    """
)


@pytest.mark.parametrize("strategy", list(STRATEGIES))
def test_what_a_writer_killed_halfway_leaves_behind(root, strategy):
    fn = {"direct": "direct", "temp name": "temp_name", "draft": "draft"}[strategy]
    code = CHILD.format(src="src", tests="tests", fn=fn, root=str(root))
    child = subprocess.Popen([sys.executable, "-c", code])
    time.sleep(0.6)  # some chunks written, not all
    child.send_signal(signal.SIGKILL)
    child.wait()
    left = sorted(os.listdir(root / "out"))
    expected = {"direct": ["final.csv"], "temp name": [".final.csv.tmp"], "draft": []}[
        strategy
    ]
    assert left == expected
    if strategy == "direct":
        assert (
            0 < (root / "out" / "final.csv").stat().st_size < len(WHOLE)
        )  # partial, at its final name


def test_a_draft_publishes_into_the_directory_it_holds_not_where_the_path_now_points(
    tmp_path,
):
    root, outside = tmp_path / "root", tmp_path / "outside"
    (root / "out").mkdir(parents=True)
    outside.mkdir()
    io = Confined(str(root))
    try:
        d = Draft(io, "out")
        d.write(b"report")
        (root / "out").rename(root / "moved")  # another writer, during the write
        (root / "out").symlink_to(outside)
        p = d.publish("final.csv")
    finally:
        io.close()
    assert (
        root / "moved" / "final.csv"
    ).read_bytes() == b"report"  # the held directory
    assert not list(outside.iterdir())  # never outside
    assert p.at_path is False  # and the event says the path no longer led there


def test_a_temporary_name_made_by_path_after_a_swap_lands_outside(tmp_path):
    root, outside = tmp_path / "root", tmp_path / "outside"
    (root / "out").mkdir(parents=True)
    outside.mkdir()
    (root / "out").rmdir()
    (root / "out").symlink_to(outside)  # swapped before the write began
    temp_name(root, pause=0)
    assert (outside / "final.csv").read_bytes() == WHOLE


def test_create_never_clobbers_where_checking_first_does(root):
    final = root / "out" / "final.csv"
    # check, then write: another writer's file appears in between
    assert not final.exists()
    final.write_bytes(b"theirs")
    with open(final, "wb") as f:  # the check passed; this clobbers it
        f.write(b"mine")
    assert final.read_bytes() == b"mine"
    final.write_bytes(b"theirs")
    io = Confined(str(root))
    try:
        d = Draft(io, "out")
        d.write(b"mine")
        with pytest.raises(FileExistsError):
            d.publish("final.csv")
        assert final.read_bytes() == b"theirs" and not d.spent  # still live
        theirs = (final.stat().st_dev, final.stat().st_ino)
        p = d.publish("final.csv", policy="replace")
        assert p.previous == theirs and final.read_bytes() == b"mine"
    finally:
        io.close()


def test_two_writers_of_one_name_interleave_directly_and_never_as_drafts(root):
    final = root / "out" / "final.csv"
    a, b = b"A" * 2048, b"B" * 2048
    # Directly: A opens and writes half; B opens (truncating) and writes all;
    # A writes its second half. The result is neither writer's output.
    fa = open(final, "wb")
    fa.write(a[:1024])
    fa.flush()
    with open(final, "wb") as fb:
        fb.write(b)
    fa.write(a[1024:])
    fa.close()
    mixed = final.read_bytes()
    assert mixed not in (a, b)
    final.unlink()
    # As drafts, the same interleaving: each writes its own object.
    io = Confined(str(root))
    try:
        da, db = Draft(io, "out"), Draft(io, "out")
        da.write(a[:1024])
        db.write(b)
        db.publish("final.csv", policy="replace")
        da.write(a[1024:])
        da.publish("final.csv", policy="replace")
    finally:
        io.close()
    assert final.read_bytes() == a


def test_readers_of_a_name_replaced_repeatedly_see_only_whole_outputs(root):
    versions = [bytes([65 + i]) * 65536 for i in range(8)]
    seen, stop = set(), threading.Event()

    def reader():
        while not stop.is_set():
            try:
                seen.add((root / "out" / "final.csv").read_bytes())
            except FileNotFoundError:
                pass

    def writer(v):
        io = Confined(str(root))
        try:
            for _ in range(20):
                d = Draft(io, "out")
                d.write(v)
                d.publish("final.csv", policy="replace", durable=False)
        finally:
            io.close()

    r = threading.Thread(target=reader)
    r.start()
    ws = [threading.Thread(target=writer, args=(v,)) for v in versions]
    for w in ws:
        w.start()
    for w in ws:
        w.join()
    stop.set()
    r.join()
    assert seen and seen <= set(versions)


def test_exchange_with_expect_undoes_a_lost_update_but_was_visible(root, monkeypatch):
    final = root / "out" / "final.csv"
    final.write_bytes(b"v0")
    expected = (final.stat().st_dev, final.stat().st_ino)
    io = Confined(str(root))
    try:
        mine = Draft(io, "out")
        mine.write(b"mine")
        theirs = Draft(io, "out")  # another writer publishes after we observed
        theirs.write(b"theirs")
        theirs.publish("final.csv", policy="replace")
        glimpsed = []
        real = pub.renameat2

        def spying(*args):
            real(*args)
            glimpsed.append(final.read_bytes())

        monkeypatch.setattr(pub, "renameat2", spying)
        with pytest.raises(Conflict):
            mine.publish("final.csv", policy="exchange", expect=expected)
        assert final.read_bytes() == b"theirs"  # their update survives
        assert glimpsed[0] == b"mine"  # but ours was briefly the file
        assert not mine.spent
    finally:
        io.close()


def test_a_published_draft_can_no_longer_be_written(root):
    io = Confined(str(root))
    try:
        d = Draft(io, "out")
        d.write(b"done")
        d.publish("final.csv")
        with pytest.raises(ValueError, match="spent"):
            d.write(b"more")
    finally:
        io.close()


@pytest.mark.parametrize("policy", ["create", "replace"])
def test_the_durability_protocol_syncs_the_file_then_publishes_then_syncs_the_directory(
    root, monkeypatch, policy
):
    import stat

    calls = []
    real_fsync, real_link, real_rename = os.fsync, os.link, os.rename

    def fsync(fd):
        calls.append(
            "fsync dir" if stat.S_ISDIR(os.fstat(fd).st_mode) else "fsync file"
        )
        real_fsync(fd)

    def link(*a, **k):
        calls.append("link")
        real_link(*a, **k)

    def rename(*a, **k):
        calls.append("rename")
        real_rename(*a, **k)

    monkeypatch.setattr(pub.os, "fsync", fsync)
    monkeypatch.setattr(pub.os, "link", link)
    monkeypatch.setattr(pub.os, "rename", rename)
    if policy == "replace":
        (root / "out" / "final.csv").write_bytes(b"old")
    io = Confined(str(root))
    try:
        d = Draft(io, "out")
        d.write(b"new")
        d.publish("final.csv", policy=policy)
    finally:
        io.close()
    published = ["link"] if policy == "create" else ["link", "rename"]
    assert calls == ["fsync file", *published, "fsync dir"]


def test_a_failed_draft_leaves_nothing(root):
    io = Confined(str(root))
    try:
        d = Draft(io, "out")
        d.write(b"half")
        d.abandon()
    finally:
        io.close()
    assert os.listdir(root / "out") == []
    shutil.rmtree(root / "out")


# -- the cells of the journal's §2 table that had no test (its audit, A.3) -------


def test_a_link_put_before_the_write_sends_a_direct_write_outside_and_refuses_a_draft(
    tmp_path,
):
    root, outside = tmp_path / "root", tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (root / "out").symlink_to(outside)  # out/ swapped before the write began
    direct(root, pause=0)
    assert (outside / "final.csv").read_bytes() == WHOLE  # written outside
    (outside / "final.csv").unlink()
    io = Confined(str(root))
    try:
        # its directory is opened beneath the root, with no symlinks: openat2
        # refuses the link with ELOOP (a plain OSError here, where the check
        # path raises ContainmentError)
        with pytest.raises(OSError) as e:
            Draft(io, "out")
        assert e.value.errno == errno.ELOOP
    finally:
        io.close()
    assert list(outside.iterdir()) == []


def test_a_temporary_names_rename_clobbers_a_file_made_after_the_check(root):
    final = root / "out" / "final.csv"
    assert not final.exists()  # the check
    final.write_bytes(b"theirs")  # another writer, after it
    temp_name(root, pause=0)
    assert final.read_bytes() == WHOLE  # rename replaced theirs


def test_temporary_name_writers_interleaved_each_land_whole_if_their_names_differ(
    root,
):
    final = root / "out" / "final.csv"
    a, b = b"A" * 2048, b"B" * 2048
    # one temporary name, opened exclusively as temp_name does: the second
    # writer cannot start while the first is writing
    tmp = root / "out" / ".final.csv.tmp"
    fa = open(tmp, "xb")
    fa.write(a[:1024])
    with pytest.raises(FileExistsError):
        open(tmp, "xb")
    fa.close()
    tmp.unlink()
    # a temporary name each: interleaved, and each lands whole
    ta, tb = root / "out" / ".a.tmp", root / "out" / ".b.tmp"
    fa = open(ta, "xb")
    fa.write(a[:1024])
    fa.flush()
    with open(tb, "xb") as fb:
        fb.write(b)
    os.rename(tb, final)
    assert final.read_bytes() == b
    fa.write(a[1024:])
    fa.close()
    os.rename(ta, final)
    assert final.read_bytes() == a  # whole; the last renamed wins
