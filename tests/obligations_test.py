"""wend._experimental.obligations: effect verbs computed from declared atoms
alone, and declared state discharged across an effect graph."""

from hypothesis import given, settings
from hypothesis import strategies as st

from wend import Step
from wend._experimental.effects import EffectGraph
from wend._experimental.obligations import obligations, verbs
from wend._experimental.typed import (
    Absent,
    Creatable,
    Dir,
    Exists,
    File,
    Listable,
    P,
    Param,
    Readable,
    StepSpec,
    T,
    Uses,
    Writable,
    facts,
)
from wend.conditions import _verbs
from wend.errors import PathOperationError


CONDS = [Exists, Absent, File, Dir, Readable, Writable, Creatable, Listable]


@settings(max_examples=500, deadline=None)
@given(
    pre=st.lists(st.sampled_from(CONDS), max_size=4, unique=True),
    post=st.lists(st.sampled_from(CONDS), max_size=4, unique=True),
)
def test_effect_verbs_are_a_function_of_the_declared_atoms(pre, post):
    # The effect graph reads Step.effects; Step.effects reads conditions.
    # Both agree with verbs() of the atoms the static types carry.
    try:
        e = (P(Param("root")) / "x").requires(*pre).ensures(*post)
    except PathOperationError:
        return  # a contradiction: rejected when declared
    assert verbs(facts(e).atoms) == _verbs(e.conditions)


root, day = Param("root"), Param("day")


class Ingest(StepSpec):
    upload = Uses(
        (P(root) / "inbox" / T(t"{day}.csv")).requires(File, Exists, Readable)
    )
    raw = Uses(
        (P(root) / "raw" / T(t"{day}.csv"))
        .requires(Absent, Creatable)
        .ensures(File, Exists)
    )


class Clean(StepSpec):
    raw = Uses((P(root) / "raw" / T(t"{day}.csv")).requires(File, Exists, Readable))
    # ensures Exists but not File: it might leave a directory
    clean = Uses(
        (P(root) / "clean" / T(t"{day}.parquet"))
        .requires(Absent, Creatable)
        .ensures(Exists)
    )


class Report(StepSpec):
    clean = Uses(
        (P(root) / "clean" / T(t"{day}.parquet")).requires(File, Exists, Readable)
    )
    folder = Uses((P(root) / "clean").requires(Dir, Exists, Listable))


def graph():
    steps = {"ingest": Ingest.step(), "clean": Clean.step(), "report": Report.step()}
    return EffectGraph(steps, shared=True)


def by_port(obs):
    return {f"{o.port.step}.{o.port.name}": o for o in obs}


def test_an_input_nothing_supplies_is_owed_by_the_world():
    o = by_port(obligations(graph()))["ingest.upload"]
    assert o.status == "external"
    assert o.needs == {"file", "exists"}


def test_a_supplier_ensuring_the_required_state_discharges_it():
    o = by_port(obligations(graph()))["clean.raw"]
    assert o.status == "discharged"
    assert [s.edge.producer.step for s in o.supplies] == ["ingest"]


def test_a_supplier_ensuring_less_than_required_is_reported():
    o = by_port(obligations(graph()))["report.clean"]
    assert o.status == "possible"
    (s,) = o.supplies
    assert s.edge.producer.step == "clean" and s.missing == {"file"}


def test_a_listing_is_met_by_a_path_ensured_below_it():
    o = by_port(obligations(graph()))["report.folder"]
    assert o.status == "discharged"


def test_the_same_classes_carry_the_static_types_and_the_graph():
    # Clean.raw is the very expression the graph reads: one declaration.
    g = graph()
    (port,) = [p for p in g.ports if (p.step, p.name) == ("clean", "raw")]
    assert port.expr is Clean.raw
    assert verbs(facts(Clean.raw).atoms) == port.verbs == {"read"}


def test_a_step_built_without_classes_works_too():
    a = Step(out=(P("o") / "x").requires(Absent, Creatable).ensures(File, Exists))
    b = Step(inp=(P("o") / "x").requires(File, Exists, Readable))
    (o,) = [o for o in obligations(EffectGraph({"a": a, "b": b})) if o.port.step == "b"]
    assert o.status == "discharged"
