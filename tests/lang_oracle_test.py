"""The language oracle (``lang_oracle``) against wend's own rendering, and
``relate(shared=False)`` against the oracle."""

import itertools

from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st
from overlap_test import PARTS, POOL, ab, expressions, s, sc
from relate_test import HEAD_OPS, pairs, renamed, rendered, under_one_head

from wend import P, Param, SubPath, T, relate
from wend._languages import (
    NFA,
    POSSIBLE,
    Exhausted,
    Side,
    Unsupported,
    _count_dims,
    _lang,
    _least_walk,
    accepts,
    budget,
    chars,
    encode,
    language,
    relate_independent,
    relate_shared,
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


def oracle_shared(a, b):
    try:
        return relate_shared(a, b)
    except Unsupported:
        assume(False)


def own(e, env):
    return {k: v for k, v in env.items() if k in e.param_names}


def shared_renderings(a, b, limit=400):
    """Pairs of paths a and b render under one pooled binding, with each name
    both give a default also left unbound."""
    names = sorted(a.param_names | b.param_names)
    defaulted = [
        n
        for n in sorted(a.param_names & b.param_names)
        if a.params[n].has_default and b.params[n].has_default
    ]
    envs = itertools.islice(itertools.product(*(POOL[k] for k in names)), limit)
    for combo in envs:
        env = dict(zip(names, combo, strict=True))
        for k in range(len(defaulted) + 1):
            for unbound in itertools.combinations(defaulted, k):
                e = {n: v for n, v in env.items() if n not in unbound}
                pa, pb = rendered(a, e), rendered(b, e)
                if pa is not None and pb is not None:
                    yield pa, pb


@settings(max_examples=300, deadline=None, suppress_health_check=list(HealthCheck))
@given(pair=ANY_PAIR)
def test_every_possible_shared_relation_renders(pair):
    # Under shared bindings a witness is one binding of both sides.
    a, b = pair
    o = oracle_shared(a, b)
    for how in HOWS:
        if o[how] in POSSIBLE:
            env = o.examples[how]["a"]
            assert env == o.examples[how]["b"]
            pa, pb = a.render(own(a, env)), b.render(own(b, env))
            assert lexically(pa, pb) == how, (a.pattern, b.pattern, how, pa, pb)


@settings(max_examples=300, deadline=None, suppress_health_check=list(HealthCheck))
@given(pair=ANY_PAIR)
def test_shared_never_and_always_hold_for_pooled_bindings(pair):
    a, b = pair
    o = oracle_shared(a, b)
    found = {how: set() for how in HOWS}
    for pa, pb in shared_renderings(a, b):
        for how in HOWS:
            found[how].add(lexically(pa, pb) == how)
    for how in HOWS:
        if o[how] == "never":
            assert True not in found[how], (a.pattern, b.pattern, how)
        if o[how] == "always":
            assert False not in found[how], (a.pattern, b.pattern, how)


@settings(max_examples=300, deadline=None, suppress_health_check=list(HealthCheck))
@given(pair=ANY_PAIR)
def test_relate_agrees_with_the_shared_oracle(pair):
    a, b = pair
    o = oracle_shared(a, b)
    r = relate(a, b)
    for how in HOWS:
        mine, exact = r[how], o[how]
        allowed = {
            "unknown": {"never", "sometimes", "always", "possible", "undecided"},
            "never": {"never", "undecided"},
            "always": {"always", "possible", "undecided"},
            "sometimes": {"sometimes", "always", "possible", "undecided"},
        }[mine]
        assert exact in allowed, (a.pattern, b.pattern, how, mine, exact)


def test_shared_bindings_tie_a_name_across_sides():
    x, s_ = Param("x"), SubPath("s")
    # One value on both sides: d/{x}/a is never d/{x}/b, though under
    # independent bindings it is not d/{x}/b either; d/{x}/{x} is d/a/{x}
    # only where x is "a".
    assert relate_shared(P("d") / x / "a", P("d") / x / "b").same == "never"
    a, b = P("d") / x / x, P("d") / "a" / x
    o = relate_shared(a, b)
    assert o.same == "possible"
    env = o.examples["same"]["a"]
    assert a.render(env) == b.render(env) == "d/a/a"
    assert relate_shared(a, P("d") / "a" / "b").same == "never"
    # A SubPath of both: d/{s...}/k is below d/{s...}, never it. No finite
    # set of candidates settles that, but the shared prefix cancels: what
    # follows is k against nothing (`_cancelled`).
    o = relate_shared(P("d") / s_ / "k", P("d") / s_)
    assert (o.same, o.inside, o.contains) == ("never", "always", "never")
    root, p, sc = Param("root"), Param("p"), SubPath("sc")
    a = P(root) / T(t"{p}.txt") / "b" / "x.txt"
    b = P(root) / T(t"{p}.txt") / "b" / ".." / sc
    o = relate_shared(a, b)
    assert (o.same, o.inside, o.contains) == ("never", "never", "never")
    assert relate_shared(P("d") / x, P("d") / x).same == "always"
    # An expression against itself is the same wherever it renders, but this
    # one renders nowhere: p would be a segment's text and a parent of
    # //{p}/... at once. "always" is not shown by any binding, so not given.
    q_ = Param("q")
    e = (P("//") / x / q_ / "x.txt" / s_).relative_to(P(x)) / q_ / q_ / "x.txt"
    o = relate_shared(e, e)
    assert all(how in o.examples for how in HOWS if o[how] in POSSIBLE)
    # Different heads cancel nothing: {x}/a is inside {y} where y is x.
    y = Param("y")
    o = relate_shared(P(T(t"{x}")) / "a", P(T(t"{y}")))
    assert o.inside == "sometimes"
    assert o.same not in ("never", "always")
    # Tied, d/{x} is never {x}/q; but with x unbound each side renders its own
    # default, and both render d/q (SEMANTICS §15.1).
    xq, xd = Param("x", default="q"), Param("x", default="d")
    a, b = P("d") / xq, P(T(t"{xd}")) / "q"
    o = relate_shared(a, b)
    assert o.same == "possible"
    assert "x" not in o.examples["same"]["a"]
    assert a.render() == b.render() == "d/q"
    # Without the defaults, never.
    assert relate_shared(P("d") / x, P(T(t"{x}")) / "q").same == "never"


def test_counts_rule_out_what_no_candidate_settles():
    p, q, x, y = Param("p"), Param("q"), Param("x"), Param("y")
    # Read apart, //{p}{q} and //{p}-{q} meet; under one binding the two
    # segments differ in length by one, on every word (`_counted_never`).
    a, b = P("//") / T(t"{p}{q}"), P("//") / T(t"{p}-{q}")
    assert relate_shared(a, b).same == "never"
    assert relate_independent(a, b).same == "sometimes"
    # Either way round: the difference is then -1 on every walk, bounded above.
    assert relate_shared(b, a).same == "never"
    # {x}/a below a/{x} would need x's text one character longer on the left.
    o = relate_shared(P(T(t"{x}")) / "a", P("a") / T(t"{x}"))
    assert (o.inside, o.contains) == ("never", "never")
    o = relate_shared(P("a") / T(t"{x}"), P(T(t"{x}")) / "a")
    assert (o.inside, o.contains) == ("never", "never")
    assert o.same in POSSIBLE  # x = "a"
    # Counts compare uses of one shape only: {x}{x} as text and {x} alone in
    # a segment are two shapes, and a value may render them apart.
    o = relate_shared(P("d") / T(t"{x}{x}"), P("d") / x)
    assert o.same in POSSIBLE
    # Different names are not tied: {x}{y} is {y}, with x empty.
    o = relate_shared(P("d") / T(t"{x}{y}"), P("d") / y)
    assert o.same in POSSIBLE


def test_the_least_walk_has_no_bound_below_a_negative_cycle():
    # A walk weighs +100, then may go round a cycle of -1 as often as it
    # likes: its least weight is unbounded, not what the passes reached.
    n = NFA()
    n.start, end = n.new(), n.new()
    n.add(n.start, chars("a"), end)
    n.add(end, chars("b"), end)
    n.finals = {end}
    assert _least_walk(n, {(0, 0): 100, (1, 0): -1}) == float("-inf")
    assert _least_walk(n, {(0, 0): 100, (1, 0): 1}) == 100


def test_a_bool_used_twice_is_not_counted():
    # A bool renders each spec its own way: {f:>5} formats it as an int,
    # "    1", where {f} is "True", so the uses' lengths differ and comparing
    # them would be wrong. Its two values are decided outright instead.
    f, x = Param("f", type=bool), Param("x")
    e = P("d") / T(t"{f:>5}") / T(t"{f}") / T(t"{x}") / T(t"{x}")
    sd = Side("a")
    _lang(e, sd)
    dims = _count_dims({"a": (e, sd)}, frozenset())
    assert {d[1][1] for d in dims} == {"x"}
    o = relate_shared(e, P("d") / "    1" / "True" / "k" / "k")
    assert o.same in POSSIBLE


def test_an_exhausted_budget_is_never_an_answer():
    # Under every budget the oracle answers as without one, or raises
    # Exhausted: work cut short is never read as a value refused, or as a
    # language that is empty.
    p, q, f = Param("p"), Param("q"), Param("f", type=bool)
    cases = [
        (P("d") / T(t"x{p}"), P("d") / T(t"x{q}")),
        (P("d") / T(t"{f:>5}") / p, P("d") / "    1" / T(t"{f}")),
        (P("d") / T(t"{p}{q}"), P("d") / T(t"{q}-{p}")),
        ((P("d") / T(t"x{p}")).with_suffix(""), P("d") / "a"),
    ]

    def seen(r):  # an answer, with each value made by the oracle read as its texts
        def text(v):
            return sorted(v.texts.items(), key=repr) if hasattr(v, "texts") else v

        envs = {
            h: {side: {k: text(v) for k, v in env.items()} for side, env in e.items()}
            for h, e in r.examples.items()
        }
        return r.same, r.inside, r.contains, envs

    for a, b in cases:
        for decide in (relate_shared, relate_independent):
            whole = seen(decide(a, b))
            k, answered = 0, False
            while not answered:
                try:
                    with budget(k):
                        got = seen(decide(a, b))
                except Exhausted:
                    k += 1
                    continue
                answered = True
                assert got == whole, (k, a.pattern, b.pattern, got, whole)
            assert k > 0
