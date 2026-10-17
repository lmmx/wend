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

import pytest
from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st

from wend import (
    InvalidBindingError,
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
