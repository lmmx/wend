"""The semantics of ``choices=`` (docs/journal/2026-10-21-choices-semantics-89.md).

Three groups:

- today's core behaviour that the entry documents, pinned so that a change
  to it is deliberate;
- gaps in core, as strict xfails: each passes once core is fixed, and then
  fails until its marker is removed (both are fixed: Param equality in #93, reading members back in #94);
- the private prototype of the proposed rules (`wend._experimental.choices`).
"""

from __future__ import annotations

import enum
from decimal import Decimal
from pathlib import PurePosixPath

import pytest

from wend import AnyPath, P, Param, SubPath, T
from wend._experimental import choices as C


class Split(enum.StrEnum):
    TRAIN = "train"


class One(enum.IntEnum):
    ONE = 1


class Colour(enum.Enum):
    RED = 1


def forms(p):
    return [
        P("x") / T(t"{p}.txt"),
        P("x") / p,
        P("x") / T(t"{p:>4}"),
    ]


MEMBER_CASES = [
    {1},
    {1, 2},
    {1.5},
    {True},
    {None},
    {0.0},
    {Decimal("1.0")},
    {One.ONE},
    {Colour.RED},
    {Split.TRAIN},
    {"a", "b"},
]


# -- today's behaviour, documented ---------------------------------------------


def test_an_int_field_does_not_read_a_bool_back():
    # SEMANTICS.md §7: "an int field does not read True". render accepts it
    # (isinstance(True, int)), so the path does not read back.
    n = Param("n", type=int)
    e = P("x") / T(t"{n}.txt")
    assert e.render(n=True) == "x/True.txt"
    assert e.match("x/True.txt") is None


def test_equal_choices_of_different_types_collapse_today():
    # A frozenset keeps one of two equal members, the first given, so the
    # declaration loses one. Recorded, not endorsed: see the entry.
    assert Param("c", choices=[1, True]).choices == frozenset({1})
    assert {type(m) for m in Param("c", choices=[True, 1]).choices} == {bool}
    e = P("x") / Param("c", choices=[1, True])
    assert e.render(c=True) == "x/True"  # accepted (True == 1) ...
    assert e.match_all("x/True") == []  # ... but not read back


# -- gaps in core ----------------------------------------------------------------


@pytest.mark.parametrize("members", [{1}, {1.5}, {True}, {None}], ids=repr)
def test_core_reads_back_every_declared_member(members):
    c = Param("c", choices=members)
    e = P("x") / T(t"{c}.txt")
    for m in members:
        assert e.match_all(e.render(c=m))


def test_core_reads_back_path_valued_choices():
    h = AnyPath("h", choices={PurePosixPath("/a")})
    s = SubPath("s", choices={PurePosixPath("a/b")})
    assert (P(h) / "x").match_all("/a/x")
    assert (P("r") / s).match_all("r/a/b")


def test_core_keeps_each_declaration_of_choices():
    # Param.__eq__ says equal Params must be interchangeable. It compared
    # defaults strictly but choices with frozenset equality, so the template
    # cache returned the Param of an earlier, equal declaration (#93).
    first = Param("c", choices={1})
    P("x") / T(t"{first}.txt")
    second = Param("c", choices={True})
    e = P("x") / T(t"{second}.txt")
    assert {type(m) for m in e.params["c"].choices} == {bool}


# -- the prototype (rules D-canonical and E) ------------------------------------------


@pytest.mark.parametrize("members", MEMBER_CASES, ids=repr)
def test_every_declared_member_reads_back_as_itself(members):
    p = Param("c", choices=members)
    for e in forms(p):
        for m in members:
            try:
                path = e.render(c=m)
            except ValueError:
                continue  # never renders here (None under >4): nothing to read
            found = C.match_all(e, path)
            assert any(
                r["c"] is m or (type(r["c"]) is type(m) and r["c"] == m) for r in found
            ), (
                e.pattern,
                m,
                found,
            )
            assert all(e.render(r) == path for r in found)


def test_path_valued_members_read_back():
    h = AnyPath("h", choices={PurePosixPath("/a")})
    s = SubPath("s", choices={PurePosixPath("a/b")})
    assert C.match_all(P(h) / "x", "/a/x") == [{"h": PurePosixPath("/a")}]
    assert C.match_all(P("r") / s, "r/a/b") == [{"s": PurePosixPath("a/b")}]


@pytest.mark.parametrize("members", MEMBER_CASES, ids=repr)
def test_no_path_that_reads_back_today_is_lost(members):
    p = Param("c", choices=members)
    values = [*members, 1, 1.0, True, "1", "a"]
    for e in [*forms(p), P("x") / T(t"{p!r}"), P("x") / T(t"{p:d}")]:
        for v in values:
            try:
                path = e.render(c=v)
            except ValueError:
                continue
            if e.match_all(path):
                found = C.match_all(e, path)
                assert found and all(e.render(r) == path for r in found)


def test_a_reading_becomes_the_member_it_stands_for():
    # Today {c:d} reads True's path as the int 1; the member is True.
    c = Param("c", choices={True})
    e = P("x") / T(t"{c:d}")
    assert e.match_all("x/1") == [{"c": 1}]
    [r] = C.match_all(e, "x/1")
    assert r["c"] is True
    s = Param("s", choices={Split.TRAIN})
    [r] = C.match_all(P("x") / s, "x/train")
    assert r["s"] is Split.TRAIN


def test_only_distinct_members_that_render_alike_are_ambiguous():
    c = Param("c", choices={"1", 1})
    found = C.match_all(P("x") / T(t"{c}.txt"), "x/1.txt")
    assert sorted(found, key=repr) == [{"c": "1"}, {"c": 1}]


def test_faithful_refuses_what_renders_unlike_its_representative():
    c = Param("c", choices={1})
    e = P("x") / T(t"{c}.txt")
    assert C.faithful(e, {"c": 1})
    assert not C.faithful(e, {"c": 1.0})  # renders 1.0, its member 1
    n = Param("n", type=int)
    assert not C.faithful(P("x") / T(t"{n}"), {"n": True})  # True vs 1
    assert C.faithful(P("x") / T(t"{n:d}"), {"n": True})  # 1 vs 1
    s = Param("s", choices={"train"})
    assert C.faithful(P("x") / s, {"s": Split.TRAIN})  # train vs train
    assert not C.faithful(P("x") / T(t"{s!r}"), {"s": Split.TRAIN})


def test_faithful_bindings_read_back_their_representatives():
    # E and D-canonical together: whatever is accepted reads back, as the
    # representative of what was bound.
    c = Param("c", choices={1, 2})
    n = Param("n", type=int)
    e = P("x") / T(t"{c}") / T(t"{n}.txt")
    for env in [{"c": 1, "n": 3}, {"c": 2, "n": One.ONE}, {"c": One.ONE, "n": 5}]:
        assert C.faithful(e, env)
        path = e.render(env)
        found = C.match_all(e, path)
        reps = {"c": C.representative(c, env["c"]), "n": C.representative(n, env["n"])}
        assert any(
            all(type(r[k]) is type(reps[k]) and r[k] == reps[k] for k in reps)
            for r in found
        ), (env, found)
