"""wend._experimental.effects: graphs of what steps declare, checked on a
realistic pipeline, on cycles, and against a Ledger of real runs."""

from __future__ import annotations

import pytest

from wend import (
    Absent,
    Exists,
    Listable,
    P,
    Param,
    Readable,
    Step,
    T,
    Writable,
)
from wend._experimental.effects import EffectGraph
from wend.lineage import Ledger


day, name = Param("day"), Param("name")


def pipeline(root):
    r = P(root)
    return {
        "ingest": Step(
            src=(r / "inbox" / T(t"{day}.csv")).requires(Readable),
            dst=(r / "raw" / T(t"{day}.parquet")).ensures(Exists),
        ),
        "clean": Step(
            src=(r / "raw" / T(t"{day}.parquet")).requires(Readable),
            dst=(r / "clean" / T(t"{day}.parquet")).ensures(Exists),
        ),
        "features": Step(
            src=(r / "clean" / T(t"{day}.parquet")).requires(Readable),
            dst=(r / "features" / day / T(t"{name}.npy")).ensures(Exists),
        ),
        "report": Step(
            src=(r / "features" / day).requires(Listable),
            dst=(r / "reports" / T(t"{day}.html")).ensures(Exists),
        ),
        "compact": Step(
            src=(r / "clean" / T(t"{day}.parquet")).requires(Readable),
            old=(r / "raw" / T(t"{day}.parquet")).ensures(Absent),
        ),
        "backfill": Step(dst=(r / "clean" / T(t"{day}.parquet")).requires(Writable)),
    }


def edges(g):
    return {(e.producer.step, e.consumer.step, e.via, e.verdict) for e in g.edges}


def test_a_pipeline_graph():
    g = EffectGraph(pipeline("data"))
    assert edges(g) == {
        ("ingest", "clean", "read", "yes"),
        ("clean", "features", "read", "yes"),
        ("backfill", "features", "read", "yes"),
        ("clean", "compact", "read", "yes"),
        ("backfill", "compact", "read", "yes"),
        ("features", "report", "list", "yes"),
    }
    # Every yes carries a path both sides render.
    for e in g.edges:
        w = e.overlap.witness
        assert e.producer.expr.render(w.a) == w.path == e.target.render(w.b)
    assert [(p.step, p.name) for p in g.external_inputs()] == [("ingest", "src")]
    assert [(p.step, p.name) for p in g.terminal_outputs()] == [("report", "dst")]
    # Deleting supplies nothing: compact's deletion of raw/ is a hazard for
    # clean (which must read raw/ first), not an edge into it.
    assert [(h.reader.step, h.deleter.step) for h in g.hazards] == [
        ("clean", "compact")
    ]
    assert {(c.first.step, c.second.step) for c in g.conflicts} == {
        ("clean", "backfill"),
        ("ingest", "compact"),
    }
    assert g.cycles() == []
    order = g.order()
    assert order.index("clean") < order.index("compact")
    assert order.index("ingest") < order.index("clean") < order.index("features")


def test_parameter_correspondence_through_a_lens():
    g = EffectGraph(pipeline("data"))
    [e] = [
        e for e in g.edges if (e.producer.step, e.consumer.step) == ("ingest", "clean")
    ]
    assert e.aligned({"day": "mon"}) is True
    assert e.readers({"day": "mon"}) == [{"day": "mon"}]
    assert e.lens()("data/raw/mon.parquet") == e.lens().target.resolve(day="mon")
    # A listing reads every path below the directory, with names of its own.
    [ls] = [e for e in g.edges if e.via == "list"]
    assert ls.readers({"day": "mon", "name": "x"}) == [
        {"day": "mon", "_listed": "x.npy"}
    ]


def test_shared_bindings_rule_out_a_cycle_independent_ones_allow():
    k = Param("k")
    steps = {
        "a": Step(
            src=(P("data") / k / "in").requires(Readable),
            dst=(P("data") / k / "mid").ensures(Exists),
        ),
        "b": Step(
            src=(P("data") / k / "mid").requires(Readable),
            dst=(P("data") / "a" / k).ensures(Exists),
        ),
    }
    # b writes data/a/{k}; a reads data/{k}/in: one path (data/a/in) when a's
    # k is "a" and b's k is "in", so with independent bindings a cycle.
    loose = EffectGraph(steps)
    assert loose.cycles() == [["a", "b"]]
    assert loose.order() is None
    # With one k for both, that needs k == "a" and k == "in" at once.
    tight = EffectGraph(steps, shared=True)
    assert tight.cycles() == []
    assert tight.order() == ["a", "b"]


def test_a_cycle_the_declarations_really_have():
    steps = {
        "report": Step(
            src=(P("features") / day).requires(Listable),
            dst=(P("reports") / T(t"{day}.html")).ensures(Exists),
        ),
        "rollup": Step(
            src=(P("reports") / T(t"{day}.html")).requires(Readable),
            dst=(P("features") / day / "summary.npy").ensures(Exists),
        ),
    }
    g = EffectGraph(steps, shared=True)
    # Listing features/{day} sees the summary rollup writes there.
    assert g.cycles() == [["report", "rollup"]]
    assert g.order() is None


def test_a_path_without_verbs_is_reported_not_guessed():
    g = EffectGraph({"s": Step(cfg=P("config.yaml"), out=P("o").ensures(Exists))})
    assert [(p.step, p.name) for p in g.unassigned] == [("s", "cfg")]
    assert g.external_inputs() == []  # cfg is not an input either


def test_ledger_runs_agree_with_the_declarations(tmp_path):
    steps = pipeline(tmp_path)
    (tmp_path / "inbox").mkdir()
    (tmp_path / "inbox" / "mon.csv").write_text("x")
    ledger = Ledger(tmp_path / "ledger.jsonl")
    for step in ["ingest", "clean", "features"]:
        with ledger.run(steps[step], day="mon", name="f") as paths:
            for k, p in paths.items():
                if steps[step].paths[k].conditions.ensures:
                    p.parent.mkdir(parents=True, exist_ok=True)
                    p.write_text("x")
    g = EffectGraph(steps)
    report = g.compare(ledger.records())
    assert report["undeclared"] == []
    # backfill never ran, so its declared dependencies were not observed.
    assert ("backfill", "features") in report["unobserved"]
    assert ("ingest", "clean") not in report["unobserved"]


def test_an_observed_dependency_the_declarations_rule_out(tmp_path):
    steps = pipeline(tmp_path)
    ledger = Ledger(tmp_path / "ledger.jsonl", digests=False)
    # The report step really read clean/mon.parquet, which it does not declare.
    made = ledger.record(
        tmp_path / "clean" / "mon.parquet", operation=repr(steps["clean"])
    )
    ledger.record(
        tmp_path / "reports" / "mon.html",
        [made.path],
        operation=repr(steps["report"]),
    )
    g = EffectGraph(steps)
    assert g.compare(ledger.records())["undeclared"] == [("clean", "report")]


@pytest.mark.parametrize("shared", [False, True])
def test_every_edge_and_conflict_is_backed_by_an_overlap(shared):
    g = EffectGraph(pipeline("data"), shared=shared)
    for e in g.edges:
        assert e.overlap.verdict in ("yes", "maybe")
    for c in g.conflicts:
        assert c.overlap.verdict in ("yes", "maybe")


def test_a_no_between_spellings_is_flagged_not_trusted():
    # Two spellings of one file (from /srv, or with raw/ a directory): the
    # overlap is NO, so the graph has no edge, and says why not to trust it.
    steps = {
        "make": Step(dst=(P("/srv/data") / T(t"{day}.csv")).ensures(Exists)),
        "use": Step(src=(P("data") / T(t"{day}.csv")).requires(Readable)),
        "up": Step(src=(P("data/raw/../x") / T(t"{day}.csv")).requires(Readable)),
    }
    g = EffectGraph(steps)
    assert g.edges == []
    assert {(p.step, why) for p, why in g.lexical_caveats()} == {
        ("use", "relative"),
        ("up", "relative"),
        ("up", ".."),
    }
    assert EffectGraph(pipeline("/srv/data")).lexical_caveats() == []


def test_steps_a_ledger_cannot_tell_apart_are_refused():
    twin = Step(src=P("in").requires(Readable), dst=P("out").ensures(Exists))
    g = EffectGraph({"one": twin, "two": twin})
    with pytest.raises(ValueError, match="cannot tell them apart"):
        g.compare([])


def test_maybe_is_a_dependency_unless_asked_for_proven_ones_only():
    # d/{p!r} might be d/zz for some value whose repr is zz: no witness, no
    # proof otherwise. The edge is MAYBE, and a schedule must honour it.
    p = Param("p")
    steps = {
        "a": Step(src=(P("d") / "zz").requires(Readable)),
        "b": Step(dst=(P("d") / T(t"{p!r}")).ensures(Exists)),
    }
    g = EffectGraph(steps)
    assert [(e.producer.step, e.consumer.step, e.verdict) for e in g.edges] == [
        ("b", "a", "maybe")
    ]
    assert g.dependencies() == {"a": {"b"}, "b": set()}
    assert g.order() == ["b", "a"]
    assert g.external_inputs() == []  # possibly supplied, so not external
    # The lower bound drops it: fine for a report, wrong as a schedule.
    assert g.dependencies(definite_only=True) == {"a": set(), "b": set()}
    assert g.order(definite_only=True) == ["a", "b"]
