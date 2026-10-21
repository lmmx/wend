"""Unions and queries (docs/SEMANTICS.md §11)."""

import os
import pickle
import time
from string.templatelib import Interpolation, Template

import pytest
from contract_test import build, envs, terms
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from wend import (
    Alt,
    AmbiguousMatchError,
    Exists,
    File,
    MissingBindingError,
    NoAlternativeError,
    NotInvertibleError,
    P,
    Param,
    PathOperationError,
    PathUnion,
    Readable,
    SubPath,
    T,
    U,
)
from wend.query import (
    FsPredicate,
    Query,
    larger_than,
    modified_after,
    modified_before,
)


d = Param("d")
k = Param("k", type=int)
LOGS = U(t"{d}/app.log{Alt('', t'.{k}')}{Alt('', '.gz')}")


# -- building -----------------------------------------------------------------


def test_alt_expands_in_order_leftmost_slowest():
    assert LOGS.alternatives == (
        P(d) / "app.log",
        P(d) / "app.log.gz",
        P(d) / T(t"app.log.{k}"),
        P(d) / T(t"app.log.{k}.gz"),
    )
    assert U(t"a{Alt('x', 'y')}{Alt('1', '2')}").alternatives == tuple(
        map(P, ["ax1", "ax2", "ay1", "ay2"])
    )


def test_alt_options_are_spliced_as_text():
    u = U(t"data/{Alt('a/b', 'c', t'{d}.csv')}/x")
    assert u.alternatives == (
        P("data/a/b/x"),
        P("data/c/x"),
        P("data") / T(t"{d}.csv") / "x",
    )
    inner = Alt("a", "b")
    nested = U(t"v{Alt('', t'-{inner}')}")
    assert [a.pattern for a in nested] == ["v", "v-a", "v-b"]
    assert U(t"{Alt(k, 'z')}.txt").alternatives == (T(t"{k}.txt"), P("z.txt"))


def test_alt_is_refused_outside_u():
    with pytest.raises(TypeError, match=r"U\(t'...'\)"):
        T(t"x{Alt('a', 'b')}")
    with pytest.raises(TypeError):
        P("a").with_name(t"{Alt('a', 'b')}")
    with pytest.raises(TypeError):
        Alt(1)
    with pytest.raises(ValueError):
        Alt()
    with pytest.raises(TypeError):
        f"{Alt('a')}"
    with pytest.raises(TypeError, match="format spec"):
        U(t"{Alt('a'):>3}")


def test_union_flattens_and_drops_repeats():
    u = P("a") | "b" | P("a") | (P("c") | "b")
    assert isinstance(u, PathUnion)
    assert [a.pattern for a in u] == ["a", "b", "c"]
    assert "x" | P("y") == U("x", "y")
    assert len(U("a", "a")) == 1


def test_operations_distribute():
    u = U("a", "b")
    assert P("/r") / u == U("/r/a", "/r/b")
    assert u / "c" == U("a/c", "b/c")
    assert u / U("x", "y") == U("a/x", "a/y", "b/x", "b/y")
    assert P("/r") / t"f.{Alt('csv', 'tsv')}" == U("/r/f.csv", "/r/f.tsv")
    assert (P("/r") / u).parent == U("/r")
    assert u.with_suffix(".txt") == U("a.txt", "b.txt")
    assert U(P(d) / "x", P(d) / "y").bind(d="/z") == U("/z/x", "/z/y")
    assert u.under("/base") == U("/base/a", "/base/b")
    assert U(P(d) / "x").param_names == {"d"}
    assert pickle.loads(pickle.dumps(LOGS)) == LOGS


# -- rendering and fallback ---------------------------------------------------


def test_render_needs_a_single_alternative():
    with pytest.raises(PathOperationError, match="4 alternatives"):
        LOGS.render(d="/v", k=1)
    assert U(P(d) / "x").render(d="/v") == "/v/x"
    assert LOGS.renderings(d="/v", k=1) == (
        "/v/app.log",
        "/v/app.log.gz",
        "/v/app.log.1",
        "/v/app.log.1.gz",
    )
    with pytest.raises(MissingBindingError):
        LOGS.renderings(d="/v")


def test_first_is_the_first_alternative_that_exists(tmp_path):
    home, app = Param("home"), Param("app")
    chain = (
        P(home) / ".config" / T(t"{app}.toml")
        | P(home) / ".local/etc" / T(t"{app}.toml")
        | P(home) / "defaults.toml"
    )
    (tmp_path / "defaults.toml").write_text("")
    assert chain.first(home=tmp_path, app="x") == tmp_path / "defaults.toml"
    (tmp_path / ".local/etc").mkdir(parents=True)
    (tmp_path / ".local/etc/x.toml").write_text("")
    assert chain.first(home=tmp_path, app="x") == tmp_path / ".local/etc/x.toml"
    # an alternative's own preconditions must hold too
    (tmp_path / ".config/x.toml").mkdir(parents=True)  # a directory, not a file
    assert (
        chain.requires(File).first(home=tmp_path, app="x")
        == tmp_path / ".local/etc/x.toml"
    )
    assert chain.first(home=tmp_path, app="x") == tmp_path / ".config/x.toml"
    with pytest.raises(NoAlternativeError) as info:
        chain.first(home=tmp_path / "nowhere", app="x")
    assert isinstance(info.value, FileNotFoundError)
    assert [s for s, _ in info.value.tried] == [
        f"{tmp_path}/nowhere/.config/x.toml",
        f"{tmp_path}/nowhere/.local/etc/x.toml",
        f"{tmp_path}/nowhere/defaults.toml",
    ]
    with pytest.raises(MissingBindingError):  # every alternative must render
        chain.first(home=tmp_path)


# -- matching and discovery ---------------------------------------------------


def test_log_rotation_matches_with_typed_bindings():
    readings = {
        p: (m.alternative, dict(m))
        for p in ["/v/app.log", "/v/app.log.1", "/v/app.log.2.gz", "/v/app.log.gz"]
        if (m := LOGS.match(p))
    }
    assert readings == {
        "/v/app.log": (0, {"d": "/v"}),
        "/v/app.log.gz": (1, {"d": "/v"}),
        "/v/app.log.1": (2, {"d": "/v", "k": 1}),
        "/v/app.log.2.gz": (3, {"d": "/v", "k": 2}),
    }
    assert LOGS.match("/v/app.log.x") is None
    assert LOGS.match("/v/app.log.1").expr == P(d) / T(t"app.log.{k}")


def test_two_alternatives_reading_a_path_is_ambiguous():
    name = Param("name")
    u = U(t"{name}.gz", t"{name}")  # app.gz reads as either
    with pytest.raises(AmbiguousMatchError) as info:
        u.match("app.gz")
    assert len(info.value.candidates) == 2
    assert u.match("app") == {"name": "app"}
    # untyped k: app.log.1.gz is k="1.gz" in one alternative and k="1" in another
    untyped = Param("k")
    loose = U(t"app.log{Alt('', t'.{untyped}')}{Alt('', '.gz')}")
    with pytest.raises(AmbiguousMatchError):
        loose.match("app.log.1.gz")


def test_glob_finds_every_rotation_in_one_call(tmp_path):
    for n in ["app.log", "app.log.1", "app.log.2.gz", "app.log.3.gz", "other.log"]:
        (tmp_path / n).write_text("")
    found = [
        (os.path.basename(m.path), m.alternative, m.get("k"))
        for m in LOGS.glob(d=tmp_path)
    ]
    assert found == [
        ("app.log", 0, None),
        ("app.log.1", 2, 1),
        ("app.log.2.gz", 3, 2),
        ("app.log.3.gz", 3, 3),
    ]


def test_glob_reports_a_path_two_alternatives_find(tmp_path):
    (tmp_path / "a.gz").write_text("")
    name = Param("name")
    u = U(P(d) / T(t"{name}.gz"), P(d) / name)
    with pytest.raises(AmbiguousMatchError):
        list(u.glob(d=tmp_path))


@pytest.fixture
def mixed(tmp_path):
    """A union and a tree with both kinds of ambiguity: ``a.b.c`` is read two
    ways by one alternative, ``m.gz`` once by each, and ``z.q.gz`` two ways
    by the first and once by the second; ``plain.txt`` is read once."""
    for n in ["a.b.c", "m.gz", "plain.txt", "z.q.gz", "zz"]:
        (tmp_path / n).write_text("")
    stem, ext, name = Param("stem"), Param("ext"), Param("name")
    return U(P(d) / T(t"{stem}.{ext}"), P(d) / T(t"{name}.gz")), tmp_path


def test_union_glob_reports_both_kinds_of_ambiguity_in_path_order(mixed):
    u, tmp = mixed
    report: list[AmbiguousMatchError] = []
    found = list(u.glob(d=tmp, ambiguous=report.append))
    assert [(os.path.basename(m.path), m.alternative) for m in found] == [
        ("plain.txt", 0)
    ]
    assert [os.path.basename(e.path) for e in report] == ["a.b.c", "m.gz", "z.q.gz"]
    # every reading of each path, by every alternative, as an AltMatch
    readings = [[(c.alternative, dict(c)) for c in e.candidates] for e in report]
    root = {"d": tmp}  # given bindings belong to every reading
    assert readings[1:] == [
        [(0, {**root, "stem": "m", "ext": "gz"}), (1, {**root, "name": "m"})],
        [
            (0, {**root, "stem": "z", "ext": "q.gz"}),
            (0, {**root, "stem": "z.q", "ext": "gz"}),
            (1, {**root, "name": "z.q"}),
        ],
    ]
    assert [c.alternative for c in report[0].candidates] == [0, 0]
    assert all(c.expr == u.alternatives[c.alternative] for c in report[2].candidates)


def test_union_glob_skips_or_raises_for_ambiguous_paths(mixed):
    u, tmp = mixed
    skipped = [os.path.basename(m.path) for m in u.glob(d=tmp, ambiguous="skip")]
    assert skipped == ["plain.txt"]
    # "raise" raises for the first ambiguous path, before any match is yielded
    walk = u.glob(d=tmp)
    with pytest.raises(AmbiguousMatchError) as info:
        next(walk)
    assert os.path.basename(info.value.path) == "a.b.c"
    # so does a path two alternatives find, though a.b.c comes first and is
    # read once here
    name = Param("name")
    loose = U(P(d) / T(t"{name}.gz"), P(d) / name)
    with pytest.raises(AmbiguousMatchError, match="m.gz"):
        next(loose.glob(d=tmp))
    with pytest.raises(ValueError, match="ambiguous must be"):
        u.glob(d=tmp, ambiguous="ignore")  # raised by the call


def test_query_glob_takes_ambiguous_for_its_source_and_its_patterns(tmp_path):
    for n in ["ab1.py", "ab12.py", "zz.py", "t.tar.gz"]:
        (tmp_path / n).write_text("")
    x, y = Param("x"), Param("y", type=int)
    py = P(tmp_path) / T(t"{Param('stem')}.py")
    # ab12.py is x="ab", y=12 or x="ab1", y=2; zz.py has no reading
    q = py & P(tmp_path) / T(t"{x}{y:d}.py")
    report: list[AmbiguousMatchError] = []
    found = [(m["x"], m["y"]) for m in q.glob(ambiguous=report.append)]
    assert found == [("ab", 1)]
    assert [os.path.basename(e.path) for e in report] == ["ab12.py"]
    assert [(m["x"], m["y"]) for m in q.glob(ambiguous="skip")] == [("ab", 1)]
    # reported when the stream reaches it
    stream = q.glob()
    assert next(stream)["y"] == 1
    with pytest.raises(AmbiguousMatchError, match="ab12.py"):
        next(stream)
    # the source's own ambiguity, and a union source's
    pair = P(tmp_path) / T(t"{Param('a')}.{Param('b')}")
    assert [m["a"] for m in (pair - py).glob(ambiguous="skip")] == []
    report.clear()
    assert list((pair | py).where(File).glob(ambiguous=report.append)) == []
    assert [os.path.basename(e.path) for e in report] == [
        "ab1.py",
        "ab12.py",
        "t.tar.gz",
        "zz.py",
    ]


# -- queries ------------------------------------------------------------------


@pytest.fixture
def src(tmp_path):
    for rel in ["a.py", "a_test.py", "pkg/b.py", "pkg/b_test.py", "pkg/big.py"]:
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x" * (100 if "big" in rel else 1))
    return tmp_path


def test_difference_drops_what_another_pattern_matches(src):
    stem = Param("stem")
    py = P(src) / SubPath("rel") / T(t"{stem}.py")
    tests = P(src) / SubPath("rel") / T(t"{stem}_test.py")
    q = py - tests
    assert isinstance(q, Query)
    got = sorted(os.path.relpath(m.path, src) for m in q.glob(kind="file"))
    assert got == ["a.py", "pkg/b.py", "pkg/big.py"]


def test_intersection_keeps_and_adds_bindings(src):
    stem, rel = Param("stem"), SubPath("rel")
    py = P(src) / rel / T(t"{stem}.py")
    in_pkg = P(src) / "pkg" / Param("file")
    got = [(m["stem"], m["file"]) for m in (py & in_pkg).glob(kind="file")]
    assert got == [("b", "b.py"), ("b_test", "b_test.py"), ("big", "big.py")]
    # a shared parameter must agree
    same = P(src) / rel / T(t"{Param('stem')}_test.py")
    assert [m["stem"] for m in (py & same).glob(kind="file")] == []


def test_predicates_filter_lazily(src):
    py = P(src) / SubPath("rel") / T(t"{Param('stem')}.py")
    assert [m["stem"] for m in py.where(larger_than(10)).glob(kind="file")] == ["big"]
    assert [
        m["stem"] for m in py.where(lambda m: m["stem"].startswith("a")).glob()
    ] == [
        "a",
        "a_test",
    ]
    future, past = time.time() + 3600, time.time() - 3600
    assert list(py.where(modified_after(future)).glob()) == []
    assert (
        len(list(py.where(modified_before(future), modified_after(past)).glob())) == 5
    )
    assert len(list(py.where(File, Readable).glob())) == 5
    with pytest.raises(TypeError):
        py.where("big")


def test_query_match_applies_every_filter(src):
    stem = Param("stem")
    py = P(src) / T(t"{stem}.py")
    q = (py - P(src) / T(t"{stem}_test.py")).where(File, Exists)
    assert q.match(src / "a.py") == {"stem": "a"}
    assert q.match(src / "a_test.py") is None
    assert q.match(src / "zz.py") is None  # matched, but not there
    # File alone says what a path is if it exists
    assert (py.where(File)).match(src / "zz.py") == {"stem": "zz"}
    assert "where(File, Exists)" in repr(q)


def test_pure_predicates_run_before_filesystem_ones(src):
    stats = []
    effect = FsPredicate("counted", lambda st: stats.append(st) or True)
    py = P(src) / T(t"{Param('stem')}.py")
    # declared first, the stat still runs only on what the pure test admits
    q = py.where(effect, lambda m: m["stem"] == "a")
    assert [m["stem"] for m in q.glob()] == ["a"]
    assert len(stats) == 1


# -- properties ---------------------------------------------------------------

_FAILS = (PathOperationError, TypeError, ValueError)


@settings(max_examples=400, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(terms, terms, envs)
def test_a_union_means_its_alternatives(t1, t2, env):
    """Matching and ambiguity of a union reduce to its alternatives': on
    each alternative's rendering, the union reports exactly that
    alternative's own verified readings plus the other alternatives', and
    `match` returns the one reading, None for none, or raises for several."""
    try:
        a, b = build(t1), build(t2)
    except _FAILS:
        return
    u = a | b
    for alt in u.alternatives:
        try:
            s = alt.render(env)
        except _FAILS:
            continue
        try:
            readings = u.match_all(s)
        except NotInvertibleError:
            return
        for r in readings:
            assert u.alternatives[r.alternative].render(dict(r)) == s
        own = [r for r in readings if u.alternatives[r.alternative] == alt]
        expected = alt.match_all(s)
        assert len(own) == len(expected)
        try:
            m = u.match(s)
        except AmbiguousMatchError:
            assert len(readings) > 1
        else:
            assert (m is None) == (not readings) and len(readings) <= 1
            assert m is None or m == readings[0]


@settings(max_examples=200, deadline=None)
@given(
    st.lists(st.sampled_from(["a", "b/c", "", ".x"]), min_size=1, max_size=3),
    st.lists(st.sampled_from(["1", "2", "z"]), min_size=1, max_size=3),
)
def test_alt_expansion_equals_substitution(opts1, opts2):
    t = Template(
        "p", Interpolation(Alt(*opts1), "a"), "/q", Interpolation(Alt(*opts2), "b")
    )
    expected = []
    for x in opts1:
        for y in opts2:
            e = P(f"p{x}/q{y}")
            if e not in expected:
                expected.append(e)
    assert list(U(t).alternatives) == expected
