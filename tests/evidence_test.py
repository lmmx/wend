"""What `checked` and `confirmed` establish, and what they do not
(SEMANTICS.md §10.2): one phase's conditions, of one rendered name, at the
instants of one call; a record that a later change leaves as it was; and
not a path, so nothing derived from it inherits it."""

import os
import pathlib
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
    Under,
)
from wend.errors import ConditionError


root, name = Param("root"), Param("name")
raw = (P(root) / "raw" / T(t"{name}.csv")).requires(
    File, Exists, Readable, Under(P(root) / "raw")
)
out = (
    (P(root) / "out" / T(t"{name}.csv"))
    .requires(Absent, Creatable)
    .ensures(File, Exists)
)


@pytest.fixture
def tree(tmp_path):
    (tmp_path / "raw").mkdir()
    (tmp_path / "raw" / "a.csv").write_text("a")
    return tmp_path


def test_a_check_records_one_phase_of_one_path(tree):
    c = raw.checked(root=tree, name="a")
    assert isinstance(c, Checked) and not isinstance(c, Confirmed)
    assert c.path == tree / "raw" / "a.csv"
    assert c.atoms == {"file", "exists", "read"}  # what it requires
    assert c.bases == (tree / "raw",)
    assert c.epoch is None  # made outside a run
    entry = out.checked(root=tree, name="a")
    assert entry.atoms == {"absent", "create"}  # never what it ensures
    (tree / "out").mkdir()
    (tree / "out" / "a.csv").write_text("made")
    exit_ = out.confirmed(root=tree, name="a")
    assert exit_.atoms == {"file", "exists"}  # never what it required
    assert raw.confirmed(root=tree, name="a").atoms == frozenset()


def test_there_is_no_evidence_of_a_check_that_failed(tree):
    with pytest.raises(ConditionError):
        raw.checked(root=tree, name="missing")
    with pytest.raises(ConditionError):
        out.confirmed(root=tree, name="a")  # not made yet


def test_evidence_records_the_past_and_a_change_does_not_update_it(tree):
    c = raw.checked(root=tree, name="a")
    (tree / "raw" / "a.csv").unlink()  # another writer
    assert c.atoms == {"file", "exists", "read"}  # still what was found then
    with pytest.raises(ConditionError):
        raw.checked(root=tree, name="a")  # a new check finds otherwise


def test_containment_was_true_at_the_moment_only(tree, tmp_path_factory):
    c = raw.checked(root=tree, name="a")
    outside = tmp_path_factory.mktemp("outside")
    (outside / "secret.csv").write_text("secret")
    (tree / "raw" / "a.csv").unlink()
    (tree / "raw" / "a.csv").symlink_to(outside / "secret.csv")  # leads out
    assert c.bases == (tree / "raw",) and "read" in c.atoms  # unchanged
    with pytest.raises(ConditionError):
        raw.checked(root=tree, name="a")  # a new check finds it outside


def test_containment_is_relative_to_where_the_base_leads_now(tree, tmp_path_factory):
    # Under(b) checks realpath(p) against realpath(b), both at the moment of
    # the check. If the base itself is redirected, what lies below it moves
    # with it, and containment still holds: Under confines a path to its
    # base, not the base to where it was. Only a held root (the confined
    # executor's openat2 beneath a descriptor) fixes the base itself.
    outside = tmp_path_factory.mktemp("outside")
    (outside / "a.csv").write_text("secret")
    (tree / "raw").rename(tree / "raw.old")
    (tree / "raw").symlink_to(outside)  # the base now leads outside
    c = raw.checked(root=tree, name="a")
    assert c.bases == (tree / "raw",)
    with open(c) as f:
        assert f.read() == "secret"  # read from outside the original tree


def test_one_check_may_find_its_conditions_true_of_two_objects(tree, monkeypatch):
    # The state atoms come from one stat; Readable is its own access() call.
    # Another writer renames a directory over the name in between: the
    # evidence says file, exists and read, and "read" was found of the
    # directory. Evidence is about a name at instants, not an object.
    target = tree / "raw" / "a.csv"
    real_access, swapped = os.access, []

    def access(p, mode, *a, **k):
        if not swapped and os.fspath(p) == os.fspath(target):
            swapped.append(True)
            target.unlink()
            (tree / "raw" / "dir").mkdir()
            (tree / "raw" / "dir").rename(target)
        return real_access(p, mode, *a, **k)

    monkeypatch.setattr(os, "access", access)
    c = raw.checked(root=tree, name="a")
    assert swapped and "file" in c.atoms and "read" in c.atoms
    assert target.is_dir()  # and yet "file" is in the evidence


def test_evidence_has_none_of_a_paths_operations(tree):
    c = raw.checked(root=tree, name="a")
    derived = [
        name
        for name in dir(pathlib.PurePosixPath) + dir(pathlib.Path)
        if not name.startswith("_")
    ]
    assert derived  # parent, joinpath, with_name, resolve, read_text, ...
    assert not [n for n in derived if hasattr(c, n) and n != "match"]
    with pytest.raises(TypeError):
        c / "below"  # type: ignore[operator]
    with pytest.raises(TypeError):
        "x" / c  # type: ignore[operator]


def test_the_path_it_is_about_is_ordinary_and_carries_nothing(tree):
    c = raw.checked(root=tree, name="a")
    assert type(c.path) is type(Path())  # a plain path
    assert not isinstance(c.path.parent, Checked)
    assert Path(c) == c.path and type(Path(c)) is type(Path())
    assert os.fspath(c) == str(c.path)
    with open(c) as f:  # used as the path it is about
        assert f.read() == "a"


def test_evidence_cannot_be_altered(tree):
    c = raw.checked(root=tree, name="a")
    for attr, value in (
        ("atoms", frozenset({"write"})),
        ("path", Path("/etc/passwd")),
        ("epoch", 1),
        ("bases", ()),
        ("_atoms", frozenset({"write"})),
    ):
        with pytest.raises(AttributeError):
            setattr(c, attr, value)
    with pytest.raises(AttributeError):
        del c.atoms
    assert c.atoms == {"file", "exists", "read"}


def test_check_and_confirm_still_return_plain_paths(tree):
    assert type(raw.check(root=tree, name="a")) is type(Path())
    (tree / "out").mkdir()
    (tree / "out" / "a.csv").write_text("made")
    assert type(out.confirm(root=tree, name="a")) is type(Path())
