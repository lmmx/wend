"""Compiling sets of expressions together (wend.compile_many)."""

import pytest
from contract_test import build, envs, terms
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from wend import (
    CompiledSet,
    InvalidBindingError,
    MissingBindingError,
    P,
    Param,
    PathOperationError,
    Segment,
    SubPath,
    T,
    compile_many,
)


root, split = Param("root"), Segment("split")
idx, total = Param("idx", type=int), Param("total", type=int)
stem, rel = Param("stem"), SubPath("rel")


def test_a_set_renders_like_each_expression():
    shard = P(root) / "data" / split / T(t"chunk_{idx:04d}-of-{total:04d}")
    exprs = [
        shard.with_suffix(".parquet"),
        shard.with_suffix(".idx"),
        P(root) / "README",
    ]
    many = compile_many(exprs)
    assert isinstance(many, CompiledSet)
    env = {"root": "/mnt", "split": "train", "idx": 7, "total": 100}
    assert many.render(env) == tuple(e.render(env) for e in exprs)
    assert many.render(root="/x", split="s", idx=1, total=2)[2] == "/x/README"
    assert many.many([env, {**env, "idx": 8}])[1][0].endswith(
        "chunk_0008-of-0100.parquet"
    )
    # shared work is emitted once
    assert many.source.count("format(_v") == 2


def test_named_sets_return_dicts():
    many = compile_many(
        {
            "src": P("src") / rel / T(t"{stem}.md"),
            "dst": P("site") / rel / T(t"{stem}.html"),
        }
    )
    assert many.render(rel="guide", stem="install") == {
        "src": "src/guide/install.md",
        "dst": "site/guide/install.html",
    }


def test_errors_are_those_of_the_first_failing_expression():
    exprs = [P(root) / "a", P(root) / split, P(root) / T(t"{idx:d}")]
    many = compile_many(exprs)
    with pytest.raises(MissingBindingError):
        many.render(root="/r")
    with pytest.raises(InvalidBindingError, match="split"):
        many.render(root="/r", split="a/b", idx="not an int")


_FAILS = (
    InvalidBindingError,
    PathOperationError,
    MissingBindingError,
    TypeError,
    ValueError,
)


def _outcome(fn):
    try:
        return "ok", fn()
    except _FAILS as e:
        return type(e).__name__, str(e)


@settings(max_examples=600, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(st.lists(terms, min_size=1, max_size=4), envs)
def test_a_compiled_set_equals_rendering_in_turn(ts, env):
    exprs = []
    for t in ts:
        try:
            exprs.append(build(t))
        except _FAILS:
            continue
    if not exprs:
        return
    try:
        many = compile_many(exprs)
    except _FAILS:  # conflicting declarations across the set
        return
    expected = _outcome(lambda: tuple(e.render(env) for e in exprs))
    assert _outcome(lambda: many.render(env)) == expected
