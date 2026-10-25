"""wend.relate: whether two families name the same path, one inside the other,
or neither, for every binding, for some, or for none (docs/SEMANTICS.md §15).

Each "always" and "never" is checked against every binding of a pool of
hostile values; each "sometimes" against its example."""

import itertools

import pytest
from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st
from overlap_test import PARTS, POOL, expressions, p, q, s, sc

from wend import Absolute, P, Param, PathExpr, Relation, SubPath, T, relate
from wend._expr import Deferred
from wend._relate import _cases, lexically
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
    every pooled binding (up to 800 shared, 120 x 120 independent)."""
    for shared in (True, False):
        r = relate(a, b, shared=shared)
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
    assume(_cases(e) is not None)
    return e


@settings(max_examples=200, deadline=None, suppress_health_check=list(HealthCheck))
@given(e=split_names())
def test_the_cases_of_a_changed_name_render_all_it_renders(e):
    # What the case split rests on (§15.3, 3): on every binding, the change
    # renders what one of its cases renders under the same binding.
    cases = _cases(e)
    assert cases is not None
    names = sorted(e.param_names)
    for combo in itertools.islice(itertools.product(*(POOL[k] for k in names)), 400):
        env = dict(zip(names, combo, strict=True))
        path = rendered(e, env)
        if path is not None:
            assert path in {rendered(c, env) for c in cases}, (e.pattern, env, path)


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
