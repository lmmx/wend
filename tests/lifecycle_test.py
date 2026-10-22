"""A step's inputs and outputs, from acquisition to publication: `Holds` and
`Makes` ports of `wend._experimental.events`, run by `Run`.

An input is checked (an event), held (which object), and observed (a
fingerprint). An output is a draft no one can see, published whole when the
step finishes, or never; and a derivation records what it was made from."""

import os
import threading
import time

import pytest

from wend import Absent, Creatable, Exists, File, P, Param, Readable, T
from wend._experimental.events import Holds, Makes, Run, Spec, Uses, seal


pytestmark = pytest.mark.linux


root, day = Param("root"), Param("day")
raw = (P(root) / "raw" / T(t"{day}.csv")).requires(File, Exists, Readable)
clean = (
    (P(root) / "clean" / T(t"{day}.csv"))
    .requires(Absent, Creatable)
    .ensures(File, Exists)
)
summary = (
    (P(root) / "clean" / T(t"{day}.txt"))
    .requires(Absent, Creatable)
    .ensures(File, Exists)
)


class Clean(Spec):
    src = Holds(raw)
    dst = Makes(clean)


class CleanTwice(Spec):
    src = Holds(raw)
    dst = Makes(clean)
    note = Makes(summary)


@pytest.fixture
def tree(tmp_path):
    (tmp_path / "raw").mkdir()
    (tmp_path / "raw" / "mon.csv").write_bytes(b"a,b\n1,2\n")
    return tmp_path


def env(tree):
    return {"root": str(tree), "day": "mon"}


def test_an_output_is_invisible_until_the_step_ends_and_then_whole(tree):
    out = tree / "clean" / "mon.csv"
    seen, stop = [], threading.Event()

    def reader():
        while not stop.is_set():
            try:
                seen.append(out.read_bytes())
            except FileNotFoundError:
                pass

    t = threading.Thread(target=reader)
    t.start()
    run = Run(str(tree))
    with run.enter(Clean, env(tree)) as s:
        data = s.src.read().upper()
        for i in range(0, len(data), 2):
            s.dst.write(data[i : i + 2])
            time.sleep(0.005)
        assert not out.exists()
    stop.set()
    t.join()
    assert out.read_bytes() == b"A,B\n1,2\n"
    assert set(seen) <= {b"A,B\n1,2\n"}
    assert run.published["clean/mon.csv"].current(run.io)


def test_a_failed_step_publishes_nothing_and_leaves_nothing(tree):
    run = Run(str(tree))
    with pytest.raises(RuntimeError):
        with run.enter(Clean, env(tree)) as s:
            s.dst.write(b"half")
            raise RuntimeError("the step fails")
    assert os.listdir(tree / "clean") == []  # its directory was made; nothing in it
    assert run.published == {} and run.derivations == []


def test_a_name_taken_during_the_step_fails_the_step_and_keeps_their_file(tree):
    run = Run(str(tree))
    with pytest.raises(FileExistsError):
        with run.enter(Clean, env(tree)) as s:
            s.dst.write(b"mine")
            (tree / "clean" / "mon.csv").write_bytes(b"theirs")  # another writer
    assert (tree / "clean" / "mon.csv").read_bytes() == b"theirs"


def test_two_outputs_are_each_whole_but_not_published_together(tree):
    run = Run(str(tree))
    with pytest.raises(FileExistsError):
        with run.enter(CleanTwice, env(tree)) as s:
            s.dst.write(b"csv")
            s.note.write(b"txt")
            (tree / "clean" / "mon.txt").write_bytes(b"theirs")
    # the first was published before the second failed: a Generation is
    # what publishes several at once
    assert (tree / "clean" / "mon.csv").read_bytes() == b"csv"
    assert (tree / "clean" / "mon.txt").read_bytes() == b"theirs"


class CleanAndSee(Spec):
    src = Holds(raw)
    seen = Uses(raw)  # the same input, as a check event
    dst = Makes(clean)


def test_knowledge_and_observation_part_ways_under_another_writer(tree):
    # The full path: an input checked (it was true), held (which object) and
    # sealed (it remains so, for the copy); an output drafted and published;
    # a derivation tying them. Then another writer changes the input.
    run = Run(str(tree))
    with run.enter(CleanAndSee, env(tree)) as s:
        event = s.seen
        copy = seal(s.src)
        s.dst.write(copy.read().upper())
    (derivation,) = run.derivations
    assert run.known(event) and derivation.stale(run.io) == {}
    (tree / "raw" / "mon.csv").write_bytes(b"a,b\n9,9\n")  # another writer
    # Knowledge assumes no other writer: the run still knows its check.
    assert run.known(event)
    # Observation sees the change, and says which output it puts in doubt.
    assert derivation.stale(run.io) == {"raw/mon.csv": "changed"}
    assert copy.read() == b"a,b\n1,2\n"  # the sealed copy is what was used
    copy.close()


def test_only_a_new_file_can_be_made():
    with pytest.raises(TypeError):
        Makes(raw)


mid = (P(root) / "mid" / T(t"{day}.csv")).requires(File, Exists, Readable)
mid_new = (
    (P(root) / "mid" / T(t"{day}.csv"))
    .requires(Absent, Creatable)
    .ensures(File, Exists)
)
final = (
    (P(root) / "final" / T(t"{day}.csv"))
    .requires(Absent, Creatable)
    .ensures(File, Exists)
)


class First(Spec):
    src = Holds(raw)
    dst = Makes(mid_new)


class Second(Spec):
    src = Holds(mid)
    dst = Makes(final)


def test_a_change_upstream_puts_every_result_downstream_in_doubt(tree):
    from wend._experimental.publish import invalidated

    run = Run(str(tree))
    for spec in (First, Second):
        with run.enter(spec, env(tree)) as s:
            s.dst.write(s.src.read() + b"+")
    assert invalidated(run.derivations, run.io) == {}
    (tree / "raw" / "mon.csv").write_bytes(b"changed")  # another writer, upstream
    # The second step's own input did not change: only the chain shows doubt.
    assert run.derivations[1].stale(run.io) == {}
    assert invalidated(run.derivations, run.io) == {
        "mid/mon.csv": {"raw/mon.csv"},
        "final/mon.csv": {"mid/mon.csv"},
    }
