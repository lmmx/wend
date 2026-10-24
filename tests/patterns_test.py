"""wend._experimental.patterns: `PathExpr.pattern` read back into the same
normal form, with the expression's declarations, and into its principal
expression without them. Expressions come from the contract's term
strategy (tests/contract_test.py), which is built to be hostile."""

import pytest
from contract_test import build, envs, terms
from hypothesis import HealthCheck, assume, given, settings

from wend import P, Param, Segment, SubPath, T
from wend._experimental.patterns import PatternError, parse
from wend._expr import REL, Field, Seg
from wend.errors import InvalidBindingError, WendError


SETTINGS = settings(
    max_examples=1500, deadline=None, suppress_health_check=[HealthCheck.too_slow]
)


def effective(e, env):
    """The bindings ``e`` renders with: ``env``, then its declared defaults
    (which the principal expression does not have)."""
    return {**{n: p.default for n, p in e.params.items() if p.has_default}, **env}


def built(term):
    try:
        return build(term)
    except WendError, ValueError, TypeError:
        assume(False)


def _nodes(x):
    """Every expression and segment inside ``x``."""
    from dataclasses import fields, is_dataclass

    yield x
    if isinstance(x, tuple):
        for y in x:
            yield from _nodes(y)
    elif is_dataclass(x) and not isinstance(x, type):
        for f in fields(x):
            yield from _nodes(getattr(x, f.name))


def ambiguous(e) -> bool:
    """Whether ``e`` has one of the two shapes the printing cannot tell from
    another: (a) a relative expression whose first segment is a whole-segment
    field of a parameter of undeclared kind, which prints as a head
    parameter; (b) a segment-role field inside a mixed segment, which prints
    as a formatted value."""
    for n in _nodes(e):
        if (
            getattr(n, "head", None) is REL
            and n.parts
            and isinstance(n.parts[0], Seg)
            and len(n.parts[0].pieces) == 1
            and isinstance(n.parts[0].pieces[0], Field)
            and n.parts[0].pieces[0].role == "segment"
        ):
            return True
        if isinstance(n, Seg) and len(n.pieces) > 1:
            if any(isinstance(p, Field) and p.role == "segment" for p in n.pieces):
                return True
    return False


@SETTINGS
@given(terms)
def test_a_pattern_with_its_declarations_is_the_expression(term):
    # Exact, except where the expression has one of the two ambiguous shapes.
    e = built(term)
    assert parse(e.pattern, e.params) == e or ambiguous(e)


def test_ambiguity_a_head_parameter_or_a_first_segment():
    w = Param("w")
    head = P("") / w  # a head parameter: a path at the head
    first = (P("/anchored") / w).relative_to(P("/anchored"))  # a first segment
    assert head.pattern == first.pattern == "{w}"
    assert head != first
    assert head.render(w="a/b") == "a/b"
    with pytest.raises(InvalidBindingError):
        first.render(w="a/b")


def test_ambiguity_b_a_segment_field_or_a_value_field():
    d = Segment("d")
    segment = T(t"bk_{P(d).name}")  # .name of a segment keeps its validation
    value = P("") / T(t"bk_{Param('d')}")
    assert segment.pattern == value.pattern == "bk_{d}"
    with pytest.raises(InvalidBindingError):
        segment.render(d="..")
    assert value.render(d="..") == "bk_.."


@SETTINGS
@given(terms, envs)
def test_the_principal_expression_renders_what_the_expression_renders(term, env):
    # Outside the ambiguous shapes. At (a) there is no principal expression:
    # a head parameter takes "a/b" and refuses 0, a segment the reverse.
    e = built(term)
    assume(not ambiguous(e))
    try:
        s = e.render(env)
    except WendError, ValueError, TypeError:
        return
    assert parse(e.pattern).render(effective(e, env)) == s


@SETTINGS
@given(terms, envs)
def test_the_principal_expression_matches_what_the_expression_matches(term, env):
    # Its readings carry undeclared values ('7' where e reads 7), so the
    # claim is coverage: every path e reads, it reads too.
    e = built(term)
    assume(not ambiguous(e))
    try:
        s = e.render(env)
        readings = e.match_all(s, limit=4)
    except WendError, ValueError, TypeError:
        return
    if readings:
        assert parse(e.pattern).match_all(s, limit=4), (e.pattern, s)


def test_printing_forgets_declarations():
    # The same structure, three declarations: one pattern.
    a = P(Param("root")) / Param("x")
    b = P(Param("root")) / Param("x", type=int)
    c = P(Param("root")) / Param("x", choices={"p", "q"})
    assert a.pattern == b.pattern == c.pattern == "{root}/{x}"
    assert len({a, b, c}) == 3
    assert parse(b.pattern) == a  # the principal expression
    assert parse(b.pattern, b.params) == b


def test_kinds_have_positions_in_the_pattern():
    s = P(Param("root")) / SubPath("s") / "f"
    assert parse(s.pattern) == s  # {s...} can only be a SubPath


@pytest.mark.parametrize("bad", ["{x", "a}b", "join({x}, {y}", "a//b/{", "{x!}"])
def test_malformed_patterns_are_refused(bad):
    with pytest.raises((PatternError, ValueError, IndexError, SyntaxError)):
        parse(bad)


def test_text_operations_and_constants_read_back():
    root = Param("root")
    e = P(root) / T(t"{(P(root) / 'q.csv').stem}.bak") / T(t"v{3}{'k'!r}")
    assert parse(e.pattern, e.params) == e


def test_inferred_layouts_are_in_the_same_language():
    # Inference is the third representation: from paths to expressions. An
    # inferred layout reads back from its pattern and reads its own paths.
    from wend.infer import infer

    paths = [
        *(f"data/{d}/part-{i:03d}.parquet" for d in "ab" for i in range(5)),
        *(f"checkpoints/run_{r}/epoch_{e:02d}.pt" for r in (1, 2) for e in (1, 2, 3)),
        "README.md",
        *(f"logs/2026-10-{d}.log" for d in (21, 22, 23)),
    ]
    schema = infer(paths)
    for layout in schema.layouts:
        e = layout.expr
        assert parse(e.pattern, e.params) == e
        assert parse(e.pattern).pattern == e.pattern
    for p in paths:
        assert any(layout.expr.match(p) is not None for layout in schema.layouts)
