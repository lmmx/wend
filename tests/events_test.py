"""wend._experimental.events at runtime: each of three guarantees, what it
gives, and where it stops.

- It was true: `Checked` and `Confirmed` events, and `Run.known`, which is
  blind to other writers.
- Which object: a `Held` input keeps its object through rename, unlink and
  replacement of its name, not its contents.
- It remains true: a `Sealed` copy, which nothing can change."""

import os
from pathlib import Path

import pytest

from wend import (
    Absent,
    Checked,
    Confirmed,
    Creatable,
    Exists,
    File,
    P,
    Param,
    Readable,
    T,
)
from wend._experimental.events import Held, Holds, Run, Spec, Uses, seal
from wend._experimental.publish import Inconsistent
from wend.errors import ConditionError


root, name = Param("root"), Param("name")
raw = (P(root) / "raw" / T(t"{name}.csv")).requires(File, Exists, Readable)
out = (
    (P(root) / "out" / T(t"{name}.csv"))
    .requires(Absent, Creatable)
    .ensures(File, Exists)
)


class Convert(Spec):
    src = Holds(raw)
    dst = Uses(out)


class Drop(Spec):
    gone = Uses(raw.requires(Exists).ensures(Absent))


class Read(Spec):
    src = Uses(raw)


@pytest.fixture
def tree(tmp_path):
    (tmp_path / "raw").mkdir()
    (tmp_path / "raw" / "a.csv").write_bytes(b"mine")
    return tmp_path


def env(tree):
    return {"root": str(tree), "name": "a"}


def test_a_step_gives_events_and_holds_its_input(tree):
    run = Run(str(tree))
    with run.enter(Convert, env(tree)) as s:
        assert isinstance(s.src, Held) and s.src.access == {"read"}
        assert isinstance(s.dst, Checked) and not isinstance(s.dst, Confirmed)
        assert s.dst.__dict__["atoms"] == {"absent", "create"}
        Path(s.dst).parent.mkdir()
        Path(s.dst).write_bytes(s.src.read().upper())
    made = run.confirmed["out/a.csv"]
    assert isinstance(made, Confirmed) and not isinstance(made, Checked)
    assert made.__dict__["epoch"] > s.dst.__dict__["epoch"]
    assert run.known(made)
    assert Convert.src is raw  # on the class, the declaration


def test_an_event_stays_known_until_this_run_invalidates_it(tree):
    run = Run(str(tree))
    with run.enter(Read, env(tree)) as s:
        read_at_entry = s.src
    assert run.known(read_at_entry)
    with run.enter(Drop, env(tree)) as d:
        os.unlink(d.gone)
    assert not run.known(read_at_entry)  # the run deleted it: forgotten


def test_known_is_blind_to_another_writer(tree):
    # It says what this run has not invalidated, not what holds.
    run = Run(str(tree))
    with run.enter(Read, env(tree)) as s:
        event = s.src
    (tree / "raw" / "a.csv").unlink()  # not a step of the run
    assert run.known(event)
    assert not Path(event).exists()


@pytest.mark.parametrize("move", ["rename", "unlink", "replace"])
def test_a_held_input_keeps_its_object_whatever_happens_to_its_name(tree, move):
    run = Run(str(tree))
    x = tree / "raw" / "a.csv"
    with run.enter(Convert, env(tree)) as s:
        before = s.src.ident
        if move == "rename":
            x.rename(tree / "raw" / "b.csv")
        elif move == "unlink":
            x.unlink()
        else:
            (tree / "raw" / "new").write_bytes(b"theirs")
            (tree / "raw" / "new").rename(x)
        assert s.src.ident == before and s.src.read() == b"mine"
        Path(s.dst).parent.mkdir()
        Path(s.dst).write_bytes(b"done")


def test_a_held_input_does_not_keep_its_contents_but_a_sealed_copy_does(tree):
    run = Run(str(tree))
    # The step read two versions of its input; its derivation could record
    # only one, so the run refuses it at exit.
    with pytest.raises(Inconsistent, match="changed while the step read it"):
        with run.enter(Convert, env(tree)) as s:
            sealed = seal(s.src)
            (tree / "raw" / "a.csv").write_bytes(b"theirs")  # another writer
            assert s.src.read() == b"theirs"  # same object, new contents
            assert sealed.read() == b"mine"  # the copy cannot change
            assert sealed.source == s.src.ident
            with pytest.raises(PermissionError):
                os.pwrite(sealed.fd, b"X", 0)
            Path(s.dst).parent.mkdir()
            Path(s.dst).write_bytes(b"done")
    sealed.close()


@pytest.mark.parametrize("kind", ["hard link", "fifo"])
def test_an_input_that_is_not_confined_is_not_held(tree, tmp_path_factory, kind):
    x = tree / "raw" / "a.csv"
    x.unlink()
    if kind == "hard link":
        outside = tmp_path_factory.mktemp("outside") / "secret"
        outside.write_bytes(b"SECRET")
        os.link(outside, x)
    else:
        os.mkfifo(x)
    run = Run(str(tree))
    with pytest.raises(ConditionError):
        with run.enter(Convert, env(tree)):
            pass


def test_a_name_added_later_does_not_change_what_was_held(tree):
    # The one-name rule is judged at the open. A hard link made afterwards
    # gives the held object a second name; it is still the same object, and
    # the type never claimed it had one name for ever.
    run = Run(str(tree))
    with run.enter(Convert, env(tree)) as s:
        before = s.src.ident
        os.link(tree / "raw" / "a.csv", tree / "elsewhere")
        assert os.fstat(s.src.fd).st_nlink == 2 and s.src.ident == before
        Path(s.dst).parent.mkdir()
        Path(s.dst).write_bytes(b"done")


def test_only_a_readable_file_can_be_held():
    with pytest.raises(TypeError):
        Holds(P("a").requires(Exists))


def test_a_swap_between_the_check_and_the_hold_is_judged_at_the_hold(
    tree, tmp_path_factory
):
    # The check of Readable judges the object too, but the hold is a second
    # open: another writer can replace the name between the two.
    outside = tmp_path_factory.mktemp("outside") / "secret"
    outside.write_bytes(b"SECRET")
    run = Run(str(tree))
    check = run.io.check

    def check_then_swap(rel, atoms):
        check(rel, atoms)
        if rel == "raw/a.csv":
            (tree / "raw" / "a.csv").unlink()
            os.link(outside, tree / "raw" / "a.csv")

    run.io.check = check_then_swap
    with pytest.raises(ConditionError, match="hard links"):
        with run.enter(Convert, env(tree)):
            pass


def test_a_held_files_path_is_only_the_name_it_was_opened_by(tree):
    # Reopening the name is a new resolution: after a replacement it is
    # another object. Only the descriptor is the held object.
    run = Run(str(tree))
    with run.enter(Convert, env(tree)) as s:
        (tree / "raw" / "new").write_bytes(b"theirs")
        (tree / "raw" / "new").rename(tree / "raw" / "a.csv")
        assert Path(s.src.path).read_bytes() == b"theirs"
        assert s.src.read() == b"mine"
        Path(s.dst).parent.mkdir()
        Path(s.dst).write_bytes(b"done")
