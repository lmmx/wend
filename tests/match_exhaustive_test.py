"""Matching checked by exhaustive enumeration over small value domains.

For each family, every binding in the product of the domains is rendered and
the results are grouped by path. Contract §7 then requires, for every path:

- completeness: every binding in its group is among ``match_all(path)``;
- soundness: every binding ``match_all`` returns renders to the path;
- ambiguity: ``match`` raises when the group has more than one binding.

Expressions that take the regex fast path must never produce a group with
more than one binding (the uniqueness argument in docs/SEMANTICS.md), and
must return exactly what the full search returns.
"""

import itertools

import pytest

from wend import AmbiguousMatchError, InvalidBindingError, P, Param, Segment, SubPath, T
from wend._match import _expr_plan


a, b, w = Param("a"), Param("b"), Param("w")
n, m = Param("n", type=int), Param("m", type=int)
s1, s2 = SubPath("s"), SubPath("t")
root, d, sa = Param("root"), Segment("d"), Segment("a")

FAMILIES = {
    "adjacent strings": (
        T(t"{a}{b}"),
        {"a": ["", "x", "xy", "y"], "b": ["", "x", "y", "yx"]},
    ),
    "separated strings": (
        T(t"{a}_{b}"),
        {"a": ["", "_", "a_", "b"], "b": ["", "_", "_c", "c"]},
    ),
    "adjacent ints": (T(t"{n:d}{m:d}"), {"n": list(range(13)), "m": list(range(13))}),
    "padded int then string": (
        T(t"{n:02d}{w}"),
        {"n": [0, 5, 12, 120], "w": ["", "1", "a", "12"]},
    ),
    "two subpaths": (
        P("r") / s1 / s2,
        {"s": [".", "a", "a/b"], "t": [".", "a", "a/b"]},
    ),
    "head then subpath": (
        root / s1 / "x",
        {"root": ["/", "/a", "a", "."], "s": [".", "a", "a/b"]},
    ),
    "fast path": (
        root / d / T(t"c_{n:03d}-{m:d}.{w}"),
        {
            "root": ["/r", "/r/s"],
            "d": ["x", "y"],
            "n": [0, 5, 999, 1000, -3],
            "m": [0, 10],
            "w": ["", "a.b", "txt"],
        },
    ),
    "repeated param": (
        P("/d") / sa / T(t"{sa}-{b}"),
        {"a": ["x", "x-y"], "b": ["", "y", "-y"]},
    ),
    "conversion and string": (
        T(t"{a!r}_{b}"),
        {"a": ["x", "_", "'", ""], "b": ["", "_", "z"]},
    ),
    "hex then string": (T(t"{n:x}{w}"), {"n": [10, 11, 171], "w": ["", "b", "ab"]}),
}


@pytest.mark.parametrize("family", sorted(FAMILIES))
def test_exhaustive_matching(family):
    expr, domains = FAMILIES[family]
    names = list(domains)
    groups: dict[str, list[dict]] = {}
    for values in itertools.product(*(domains[k] for k in names)):
        env = dict(zip(names, values, strict=True))
        try:
            path = expr.render(env)
        except InvalidBindingError:
            continue
        groups.setdefault(path, []).append(env)
    assert groups, "domain produced no valid bindings"
    fast = _expr_plan(expr) is not None
    for path, envs in groups.items():
        sols = expr.match_all(path)
        for env in envs:
            assert env in sols, (
                f"{family}: {env} renders to {path!r} but match_all gave {sols}"
            )
        for sol in sols:
            assert expr.render(sol) == path
        if len(envs) > 1:
            with pytest.raises(AmbiguousMatchError):
                expr.match(path)
        if fast:
            assert len(envs) == 1, (
                f"fast-path expression has an ambiguous path {path!r}: {envs}"
            )
            assert sols == expr.match_all(path, fast=False)
    assert fast == (family == "fast path"), f"{family}: fast path eligibility is {fast}"
