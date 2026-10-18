"""Matching checked by exhaustive enumeration over small value domains.

For each family, every binding in the product of the domains is rendered and
the results are grouped by path. Contract §7 then requires, for every path:

- completeness: every binding in its group is among ``match_all(path)``;
- soundness: every binding ``match_all`` returns renders to the path;
- ambiguity: ``match`` raises when the group has more than one binding.

Expressions that take the regex fast path must never produce a group with
more than one binding (the uniqueness argument in docs/SEMANTICS.md §8), and
must return exactly what the full search returns.
"""

import itertools
from string.templatelib import Interpolation, Template

import pytest

from wend import AmbiguousMatchError, InvalidBindingError, P, Param, Segment, SubPath, T
from wend._match import _expr_plan


a, b, w = Param("a"), Param("b"), Param("w")
n, m, k = Param("n", type=int), Param("m", type=int), Param("k", type=int)
u = Param("u")
s1, s2 = SubPath("s"), SubPath("t")
root, d, sa = Param("root"), Segment("d"), Segment("a")
split = Param("c", choices={"train", "test", "val"})
nested = Param("c", choices={"a", "a_b", "b"})
exts = Param("c", choices={"gz", "tar.gz", "txt"})
flat_exts = Param("c", choices={"gz", "txt", "csv"})
letters = Param("c", choices={"a", "b"})

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
    # One SubPath after a fixed head, with a fixed number of segments after it.
    "subpath fixed tail": (
        P("/r") / s1 / "x" / T(t"c_{n:02d}.bin"),
        {"s": [".", "a", "x", "a/x", "x/x"], "n": [0, 5, 12, -3]},
    ),
    "subpath then string": (
        P("r") / s1 / T(t"{w}.py"),
        {"s": [".", "a", "a.py", "a/b"], "w": ["", "a", "b.py", "."]},
    ),
    "subpath last": (
        P("/r") / d / s1,
        {"d": ["x", "y"], "s": [".", "x", "x/y", "y/x"]},
    ),
    "subpath only": (P(s1), {"s": [".", "a", "a/b", "b"]}),
    # Integer presentation types: a field ends at a literal outside its digit
    # class, or (read from the right) starts after one that is not "-" either.
    "int bases": (
        T(t"{n:x}-{m:03o}.{k:b}"),
        {"n": [-17, -1, 0, 10, 255], "m": [-8, 0, 7, 64], "k": [-2, 0, 1, 5]},
    ),
    "hex before a hex letter": (
        T(t"{n:x}a{m:d}"),
        {"n": [-1, 0, 10, 171], "m": [-1, 0, 12]},
    ),
    "hex with a hex-letter literal": (
        T(t"{n:x}b{m:x}"),
        {"n": [0xA, 0xAB, 0], "m": [0x1, 0xB1, 0xB]},
    ),
    # A free string field before other fields, bounded from the right.
    "string before int": (
        T(t"{w}_{n:03d}.pt"),
        {"w": ["", "a", "_", "a_001", "-"], "n": [-5, 0, 7, 1000]},
    ),
    "string, dash, int": (T(t"{w}-{n:d}"), {"w": ["", "x", "x-"], "n": [-5, 5]}),
    # choices: finitely many alternatives, unique when no two of them can
    # both be followed (or preceded) by the adjacent literal.
    "choices then string": (
        T(t"{split}_{w}"),
        {"c": ["train", "test", "val"], "w": ["", "_", "test", "a_b"]},
    ),
    "nested choices then string": (
        T(t"{nested}_{w}"),
        {"c": ["a", "a_b", "b"], "w": ["", "b", "b_x", "x"]},
    ),
    "string then suffix choices": (
        T(t"{w}.{exts}"),
        {"w": ["a", "a.tar", "b"], "c": ["gz", "tar.gz", "txt"]},
    ),
    "string then distinct choices": (
        T(t"{w}.{flat_exts}"),
        {"w": ["a", "a.gz", ""], "c": ["gz", "txt", "csv"]},
    ),
    "adjacent prefix-free choices": (
        T(t"{letters}{n:d}"),
        {"c": ["a", "b"], "n": [-1, 0, 12]},
    ),
    # Regressions: an untyped "05" spec formats (and parses) a str, and a free
    # string may contain a newline. (Values are 5+ characters: a shorter str
    # is zero-filled on the right, which the str inversion does not undo.)
    "untyped padded spec": (
        T(t"x{u:05}"),
        {"u": ["abcdef", "00003", "-0001", "12345"]},
    ),
    "newline in a string": (
        P("/r") / T(t"{w}.txt"),
        {"w": ["a\nb", "\n", "a", "a.txt\n"]},
    ),
}

FAST = {
    "fast path",
    "subpath fixed tail",
    "subpath then string",
    "subpath last",
    "subpath only",
    "int bases",
    "hex before a hex letter",
    "string before int",
    "choices then string",
    "string then distinct choices",
    "adjacent prefix-free choices",
    "newline in a string",
}


def render_groups(expr, domains):
    names = list(domains)
    groups: dict[str, list[dict]] = {}
    for values in itertools.product(*(domains[k] for k in names)):
        env = dict(zip(names, values, strict=True))
        try:
            path = expr.render(env)
        except InvalidBindingError:
            continue
        groups.setdefault(path, []).append(env)
    return groups


def check_groups(label, expr, groups):
    fast = _expr_plan(expr) is not None
    for path, envs in groups.items():
        sols = expr.match_all(path)
        for env in envs:
            assert env in sols, (
                f"{label}: {env} renders to {path!r} but match_all gave {sols}"
            )
        for sol in sols:
            assert expr.render(sol) == path
        if len(envs) > 1:
            with pytest.raises(AmbiguousMatchError):
                expr.match(path)
        if fast:
            assert len(envs) == 1, (
                f"{label}: fast-path expression has an ambiguous path {path!r}: {envs}"
            )
            assert sols == expr.match_all(path, fast=False)
    return fast


@pytest.mark.parametrize("family", sorted(FAMILIES))
def test_exhaustive_matching(family):
    expr, domains = FAMILIES[family]
    groups = render_groups(expr, domains)
    assert groups, "domain produced no valid bindings"
    fast = check_groups(family, expr, groups)
    assert fast == (family in FAST), f"{family}: fast path eligibility is {fast}"


# Every segment template "lead {f1} lit {f2} trail" over the field kinds below
# and literals that touch their digit classes, the "-" sign, and the choices'
# prefixes and suffixes. For each template with a fast plan, every rendered
# path must have one binding, and the plan must return the full search's
# result.

A_, B_ = Param("a", type=int), Param("b", type=int)
INTS = [-17, -1, 0, 10, 255]
FIRST = {
    "a:d": (A_, "d", INTS),
    "a:03d": (A_, "03d", INTS),
    "a:x": (A_, "x", INTS),
    "a:02X": (A_, "02X", INTS),
    "a:o": (A_, "o", INTS),
    "a:03b": (A_, "03b", INTS),
    "w": (w, "", ["", "a", "-", "a-1", "0", "x_"]),
    "c": (Param("c", choices={"a", "ab", "b", ""}), "", ["", "a", "ab", "b"]),
    "e": (Param("e", choices={"x", "x-1", "1"}), "", ["x", "x-1", "1"]),
}
SECOND = {
    "b:d": (B_, "d", INTS),
    "b:03d": (B_, "03d", INTS),
    "b:x": (B_, "x", INTS),
    "b:o": (B_, "o", INTS),
    "v": (Param("v"), "", ["", "a", "-", "1", "a_b"]),
    "c": FIRST["c"],
    "e": FIRST["e"],
}
LITERALS = ["", "-", "_", "a", "1", "0", "x", "-1", "a-"]


@pytest.mark.parametrize("first", sorted(FIRST))
def test_exhaustive_two_field_templates(first):
    p1, spec1, dom1 = FIRST[first]
    planned = 0
    for (second, (p2, spec2, dom2)), lit, (lead, trail) in itertools.product(
        SECOND.items(), LITERALS, [("", ""), ("r", ".t")]
    ):
        if p1 is p2:
            continue
        items = [
            lead,
            Interpolation(p1, p1.name, None, spec1),
            lit,
            Interpolation(p2, p2.name, None, spec2),
            trail,
        ]
        expr = P("/q") / Template(*items)
        if _expr_plan(expr) is None:
            continue  # the full search is the reference: nothing to compare
        planned += 1
        groups = render_groups(expr, {p1.name: dom1, p2.name: dom2})
        check_groups((lead, first, lit, second, trail), expr, groups)
    assert planned, f"no template starting with {first} has a fast plan"
