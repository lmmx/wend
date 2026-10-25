"""wend.relate: whether two families name the same path, one inside the other,
or neither, for every binding, for some, or for none (docs/SEMANTICS.md §15).

Each "always" and "never" is checked against every binding of a pool of
hostile values; each "sometimes" against its example."""

import itertools

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from overlap_test import POOL, expressions

from wend import Absolute, P, Param, PathExpr, Relation, SubPath, T, relate
from wend._relate import lexically
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


@st.composite
def pairs(draw):
    """Two expressions, often sharing a prefix (head and parts), as the paths
    of one pipeline do."""
    a = draw(expressions())
    if draw(st.booleans()):
        b = draw(expressions())
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


@settings(max_examples=300, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(pair=pairs())
def test_every_always_and_never_holds_for_every_pooled_binding(pair):
    a, b = pair
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
