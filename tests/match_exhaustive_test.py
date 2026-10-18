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
v = Param("v")
q, r = Param("q", type=bool), Param("r", type=bool)

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
    # Regressions: an untyped "05" spec reads both str and int values (a str is
    # zero-filled on the right, an int after its sign), and a free string may
    # contain a newline.
    "untyped padded spec": (
        T(t"x{u:05}"),
        {
            "u": [
                *("", "ab", "ab0", "ab000", "abcdef", "00003", "-0001", "12345"),
                *(3, -1, 12345, 0, 123456),
            ]
        },
    ),
    "untyped padded spec, then a string": (
        T(t"{u:03}_{w}"),
        {"u": ["", "1", "1_", "10", "100", 1, -1, 100], "w": ["", "0", "_0"]},
    ),
    # Only numbers take a sign or grouping, so these untyped fields read ints
    # (issue #55); no str renders.
    "untyped signed int, then a string": (
        T(t"{u:+}{w}"),
        {"u": ["a", "", -1, 0, 5, 12, 125], "w": ["", "5", "+5", "a"]},
    ),
    "untyped grouped ints": (
        T(t"{u:,}{v:_}"),
        {"u": [0, 1, 1000, 10, "1"], "v": [0, 1, 1000, -1]},
    ),
    "newline in a string": (
        P("/r") / T(t"{w}.txt"),
        {"w": ["a\nb", "\n", "a", "a.txt\n"]},
    ),
    # bool fields: True and False under the empty spec, 1 and 0 under any
    # other (issue #55), next to fields whose texts look alike.
    "bool then string": (
        T(t"{q}{w}"),
        {"q": [True, False], "w": ["", "True", "e", "1", "False"]},
    ),
    "bool as a number": (
        T(t"{q:d}{n:d}_{r:>2}"),
        {"q": [True, False], "n": [0, 1, 10, 11], "r": [True, False]},
    ),
    "bool segment, bool as a float": (
        P("d") / Segment("q", type=bool) / T(t"{r:.1f}"),
        {"q": [True, False], "r": [True, False]},
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
    "a:03": (A_, "03", INTS),  # declared int: one reading, like 03d
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
    "b:03": (B_, "03", INTS),
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


# The same templates with a padded first field, whose fill a value or the
# literal after it may contain. None has a fast plan: every rendered binding
# must be found by the full search, and a path with several must be reported
# as ambiguous.

PADDED = {
    "u:03": (u, "03", ["", "1", "10", "100", "1000", "-1", 1, -1, 10, 100, 0]),
    "w:x<3": (w, "x<3", ["", "x", "1x", "x1", "xx", "1xx", "xx1x"]),
    "a:0<3": (A_, "0<3", [-1, 0, 1, 10, 100, 1000]),
    "a:-^4": (A_, "-^4", [-1, 0, 1, -10, 10]),
}


@pytest.mark.parametrize("first", sorted(PADDED))
def test_exhaustive_padded_field_templates(first):
    p1, spec1, dom1 = PADDED[first]
    for (second, (p2, spec2, dom2)), lit, (lead, trail) in itertools.product(
        SECOND.items(), LITERALS, [("", ""), ("r", ".t")]
    ):
        items = [
            lead,
            Interpolation(p1, p1.name, None, spec1),
            lit,
            Interpolation(p2, p2.name, None, spec2),
            trail,
        ]
        expr = P("/q") / Template(*items)
        groups = render_groups(expr, {p1.name: dom1, p2.name: dom2})
        assert not check_groups((lead, first, lit, second, trail), expr, groups)


# Padded fields (docs/SEMANTICS.md §7). For each spec, every str over a small
# alphabet up to one character wider than the width, and every int whose
# digits come from that alphabet, is rendered as an untyped, a str and an int
# field. A str that renders to a text is a substring of it, and an int's
# digits appear in its rendering, so up to that length the domains are
# closed: the full search must find exactly the values of the field's parse
# types that render to each text. The alphabets hold the fill character, a
# sign, and characters the fill can be confused with.

PAD_SPECS = {
    # spec: (width, alphabet, what an untyped field reads). Each spec is also
    # tried on str, int and bool fields.
    "03": (3, "01-a", {str, int}),  # issue #45: "0" flag, no alignment
    "+03": (3, "01-+", {int}),  # only a number formats with a sign
    "04,": (4, "01,", {int}),  # zero padding with grouping exceeds the width
    # Options only numbers take: an untyped field reads ints (issue #55).
    "+4": (4, "01-+ ", {int}),
    " 3": (3, "01- ", {int}),
    "=4": (4, "01- ", {int}),
    "x=+4": (4, "01-+x", {int}),
    "-#3": (3, "01-", {int}),
    ",": (5, "01,", {int}),
    "_": (5, "01_", {int}),
    "n": (3, "01-", {int}),
    "3": (3, "01- ", {str}),
    "x<3": (3, "01-x", {str}),
    "x>3": (3, "01-x", {str}),
    "x^3": (3, "01x", {str}),
    "x^4": (4, "01x", {str}),
    "0<3": (3, "01-", {str}),
    "0>3": (3, "01-", {str}),
    "0^4": (4, "01-", {str}),
    "<03": (3, "01-", {str}),
    ">03": (3, "01-", {str}),
    "^04": (4, "01-", {str}),
    "-<3": (3, "01-", {str}),
    "->3": (3, "01-", {str}),
    "1>3": (3, "01-", {str}),
    "1^4": (4, "01-", {str}),
    "0=3": (3, "01-", {str}),
    "-=3": (3, "01-", {str}),
    "1=3": (3, "01-", {str}),
    "03x": (3, "01-a", {int}),
    "a>3x": (3, "01-a", {int}),
    "a^4x": (4, "01a", {int}),
    "3c": (3, "01- q", {int}),  # c writes characters no int has
    "0>3c": (3, "01-a", {int}),
}


def pad_domain(spec, width, alphabet, types):
    longest = width + 1
    values: list = [False, True] if bool in types else []
    if str in types:
        values += [
            "".join(p)
            for k in range(longest + 1)
            for p in itertools.product(alphabet, repeat=k)
        ]
    if int in types:
        if spec.endswith("c"):
            values += [ord(c) for c in alphabet]
        else:
            base = 16 if spec.endswith("x") else 10
            digits = [c for c in alphabet if c in "0123456789abcdef"[:base]]
            values += sorted(
                {
                    sign * int("".join(p), base)
                    for k in range(1, longest + 1)
                    for p in itertools.product(digits, repeat=k)
                    for sign in (1, -1)
                }
            )
    return values, longest


def typed_set(solutions, name):
    return {(type(s[name]), s[name]) for s in solutions}


@pytest.mark.parametrize("spec", sorted(PAD_SPECS))
def test_exhaustive_padded_fields(spec):
    width, alphabet, untyped = PAD_SPECS[spec]
    rendered = 0
    for declared in (None, str, int, bool):
        types = untyped if declared is None else {declared}
        p = Param("u", type=declared)
        expr = P("d") / T(Template(Interpolation(p, "u", None, spec)))
        values, longest = pad_domain(spec, width, alphabet, types)
        groups: dict[str, set] = {}
        for v in values:
            try:
                path = expr.render(u=v)
            except InvalidBindingError:
                continue
            groups.setdefault(path, set()).add((type(v), v))
        rendered += len(groups)
        planned = _expr_plan(expr) is not None
        for path, want in groups.items():
            got = typed_set(expr.match_all(path, fast=False), "u")
            label = (spec, declared, path)
            if len(path) - len("d/") <= longest:
                assert got == want, label  # the domains are closed up to here
            else:
                assert want <= got, label
            for _, v in got:
                assert expr.render(u=v) == path, label
            if len(got) > 1:
                with pytest.raises(AmbiguousMatchError):
                    expr.match(path)
            else:
                assert typed_set([expr.match(path)], "u") == got, label
            if planned:
                assert len(got) == 1, label
                assert typed_set(expr.match_all(path), "u") == got, label
    assert rendered, f"{spec}: no value rendered"


# The limits of completeness (docs/SEMANTICS.md §7): a precision truncates a
# str, a float type rounds, and an untyped field does not read the floats
# that render under its spec. A path then has more bindings than the search
# returns, but every binding it does return must render to the path, and the
# reading named below must be among them.

xf = Param("x", type=float)
LIMITS = {
    # name: (expr, name, domain, readings of a path's text that are returned)
    "str precision": (
        T(t"k{u:.2}"),
        "u",
        ["".join(p) for k in range(5) for p in itertools.product("ab.", repeat=k)],
        lambda text: {(str, text)},
    ),
    "padded str precision": (
        T(t"k{u:_<4.2}"),
        "u",
        ["".join(p) for k in range(5) for p in itertools.product("a_", repeat=k)],
        lambda text: {(str, text.rstrip("_"))},
    ),
    "rounding float": (
        T(t"k{xf:.1f}"),
        "x",
        [i / 100 for i in range(-300, 300)] + [float("inf"), -0.0],
        lambda text: {(float, float(text))},
    ),
    "rounding percentage": (
        T(t"k{xf:.0%}"),
        "x",
        [i / 1000 for i in range(-100, 100)],
        lambda text: {(float, float(text[:-1]) / 100)},
    ),
    "int under a rounding float type": (
        T(t"k{n:.1e}"),
        "n",
        list(range(-300, 3000, 7)),
        lambda text: {(int, int(float(text)))},
    ),
    "floats under an untyped zero-padded spec": (
        T(t"k{u:05}"),
        "u",
        [i / 4 for i in range(-20, 20)] + [5, -5, "5.0", "005.0"],
        lambda text: {(str, text)},
    ),
    "floats under an untyped signed spec": (
        T(t"k{u:+}"),
        "u",
        [i / 4 for i in range(-20, 20)] + list(range(-5, 5)),
        lambda text: set(),
    ),
}


@pytest.mark.parametrize("family", sorted(LIMITS))
def test_limits_return_only_verified_bindings(family):
    expr, name, domain, reading = LIMITS[family]
    groups: dict[str, set] = {}
    for value in domain:
        try:
            path = expr.render({name: value})
        except InvalidBindingError:
            continue
        groups.setdefault(path, set()).add((type(value), value))
    missed = 0
    for path, want in groups.items():
        got = typed_set(expr.match_all(path, fast=False), name)
        for _, value in got:
            assert expr.render({name: value}) == path, (family, path, value)
        assert reading(path[1:]) <= got, (family, path, got)
        missed += len(want - got)
    assert missed, f"{family}: completeness holds here, so update §7's limits"
