"""`PathExpr.declares` (docs/SEMANTICS.md §10.1): the declared conditions as
atoms per phase and bases, how operations carry them, what a union declares,
and the effect verbs computed from them."""

import pytest
from contract_test import build, terms
from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st

from wend import (
    Absent,
    AnyPath,
    Creatable,
    Dir,
    Exists,
    File,
    Listable,
    P,
    Param,
    Readable,
    Step,
    T,
    Under,
    Writable,
)
from wend.conditions import NONE, Declarations
from wend.errors import WendError


CONDS = [Exists, Absent, File, Dir, Readable, Writable, Creatable, Listable]
SETTINGS = settings(
    max_examples=600, deadline=None, suppress_health_check=[HealthCheck.too_slow]
)
root, name = Param("root"), Param("name")


def test_each_condition_declares_its_atom_in_its_phase():
    e = (P(root) / T(t"{name}.csv")).requires(File, Exists, Readable)
    e = e.ensures(Exists, Writable)
    assert e.declares == Declarations(
        frozenset({"file", "exists", "read"}), frozenset({"exists", "write"}), ()
    )
    assert (P(root) / "x").declares == NONE


def test_bases_of_either_phase_are_listed_once_in_order():
    e = (P("/srv") / AnyPath("rel")).requires(Under("/srv"), Readable)
    e = e.ensures(Under("/srv"), Under("/"))
    assert [b.pattern for b in e.declares.under] == ["/srv", "/"]


def test_bind_moves_the_bases_and_keeps_the_atoms():
    e = (P(root) / AnyPath("rel")).requires(Under(P(root)), Readable)
    b = e.bind(root="/srv")
    assert b.declares.requires == e.declares.requires
    assert [x.pattern for x in b.declares.under] == ["/srv"]


def test_rebase_moves_a_base_built_from_old_and_keeps_another():
    e = (P("/srv/static") / AnyPath("rel")).requires(Under("/srv/static"), Under("/"))
    moved = e.rebase(P("/srv/static"), P("/tmp"))
    assert [x.pattern for x in moved.declares.under] == ["/tmp", "/"]


def test_a_union_declares_what_every_alternative_declares():
    a = (P(root) / "a").requires(File, Exists, Readable).ensures(Exists)
    b = (P(root) / "b").requires(Exists, Readable, Under("/"))
    assert (a | b).declares == Declarations(
        frozenset({"exists", "read"}), frozenset(), ()
    )


# -- verbs ---------------------------------------------------------------------


def old_verbs(conds):
    """Step.effects' verbs as computed from conditions before §10.1."""
    effects = {
        Readable: "read",
        Writable: "write",
        Creatable: "create",
        Listable: "list",
    }
    if conds is None:
        return frozenset()
    pre, post = conds.requires, conds.ensures
    verbs = {effects[c] for c in (*pre, *post) if c in effects}
    if Exists in post and Exists not in pre:
        verbs.add("create")
    if Absent in post and Absent not in pre:
        verbs.add("delete")
    return frozenset(verbs)


declarations = st.tuples(
    st.lists(st.sampled_from(CONDS), max_size=4, unique=True),
    st.lists(st.sampled_from(CONDS), max_size=4, unique=True),
)


@SETTINGS
@given(declarations)
def test_verbs_are_what_step_effects_reported_from_conditions(d):
    pre, post = d
    try:
        e = (P(root) / "x").requires(*pre).ensures(*post)
    except WendError:
        return  # contradictory in one phase: refused when declared
    assert e.declares.verbs == old_verbs(e.conditions)
    assert Step(p=e).effects()[0].verbs == e.declares.verbs


def test_declaring_more_can_remove_create():
    made = (P(root) / "x").ensures(Exists)
    assert "create" in made.declares.verbs
    assert "create" not in made.requires(Exists).declares.verbs


# -- propagation over the contract's terms ------------------------------------

KEEP = ["bind", "rebase", "tag", "P"]
DROP = [
    lambda e: e.parent,
    lambda e: e.with_suffix(".x"),
    lambda e: e.with_name("n.txt"),
    lambda e: e.with_stem("s"),
    lambda e: e.sibling("s.json"),
    lambda e: e.cousin("../o", "c.csv"),
    lambda e: e / "x",
    lambda e: e.under(P("/b")),
]


def declared(term, pre, post, base):
    try:
        e = build(term)
        if base:
            e = e.requires(Under("/"))
        return e.requires(*pre).ensures(*post)
    except WendError, ValueError, TypeError:
        assume(False)


@SETTINGS
@given(terms, declarations, st.booleans(), st.integers(0, len(DROP) - 1))
def test_every_other_operation_declares_nothing(term, d, base, i):
    e = declared(term, *d, base)
    try:
        out = DROP[i](e)
    except WendError, ValueError, TypeError:
        return
    assert out.declares == NONE


@SETTINGS
@given(terms, declarations, st.booleans(), st.sampled_from(KEEP))
def test_bind_rebase_tag_and_p_keep_the_atoms(term, d, base, op):
    e = declared(term, *d, base)
    names = sorted(e.params)
    try:
        if op == "bind":
            assume(names)
            env = {names[0]: "v"}
            out = e.bind(env)
            want = []
            for b in e.declares.under:
                m = b.bind(env)
                if m not in want:
                    want.append(m)
            assert list(out.declares.under) == want
        elif op == "rebase":
            out = e.rebase(P("/"), P("/elsewhere"))
        elif op == "tag":
            out = e.tag(k="v")
        else:
            out = P(e)
    except WendError, ValueError, TypeError:
        return
    assert out.declares.requires == e.declares.requires
    assert out.declares.ensures == e.declares.ensures
    if op in ("tag", "P"):
        assert out.declares == e.declares


EXPECTED = {
    Exists: "exists",
    Absent: "absent",
    File: "file",
    Dir: "dir",
    Readable: "read",
    Writable: "write",
    Creatable: "create",
    Listable: "list",
}


@pytest.mark.parametrize("cond", CONDS, ids=repr)
def test_every_condition_declares_the_atom_semantics_names(cond):
    e = (P(root) / "x").requires(cond).ensures(cond)
    assert e.declares.requires == e.declares.ensures == {EXPECTED[cond]}
