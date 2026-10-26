"""wend._experimental.overlap: verdicts against wend's own render and match.

A NO is checked by trying to falsify it: render one expression with values
from a pool and match the result against the other (or, with shared
bindings, render both with one environment). Any common path refutes a NO.
A YES is checked by its witness, which both expressions must match.
"""

from __future__ import annotations

import enum
import itertools
from pathlib import PurePosixPath

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from wend import Absolute, P, Param, SubPath, T
from wend._experimental.overlap import intersect, overlaps, shapes
from wend.errors import NotInvertibleError, WendError


# -- examples -------------------------------------------------------------------

idx = Param("idx", type=int)
name, stem = Param("name"), Param("stem")
split = Param("split", choices={"train", "valid"})
rel = SubPath("rel")


class Colour(enum.Enum):
    RED = "red"
    BLUE = "blue"


EXAMPLES = [
    # (a, b, shared, verdict)
    (
        P("data") / split / T(t"chunk_{idx:04d}.parquet"),
        "data/train/chunk_0007.parquet",
        False,
        "yes",
    ),
    (
        P("data") / split / T(t"chunk_{idx:04d}.parquet"),
        "data/test/chunk_0007.parquet",
        False,
        "maybe",
    ),  # choices are not exhaustive
    (
        P("data") / split / T(t"chunk_{idx:04d}.parquet"),
        "data/train/notes.txt",
        False,
        "no",
    ),
    (P("out") / T(t"{stem}.csv"), P("out") / T(t"{stem}.json"), False, "no"),
    (P("out") / T(t"{stem}.csv"), P("out") / T(t"{name}"), False, "yes"),
    (P("src") / rel / T(t"{stem}.py"), "src/pkg/mod.py", False, "yes"),
    (P("src") / rel / T(t"{stem}.py"), "build/pkg/mod.py", False, "no"),
    (P("/abs") / name, P("rel") / name, False, "no"),
    (Param("root") / "x", "y", False, "no"),  # a PATH head still ends in x
    (Param("root") / "x", "y/x", False, "yes"),
    (P("a") / name / name, "a/b/b", False, "yes"),
    (P("a") / T(t"{Param('c', type=Colour)}"), "a/Colour.RED", False, "yes"),
    (P("a") / T(t"{Param('c', type=Colour)}"), "a/RED", False, "no"),
    (P("a") / T(t"{Param('f', type=bool)}.txt"), "a/True.txt", False, "yes"),
    (P("a") / T(t"{Param('f', type=bool)}.txt"), "a/1.txt", False, "no"),
    # Shared bindings: one value of stem for both.
    (P("in") / T(t"{stem}.csv"), P("in") / T(t"{stem}.csv"), True, "yes"),
]


@pytest.mark.parametrize(("a", "b", "shared", "verdict"), EXAMPLES)
def test_examples(a, b, shared, verdict):
    r = overlaps(a, b, shared=shared)
    assert r.verdict == verdict, r
    if r.witness is not None:
        assert P(a).render(r.witness.a) == r.witness.path
        assert P(b).render(r.witness.b) == r.witness.path


def test_shared_bindings_change_the_answer():
    a, b = P("x") / name / "a", P("x") / "b" / name
    # Independent: name=b in a and name=a in b both render x/b/a.
    r = overlaps(a, b)
    assert r.verdict == "yes" and r.witness.path == "x/b/a"
    assert r.witness.a == {"name": "b"} and r.witness.b == {"name": "a"}
    # Shared, that would need name == "a" and name == "b" at once.
    r = overlaps(a, b, shared=True)
    assert r.verdict == "no", r
    assert "repeated parameter" in r.reason


def test_a_repeated_parameter_cannot_take_two_values():
    e = P("a") / name / name
    r = overlaps(e, "a/b/c")
    assert r.verdict == "no" and "repeated parameter" in r.reason
    assert overlaps(e, "a/b/b").verdict == "yes"
    # Only whole-segment occurrences are tied: inside a segment, the
    # occurrences are not compared, and the answer is honest about it.
    inside = P("a") / T(t"{name}.txt") / name
    assert overlaps(inside, "a/b.txt/c").verdict != "yes"
    assert overlaps(inside, "a/b.txt/b").verdict == "yes"


def test_shared_bindings_tie_parameters_across_steps():
    day = Param("day")
    raw, clean = P("raw") / T(t"{day}.csv"), P("raw") / T(t"{day}.csv")
    r = overlaps(raw, clean, shared=True)
    assert r.verdict == "yes" and r.witness.a == r.witness.b
    other = P("raw") / day / "a.csv"
    assert overlaps(P("raw") / "mon" / T(t"{day}.csv"), other, shared=True).verdict in (
        "yes",
        "maybe",
    )


def test_choices_are_exhaustive_only_for_builtin_values():
    shard = P("data") / split / T(t"chunk_{idx:04d}.parquet")
    test = "data/test/chunk_0007.parquet"
    assert overlaps(shard, test).verdict == "maybe"
    r = overlaps(shard, test, builtin_values=True)
    assert r.verdict == "no" and r.assumptions == {"builtin_values"}
    # The contract accepts any value equal to a choice, and each renders its
    # own way: 1.0 and True pass for choices={1}.
    c = Param("c", choices={1, 2})
    e = P("r") / T(t"{c}.txt")
    assert e.render(c=1.0) == "r/1.0.txt" and e.render(c=True) == "r/True.txt"
    for path, value in [
        ("r/1.0.txt", 1.0),
        ("r/True.txt", True),
        ("r/(1+0j).txt", 1 + 0j),
    ]:
        for builtin in (False, True):
            r = overlaps(e, path, builtin_values=builtin)
            assert r.verdict == "yes" and r.witness.a == {"c": value}, (
                path,
                builtin,
                r,
            )
    assert overlaps(e, "r/3.txt").verdict == "maybe"
    assert overlaps(e, "r/3.txt", builtin_values=True).verdict == "no"

    class Sly(str):
        def __format__(self, spec):
            return "zz"

        __hash__ = str.__hash__

    # A str subclass equal to a choice is that choice to the check, not to
    # formatting.
    assert e.render(c=1) == "r/1.txt"
    s = Param("s", choices={"a", "b"})
    assert (P("r") / T(t"{s}.txt")).render(s=Sly("a")) == "r/zz.txt"
    assert overlaps(P("r") / T(t"{s}.txt"), "r/zz.txt").verdict != "no"


def test_a_repeated_parameter_is_exact_when_it_has_a_finite_domain():
    c = Param("c", choices={"a", "b"})
    seg = P("r") / T(t"{c}-{c}")
    assert overlaps(seg, "r/a-a").verdict == "yes"
    assert overlaps(seg, "r/a-b", builtin_values=True).verdict == "no"
    f = Param("f", type=bool)  # exhaustive under the contract alone
    assert overlaps(P("r") / T(t"{f}-{f}"), "r/True-False").verdict == "no"


def test_builtin_values_is_an_assumption_not_a_fact():
    n = Param("n", type=int)
    e = P("logs") / T(t"{n:04d}")

    class Odd(int):
        def __format__(self, spec):
            return "abcd"

    # The contract lets an int subclass format as letters: e renders logs/abcd.
    assert e.render(n=Odd(3)) == "logs/abcd"
    strict = overlaps(e, "logs/abcd")
    assert strict.verdict != "no"
    trusting = overlaps(e, "logs/abcd", builtin_values=True)
    assert trusting.verdict == "no"
    assert trusting.assumptions == {"builtin_values"}


def test_a_yes_never_rests_on_an_assumption():
    n = Param("n", type=int)
    r = overlaps(P("logs") / T(t"{n:04d}"), "logs/0042", builtin_values=True)
    assert r.verdict == "yes" and r.witness.a == {"n": 42}


def test_a_finite_witness_search_renders_each_binding_once(monkeypatch):
    # Each candidate path used to re-render every binding, and a deferred
    # head re-ran that per start path: 35k renders and 1.3 s for this pair.
    from wend._experimental import overlap as O

    calls = 0
    real = O._rendered

    def counted(e, env):
        nonlocal calls
        calls += 1
        return real(e, env)

    monkeypatch.setattr(O, "_rendered", counted)
    O._cached_render_index.cache_clear()
    rc = Param("rc", choices={"a", "/x", "b/c", "a/.."})
    ci = Param("ci", choices={1, 2})
    sc = SubPath("sc", choices={".", "a", "a/b"})
    a = (P(rc) / T(t"{f}.txt") / T(t"v{ci:d}") / sc).parent
    b = P("/") / T(t"{n:d}.{p}") / p / T(t"{ci}{ci}")
    assert overlaps(a, b).verdict == "maybe"
    assert calls < 2000
    # The index still finds witnesses only rendering can: Enum fields.
    Colour = enum.Enum("Colour", "RED GREEN")
    col = Param("col", type=Colour)
    r = overlaps((P("r") / T(t"{col}") / "x").parent, "r/Colour.GREEN")
    assert r.verdict == "yes" and r.witness.a == {"col": Colour.GREEN}


def test_bool_is_a_builtin_int():
    # format(True, "") is "True": a type=int field without a presentation
    # type renders it, so builtin values cannot mean digits only.
    n = Param("n", type=int)
    for e in [P("x") / T(t"{n}.txt"), P("x") / n / "y"]:
        path = e.render(n=True)
        r = overlaps(e, path, builtin_values=True)
        assert r.verdict == "yes" and r.witness.a == {"n": True}
    # With a presentation type it formats as 1, and digits are exact.
    assert (
        overlaps(P("x") / T(t"{n:d}.txt"), "x/True.txt", builtin_values=True).verdict
        == "no"
    )
    assert overlaps(P("x") / n, "x/data.json", builtin_values=True).verdict == "no"


def test_unions_overlap_if_some_alternatives_do():
    u = (P("a") / name) | (P("b") / name)
    assert overlaps(u, "b/x").verdict == "yes"
    assert overlaps(u, "c/x").verdict == "no"


def test_intersect_finds_texts_longer_than_any_bound():
    # A width far past any fixed search depth, so the search must be exact.
    n = Param("n", type=int)
    [la], _ = shapes(P(T(t"{n:070d}")), builtin_values=True)
    [lb], _ = shapes(P(T(t"{name}9")))
    texts = intersect(la.items[0].lang, lb.items[0].lang)
    assert texts and len(texts[0]) == 70 and texts[0].endswith("9")


def _lang_of(e):
    [shape], _ = shapes(P(e))
    return shape.items[0].lang


def test_many_languages_meet_two_at_a_time(monkeypatch):
    # The segments one alignment holds equal are met as one language. Met
    # two at a time, each product trimmed, they stay small; met all at once
    # they were a product of every language's states.
    import wend._overlap as O

    x, y, z = Param("x"), Param("y"), Param("z")
    xb, yab, zbb, zab = (
        _lang_of(T(t"{x}.b")),
        _lang_of(T(t"{y}a.b")),
        _lang_of(T(t"{z}b.b")),
        _lang_of(T(t"{z}a.b")),
    )
    assert O.intersect_all([xb, yab, zbb]) == []
    assert O.intersect_all([xb, yab, zab]) == ["a.b"]

    # What a language excludes stays excluded, whichever is met first.
    def dots(exclude):
        b = O._Builder()
        b.repeat(O.Chars(frozenset(".")), 1, 2)
        return O.Lang(nfa=b.nfa, start=b.start, end=b.end, exclude=exclude)

    assert O.intersect_all([dots(()), dots(()), dots((".",))]) == [".."]
    assert O.intersect_all([dots(()), dots(()), dots((".", ".."))]) == []
    # A language met many times is met once.
    nn = _lang_of(T(t"{n:02d}"))
    assert O.intersect_all([nn] * 18) == O.intersect(nn, nn)
    # Past MEET_STATES, decided neither way.
    monkeypatch.setattr(O, "MEET_STATES", 1)
    with pytest.raises(O.TooHard):
        O.intersect_all([xb, yab, zab])


def test_an_intersection_too_hard_rules_nothing_out(monkeypatch):
    import wend._overlap as O

    x = Param("x")
    a, b = P("d") / x / x, P("d") / "a" / "b"
    assert overlaps(a, b, shared=True).verdict == "no"

    def hard(*args):
        raise O.TooHard("past the bound")

    monkeypatch.setattr(O, "_solve", hard)
    assert overlaps(a, b, shared=True).verdict == "maybe"


# -- falsifying NO on random expressions ------------------------------------------

p, q = Param("p"), Param("q")
n = Param("n", type=int)
c = Param("c", choices={"a", "b", "x.txt"})
s = SubPath("s")
sc = SubPath("sc", choices={".", "a", "a/b"})
root = Param("root")
f = Param("f", type=bool)
ab = Absolute("ab")

POOL = {
    # Every kind of value builtin_values allows: bool is an int, and an
    # untyped parameter may be bound to any builtin type.
    "p": [
        "a",
        "b",
        "x",
        "a.b",
        "x.txt",
        "x.",
        "1",
        "01",
        "...",
        3,
        2.5,
        None,
        True,
        PurePosixPath("x.txt"),
    ],
    "q": ["a", "b", "x.txt", "7", False, 1 + 2j],
    "n": [0, 1, 7, 12, -1, 100, 2026, True, False],
    "c": ["a", "b", "x.txt"],
    "s": [".", "a", "a/b", "b/x.txt", "x.txt"],
    "sc": [".", "a", "a/b"],
    "root": ["", "a", "/", "/a", "..", "a/..", "//x"],
    "f": [False, True],
    "ab": ["/", "/a", "/a/b", "//x"],
}

HEADS = [
    lambda: P("."),
    lambda: P("/"),
    lambda: P("data"),
    lambda: P(root),
    lambda: P("//"),
    lambda: P(ab),
]
PARTS = [
    lambda: "a",
    lambda: "b",
    lambda: "x.txt",
    lambda: "..",
    lambda: p,
    lambda: q,
    lambda: c,
    lambda: s,
    lambda: sc,
    lambda: T(t"{p}.txt"),
    lambda: T(t"{n:02d}"),
    lambda: T(t"{n}"),
    lambda: T(t"x{p}"),
    lambda: T(t"{p}-{q}"),
    lambda: T(t"{p}{q}"),
    lambda: T(t"{c}.txt"),
    lambda: T(t"{f}.txt"),
    lambda: T(t"{n:d}.{p}"),
    lambda: T(t"chunk_{n:03d}"),
    # A bool's text against an int field's: bool is an int.
    lambda: "True",
    lambda: T(t"{f}"),
    lambda: T(t"{n}.txt"),
]


@st.composite
def expressions(draw):
    e = HEADS[draw(st.integers(0, len(HEADS) - 1))]()
    for _ in range(draw(st.integers(0, 3))):
        e = e / PARTS[draw(st.integers(0, len(PARTS) - 1))]()
    return e


def renders(e):
    """Every path ``e`` renders from the pool, with its binding."""
    names = sorted(e.param_names)
    for combo in itertools.product(*(POOL[k] for k in names)):
        env = dict(zip(names, combo, strict=True))
        try:
            yield e.render(env), env
        except WendError, ValueError:
            pass


def readings(e, path):
    try:
        return e.match_all(path, limit=4)
    except NotInvertibleError:
        return None


@settings(max_examples=300, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(a=expressions(), b=expressions())
def test_no_is_never_refuted_and_yes_is_always_witnessed(a, b):
    for shared, builtin in [(False, False), (False, True), (True, False)]:
        r = overlaps(a, b, shared=shared, builtin_values=builtin)
        if r.verdict == "yes":
            w = r.witness
            assert a.render(w.a) == w.path and b.render(w.b) == w.path
            if shared:
                assert all(w.a[k] == w.b[k] for k in a.param_names & b.param_names)
        if r.verdict != "no":
            continue
        if shared:
            # Falsify: no one environment renders the same path from both.
            names = sorted(a.param_names | b.param_names)
            pools = (POOL[k] for k in names)
            for combo in itertools.islice(itertools.product(*pools), 400):
                env = dict(zip(names, combo, strict=True))
                try:
                    same = a.render(env) == b.render(env)
                except WendError, ValueError:
                    continue
                assert not same, (
                    f"shared NO refuted by {env}: {a.pattern} vs {b.pattern}"
                )
            continue
        # Falsify: no rendering of a is a rendering of b, or a path b matches.
        common = {x for x, _ in renders(a)} & {x for x, _ in renders(b)}
        assert not common, (
            f"NO refuted by {sorted(common)[:2]}: {a.pattern} vs {b.pattern}"
        )
        for path, _ in itertools.islice(renders(a), 300):
            found = readings(b, path)
            assert not found, f"NO refuted by {path!r}: {a.pattern} vs {b.pattern}"


@settings(max_examples=150, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(e=expressions())
def test_an_expression_overlaps_itself(e):
    if next(renders(e), None) is None:
        return  # renders nothing from the pool; it may render nothing at all
    for shared in (False, True):
        # Not only never NO: a sample rendering of e is a witness, so the
        # search should always find one.
        r = overlaps(e, e, shared=shared)
        assert r.verdict == "yes", (e.pattern, shared, r)
