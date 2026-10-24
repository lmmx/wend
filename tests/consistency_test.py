"""Several inputs and several outputs: what a pipeline can know about them
together.

- Detecting: a double collect over files, under adversarial schedules. With
  a writer through dirty pages of a shared mapping, every observer accepts
  a snapshot of two files that never existed together.
- Publishing several outputs at once: a generation directory, published by
  one exchange. A reader that holds it reads one generation; a reader that
  goes by names can read two.
- Invalidating: a derivation names the inputs that changed, as observed."""

import mmap
import os
import shutil
import threading
import time
from pathlib import Path

import pytest

from wend._experimental.confined import Confined
from wend._experimental.fresh import Busy, collect, observe
from wend._experimental.publish import Derivation, Draft, Generation, hold_dir, read_in


pytestmark = pytest.mark.linux


SIZE = 4096
A0, A1 = b"a" * SIZE, b"A" * SIZE
B0, B1 = b"b" * SIZE, b"B" * SIZE


class Files:
    """Two inputs, and another writer who changes both at once (as one
    transaction of its own), by ``write`` or through dirty mapped pages."""

    def __init__(self, root: Path, mapped: bool) -> None:
        self.root = root
        for n, v in (("a", A0), ("b", B0)):
            (root / n).write_bytes(v)
        self.maps = {}
        if mapped:
            for n in ("a", "b"):
                fd = os.open(root / n, os.O_RDWR)
                m = mmap.mmap(fd, SIZE)
                m[0:1] = m[0:1]  # dirty the page; no change of contents
                self.maps[n] = (fd, m)
            time.sleep(0.01)

    def set(self, a: bytes, b: bytes) -> None:
        for n, v in (("a", a), ("b", b)):
            if self.maps:
                self.maps[n][1][:] = v
            else:
                fd = os.open(self.root / n, os.O_WRONLY)
                os.pwrite(fd, v, 0)
                os.close(fd)

    def close(self) -> None:
        for fd, m in self.maps.values():
            m.close()
            os.close(fd)


def schedule(files: Files):
    """Copy a, then (a1, b1); copy b; then (a0, b0); check a; then (a1, b1);
    check b. The copies are a0 and b1, which never existed together, and
    each check finds its file as it was copied."""
    moves = {("first", 0): (A1, B1), ("first", 1): (A0, B0), ("second", 0): (A1, B1)}

    def between(phase, i):
        if (phase, i) in moves:
            files.set(*moves[(phase, i)])

    return between


@pytest.mark.parametrize("mapped", [False, True], ids=["write", "dirty mapped pages"])
@pytest.mark.parametrize("observer", ["meta", "digest", "meta+digest", "watch"])
def test_which_observer_accepts_a_snapshot_that_never_existed(
    tmp_path, observer, mapped
):
    files = Files(tmp_path, mapped)
    io = Confined(str(tmp_path))
    try:
        copies, coherent = collect(
            io, ["a", "b"], observer=observer, between=schedule(files)
        )
    finally:
        io.close()
        files.close()
    assert (copies["a"].read(), copies["b"].read()) == (A0, B1)  # never together
    # Through write(), any observer of metadata or events sees the change;
    # contents alone see nothing, the change having been undone. Through dirty
    # mapped pages, nothing sees it.
    fooled = mapped or observer == "digest"
    assert coherent is fooled


def test_a_read_lease_excludes_the_writer_no_observer_sees(tmp_path):
    # The writer every observer misses holds dirty pages of a shared
    # mapping. It cannot be seen changing a file, but the kernel knows it
    # can: no read lease is granted while it exists.
    files = Files(tmp_path, mapped=True)
    io = Confined(str(tmp_path))
    try:
        with pytest.raises(Busy):
            collect(io, ["a", "b"], observer="lease")
        files.close()  # once it is gone, the copies are made with no writer
        copies, coherent = collect(io, ["a", "b"], observer="lease")
        assert coherent and (copies["a"].read(), copies["b"].read()) == (A0, B0)
    finally:
        io.close()


def test_a_writer_that_arrives_during_a_leased_collect_is_held_off_and_seen(
    tmp_path,
):
    files = Files(tmp_path, mapped=False)
    tried = []

    def between(phase, i):
        if (phase, i) == ("first", 0):
            # another writer opens b for writing: it must wait, and asking
            # breaks the lease (here it does not wait: O_NONBLOCK)
            try:
                os.open(tmp_path / "b", os.O_WRONLY | os.O_NONBLOCK)
            except BlockingIOError:
                tried.append("held off")

    io = Confined(str(tmp_path))
    try:
        copies, coherent = collect(io, ["a", "b"], observer="lease", between=between)
    finally:
        io.close()
        files.close()
    assert tried == ["held off"] and coherent is False  # conservative: retry
    assert (copies["a"].read(), copies["b"].read()) == (A0, B0)


def test_holding_a_generation_reads_one_generation_and_names_can_read_two(tmp_path):
    io = Confined(str(tmp_path))
    try:
        g = Generation(io, "", "current")
        g.add("a.csv", b"A1")
        g.add("b.csv", b"B1")
        g.commit()
        held = hold_dir(io, "current")
        by_name_a = (tmp_path / "current" / "a.csv").read_bytes()
        held_a = read_in(held, "a.csv")
        g = Generation(io, "", "current")
        g.add("a.csv", b"A2")
        g.add("b.csv", b"B2")
        g.commit()  # between the two reads
        assert (held_a, read_in(held, "b.csv")) == (b"A1", b"B1")
        assert (by_name_a, (tmp_path / "current" / "b.csv").read_bytes()) == (
            b"A1",
            b"B2",
        )
        os.close(held)
    finally:
        io.close()


def test_outputs_replaced_one_at_a_time_are_seen_half_updated(tmp_path):
    (tmp_path / "out").mkdir()
    io = Confined(str(tmp_path))
    try:
        for name, v in (("a.csv", b"A1"), ("b.csv", b"B1")):
            d = Draft(io, "out")
            d.write(v)
            d.publish(name)
        d = Draft(io, "out")
        d.write(b"A2")
        d.publish("a.csv", policy="replace")
        # a reader now: each file whole, the pair from two runs
        pair = tuple((tmp_path / "out" / n).read_bytes() for n in ("a.csv", "b.csv"))
        assert pair == (b"A2", b"B1")
    finally:
        io.close()


def test_readers_holding_generations_never_see_a_mixture_under_a_busy_producer(
    tmp_path,
):
    # With its control, under the same producer: readers that go by name,
    # reading current/a.csv and then current/b.csv, do see mixtures. Without
    # it, a producer too slow to interleave would pass the test too.
    io = Confined(str(tmp_path))
    g = Generation(io, "", "current")
    g.add("a.csv", b"0")
    g.add("b.csv", b"0")
    g.commit()
    stop = threading.Event()
    mixtures: dict[str, list] = {"held": [], "by name": []}
    reads = {"held": 0, "by name": 0}
    olds = []

    def producer():
        pio = Confined(str(tmp_path))
        try:
            for i in range(1, 60):
                g = Generation(pio, "", "current")
                g.add("a.csv", str(i).encode())
                g.add("b.csv", str(i).encode())
                old = g.commit()
                if old:
                    olds.append(old)  # kept, for readers that hold it
        finally:
            pio.close()

    def reader(kind):
        rio = Confined(str(tmp_path))
        try:
            while not stop.is_set():
                if kind == "held":
                    held = hold_dir(rio, "current")
                    try:
                        pair = (read_in(held, "a.csv"), read_in(held, "b.csv"))
                    finally:
                        os.close(held)
                else:
                    try:
                        pair = (
                            rio.read_bytes("current/a.csv"),
                            rio.read_bytes("current/b.csv"),
                        )
                    except FileNotFoundError:
                        continue  # between the producer's two renames
                reads[kind] += 1
                if pair[0] != pair[1]:
                    mixtures[kind].append(pair)
        finally:
            rio.close()

    readers = [
        threading.Thread(target=reader, args=(kind,))
        for kind in ("held", "by name")
        for _ in range(3)
    ]
    for r in readers:
        r.start()
    producer()
    stop.set()
    for r in readers:
        r.join()
    io.close()
    assert reads["held"] > 0 and not mixtures["held"]
    assert reads["by name"] > 0 and mixtures["by name"]  # the control


def test_reclaiming_a_generation_a_reader_holds_fails_its_reads_closed(tmp_path):
    io = Confined(str(tmp_path))
    try:
        g = Generation(io, "", "current")
        g.add("a.csv", b"A1")
        g.add("b.csv", b"B1")
        g.commit()
        held = hold_dir(io, "current")
        assert read_in(held, "a.csv") == b"A1"
        g = Generation(io, "", "current")
        g.add("a.csv", b"A2")
        g.add("b.csv", b"B2")
        old = g.commit()
        shutil.rmtree(tmp_path / old)  # reclaimed before the reader finished
        with pytest.raises(FileNotFoundError):
            read_in(held, "b.csv")  # neither B1 nor B2: the read fails
        os.close(held)
    finally:
        io.close()


def test_a_derivation_names_what_changed_and_what_superseded_it(tmp_path):
    (tmp_path / "raw").mkdir()
    (tmp_path / "out").mkdir()
    (tmp_path / "raw" / "a.csv").write_bytes(b"1,2")
    (tmp_path / "raw" / "b.csv").write_bytes(b"3,4")
    io = Confined(str(tmp_path))
    try:
        inputs = {r: observe(io, r) for r in ("raw/a.csv", "raw/b.csv")}
        d = Draft(io, "out")
        d.write(b"sum")
        dv = Derivation(d.publish("sum.csv"), inputs)
        assert dv.stale(io) == {}
        (tmp_path / "raw" / "b.csv").write_bytes(b"3,5")  # another writer
        assert dv.stale(io) == {"raw/b.csv": "changed"}
        d = Draft(io, "out")
        d.write(b"theirs")
        d.publish("sum.csv", policy="replace")
        assert dv.stale(io) == {"raw/b.csv": "changed", "out/sum.csv": "superseded"}
    finally:
        io.close()


def test_a_name_renamed_over_between_the_collects_is_seen_by_its_name(tmp_path):
    # The held copy of a is unchanged (same object, same contents), so only
    # resolving the name again shows that a now means another file.
    for n, v in (("a", A0), ("b", B0)):
        (tmp_path / n).write_bytes(v)

    def between(phase, i):
        if (phase, i) == ("first", 1):
            (tmp_path / "new").write_bytes(A1)
            (tmp_path / "new").rename(tmp_path / "a")

    io = Confined(str(tmp_path))
    try:
        _, coherent = collect(io, ["a", "b"], observer="digest", between=between)
    finally:
        io.close()
    assert coherent is False


def test_a_collect_observes_the_bytes_it_copies(tmp_path, monkeypatch):
    # The first pass once took its digest from one read and its copy from
    # another. A change between the two, undone before the second pass, then
    # gave a copy the observation never saw, reported coherent. Now the copy
    # is the read the digest is taken from.
    from wend._experimental import fresh

    (tmp_path / "a").write_bytes(A0)
    real, calls = fresh.fingerprint, []

    def fingerprint(fd, *, content):
        fp = real(fd, content=content)
        if not calls:  # just after the first observation, another writer
            (tmp_path / "a").write_bytes(A1)
        calls.append(fp)
        return fp

    def between(phase, i):
        if phase == "first":
            (tmp_path / "a").write_bytes(A0)  # and undoes it

    monkeypatch.setattr(fresh, "fingerprint", fingerprint)
    io = Confined(str(tmp_path))
    try:
        copies, coherent = collect(io, ["a"], observer="digest", between=between)
    finally:
        io.close()
    assert calls  # the writer acted
    assert not coherent or copies["a"].read() == A0
