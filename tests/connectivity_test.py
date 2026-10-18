"""Connectivity (docs/SEMANTICS.md §9): derivations, bases, siblings, rebasing."""

import pickle

import pytest
from contract_test import ANY, ROOT, SEG, SUB, build, envs, terms
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from wend import NotStaticError, P, Param, PathOperationError, T


root = Param("root")


def test_a_child_remembers_its_base():
    project = P(root)
    config = project.child("config.yaml")
    assert config.base is project
    assert config.base_rel == P("config.yaml")
    assert config.rebase(P("/tmp/test")).render() == "/tmp/test/config.yaml"
    # equality ignores how a path was built
    assert config == P(root) / "config.yaml"
    assert hash(config) == hash(P(root) / "config.yaml")


def test_bases_chain_and_relative_to_flattens():
    raw = P(root) / "data" / "raw"
    assert raw.base == P(root) / "data"
    assert raw.base.base == P(root)
    assert raw.relative_to(P(root)) == P("data/raw")


def test_a_sibling_moves_with_its_source():
    name = Param("name")
    csv_in = P(root) / "data" / T(t"{name}.csv")
    schema = csv_in.sibling("schema.json")
    assert schema == P(root) / "data" / "schema.json"
    assert schema.param_names == {"root"}  # the sibling does not need `name`
    moved = csv_in.rebase(P(root) / "data", P("/archive"))
    assert schema.rebase(csv_in, moved).render() == "/archive/schema.json"
    assert schema.derived_from(csv_in)
    assert not schema.derived_from(P("/archive"))


def test_dependents_move_together():
    data = P(root) / "data" / "input.csv"
    paths = {
        "data": data,
        "schema": data.sibling("schema.json"),
        "meta": data.with_suffix(".meta.json"),
        "out": data.cousin("../out", "result.csv"),
        "log": P("/var/log/app.log"),
    }
    test_data = P("/tmp/t") / "input.csv"
    moved = {
        k: e.rebase(data, test_data) if e.derived_from(data) else e
        for k, e in paths.items()
    }
    assert {k: e.render() for k, e in moved.items()} == {
        "data": "/tmp/t/input.csv",
        "schema": "/tmp/t/schema.json",
        "meta": "/tmp/t/input.meta.json",
        "out": "/tmp/out/result.csv",
        "log": "/var/log/app.log",
    }


def test_cousin_steps_up_structurally():
    f = P("/proj/in") / T(t"{Param('stem')}.csv")
    assert f.cousin("../output", "output.csv") == P("/proj/output/output.csv")
    assert f.cousin("sub") == P("/proj/in/sub")
    with pytest.raises(PathOperationError):
        f.cousin("/abs")


def test_fragments_go_under_any_base():
    frag = P("cache") / "models" / "v1"
    bases = [P("/home/a/.myapp"), P(root)]
    placed = [frag.under(b) for b in bases]
    assert [str(p.pattern) for p in placed] == [
        "/home/a/.myapp/cache/models/v1",
        "{root}/cache/models/v1",
    ]
    assert placed[1].base == P(root)


def test_rebasing_re_applies_the_position_rule():
    x = Param("x")
    e = P("/srv") / x  # x is one segment below /srv
    with pytest.raises(ValueError):
        e.render(x="a/b")
    assert e.rebase(P(".")).render(x="a/b") == "a/b"  # at the head, x is a path


def test_rebase_falls_back_to_a_structural_prefix():
    literal = P("/x/a/b")  # built in one step: no derivation to follow
    assert literal.rebase(P("/x"), P("/y")) == P("/y/a/b")
    with pytest.raises(PathOperationError):
        literal.rebase(P("/elsewhere"), P("/y"))  # not under /elsewhere
    with pytest.raises(NotStaticError):
        (P(root) / "a").rebase(P(Param("other")), P("/y"))  # unknowable
    with pytest.raises(ValueError):
        literal.rebase(P("/y"))  # not built by a join


def test_derivations_survive_pickling():
    schema = (P(root) / "a.csv").sibling("schema.json")
    back = pickle.loads(pickle.dumps(schema))
    assert back == schema
    assert back.derivation.op == "sibling"
    assert back.rebase(P(root) / "a.csv", P("/z/a.csv")) == P("/z/schema.json")


# -- properties ---------------------------------------------------------------

# Operations whose expression arguments are recorded in the derivation, by
# position in the term tuple.
_DERIVED = {
    "join": (1, 2),
    "joinp": (1,),
    "parent": (1,),
    "with_suffix": (1,),
    "with_name": (1,),
    "with_stem": (1,),
    "relative_to": (1, 2),
    "sibling": (1,),
    "cousin": (1,),
}
_FAILS = (PathOperationError, TypeError, ValueError, NotStaticError)


def _try_build(term):
    try:
        return build(term)
    except _FAILS:
        return None


def _reachable(term):
    yield term
    for i in _DERIVED.get(term[0], ()):
        yield from _reachable(term[i])


def _substitute(term, old, new_term):
    """Replace every derivation-reachable subterm that builds to ``old``."""
    if _try_build(term) == old:
        return new_term
    out = list(term)
    for i in _DERIVED.get(term[0], ()):
        out[i] = _substitute(term[i], old, new_term)
    return tuple(out)


def _outcome(fn):
    try:
        return "ok", fn()
    except _FAILS as e:
        return "error", type(e)


@settings(max_examples=600, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(terms, terms, st.data())
def test_rebase_rederives_like_a_fresh_build(term, new_term, data):
    e = _try_build(term)
    new = _try_build(new_term)
    if e is None or new is None:
        return
    subs = [s for s in _reachable(term) if _try_build(s) is not None]
    old = build(data.draw(st.sampled_from(subs)))
    got = _outcome(lambda: e.rebase(old, new))
    expected = _outcome(lambda: build(_substitute(term, old, new_term)))
    assert got[0] == expected[0], (term, old, new_term, got, expected)
    if got[0] == "ok":
        assert got[1] == expected[1], (term, old, new_term)


@settings(max_examples=400, deadline=None)
@given(terms, st.sampled_from([ROOT, SEG, SUB, ANY]))
def test_a_join_is_its_base_joined_with_its_base_rel(term, param):
    left = _try_build(term)
    if left is None:
        return
    for right in (param, P(param)):
        e = _outcome(lambda right=right: left / right)
        if e[0] != "ok":
            continue
        joined = e[1]
        assert joined.base is left
        assert joined.base / joined.base_rel == joined
        assert joined.rebase(left) == joined


@settings(max_examples=400, deadline=None)
@given(terms, envs)
def test_bound_and_joined_parameter_tables_equal_a_fresh_walk(term, env):
    """Construction and bind keep parameter tables without re-walking the
    expression; they must equal the table a fresh walk computes."""
    from wend._expr import PathExpr

    e = _try_build(term)
    if e is None:
        return
    for x in (e, _outcome(lambda: e.bind(env))[1]):
        if isinstance(x, PathExpr):
            fresh = PathExpr(x.head, x.parts)
            assert x.params == fresh.params, term
            assert x.param_names == fresh.param_names, term
