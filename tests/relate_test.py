"""wend.relate: whether two families name the same path, one inside the other,
or neither, for every binding, for some, or for none (docs/SEMANTICS.md §15).

Each "always" and "never" is checked against every binding of a pool of
hostile values; each "sometimes" against its example."""

import itertools
import os
import subprocess
import sys
import time
from pathlib import PurePosixPath

import pytest
from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st
from overlap_test import PARTS, POOL, ab, expressions, n, p, q, s, sc

from wend import Absolute, P, Param, PathExpr, Relation, SubPath, T, relate
from wend._expr import REL, Deferred, Splice
from wend._relate import Memo, _cases, _depth, _segments, lexically
from wend.errors import WendError


root, day, other = Param("root"), Param("day", type=str), Param("other", type=str)
raw = P(root) / "raw" / T(t"{day}.csv")
clean = P(root) / "clean" / T(t"{day}.parquet")


def check_examples(a, b, r: Relation):
    for ex in r.examples:
        assert r[ex.how] in ("always", "sometimes")
        assert P(a).render(ex.a_bindings) == ex.a_path
        assert P(b).render(ex.b_bindings) == ex.b_path
        assert lexically(ex.a_path, ex.b_path) == ex.how
        if r.shared:
            common = ex.a_bindings.keys() & ex.b_bindings.keys()
            assert all(ex.a_bindings[k] == ex.b_bindings[k] for k in common)


def test_two_stages_of_one_pipeline_are_disjoint():
    r = relate(raw, clean)
    assert (r.same, r.inside, r.contains) == ("never", "never", "never")
    assert r.kind == "disjoint" and r.disjoint and not r


def test_one_family_spelt_twice_is_always_the_same_path():
    again = (P(root) / "raw").joinpath(T(t"{Param('day')}.csv"))  # declared otherwise
    r = relate(raw, again)
    assert r.kind == "same" and (r.inside, r.contains) == ("never", "never")
    check_examples(raw, again, r)
    assert r.examples and r.examples[0].a_path == r.examples[0].b_path


def test_a_file_is_always_inside_its_directory_and_the_directory_contains_it():
    assert relate(raw, P(root) / "raw").kind == "inside"
    assert relate(P(root) / "raw", raw).kind == "contains"
    assert relate(raw, P(root)).inside == "always"


def test_a_subpath_may_be_empty_so_nesting_is_only_sometimes():
    r = relate(P(root) / "raw" / SubPath("rest"), P(root) / "raw")
    assert (r.same, r.inside, r.contains) == ("sometimes", "sometimes", "never")
    check_examples(P(root) / "raw" / SubPath("rest"), P(root) / "raw", r)


def test_a_parameter_in_place_of_a_literal_overlaps_with_an_example():
    any_day = P(root) / "raw" / T(t"{other}.csv")
    r = relate(raw, any_day)
    assert r.kind == "overlapping" and r.same == "sometimes"
    check_examples(raw, any_day, r)


def test_different_defaults_break_always():
    a = P(Param("root", default="a")) / "x"
    b = P(Param("root", default="b")) / "x"
    r = relate(a, b)
    assert r.same == "sometimes"  # bound, both render one path; unbound, two
    assert relate(a, P(root) / "x").same == "always"  # one default is not a conflict


def test_a_name_changed_under_different_defaults_is_not_tied():
    # A view's text, and a parent's SubPath, stand for what the operation
    # renders. With a name defaulted differently on each side, the two sides
    # render different texts when it is unbound, so the texts are not one.
    xa, xb = Param("x", default="a"), Param("x", default="b")
    a = (P("data") / xa).with_suffix(".q") / "y"
    b = (P("data") / xb).with_suffix(".q") / "y"
    assert (a.render({}), b.render({})) == ("data/a.q/y", "data/b.q/y")
    r = relate(a, b)
    assert r.same == "sometimes" and r.kind == "overlapping"
    assert relate(a, a).same == "always"
    # A parent's SubPath, defaulted "x/z" on one side and "x" on the other:
    # unbound, both render data/x/a.
    rel_a, rel_b = SubPath("rel", default="x/z"), SubPath("rel", default="x")
    up, z = P("data") / rel_a, Param("z")
    a = up.parent / "a"
    b = (P("data") / rel_b).parent / "x" / T(t"{z}")
    assert a.render({}) == b.render({"z": "a"}) == "data/x/a"
    assert relate(a, b).same != "never"
    # Defaults belong to names: swapped between two names, they render "ab" on
    # one side and "ba" on the other.
    x1, y1 = Param("x", default="a"), Param("y", default="b")
    x2, y2 = Param("x", default="b"), Param("y", default="a")
    a = (P("data") / T(t"{x1}{y1}")).with_suffix(".q")
    b = (P("data") / T(t"{x2}{y2}")).with_suffix(".q")
    assert (a.render({}), b.render({})) == ("data/ab.q", "data/ba.q")
    assert relate(a, b).same == "sometimes"


def test_independent_bindings_need_static_paths_for_always():
    assert relate(raw, raw, shared=False).same == "sometimes"
    assert relate(P("/a/b"), P("/a/b"), shared=False).same == "always"
    assert relate(P("/a"), P("/a/b"), shared=False).contains == "always"
    assert relate(P("/a/x") / day, P("/a/y") / day, shared=False).kind == "disjoint"


def test_dotdot_makes_a_path_lexically_inside_and_is_never_ruled_out_by_shape():
    # "/x/.." is inside "/x" as a string, which "strictly below" cannot spell
    # with a segment parameter; the engine's NO is not trusted for it.
    a = P(Absolute("ab")) / ".."
    r = relate(a, P("/x"))
    assert r.inside != "never"
    assert lexically(a.render(ab="/x"), "/x") == "inside"
    assert relate(P("x") / "..", P("x")).inside == "always"


def test_a_changed_name_keeps_its_parent_and_what_the_change_fixes():
    # with_suffix on {day}.csv is deferred: an empty day renders ".csv",
    # which has no suffix, so the new name is ".csv.parquet", not ".parquet".
    pq = raw.with_suffix(".parquet")
    r = relate(pq, P(root) / "raw" / T(t"{day}.parquet"))
    assert (r.same, r.inside, r.contains) == ("sometimes", "never", "never")
    assert pq.render(root="r", day="") == "r/raw/.csv.parquet"
    assert relate(pq, raw).kind == "disjoint"  # it always ends in .parquet
    assert relate(pq, clean.with_suffix(".parquet")).kind == "disjoint"
    assert relate(pq, P(root) / "raw").kind == "inside"
    assert relate(pq, raw.with_suffix(".parquet")).kind == "same"
    assert relate(raw.with_stem("x"), P(root) / "raw" / "x.csv").same == "sometimes"
    assert relate(raw.with_stem("x"), P(root) / "raw" / "y.csv").kind == "disjoint"
    stem = (P("_") / T(t"{other}")).name
    assert relate(raw.with_stem(stem), P(root) / "raw" / "x.csv").same == "sometimes"
    assert relate(raw.with_name("a.json"), P(root) / "raw" / "a.json").kind == "same"
    assert relate(raw.with_name("a.json") / "x", P(root) / "raw").kind == "inside"
    # A name changed twice: the second change fixes it whatever the first did.
    assert relate(pq.with_name("a.json"), P(root) / "raw" / "a.json").kind == "same"


def test_a_changed_name_may_be_dotdot():
    # pathlib keeps the name ".." through with_suffix(""), and makes it from
    # the stem "..", or the stem "." before the suffix ".": no relation may
    # rule out a ".." the operation renders.
    d = Param("d")
    a = (P(root) / T(t"{d}")).with_stem(".")
    assert a.render(root="q", d="x.") == "q/.."
    assert relate(a, P(root) / "..").same != "never"
    a = (P(root) / T(t"{d}")).with_stem("..")
    assert a.render(root="q", d="x") == "q/.."
    assert relate(a, P(root) / "..").same != "never"
    b = P(root).with_suffix("")
    assert (b / "..").render(root="a") == b.render(root="a/..") == "a/.."
    assert relate(b / "..", b, shared=False).same != "never"


def test_different_anchors_never_meet():
    assert relate(P("."), P("/")).kind == "disjoint"
    assert (
        relate(P("x") / T(t"{day}.csv"), P("/x") / T(t"{day}.csv")).kind == "disjoint"
    )
    assert relate(P(Absolute("ab")) / "x", P("x")).kind == "disjoint"
    assert relate(P("/x"), P("//x")).kind == "disjoint"
    # An absolute value may start with "//", which POSIX keeps as an anchor.
    assert relate(P(Absolute("ab")), P("//x")).same == "sometimes"
    # Only a changed name keeps its base's anchor: relative_to drops it.
    assert relate(P(Absolute("ab")).relative_to(P("/")), P("x")).same == "sometimes"


def test_parents_relative_paths_and_joins_have_their_anchors():
    rel = SubPath("rel")
    up = (P("/srv") / rel).parent  # deferred: rel may be empty
    assert isinstance(up.head, Deferred)
    assert relate(up, P("data")).kind == "disjoint"
    assert relate(up, P("/srv")).same == "sometimes"
    # Made relative to anything, a path is relative.
    made = (P(root) / "x").relative_to(P(Param("b")))
    assert relate(made, P("/srv") / "x").kind == "disjoint"
    # A join keeps its left side's anchor where the right side is relative.
    joined = P("/srv") / (P("a") / rel).parent
    assert isinstance(joined.head, Deferred) and joined.head.op == "join"
    assert relate(joined, P("data")).kind == "disjoint"
    assert relate(joined, P("/srv") / "a").same == "sometimes"
    # An absolute right side replaces a relative left side's anchor.
    reset = P("data") / (P("/x") / rel).parent
    assert isinstance(reset.head, Deferred) and reset.head.op == "join"
    assert relate(reset, P("/x")).same == "sometimes"
    assert relate(reset, P("data")).kind == "disjoint"


def test_a_deferred_parent_is_written_out_by_its_subpath():
    name = Param("name", type=str)
    up = (P(root) / "raw" / T(t"{name}") / SubPath("rel")).parent
    # {root}/raw/{name}/{...}, or {root}/raw where rel is empty: never out/.
    assert relate(up, P(root) / "out" / "x").kind == "disjoint"
    assert relate(up, P(root) / "raw").same == "sometimes"
    assert relate(up, P(root) / "raw" / T(t"{name}") / "x").kind != "disjoint"


def test_paths_of_fixed_depth_nest_only_by_depth():
    a = P(root) / "raw" / T(t"{day}.csv")
    b = P(root) / T(t"{other}") / T(t"{day}.parquet")
    r = relate(a, b)
    assert (r.inside, r.contains) == ("never", "never")
    r = relate(P(root) / T(t"{other}"), a)
    assert (r.same, r.inside) == ("never", "never")


def test_segments_that_differ_on_every_run_never_meet():
    s = Param("s", type=str)
    R = P(root)
    # Equal pieces at either end cancel; what remains differs in a character.
    for a, b in [
        (R / T(t"{day}.csv"), R / T(t"{day}.csv.gz")),
        (R / T(t"{s}-a"), R / T(t"{s}-b")),
        (R / T(t"run{s}") / "x", R / T(t"run{s}.log")),
        (R / T(t"{day}.csv") / "x", R / T(t"{day}.tsv")),
    ]:
        assert relate(a, b).kind == "disjoint", (a, b)
    # Different parameters, or one bound apart, may render alike.
    assert relate(R / T(t"{day}.csv"), R / T(t"{s}.csv")).same == "sometimes"
    assert relate(R / T(t"a{s}x"), R / T(t"a{s}")).same == "never"
    # Bound apart, a{s}x is a{s} for the other's s ending in x.
    d = P("data")
    assert relate(d / T(t"a{s}x"), d / T(t"a{s}"), shared=False).same == "sometimes"
    # A name with a different default on each side renders differently when
    # unbound: unbound, both render xx.
    a = R / T(t"{Param('n', default='x')}x.")
    b = R / T(t"{Param('n', default='xx')}.")
    assert relate(a, b).same != "never"
    # A lone field is a segment-valued parameter, which a str subclass may
    # render apart from its value in text: no cancellation across roles.
    assert relate(R / T(t"{s}.json"), R / T(t"{s}")).same == "unknown"


def test_a_field_renders_its_value_alike_in_a_segment_and_in_text():
    # A shard directory and its manifest. Alone in a segment, `split` is a
    # segment-valued parameter (os.fspath of a str); in text it is formatted.
    split = Param("split")
    shard, manifest = P(root) / split, P(root) / T(t"{split}.json")
    for a, b in [(shard, manifest), (shard / "part.parquet", manifest)]:
        trusting = relate(a, b, builtin_values=True)
        assert trusting.kind == "disjoint", (a, b, trusting)
        assert trusting.assumptions == {"builtin_values"}
        assert relate(a, b).kind == "unknown"

    # The assumption carries weight: a str whose __format__ drops its suffix
    # renders one path in both places.
    class Odd(str):
        def __format__(self, spec):
            return str.__format__(self.removesuffix(".json"), spec)

    env = {"root": "r", "split": Odd("a.json")}
    assert shard.render(env) == manifest.render(env) == "r/a.json"
    # !s is str() itself, so plain too.
    plain_s = P(root) / T(t"{split!s}.json")
    assert relate(shard, plain_s, builtin_values=True).kind == "disjoint"
    # A spec or a !r conversion is not plain, and does not cancel: "abc"
    # renders alike either way, "a" does not.
    for text in (T(t"{split:>3}"), T(t"{split!r}")):
        r = relate(shard, P(root) / text, builtin_values=True)
        assert r.same in ("sometimes", "unknown"), (text, r)
    # Without a field in each role, no answer rests on the assumption.
    assert relate(shard, P(root) / "x", builtin_values=True).assumptions == set()


_HASHED = """
from wend import P, Param, SubPath, T, relate
p, q, root, rel = Param("p"), Param("q"), Param("root"), SubPath("rel")
c = Param("c", choices={"a", "b", "x.txt", "y", "z.txt"})
pairs = [
    (P("/") / T(t"{c}.txt") / T(t"{p}{q}"),
     P("/") / T(t"{c}.txt") / T(t"{c}.txt") / T(t"{p}{q}")),
    ((P("/") / T(t"{p}.txt") / "b" / c).with_stem("a") / T(t"{p}.txt") / q / c,
     P("/") / T(t"{p}.txt") / "b" / T(t"{q}.txt") / T(t"{p}.txt") / q / c),
    ((P(root) / T(t"{p}.csv")).with_suffix(".x"), (P(root) / T(t"{q}.csv")).with_stem("y")),
    ((P(root) / rel).parent / "x", (P(root) / "raw" / rel).parent),
]
for a, b in pairs:
    for shared in (True, False):
        r = relate(a, b, shared=shared)
        print(r, r.examples)
"""


def test_answers_do_not_depend_on_string_hashing():
    # The samples tried for an example once followed a frozenset of choices,
    # and views named their text by hash(): which example was found, and so
    # "sometimes" or "unknown", changed with PYTHONHASHSEED.
    runs = {
        subprocess.run(
            [sys.executable, "-c", _HASHED],
            env={**os.environ, "PYTHONHASHSEED": str(seed)},
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        for seed in (0, 1, 2, 3)
    }
    assert len(runs) == 1, runs


def test_a_view_never_takes_a_name_of_the_expressions():
    # A view's text and a parent's SubPath get names of their own. Were one
    # to share a name with a parameter of the other side, shared bindings
    # would tie them: the view "{root}/{_name_0}.csv" is then the other side
    # itself, and would read "always".
    x, taken = Param("x"), Param("_name_0")
    a = (P(root) / x).with_suffix(".csv")
    b = P(root) / T(t"{taken}.csv")
    env = {"root": "r", "x": "f", "_name_0": "g"}
    assert (a.render(env), b.render(env)) == ("r/f.csv", "r/g.csv")
    assert relate(a, b).same == "sometimes"
    assert relate(b, a).same == "sometimes"
    rest = SubPath("_rest_0")
    up = (P(root) / "raw" / SubPath("rel")).parent
    assert relate(up, P(root) / "raw" / rest).same != "never"


def test_finite_choices_that_multiply_shapes_stay_quick():
    # With builtin_values the choices of `sc` are exhaustive, and each `sc`
    # gives the overlap analysis three shapes: 54 for one side, 162 for the
    # other. Pairing every one took minutes; once two shapes meet, the
    # analysis now stops when it has candidates enough.
    base = (P(ab) / sc / q / sc / s).with_suffix(".b")
    a = base / s / n / sc
    b = a / s / n / sc
    start = time.monotonic()
    for shared in (True, False):
        relate(a, b, shared=shared, builtin_values=True)
    assert time.monotonic() - start < 30


def test_names_changed_from_one_base_are_written_out_by_its_split():
    raw = P(root) / "raw" / T(t"{day}.csv")
    parquet, summary = raw.with_suffix(".parquet"), raw.with_stem("summary")
    # {day}.parquet or .csv.parquet, against summary.csv or summary.
    assert relate(parquet, summary).kind == "disjoint"
    assert relate(parquet, raw.with_suffix(".json")).kind == "disjoint"
    # With day empty, .csv has no suffix: each case is a real rendering.
    assert parquet.render(root="r", day="") == "r/raw/.csv.parquet"
    assert relate(parquet, P(root) / "raw" / ".csv.parquet").same == "sometimes"
    assert summary.render(root="r", day="") == "r/raw/summary"
    assert relate(summary, P(root) / "raw" / "summary").same == "sometimes"
    # A day named summary: the stem changed to its own value.
    assert relate(summary, raw).same == "sometimes"
    # The suffix starts at the last dot: {day}.tar.gz becomes {day}.tar.zip.
    tgz = P(root) / T(t"{day}.tar.gz")
    assert (
        relate(tgz.with_suffix(".zip"), P(root) / T(t"{day}.tar.zip")).same != "never"
    )
    assert relate(tgz.with_suffix(".zip"), P(root) / T(t"{day}.zip")).same == "never"
    # A literal character before the dot leaves one case: a.{day}.csv always
    # has the suffix .csv.
    lit = P(root) / T(t"a.{day}.csv")
    assert relate(lit.with_stem("b"), P(root) / "b").same == "never"
    assert relate(raw.with_stem("b"), P(root) / "raw" / "b").same == "sometimes"


def test_strings_and_unions_relate_too():
    assert relate("data/raw", "data/raw/x.csv").kind == "contains"
    r = relate(raw | clean, clean)
    assert r.same == "sometimes" and r.kind == "overlapping"
    assert relate(raw | clean, P(root) / "models").kind == "disjoint"


def test_a_relation_reads_as_one_word_and_three_answers():
    r = relate(raw, P(root) / "raw")
    assert r["inside"] == "always"
    assert repr(r) == (
        "Relation(inside: same='never', inside='always', contains='never')"
    )


# -- every claim against every pooled binding ----------------------------------------


NAMES = [
    ("with_suffix", lambda: ".txt"),
    ("with_suffix", lambda: ""),
    ("with_suffix", lambda: ".b"),
    ("with_stem", lambda: "x"),
    ("with_stem", lambda: "a"),
    ("with_stem", lambda: (P("_") / T(t"{p}")).name),
    ("with_name", lambda: "x.txt"),
    ("with_name", lambda: (P("_") / T(t"{q}.txt")).name),
    # Literal stems and names pathlib may turn into "..": the stem "..", or
    # "." before the suffix "."; the name "..".
    ("with_stem", lambda: ".."),
    ("with_stem", lambda: "."),
    ("with_name", lambda: ".."),
]


@st.composite
def derived(draw):
    """An expression, its name sometimes changed by ``with_name``,
    ``with_suffix`` or ``with_stem`` (deferred while the name is unknown),
    and sometimes joined onto afterwards."""
    e = draw(expressions())
    for _ in range(draw(st.integers(0, 2))):
        op, arg = NAMES[draw(st.integers(0, len(NAMES) - 1))]
        try:
            e = getattr(e, op)(arg())
        except WendError, ValueError, TypeError:
            break
    if draw(st.booleans()):
        e = e / draw(st.sampled_from(["a", "x.txt", ".."]))
    return e


@st.composite
def pairs(draw):
    """Two expressions, often sharing a prefix (head and parts), as the paths
    of one pipeline do; sometimes with names changed (`derived`)."""
    a = draw(derived() if draw(st.booleans()) else expressions())
    if draw(st.booleans()):
        b = draw(derived() if draw(st.booleans()) else expressions())
    elif isinstance(a.head, Deferred):
        # A sibling of the changed name, or another change of it: the pairs
        # whose names may coincide.
        base = a.head.base
        while isinstance(base.head, Deferred):
            base = base.head.base
        rest = draw(derived() if draw(st.booleans()) else expressions())
        b = PathExpr(base.head, base.parts[:-1] + rest.parts)
        if draw(st.booleans()):
            op, arg = NAMES[draw(st.integers(0, len(NAMES) - 1))]
            try:
                b = getattr(base, op)(arg())
            except WendError, ValueError, TypeError:
                pass
    else:
        k = draw(st.integers(0, len(a.parts)))
        rest = draw(expressions())
        b = PathExpr(a.head, a.parts[:k] + rest.parts)
    return a, b


def rendered(e, env):
    try:
        return e.render({k: v for k, v in env.items() if k in e.param_names})
    except WendError, ValueError:
        return None


def assert_sound(a, b):
    """Every "always" and "never" of relate(a, b), in both modes, holds for
    every pooled binding (up to 800 shared, 120 x 120 independent). The pool's
    values are of builtin types, so the answers under builtin_values=True
    must hold too."""
    for shared, builtin in itertools.product((True, False), (False, True)):
        r = relate(a, b, shared=shared, builtin_values=builtin)
        check_examples(a, b, r)
        if shared:
            names = sorted(a.param_names | b.param_names)
            envs = (
                dict(zip(names, combo, strict=True))
                for combo in itertools.product(*(POOL[k] for k in names))
            )
            seen = (
                (rendered(a, env), rendered(b, env), env)
                for env in itertools.islice(envs, 800)
            )
        else:
            ea = [
                dict(zip(sorted(a.param_names), c, strict=True))
                for c in itertools.product(*(POOL[k] for k in sorted(a.param_names)))
            ]
            eb = [
                dict(zip(sorted(b.param_names), c, strict=True))
                for c in itertools.product(*(POOL[k] for k in sorted(b.param_names)))
            ]
            seen = (
                (rendered(a, x), rendered(b, y), (x, y))
                for x, y in itertools.product(ea[:120], eb[:120])
            )
        for pa, pb, env in seen:
            if pa is None or pb is None:
                continue
            how = lexically(pa, pb)
            for h in ("same", "inside", "contains"):
                if r[h] == "always":
                    assert how == h, (h, "always", a.pattern, b.pattern, env, pa, pb)
                if r[h] == "never":
                    assert how != h, (h, "never", a.pattern, b.pattern, env, pa, pb)


@settings(max_examples=300, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(pair=pairs())
def test_every_always_and_never_holds_for_every_pooled_binding(pair):
    assert_sound(*pair)


@st.composite
def renamed(draw):
    """A name changed by ``with_name``, ``with_suffix`` or ``with_stem``, and
    a path beside it, or the same name changed again: pairs whose names may
    coincide, which `pairs` draws rarely."""
    base = draw(expressions())
    if not base.parts:
        base = base / "x.txt"
    op, arg = NAMES[draw(st.integers(0, len(NAMES) - 1))]
    try:
        a = getattr(base, op)(arg())
    except WendError, ValueError, TypeError:
        a = base
    if draw(st.booleans()):
        op, arg = NAMES[draw(st.integers(0, len(NAMES) - 1))]
        try:
            b = getattr(base, op)(arg())
        except WendError, ValueError, TypeError:
            b = base
    else:
        last = PARTS[draw(st.integers(0, len(PARTS) - 1))]()
        b = PathExpr(base.head, base.parts[:-1]) / last
    if draw(st.booleans()):
        a = a / "a"
    return a, b


@settings(max_examples=300, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(pair=renamed())
def test_changed_names_hold_for_every_pooled_binding(pair):
    assert_sound(*pair)


HEAD_OPS = [
    lambda e: e.parent,
    lambda e: e.relative_to(P(p)),
    lambda e: e.relative_to(P(root)),
    *(lambda e, op=op, arg=arg: getattr(e, op)(arg()) for op, arg in NAMES),
]


@st.composite
def under_one_head(draw):
    """Two paths below one deferred head (a parent below a SubPath, a path
    relative to a parameter, a changed name), built twice, or below two such
    heads made from one base: the pairs whose shared prefix cancels only
    through a deferred head."""
    base = draw(expressions())
    if draw(st.booleans()):
        base = base / draw(st.sampled_from([s, sc]))
    elif not base.parts:
        base = base / "x.txt"
    i = draw(st.integers(0, len(HEAD_OPS) - 1))
    j = i if draw(st.booleans()) else draw(st.integers(0, len(HEAD_OPS) - 1))
    try:
        ha, hb = HEAD_OPS[i](base), HEAD_OPS[j](base)
    except WendError, ValueError, TypeError:
        assume(False)
    assume(isinstance(ha.head, Deferred) or isinstance(hb.head, Deferred))
    ra = draw(expressions()).parts
    rb = ra[: draw(st.integers(0, len(ra)))] + draw(expressions()).parts
    return PathExpr(ha.head, ha.parts + ra), PathExpr(hb.head, hb.parts + rb)


@settings(max_examples=100, deadline=None, suppress_health_check=list(HealthCheck))
@given(pair=under_one_head())
def test_paths_below_one_deferred_head_hold_for_every_pooled_binding(pair):
    assert_sound(*pair)


DEFAULTS = [".", "a", "x", "a/b", "x/z", "w", "x/a"]


@st.composite
def defaulted(draw):
    """Two expressions over one base ending in a name with a default on each
    side, perhaps a different one: a SubPath or a segment, changed by a name
    operation or a parent, then joined onto."""

    def side():
        if draw(st.booleans()):
            last = SubPath("rel", default=draw(st.sampled_from(DEFAULTS)))
        else:
            last = Param("rel", default=draw(st.sampled_from(["a", "x", "w", "x.q"])))
        e = P("data") / last
        op = draw(
            st.sampled_from(["parent", "with_suffix", "with_stem", "with_name", ""])
        )
        try:
            if op == "parent":
                e = e.parent
            elif op == "with_suffix":
                e = e.with_suffix(draw(st.sampled_from([".q", ""])))
            elif op:
                e = getattr(e, op)(draw(st.sampled_from(["x", "y"])))
        except WendError, ValueError:
            pass
        for part in draw(st.lists(st.sampled_from(["a", "x", "y", "z"]), max_size=2)):
            e = e / (T(t"{Param('z')}") if part == "z" else part)
        return e

    return side(), side()


@settings(max_examples=300, deadline=None, suppress_health_check=list(HealthCheck))
@given(pair=defaulted())
def test_names_defaulted_apart_hold_bound_and_unbound(pair):
    # The pooled bindings bind every name, so a default never renders there:
    # here `rel` is also left unbound, and each side renders its own.
    a, b = pair
    r = relate(a, b)
    check_examples(a, b, r)
    for rel in [None, ".", "a", "x", "x/z", "w/x"]:
        for z in ["a", "x", "y"]:
            env = {"z": z} if rel is None else {"z": z, "rel": rel}
            pa, pb = rendered(a, env), rendered(b, env)
            if pa is None or pb is None:
                continue
            how = lexically(pa, pb)
            for h in ("same", "inside", "contains"):
                if r[h] == "always":
                    assert how == h, (h, a.pattern, b.pattern, env, pa, pb, r)
                if r[h] == "never":
                    assert how != h, (h, a.pattern, b.pattern, env, pa, pb, r)


def test_one_deferred_head_cancels_as_a_prefix():
    # A parent below a SubPath is not known until binding; spelt twice, it
    # renders one string, so what follows it decides.
    up = (P(root) / T(t"{other}") / SubPath("rel")).parent
    assert relate(up, up).kind == "same"
    assert relate(up / "a", up).kind == "inside"
    assert relate(up / T(t"{day}.csv"), up / T(t"{day}.parquet")).kind == "disjoint"
    rel = (P(root) / "a" / T(t"{day}.csv")).relative_to(P(Param("base")))
    assert relate(rel, rel).kind == "same"
    # Unless the head's parameters may render differently: a default each.
    x = (P(root) / T(t"{Param('n', default='x')}") / SubPath("rel")).parent
    y = (P(root) / T(t"{Param('n', default='y')}") / SubPath("rel")).parent
    assert relate(x, y).same == "sometimes"
    # Or the two sides are bound independently.
    assert relate(up, up, shared=False).same == "sometimes"


TAILS = [
    lambda: T(t"{p}.csv"),
    lambda: T(t"{p}.tar.gz"),
    lambda: T(t"{p}{q}.x"),
    lambda: T(t"a.{p}.b"),
    lambda: T(t"{p}."),
    lambda: "x.txt",
]


@st.composite
def split_names(draw):
    """A suffix or stem changed on a base whose name ends in text with a dot."""
    base = draw(expressions()) / TAILS[draw(st.integers(0, len(TAILS) - 1))]()
    op, arg = NAMES[draw(st.integers(0, len(NAMES) - 1))]
    assume(op != "with_name")
    try:
        e = getattr(base, op)(arg())
    except WendError, ValueError, TypeError:
        assume(False)
    assume(_cases(e, Memo()) is not None)
    return e


@settings(max_examples=200, deadline=None, suppress_health_check=list(HealthCheck))
@given(e=split_names())
def test_the_cases_of_a_changed_name_render_all_it_renders(e):
    # What the case split rests on (§15.3, 3): on every binding, the change
    # renders what one of its cases renders under the same binding.
    cases = _cases(e, Memo())
    assert cases is not None
    names = sorted(e.param_names)
    for combo in itertools.islice(itertools.product(*(POOL[k] for k in names)), 400):
        env = dict(zip(names, combo, strict=True))
        path = rendered(e, env)
        if path is not None:
            assert path in {rendered(c, env) for c in cases}, (e.pattern, env, path)


@st.composite
def parents(draw):
    """A parent deferred because its base ends in a SubPath."""
    e = draw(expressions()) / draw(st.sampled_from([s, sc]))
    e = e.parent
    if draw(st.booleans()):
        e = e / draw(st.sampled_from(["a", "x.txt", ".."]))
    assume(_cases(e, Memo()) is not None)
    return e


@settings(max_examples=200, deadline=None, suppress_health_check=list(HealthCheck))
@given(e=parents())
def test_the_cases_of_a_parent_render_all_it_renders(e):
    # What the parent's cases rest on: on every binding, the parent renders
    # what one of its cases renders under the same binding.
    cases = _cases(e, Memo())
    assert cases is not None
    names = sorted(e.param_names)
    for combo in itertools.islice(itertools.product(*(POOL[k] for k in names)), 400):
        env = dict(zip(names, combo, strict=True))
        path = rendered(e, env)
        if path is not None:
            seen = {rendered(c, env | _rest(c, e, env)) for c in cases}
            assert path in seen, (e.pattern, env, path)


RENAMES = [
    ("with_suffix", ".csv"),
    ("with_suffix", ""),
    ("with_stem", "x"),
    ("with_name", "x.txt"),
]


@st.composite
def renamed_below(draw):
    """A name changed while its base ends in a SubPath."""
    e = draw(expressions()) / draw(st.sampled_from([s, sc]))
    op, arg = draw(st.sampled_from(RENAMES))
    try:
        e = getattr(e, op)(arg)
    except WendError, ValueError:
        assume(False)
    if draw(st.booleans()):
        e = e / draw(st.sampled_from(["a", "x.txt", ".."]))
    assume(_cases(e, Memo()) is not None)
    return e


@settings(max_examples=200, deadline=None, suppress_health_check=list(HealthCheck))
@given(e=renamed_below())
def test_the_cases_of_a_renamed_subpath_render_all_it_renders(e):
    # On every binding, the changed name renders what one of its cases
    # renders, with the SubPath split into all but its last segment and that
    # segment.
    cases = _cases(e, Memo())
    assert cases is not None
    names = sorted(e.param_names)
    for combo in itertools.islice(itertools.product(*(POOL[k] for k in names)), 400):
        env = dict(zip(names, combo, strict=True))
        path = rendered(e, env)
        if path is not None:
            seen = {rendered(c, env | _split_env(c, e, env)) for c in cases}
            assert path in seen, (e.pattern, env, path)


SPLIT_VALUES = [".", "a", "x", "a/x", "x/y", "data", "a/b/x", "x.b", "y/x.b"]


@st.composite
def below_two_subpaths(draw):
    """Two parents or changed names, each of a base ending in its own
    SubPath, then joined onto: the SubPaths split independently."""

    def side(rel):
        e = draw(st.sampled_from([P("data"), P("/"), P(root), P(".")]))
        for part in draw(st.lists(st.sampled_from(["a", "x", "data"]), max_size=1)):
            e = e / part
        e = e / rel
        op = draw(st.sampled_from(["parent", "with_suffix", "with_stem", "with_name"]))
        try:
            if op == "parent":
                e = e.parent
            else:
                e = getattr(e, op)(
                    draw(
                        st.sampled_from(
                            [".b", ""] if op == "with_suffix" else ["x", "x.b"]
                        )
                    )
                )
        except WendError, ValueError:
            pass
        for part in draw(
            st.lists(st.sampled_from(["a", "x", "data", "x.b", ".."]), max_size=2)
        ):
            e = e / part
        return e

    return side(SubPath("r1")), side(SubPath("r2"))


@settings(max_examples=200, deadline=None, suppress_health_check=list(HealthCheck))
@given(pair=below_two_subpaths())
def test_names_changed_below_two_subpaths_hold_for_pooled_bindings(pair):
    # Each side is split by its own SubPath, so their cases are paired every
    # way: the SubPaths may render any number of segments each.
    a, b = pair
    r = relate(a, b)
    check_examples(a, b, r)
    for v1, v2, rv in itertools.product(SPLIT_VALUES, SPLIT_VALUES, ["r", "/x"]):
        env = {"r1": v1, "r2": v2, "root": rv}
        pa, pb = rendered(a, env), rendered(b, env)
        if pa is None or pb is None:
            continue
        how = lexically(pa, pb)
        for h in ("same", "inside", "contains"):
            if r[h] == "always":
                assert how == h, (h, a.pattern, b.pattern, env, pa, pb, r)
            if r[h] == "never":
                assert how != h, (h, a.pattern, b.pattern, env, pa, pb, r)


def _split_env(case, e, env):
    """A case's own SubPath and segment, bound to the base's SubPath less its
    last segment, and that segment."""
    value = PurePosixPath(str(env[e.head.base.parts[-1].param.name]))
    out = {}
    for name in case.param_names - e.param_names:
        if name.startswith("_rest_"):
            out[name] = str(value.parent)
        elif name.startswith("_seg_"):
            out[name] = value.name or "."
    return out


def test_a_name_changed_below_a_subpath_is_written_out():
    rel = SubPath("rel")
    # The changed name keeps its base's prefix: never below {root}/out.
    a = (P(root) / "raw" / rel).with_suffix(".csv")
    assert relate(a, P(root) / "out" / "x").kind == "disjoint"
    # A plain path that begins with the base is split alike, and under shared
    # bindings only cases of one branch are paired: the SubPath renders one
    # text on both sides. A name changed in place is never strictly inside or
    # above its unchanged self.
    sc_ = SubPath("sc", choices={".", "a", "a/b"})
    r = relate((P("data") / sc_).with_suffix(".b"), P("data") / sc_)
    assert (r.inside, r.contains) == ("never", "never")
    # Bound apart, the branches are not paired, and nothing is proved.
    r = relate((P("data") / rel).with_suffix(".b"), P("data") / rel, shared=False)
    assert "never" not in (r.inside, r.contains)
    # Bases split on two SubPaths have branches of their own: here the first
    # renders a segment and the second none.
    a = (P("x") / SubPath("r1")).with_suffix(".b") / ".." / "a"
    b = (P("data") / SubPath("r2")).with_stem("x") / "x.b"
    assert (a.render({"r1": "x"}), b.render({"r2": "."})) == ("x/x.b/../a", "x/x.b")
    assert relate(a, b).inside != "never"
    # A parent and a changed name of one base share the split.
    r = relate((P("data") / rel).parent, (P("data") / rel).with_suffix(".b"))
    assert (r.same, r.inside, r.contains) == ("never", "never", "sometimes")


@st.composite
def dot_stems(draw):
    """The stem "." or ".." given to a name pathlib cannot split yet: a
    segment's with fields, or a SubPath's last."""
    e = draw(expressions())
    e = e / PARTS[draw(st.integers(0, len(PARTS) - 1))]()
    try:
        e = e.with_stem(draw(st.sampled_from([".", ".."])))
    except WendError, ValueError:
        assume(False)
    assume(isinstance(e.head, Deferred))
    if draw(st.booleans()):
        e = e / draw(st.sampled_from(["a", "x.txt", ".."]))
    assume(_cases(e, Memo()) is not None)
    return e


def _dot_env(case, e, env):
    """A case's own names: the suffix's text, bound to the base's suffix less
    its dot, and a SubPath split as `_split_env` splits it."""
    base = e.head.base
    out = {}
    if isinstance(base.parts[-1], Splice):
        out = _split_env(case, e, env)
    suffix = PurePosixPath(base.render(env)).suffix[1:]
    for name in case.param_names - e.param_names:
        if name.startswith("_name_"):
            out[name] = suffix
    return out


@settings(max_examples=200, deadline=None, suppress_health_check=list(HealthCheck))
@given(e=dot_stems())
def test_the_cases_of_a_dot_stem_render_all_it_renders(e):
    # On every binding, the stem "." or ".." renders what one of its cases
    # renders: the stem, a dot and the suffix's text, or the name "..".
    cases = _cases(e, Memo())
    assert cases is not None
    names = sorted(e.param_names)
    for combo in itertools.islice(itertools.product(*(POOL[k] for k in names)), 400):
        env = dict(zip(names, combo, strict=True))
        path = rendered(e, env)
        if path is not None:
            seen = {rendered(c, env | _dot_env(c, e, env)) for c in cases}
            assert path in seen, (e.pattern, env, path)


@settings(max_examples=200, deadline=None, suppress_health_check=list(HealthCheck))
@given(a=dot_stems(), b=st.one_of(expressions(), dot_stems()))
def test_dot_stems_hold_for_pooled_bindings(a, b):
    assert_sound(a, b)


def test_a_dot_stem_is_written_out():
    x = Param("x")
    # The stem ".." renders the name "..", where the name has no suffix, or
    # ".." then the suffix: never a name without a leading dot.
    a = (P("d") / T(t"{x}")).with_stem("..")
    assert (a.render(x="q"), a.render(x="q.t")) == ("d/..", "d/...t")
    assert relate(a, P("d") / "a").kind == "disjoint"
    assert relate(a, P("d") / "..").same == "sometimes"
    # The stem "." renders "." then the suffix, which begins with a dot: two
    # dots at least.
    a = (P("d") / T(t"{x}")).with_stem(".")
    assert (a.render(x="q."), a.render(x="q.t")) == ("d/..", "d/..t")
    assert relate(a, P("d") / ".a").kind == "disjoint"
    assert relate(a, P("d") / "..t").same != "never"
    # Below a SubPath, the changed name's cases are written out in turn: one
    # base's name changed two ways renders two names at one depth.
    rel = SubPath("rel")
    a = (P("d") / rel).with_stem("..") / "a"
    assert relate(a, P("d") / "b").same == "never"
    assert relate(a, P("d") / "b", shared=False).same == "never"
    r = relate((P("data") / rel).with_stem(".."), (P("data") / rel).with_suffix(".b"))
    assert (r.inside, r.contains) == ("never", "never")


@st.composite
def depth_cases(draw):
    """Expressions under deferred operations, perhaps several, and joined
    onto: those whose depth `_depth` may know."""
    e = draw(expressions())
    if draw(st.booleans()):
        e = e / draw(st.sampled_from([s, sc]))
    ops = [
        *HEAD_OPS,
        # A deferred path joined on is deferred: relative, or absolute.
        lambda e: e / (P("x") / s).parent,
        lambda e: e / (P(ab) / sc).parent,
    ]
    for _ in range(draw(st.integers(0, 2))):
        try:
            e = ops[draw(st.integers(0, len(ops) - 1))](e)
        except WendError, ValueError, TypeError:
            pass
        if draw(st.booleans()):
            e = e / PARTS[draw(st.integers(0, len(PARTS) - 1))]()
    return e


def _count(path):
    return len(_segments(path)[1])


@settings(max_examples=300, deadline=None, suppress_health_check=list(HealthCheck))
@given(e=depth_cases())
def test_a_depth_counts_the_segments_rendered(e):
    # On every binding, an expression renders its count of segments, and
    # what each part of varying count renders alone.
    d = _depth(e)
    assume(d is not None)
    n, signed = d
    names = sorted(e.param_names)
    for combo in itertools.islice(itertools.product(*(POOL[k] for k in names)), 400):
        env = dict(zip(names, combo, strict=True))
        path = rendered(e, env)
        if path is None:
            continue
        alone = [
            (
                c,
                rendered(
                    PathExpr(REL, (x,)) if isinstance(x, Splice) else PathExpr(x), env
                ),
            )
            for c, x in signed
        ]
        assert all(x is not None for _, x in alone), (e.pattern, env)
        count = n + sum(c * _count(x) for c, x in alone)
        assert _count(path) == count, (e.pattern, env, path)


def test_depths_decide_with_shared_subpaths():
    # A changed name keeps its base's depth, and a SubPath shared by both
    # sides renders one count of segments on both: here 2 + |s| against
    # 3 + |s|, so never the same, nor the first inside the second.
    a = (P(root) / T(t"{n:d}.{p}") / s).with_suffix("")
    b = P(root) / T(t"{n:d}.{p}") / T(t"{n:d}.{p}") / s
    r = relate(a, b)
    assert (r.same, r.inside) == ("never", "never")
    # Bound apart, each side's SubPath renders a count of its own.
    assert relate(a, b, shared=False).same == "sometimes"
    # A parent has one fewer segment, where its base renders one of its own.
    raw = P(root) / "raw" / SubPath("rel")
    r = relate(raw.parent / "x" / "y", raw.with_suffix(".csv"))
    assert (r.same, r.contains) == ("never", "never")
    # Counted with their multiplicity: {s}/{s} and {s}/a are one path where
    # s is "a".
    assert relate(P("d") / s / s, P("d") / s / "a").same == "sometimes"
    # A SubPath defaulted differently on each side renders two counts when
    # unbound: d/{rel} and d/{rel}/y are both d/x/y.
    ra, rb = SubPath("rel", default="x/y"), SubPath("rel", default="x")
    a, b = P("d") / ra, P("d") / rb / "y"
    assert a.render({}) == b.render({}) == "d/x/y"
    assert relate(a, b).same != "never"


def _rest(case, e, env):
    """The longer case's own SubPath, bound to the base's SubPath less its
    last segment."""
    fresh = sorted(case.param_names - e.param_names)
    if not fresh:
        return {}
    value = str(env[e.head.base.parts[-1].param.name])
    return {fresh[0]: str(PurePosixPath(value).parent)}


@settings(max_examples=150, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(e=expressions())
def test_an_expression_is_always_itself(e):
    r = relate(e, e)
    assert r.same == "always" and r.inside == "never" and r.contains == "never"


@pytest.mark.parametrize("shared", [True, False])
def test_relate_is_symmetric_with_inside_and_contains_swapped(shared):
    for a, b in itertools.product([raw, clean, P(root) / "raw", P(root)], repeat=2):
        r, s = relate(a, b, shared=shared), relate(b, a, shared=shared)
        assert (r.same, r.inside, r.contains) == (s.same, s.contains, s.inside)
