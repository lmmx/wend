"""Property tests: wend against an independent eager pathlib oracle.

Each test builds a random expression program twice: once with wend, once as a
function that computes the same operations eagerly with PurePosixPath on the
formatted strings. The core semantic claim checked here:

- if wend renders a value, the oracle renders the same value;
- if the oracle raises (pathlib rejects the operation), wend raises too;
- wend may reject bindings with InvalidBindingError only when some value would
  change the segment structure ("nice" values are never rejected).

Structural operations eliminate parameters (the parent of ``root / seg`` does
not depend on ``seg``). Their result is defined as the value pathlib gives for
every *valid* binding of the eliminated parameters, so equality with the
oracle is asserted for bindings that every intermediate expression accepts.
Evaluation is non-strict: a sub-expression discarded by a structural operation
(e.g. everything before an absolute join) is never evaluated.
"""

from __future__ import annotations

import string
from pathlib import PurePosixPath
from string.templatelib import Interpolation, Template

import pytest
from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st

from wend import (
    InvalidBindingError,
    Kind,
    NotInvertibleError,
    P,
    Param,
    PathOperationError,
    SubPath,
    T,
    WendError,
)


ROOT = Param("root")
SEG = Param("seg")
SUB = SubPath("sub")
N = Param("n", type=int)
W = Param("w", type=str)

TEMPLATES = [
    (lambda: T(t"chunk_{N:04d}.parquet"), lambda e: f"chunk_{e['n']:04d}.parquet"),
    (lambda: T(t"{W}.csv"), lambda e: f"{e['w']}.csv"),
    (lambda: T(t"{W}_{N}"), lambda e: f"{e['w']}_{e['n']}"),
    (lambda: T(t"{N:d}"), lambda e: f"{e['n']:d}"),
    (lambda: T(t"{W}.{N:02d}"), lambda e: f"{e['w']}.{e['n']:02d}"),
    (lambda: T(t"{W!r}"), lambda e: f"{e['w']!r}"),
    (lambda: T(t"x{N:x}"), lambda e: f"x{e['n']:x}"),
    # Padded fields whose fill characters values may contain (§7).
    (lambda: T(t"v{W:0<6}"), lambda e: f"v{e['w']:0<6}"),
    (lambda: T(t"{N:03}_{W:_^7}"), lambda e: f"{e['n']:03}_{e['w']:_^7}"),
    # A whole-segment interpolation is a path operand: joined, not formatted
    # into the string (so an empty value cannot make the path absolute).
    (lambda: T(t"{SEG}/{W}.txt"), lambda e: PurePosixPath(e["seg"]) / f"{e['w']}.txt"),
]

LITERALS = [
    "a",
    "b.txt",
    "c/d",
    "..",
    ".",
    "",
    "/abs",
    ".hid",
    "x.tar.gz",
    "a.",
    "e/./f",
]
SUFFIXES = ["", ".json", ".tar.gz", ".", "json", "a/b"]
NAMES = ["new.txt", "", ".", "a/b", "..", ".rc", "z"]
STEMS = ["st", "", ".s"]

starts = st.sampled_from(["root", "/", "/base", "rel", ".", "a/b.c", "x.tar.gz"])
steps = st.lists(
    st.one_of(
        st.tuples(st.just("lit"), st.sampled_from(LITERALS)),
        st.tuples(st.just("seg"), st.none()),
        st.tuples(st.just("sub"), st.none()),
        st.tuples(st.just("tpl"), st.integers(0, len(TEMPLATES) - 1)),
        st.tuples(st.just("parent"), st.none()),
        st.tuples(st.just("with_suffix"), st.sampled_from(SUFFIXES)),
        st.tuples(st.just("with_name"), st.sampled_from(NAMES)),
        st.tuples(st.just("with_stem"), st.sampled_from(STEMS)),
    ),
    max_size=6,
)

nice_segment = st.text(alphabet="abz019_-.", min_size=1, max_size=5).filter(
    lambda s: s not in (".", "..")
)
wild_segment = st.text(alphabet="ab./", max_size=5)
nice_env = st.fixed_dictionaries(
    {
        "root": st.sampled_from(["/mnt/x", "rel", "/", ".", "a/b", "//net", "/x.y/"]),
        "seg": nice_segment,
        "sub": st.lists(nice_segment, max_size=3).map(lambda xs: "/".join(xs) or "."),
        "n": st.integers(0, 70000),
        "w": nice_segment,
    }
)
wild_env = st.fixed_dictionaries(
    {
        "root": st.sampled_from(["/mnt/x", "rel", "", "a/../b", "/"]),
        "seg": wild_segment,
        "sub": st.sampled_from(["a/b", "/abs", "..", "a/../b", "", "."]),
        "n": st.integers(-5, 70000),
        "w": wild_segment,
    }
)


def build(start, prog, trace=None):
    """Return (wend expression or construction exception, oracle function)."""
    if start == "root":
        expr: object = P(ROOT)

        def oracle(e):
            return PurePosixPath(e["root"])

    else:
        expr = P(start)

        def oracle(e, s=start):
            return PurePosixPath(s)

    for op, arg in prog:
        prev = oracle
        if op == "lit":
            oracle = lambda e, prev=prev, a=arg: prev(e) / a  # noqa: E731
            make = lambda x, a=arg: x / a  # noqa: E731
        elif op == "seg":
            oracle = lambda e, prev=prev: prev(e) / e["seg"]  # noqa: E731
            make = lambda x: x / SEG  # noqa: E731
        elif op == "sub":
            oracle = lambda e, prev=prev: prev(e) / e["sub"]  # noqa: E731
            make = lambda x: x / SUB  # noqa: E731
        elif op == "tpl":
            tmake, tfmt = TEMPLATES[arg]
            oracle = lambda e, prev=prev, f=tfmt: prev(e) / f(e)  # noqa: E731
            make = lambda x, m=tmake: x / m()  # noqa: E731
        elif op == "parent":
            oracle = lambda e, prev=prev: prev(e).parent  # noqa: E731
            make = lambda x: x.parent  # noqa: E731
        else:
            oracle = lambda e, prev=prev, o=op, a=arg: getattr(prev(e), o)(a)  # noqa: E731
            make = lambda x, o=op, a=arg: getattr(x, o)(a)  # noqa: E731
        if isinstance(expr, Exception):
            continue
        if trace is not None:
            trace.append(expr)
        try:
            expr = make(expr)
        except (WendError, ValueError, TypeError) as exc:
            expr = exc
    return expr, oracle


def outcome(fn):
    try:
        return "ok", fn()
    except InvalidBindingError as e:
        return "invalid", e
    except (PathOperationError, ValueError) as e:
        return "op", e


def check(start, prog, env, *, nice):
    trace: list = []
    expr, oracle = build(start, prog, trace)
    want_kind, want = outcome(lambda: str(oracle(env)))
    inter = [outcome(lambda x=x: x.render(env))[0] for x in trace]
    valid_program = "invalid" not in inter and "op" not in inter
    if isinstance(expr, Exception):
        # A construction-time error claims the operation is invalid for every
        # binding that the intermediate expressions accept.
        if valid_program:
            assert want_kind == "op", (
                f"wend rejected at construction ({expr!r}) but pathlib gave {want!r}"
            )
        return None
    got_kind, got = outcome(lambda: expr.render(env))
    if not valid_program:
        # An intermediate expression has no value for these bindings. Structural
        # operations (parent, absolute joins) may discard that sub-expression,
        # and wend is non-strict: discarded parts are never evaluated. Only
        # require that nice bindings are never rejected.
        assert not (nice and "invalid" in inter), (
            f"{expr!r}: an intermediate rejected nice bindings {env}"
        )
        return expr, got_kind, got
    if got_kind == "ok":
        assert want_kind == "ok", f"{expr!r}: wend {got!r}, pathlib raised {want!r}"
        assert got == want, f"{expr!r} with {env}: wend {got!r} != pathlib {want!r}"
    elif got_kind == "op":
        assert want_kind == "op", (
            f"{expr!r}: wend raised {got!r}, pathlib gave {want!r}"
        )
    else:
        assert not nice, f"{expr!r} rejected nice bindings {env}: {got}"
    return expr, got_kind, got


SETTINGS = settings(
    max_examples=600, deadline=None, suppress_health_check=[HealthCheck.too_slow]
)


@SETTINGS
@given(starts, steps, nice_env)
def test_matches_pathlib_on_nice_values(start, prog, env):
    check(start, prog, env, nice=True)


@SETTINGS
@given(starts, steps, wild_env)
def test_never_disagrees_on_wild_values(start, prog, env):
    check(start, prog, env, nice=False)


@SETTINGS
@given(
    starts, steps, nice_env, st.sets(st.sampled_from(["root", "seg", "sub", "n", "w"]))
)
def test_partial_binding_commutes(start, prog, env, first):
    expr, _ = build(start, prog)
    assume(not isinstance(expr, Exception))
    direct = outcome(lambda: expr.render(env))
    staged = outcome(
        lambda: expr.bind({k: v for k, v in env.items() if k in first}).render(
            {k: v for k, v in env.items() if k not in first}
        )
    )
    assert direct[0] == staged[0], (expr, direct, staged)
    if direct[0] == "ok":
        assert direct[1] == staged[1]


def canonical_env(expr, env):
    out = {}
    for name, p in expr.params.items():
        v = env[name]
        if name == "root":
            v = str(PurePosixPath(v))
        elif name == "sub":
            v = str(PurePosixPath(v))
        out[name] = v
    return out


@SETTINGS
@given(starts, steps, nice_env)
def test_match_recovers_bindings(start, prog, env):
    expr, _ = build(start, prog)
    assume(not isinstance(expr, Exception))
    kind, rendered = outcome(lambda: expr.render(env))
    assume(kind == "ok")
    try:
        solutions = expr.match_all(rendered)
    except NotInvertibleError:
        return
    for sol in solutions:
        assert expr.render(sol) == rendered
    target = canonical_env(expr, env)
    assert target in solutions, (
        f"{expr!r}: {target} not among {solutions} for {rendered!r}"
    )


@SETTINGS
@given(starts, steps, nice_env)
def test_static_name_ops_agree_with_pathlib(start, prog, env):
    trace: list = []
    expr, oracle = build(start, prog, trace)
    assume(not isinstance(expr, Exception))
    assume(all(outcome(lambda x=x: x.render(env))[0] == "ok" for x in [*trace, expr]))
    p = oracle(env)
    for attr in ("name", "stem", "suffix"):
        assert getattr(expr, attr).render(env) == getattr(p, attr), attr


@pytest.mark.parametrize("ch", sorted(set(string.punctuation) - {"/"}))
def test_segment_punctuation_round_trips(ch):
    name = f"a{ch}b"
    e = P("/r") / Param("x")
    assert e.render(x=name) == f"/r/{name}"
    assert e.match(f"/r/{name}") == {"x": name}


@settings(max_examples=3000, deadline=None)
@given(st.text(alphabet="ab./", max_size=8))
def test_canonical_fast_path_equals_pathlib(s):
    from wend._expr import canonical

    assert canonical(s) == str(PurePosixPath(s))


@SETTINGS
@given(starts, steps, st.one_of(nice_env, wild_env))
def test_compiled_equals_interpreter(start, prog, env):
    expr, _ = build(start, prog)
    assume(not isinstance(expr, Exception))
    compiled = expr.compile()
    a = outcome(lambda: expr.render(env))
    b = outcome(lambda: compiled.render(env))
    assert a[0] == b[0], (expr, a, b)
    if a[0] == "ok":
        assert a[1] == b[1]
    else:
        assert type(a[1]) is type(b[1]) and str(a[1]) == str(b[1])


@SETTINGS
@given(starts, steps, st.one_of(nice_env, wild_env))
def test_match_fast_path_equals_search(start, prog, env):
    expr, _ = build(start, prog)
    assume(not isinstance(expr, Exception))
    kind, rendered = outcome(lambda: expr.render(env))
    assume(kind == "ok")
    try:
        slow = expr.match_all(rendered, fast=False)
    except NotInvertibleError:
        return
    fast = expr.match_all(rendered)
    assert fast == slow, (expr, fast, slow)


# -- Fast-path shapes (docs/SEMANTICS.md §8) ---------------------------------
#
# Expressions are generated from templates that mix integer fields (every
# supported presentation type, padded or not, typed or untyped), free string
# fields, fields padded with explicit fills, `choices` fields, whole-segment
# parameters, SubPath splices and literals chosen to sit next to fields'
# digit classes ("-", "a", "0", "f").
# Wherever an expression has a fast plan, its result must equal the full
# search, on rendered paths and on paths a few edits away from them.

FP_INTS = [Param(f"n{i}", type=int) for i in range(3)]
FP_UNTYPED = Param("u")
FP_STRS = [Param("fw"), Param("fv", type=str)]
FP_CHOICES = [
    Param("c0", choices={"a", "ab", "b"}),
    Param("c1", choices={"train", "test", "val"}),
    Param("c2", choices={"x", "x_1", ""}),
    Param("c3", choices={"0", "1a", "-", "f"}),
    Param("c4", type=str, choices={"gz", "tar.gz", "txt"}),
]
FP_BOOL = Param("fq", type=bool)
FP_BOOL_SPECS = ["", "d", "03", "x", "_>3", "+"]
FP_SEG = Param("fs", choices={"p", "q.r"})
FP_SUBS = [SubPath("s0"), SubPath("s1")]
FP_ROOTS = {"root": Param("root"), "abs": Param("abs", kind=Kind.ABSOLUTE)}

FP_INT_SPECS = ["", "d", "03d", "x", "02x", "X", "o", "03o", "b", "04b"]
FP_UNTYPED_SPECS = ["d", "x", "05", "02X", "o"]
# Padded specs, whose fill a value may contain (none has a fast plan).
FP_INT_SPECS += ["03", "0<3", "->3d", "x^4x"]
FP_UNTYPED_SPECS += ["03", "+03", "x<3", "0^4"]
# Options only numbers take, which an untyped field reads as an int (§7).
FP_UNTYPED_SPECS += ["+", ",", "=3", " ", "_", "#", "x=+4", "n"]
FP_STR_SPECS = ["03", "x<3", "_>4", "0^5"]
FP_LITERALS = ["_", "-", ".", "a", "f", "0", "9", "x", "-v", "a-", "_1", " ", "\n"]
FP_ALPHABET = "ab_-.0x1f \n"

fp_field = st.one_of(
    st.tuples(st.just("int"), st.integers(0, 2), st.sampled_from(FP_INT_SPECS)),
    st.tuples(st.just("untyped"), st.just(0), st.sampled_from(FP_UNTYPED_SPECS)),
    st.tuples(
        st.just("str"),
        st.integers(0, 1),
        st.one_of(st.just(""), st.sampled_from(FP_STR_SPECS)),
    ),
    st.tuples(st.just("choice"), st.integers(0, len(FP_CHOICES) - 1), st.just("")),
    st.tuples(st.just("bool"), st.just(0), st.sampled_from(FP_BOOL_SPECS)),
)
fp_lit = st.sampled_from(["", *FP_LITERALS])  # "" makes the fields adjacent
# A template segment: a leading literal, then fields each followed by a literal.
fp_template = st.tuples(
    fp_lit, st.lists(st.tuples(fp_field, fp_lit), min_size=1, max_size=3)
)
fp_part = st.one_of(
    st.tuples(st.just("tpl"), fp_template),
    st.tuples(st.just("lit"), st.sampled_from(["a", "x.y", "..", "0"])),
    st.tuples(st.just("seg"), st.none()),
    st.tuples(st.just("sub"), st.integers(0, 1)),
)
fp_start = st.sampled_from([".", "/", "//", "/base", "root", "abs"])


def fp_build(start, parts):
    expr = P(FP_ROOTS[start]) if start in FP_ROOTS else P(start)
    for kind, arg in parts:
        if kind == "lit":
            expr = expr / arg
        elif kind == "seg":
            expr = expr / FP_SEG
        elif kind == "sub":
            expr = expr / FP_SUBS[arg]
        else:
            lead, fields = arg
            items: list = [lead]
            for (what, i, spec), lit in fields:
                if what == "int":
                    p = FP_INTS[i]
                elif what == "choice":
                    p = FP_CHOICES[i]
                elif what == "str":
                    p = FP_STRS[i]
                elif what == "bool":
                    p = FP_BOOL
                else:
                    p = FP_UNTYPED
                items += [Interpolation(p, p.name, None, spec), lit]
            expr = expr / T(Template(*items))
    return expr


fp_text = st.text(alphabet=FP_ALPHABET, max_size=4)
fp_int = st.one_of(
    st.integers(-300, 300), st.sampled_from([0, -1, 10, -10, 255, -255, 4096])
)
fp_env = st.fixed_dictionaries(
    {
        "root": st.sampled_from(["/mnt/x", "rel", "/", "//", ".", "a/b", "//net", "0"]),
        "abs": st.sampled_from(["/", "//", "/a", "//n/b", "/0/x"]),
        **{p.name: fp_int for p in FP_INTS},
        "u": st.one_of(fp_int, fp_text),
        "fw": fp_text,
        "fv": fp_text,
        **{p.name: st.sampled_from(sorted(p.choices)) for p in FP_CHOICES},
        "fs": st.sampled_from(["p", "q.r"]),
        "fq": st.booleans(),
        "s0": st.sampled_from([".", "a", "a/b", "0/x", "..", "x.y"]),
        "s1": st.sampled_from([".", "b", "a/.."]),
    }
)


def typed(solutions):
    """Solutions with each value's type, so that 1 and True (or 1.0) differ."""
    return [{k: (type(v), v) for k, v in s.items()} for s in solutions]


def check_fast_equals_search(expr, path):
    from wend._match import _expr_plan

    try:
        slow = expr.match_all(path, fast=False)
    except NotInvertibleError:
        return None
    fast = expr.match_all(path)
    assert typed(fast) == typed(slow), (expr, path, fast, slow)
    planned = _expr_plan(expr) is not None
    if planned:
        assert len(slow) <= 1, (expr, path, slow)
    return planned


def mutate(path, edits):
    for op, i, ch in edits:
        i = i % (len(path) + 1)
        if op == 0:
            path = path[:i] + ch + path[i:]
        elif op == 1:
            path = path[:i] + path[i + 1 :]
        else:
            path = path[:i] + ch + path[i + 1 :]
    return path or "."


fp_edits = st.lists(
    st.tuples(
        st.integers(0, 2), st.integers(0, 60), st.sampled_from(FP_ALPHABET + "/")
    ),
    min_size=1,
    max_size=3,
)

FP_SETTINGS = settings(
    max_examples=1500, deadline=None, suppress_health_check=[HealthCheck.too_slow]
)


@FP_SETTINGS
@given(fp_start, st.lists(fp_part, max_size=4), fp_env, st.lists(fp_edits, max_size=3))
def test_fast_plan_equals_search_on_new_shapes(start, parts, env, edits):
    try:
        expr = fp_build(start, parts)
    except WendError, ValueError, TypeError:
        return
    kind, rendered = outcome(lambda: expr.render(env))
    if kind != "ok":
        rendered = "/base/a"  # unrenderable bindings still give edits to match
    check_fast_equals_search(expr, rendered)
    for e in edits:
        check_fast_equals_search(expr, mutate(rendered, e))


# -- Padded fields (docs/SEMANTICS.md §7) ------------------------------------
#
# Random standard specs (fill and alignment, sign, "#", the 0 flag, width,
# grouping, type) on untyped, str and int fields between literals. Whenever a
# value renders and its type is one the field reads, the full search must
# return it; every value the search returns must have such a type and render
# to the path; and the fast path must agree with the search.

pad_lit = st.sampled_from(["", "a", "0", "-", "x", "_", "1"])


@st.composite
def padded_cases(draw):
    """(declared type, spec parts, value, lead, trail), with spec options the
    value's type accepts (a str takes no sign, "#", grouping or "=")."""
    declared = draw(st.sampled_from([None, str, int, bool]))
    is_str = declared is str or (declared is None and draw(st.booleans()))
    if is_str:
        value = draw(st.text(alphabet="01-x_ a+,", max_size=6))
    elif declared is bool:
        value = draw(st.booleans())
    else:
        value = draw(st.integers(-3000, 3000))
    parts = (
        draw(st.sampled_from(["", "0", "x", "-", "1", " ", "_"])),  # fill, if aligned
        draw(st.sampled_from(["", "<", ">", "^"] + ([] if is_str else ["="]))),
        "" if is_str else draw(st.sampled_from(["", "+", "-", " ", "#", "-#"])),
        draw(st.booleans()),  # the 0 flag
        draw(st.one_of(st.none(), st.integers(1, 6))),
        "" if is_str else draw(st.sampled_from(["", ",", "_"])),
        draw(st.sampled_from(["", "s"] if is_str else ["", "d", "x"])),
    )
    return declared, parts, value, draw(pad_lit), draw(pad_lit)


def pad_reads(parts, declared):
    """The types a field reads (§7), from the parts of its spec."""
    _, align, sign, zero, width, grouping, kind = parts
    if declared is not None:
        return {declared}
    if kind:
        return {str} if kind == "s" else {int}
    if sign or grouping or align == "=":  # no str takes these ("#" is a sign here)
        return {int}
    return {str, int} if zero and width is not None and not align else {str}


@settings(
    max_examples=1000,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.filter_too_much],
)
@given(padded_cases())
def test_padded_fields_match_every_reading(case):
    declared, parts, value, lead, trail = case
    fill, align, sign, zero, width, grouping, kind = parts
    spec = (
        (fill + align if align else "")
        + sign
        + ("0" if zero else "")
        + ("" if width is None else str(width))
        + grouping
        + kind
    )
    p = Param("u", type=declared)
    expr = P("/d") / T(Template(lead, Interpolation(p, "u", None, spec), trail))
    kind_, rendered = outcome(lambda: expr.render(u=value))
    assume(kind_ == "ok")
    reads = pad_reads(parts, declared)
    slow = expr.match_all(rendered, fast=False)
    for sol in slow:
        assert type(sol["u"]) in reads, (spec, declared, rendered, slow)
        assert expr.render(sol) == rendered
    if type(value) in reads:
        assert (type(value), value) in {(type(s["u"]), s["u"]) for s in slow}, (
            spec,
            declared,
            rendered,
            slow,
        )
    assert typed(expr.match_all(rendered)) == typed(slow)
