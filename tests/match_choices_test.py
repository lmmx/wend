"""match reads every declared choice back as itself (docs/SEMANTICS.md §7, #94).

A parameter with ``choices`` reads, in each position, every member whose
rendering there is the text, as well as what its type or spec reads; a value
read that equals a member is returned as that member when the member renders
the same text. Rendering is unchanged.
"""

from __future__ import annotations

import enum
from decimal import Decimal
from pathlib import PurePosixPath

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from wend import AmbiguousMatchError, AnyPath, P, Param, SubPath, T


class Split(enum.StrEnum):
    TRAIN = "train"
    VALID = "valid"


class One(enum.IntEnum):
    ONE = 1


class Colour(enum.Enum):
    RED = 1


def readings(e, path, **kw):
    return list(e.match_all(path, **kw))


def holds(found, name, value):
    return any(
        r[name] is value or (type(r[name]) is type(value) and r[name] == value)
        for r in found
    )


@pytest.mark.parametrize(
    "members",
    [
        {1},
        {1, 2},
        {1.5},
        {True},
        {None},
        {0.0},
        {Decimal("1.0")},
        {One.ONE},
        {Colour.RED},
    ],
    ids=repr,
)
def test_a_declared_member_reads_back_in_a_field_and_a_segment(members):
    c = Param("c", choices=members)
    for e in [P("x") / T(t"{c}.txt"), P("x") / c, P("x") / T(t"v{c}")]:
        for m in members:
            path = e.render(c=m)
            assert holds(e.match_all(path), "c", m), (e.pattern, m)


def test_path_valued_members_read_back_as_heads_and_subpaths():
    h = AnyPath("h", choices={PurePosixPath("/srv/a"), PurePosixPath("b")})
    s = SubPath("s", choices={PurePosixPath("a/b"), PurePosixPath(".")})
    assert (P(h) / "x").match("/srv/a/x")["h"] == PurePosixPath("/srv/a")
    assert (P(h) / "x").match("b/x")["h"] == PurePosixPath("b")
    assert (P("r") / s / "f").match("r/a/b/f")["s"] == PurePosixPath("a/b")
    assert (P("r") / s / "f").match("r/f")["s"] == PurePosixPath(".")
    assert (P("r") / s / "f").match("r/c/f") is None


def test_a_reading_is_the_member_it_stands_for():
    # Today's readings ("train", 1) equal the members; the member is returned.
    s = Param("s", choices={Split.TRAIN, Split.VALID})
    assert (P("d") / s).match("d/train")["s"] is Split.TRAIN
    assert (P("d") / T(t"{s}.csv")).match("d/valid.csv")["s"] is Split.VALID
    t = Param("t", choices={True})
    assert (P("x") / T(t"{t:d}")).match("x/1")["t"] is True
    o = Param("o", choices={One.ONE})
    assert (P("x") / T(t"{o:d}")).match("x/1")["o"] is One.ONE


def test_plain_string_and_integer_choices_read_as_before():
    s = Param("s", choices={"train", "valid"})
    m = (P("d") / T(t"{s}.csv")).match("d/train.csv")
    assert m["s"] == "train" and type(m["s"]) is str
    n = Param("n", type=int, choices={1, 2})
    assert (P("x") / T(t"{n:02d}")).match("x/02")["n"] == 2
    assert (P("x") / T(t"{n:02d}")).match("x/03") is None


def test_a_value_that_renders_unlike_its_member_still_reads_as_today():
    # 1.0 is accepted for {1} (it equals 1) and renders 1.0, which no member
    # renders; under !r it reads back as itself, as it did before.
    c = Param("c", choices={1})
    e = P("x") / T(t"{c!r}")
    assert e.render(c=1.0) == "x/1.0"
    assert readings(e, "x/1.0") == [{"c": 1.0}]


def test_distinct_members_that_render_alike_are_ambiguous():
    c = Param("c", choices={"1", 1})
    e = P("x") / T(t"{c}.txt")
    assert sorted(e.match_all("x/1.txt"), key=repr) == [{"c": "1"}, {"c": 1}]
    with pytest.raises(AmbiguousMatchError):
        e.match("x/1.txt")


def test_a_repeated_choice_parameter_reads_one_member():
    c = Param("c", choices={1, 2})
    e = P("x") / T(t"{c}") / T(t"{c}.txt")
    assert e.match("x/2/2.txt")["c"] == 2
    assert e.match("x/1/2.txt") is None


def test_glob_finds_paths_of_declared_members(tmp_path):
    (tmp_path / "a" / "b").mkdir(parents=True)
    (tmp_path / "a" / "b" / "f").write_text("")
    (tmp_path / "c").mkdir()
    (tmp_path / "c" / "f").write_text("")
    (tmp_path / "1.txt").write_text("")
    s = SubPath("s", choices={PurePosixPath("a/b")})
    found = list((P(tmp_path) / s / "f").glob())
    assert [m["s"] for m in found] == [PurePosixPath("a/b")]
    c = Param("c", choices={1, 2})
    assert [m["c"] for m in (P(tmp_path) / T(t"{c}.txt")).glob()] == [1]


POOL = [
    1,
    2,
    1.5,
    True,
    None,
    0.0,
    "a",
    "1",
    Decimal("1.0"),
    Colour.RED,
    One.ONE,
    Split.TRAIN,
]
FORMS = [
    lambda c: P("x") / T(t"{c}.txt"),
    lambda c: P("x") / c,
    lambda c: P("x") / T(t"{c:>4}"),
    lambda c: P("x") / T(t"{c!r}"),
    lambda c: P("x") / T(t"{c:d}"),
    lambda c: P("x") / T(t"k{c}k"),
    lambda c: P("x") / T(t"{c}") / T(t"{c}.txt"),
]


@settings(max_examples=300, deadline=None)
@given(
    members=st.lists(st.sampled_from(POOL), min_size=1, max_size=4),
    form=st.sampled_from(FORMS),
)
def test_every_member_reads_back_and_every_reading_renders(members, form):
    c = Param("c", choices=members)
    e = form(c)
    for m in c.choices:  # the members the declaration kept
        try:
            path = e.render(c=m)
        except ValueError:
            continue  # this member never renders here
        found = e.match_all(path)
        assert holds(found, "c", m), (e.pattern, m, found)
        assert all(e.render(r) == path for r in found)
        # The fast path, where it applies, agrees with the full search.
        slow = e.match_all(path, fast=False)
        key = lambda r: (type(r["c"]).__name__, repr(r["c"]))  # noqa: E731
        assert sorted(map(key, found)) == sorted(map(key, slow))
