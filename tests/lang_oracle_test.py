"""The language oracle (``lang_oracle``) against wend's own rendering, and
``relate(shared=False)`` against the oracle."""

import itertools

from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st
from overlap_test import PARTS, POOL, ab, expressions, s, sc
from relate_test import HEAD_OPS, pairs, renamed, rendered, under_one_head

from wend import P, Param, SubPath, T, relate
from wend._experimental.lang_oracle import (
    POSSIBLE,
    Unsupported,
    accepts,
    encode,
    language,
    relate_independent,
)
from wend._relate import lexically
from wend.errors import WendError


HOWS = ("same", "inside", "contains")


def renderings(e, limit=300):
    names = sorted(e.param_names)
    for combo in itertools.islice(itertools.product(*(POOL[k] for k in names)), limit):
        path = rendered(e, dict(zip(names, combo, strict=True)))
        if path is not None:
            yield path


@st.composite
def derived(draw):
    """Expressions under up to two deferred operations (parents, paths made
    relative, changed names, joins), with parts joined on."""
    e = draw(expressions())
    if draw(st.booleans()):
        e = e / draw(st.sampled_from([s, sc]))
    ops = [
        *HEAD_OPS,
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


def oracle(a, b):
    try:
        return relate_independent(a, b)
    except Unsupported:
        assume(False)


@settings(max_examples=300, deadline=None, suppress_health_check=list(HealthCheck))
@given(e=derived())
def test_a_language_holds_every_rendering(e):
    try:
        lang = language(e)
    except Unsupported:
        assume(False)
    for path in renderings(e):
        assert accepts(lang, encode(path)), (e.pattern, path)


ANY_PAIR = st.one_of(pairs(), renamed(), under_one_head())


@settings(max_examples=300, deadline=None, suppress_health_check=list(HealthCheck))
@given(pair=ANY_PAIR)
def test_every_possible_relation_renders(pair):
    # Whatever the oracle finds possible comes with bindings, and wend renders
    # them into paths that relate so.
    a, b = pair
    o = oracle(a, b)
    for how in HOWS:
        if o[how] in POSSIBLE:
            env = o.examples[how]
            pa, pb = a.render(env["a"]), b.render(env["b"])
            assert lexically(pa, pb) == how, (a.pattern, b.pattern, how, pa, pb)


@settings(max_examples=300, deadline=None, suppress_health_check=list(HealthCheck))
@given(pair=ANY_PAIR)
def test_never_and_always_hold_for_pooled_bindings(pair):
    a, b = pair
    o = oracle(a, b)
    ra, rb = set(renderings(a)), set(renderings(b))
    for how in HOWS:
        found = {lexically(pa, pb) == how for pa in ra for pb in rb}
        if o[how] == "never":
            assert True not in found, (a.pattern, b.pattern, how)
        if o[how] == "always":
            assert False not in found, (a.pattern, b.pattern, how)


@settings(max_examples=300, deadline=None, suppress_health_check=list(HealthCheck))
@given(pair=ANY_PAIR)
def test_relate_agrees_with_the_oracle(pair):
    # relate may say less than the oracle ("unknown", or "sometimes" where it
    # holds always), never something else.
    a, b = pair
    o = oracle(a, b)
    r = relate(a, b, shared=False)
    for how in HOWS:
        mine, exact = r[how], o[how]
        # "possible" holds at least once, "undecided" says nothing.
        allowed = {
            "unknown": {"never", "sometimes", "always", "possible", "undecided"},
            "never": {"never", "undecided"},
            "always": {"always", "possible", "undecided"},
            "sometimes": {"sometimes", "always", "possible", "undecided"},
        }[mine]
        assert exact in allowed, (a.pattern, b.pattern, how, mine, exact)


def test_the_oracle_follows_pathlib_on_names():
    x = Param("x")
    stem_dot = language((P("d") / T(t"{x}")).with_stem("."))
    # pathlib: the stem "." of a name without a suffix is refused; of "q." it
    # is ".."; of "q.t" it is "..t".
    assert accepts(stem_dot, encode("d/.."))
    assert accepts(stem_dot, encode("d/..t"))
    assert not accepts(stem_dot, encode("d/.t"))
    no_suffix = language((P("d") / x).with_suffix(""))
    assert accepts(no_suffix, encode("d/.x"))  # ".x" has no suffix
    assert accepts(no_suffix, encode("d/a.b"))  # from "a.b.c"
    assert not accepts(language((P("d") / x).with_suffix(".q")), encode("d/.q"))


def test_the_oracle_decides_what_relate_leaves_unknown():
    x = Param("x")
    # A stem is never empty, so no name changed to the suffix ".q" is ".q".
    a, b = (P("data") / x).with_suffix(".q"), P("data") / ".q"
    assert relate(a, b, shared=False).same == "unknown"
    assert relate_independent(a, b).same == "never"


def test_a_spec_does_not_narrow_a_value_without_builtin_values():
    # A value's __format__ may return any text: {n:03d} renders "zz", which
    # the oracle shows with a value of its own.
    n = Param("n")
    a, b = P("d") / T(t"{n:03d}"), P("d") / "zz"
    o = relate_independent(a, b)
    assert o.same == "sometimes"
    assert a.render(o.examples["same"]["a"]) == "d/zz"


def test_a_name_used_twice_is_decided_through_its_values():
    p, q, n, rel = Param("p"), Param("q"), Param("n"), SubPath("rel")
    # Not regular, so not a language of its own:
    try:
        language(P(T(t"{p}.a")) / T(t"{p}.b"))
    except Unsupported:
        pass
    else:
        raise AssertionError("a name used twice in one shape is not regular")
    # Uses of one shape render one text: here every text either use can take
    # is tried, so "never" is exact.
    a = P("d") / T(t"{p}-{q}") / T(t"{p}-{q}")
    assert relate_independent(a, P("d") / "a-b" / "a-c").same == "never"
    o = relate_independent(a, P("d") / "a-b" / "a-b")
    assert o.same == "possible"
    assert a.render(o.examples["same"]["a"]) == "d/a-b/a-b"
    a = P("d") / T(t"{n:03d}") / T(t"{n:03d}.b")
    assert relate_independent(a, P("d") / "007" / "7.b").same == "never"
    # Uses of different shapes need not: a value may format "007" with the
    # spec 03d and "7" without (rendering is a function of structure,
    # SEMANTICS §15.3, 1), so these meet.
    a = P("d") / T(t"{n:03d}") / T(t"{n}")
    o = relate_independent(a, P("d") / "007" / "7")
    assert o.same == "sometimes"
    assert a.render(o.examples["same"]["a"]) == "d/007/7"
    # Where a use can take infinitely many texts, the candidates are not all
    # of them, and none showing the relation proves nothing: here p is "A"
    # in one use and "B" in the other, neither of which holds, while "AB"
    # (with q "B" and r "A") does.
    p_, q_, r_ = Param("p"), Param("q"), Param("r")
    a = P("d") / T(t"{p_}.x") / T(t"{p_}.y")
    b = P("d") / T(t"A{q_}.x") / T(t"{r_}B.y")
    assert a.render(p="AB") == b.render(q="B", r="A")
    assert relate_independent(a, b).same != "never"
    # A SubPath used twice: d/{rel}/k/{rel} is below d/a/k/b where rel is
    # a/k/b/..., and never is it.
    a = P("d") / rel / "k" / rel
    o = relate_independent(a, P("d") / "a" / "k" / "b")
    assert (o.same, o.inside) == ("never", "possible")
