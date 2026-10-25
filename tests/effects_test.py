"""wend.effects.EffectGraph: what a pipeline's steps declare, related before any
binding: dependencies, hazards, conflicts, a safe order, the steps that may run
together, and how sure each link is (docs/SEMANTICS.md §15)."""

import itertools
import random
from unittest import mock

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from overlap_test import POOL, expressions

from wend import (
    Absent,
    Creatable,
    Exists,
    File,
    Listable,
    P,
    Param,
    Readable,
    Step,
    SubPath,
    T,
    Writable,
)
from wend._relate import lexically
from wend.effects import EffectGraph
from wend.errors import WendError
from wend.lineage import Ledger


root, day, model = Param("root"), Param("day", type=str), Param("model", type=str)
R = P(root)
raw = R / "raw" / T(t"{day}.csv")
clean = R / "clean" / T(t"{day}.parquet")
features = R / "features"
feats = features / T(t"{day}.npz")
weights = R / "models" / T(t"{model}.pkl")
report = R / "reports" / T(t"{day}.html")


def pipeline():
    return {
        "ingest": Step(out=raw.ensures(Exists)),
        "clean": Step(
            src=raw.requires(Readable), dst=clean.requires(Creatable).ensures(File)
        ),
        "featurise": Step(
            src=clean.requires(Readable), dst=feats.requires(Creatable).ensures(File)
        ),
        "train": Step(
            feats=features.requires(Listable),
            out=weights.requires(Creatable).ensures(File),
        ),
        "report": Step(
            src=clean.requires(Readable),
            m=weights.requires(Readable),
            out=report.requires(Creatable).ensures(File),
        ),
        "purge": Step(old=raw.ensures(Absent)),
    }


def links(g):
    return {(e.producer.step, e.consumer.step, e.via, e.certainty) for e in g.edges}


def test_a_pipeline_sharing_one_root_has_exactly_its_real_dependencies():
    g = EffectGraph(pipeline())
    assert links(g) == {
        ("ingest", "clean", "read", "always"),
        ("clean", "featurise", "read", "always"),
        ("featurise", "train", "list", "always"),
        ("clean", "report", "read", "always"),
        ("train", "report", "read", "always"),
    }
    assert [(h.reader.step, h.deleter.step, h.certainty) for h in g.hazards] == [
        ("clean", "purge", "always")
    ]
    assert [(c.first.step, c.second.step, c.certainty) for c in g.conflicts] == [
        ("ingest", "purge", "always")
    ]
    assert g.self_loops() == [] and g.cycles() == []


def test_order_and_stages_respect_dependencies_hazards_and_conflicts():
    g = EffectGraph(pipeline())
    assert g.order() == ["ingest", "clean", "featurise", "purge", "train", "report"]
    # purge waits for clean (a hazard); featurise and purge touch nothing in
    # common, so they may run together.
    assert g.stages() == [
        ["ingest"],
        ["clean"],
        ["featurise", "purge"],
        ["train"],
        ["report"],
    ]
    assert g.independent("featurise", "report")
    assert g.independent("clean", "train")
    assert not g.independent("ingest", "purge")  # a conflict


def test_certain_dependencies_and_the_pipelines_inputs_and_outputs():
    g = EffectGraph(pipeline())
    assert {k: v for k, v in g.dependencies(certain=True).items() if v} == {
        "clean": {"ingest"},
        "featurise": {"clean"},
        "train": {"featurise"},
        "report": {"clean", "train"},
    }
    assert g.external_inputs() == []
    assert [str(p) for p in g.terminal_outputs()] == ["report.out"]


def test_explanations_name_the_ports_the_certainty_and_an_example():
    g = EffectGraph(pipeline())
    (line,) = g.explain("clean", "ingest")
    assert line.startswith("clean.src reads what ingest.out writes, on every run:")
    assert "{root}/raw/{day}.csv" in line and "(e.g. " in line
    lines = g.explain("purge")
    assert any("so clean runs first" in x for x in lines)
    assert any("purge.old deletes what ingest.out writes" in x for x in lines)


def test_examples_render_the_paths_they_show():
    g = EffectGraph(pipeline())
    for link in [*g.edges, *g.hazards, *g.conflicts]:
        ex = link.example()
        assert ex is not None
        assert ex.a_path == ex.b_path or ex.how != "same"


def test_independent_bindings_are_honest_about_a_free_root():
    # Each step's root may differ: nothing is apart, and nothing always holds.
    g = EffectGraph(pipeline(), shared=False)
    assert all(e.certainty == "sometimes" for e in g.edges)
    assert g.dependencies(certain=True) == {s: set() for s in g.steps}
    assert g.order() is None  # train may list what it writes, under another root


def test_deleting_a_directory_endangers_what_is_read_below_it():
    steps = {
        "read": Step(src=raw.requires(Readable)),
        "wipe": Step(gone=(R / "raw").ensures(Absent)),
    }
    g = EffectGraph(steps)
    (h,) = g.hazards
    assert (h.reader.step, h.deleter.step, h.certainty) == ("read", "wipe", "always")
    assert g.order() == ["read", "wipe"]


def test_deleting_inside_a_listed_directory_endangers_the_listing():
    steps = {
        "train": Step(feats=features.requires(Listable)),
        "prune": Step(old=feats.ensures(Absent)),
    }
    g = EffectGraph(steps)
    assert [(h.reader.step, h.deleter.step, h.certainty) for h in g.hazards] == [
        ("train", "prune", "always")
    ]


def test_a_dependency_that_holds_on_some_runs_only():
    steps = {
        "write": Step(dst=(R / "out" / T(t"{day}.csv")).ensures(Exists)),
        "read": Step(src=(R / "out" / "latest.csv").requires(Readable)),
    }
    g = EffectGraph(steps)
    (e,) = g.edges
    assert e.certainty == "sometimes"
    assert e.example().a_path.endswith("out/latest.csv")
    assert g.dependencies() == {"write": set(), "read": {"write"}}
    assert g.dependencies(certain=True) == {"write": set(), "read": set()}


def test_unknown_is_a_dependency_for_the_order_but_never_certain():
    # An untyped value's repr can be any text: neither proved nor ruled out.
    steps = {
        "write": Step(dst=(R / T(t"{Param('n')!r}.csv")).ensures(Exists)),
        "read": Step(src=(R / "q.csv").requires(Readable)),
    }
    g = EffectGraph(steps)
    (e,) = g.edges
    assert e.certainty == "unknown" and e.example() is None
    assert "possibly (not ruled out)" in g.explain("read")[0]
    assert g.order() == ["write", "read"]
    assert g.stages() == [["write"], ["read"]]
    assert not g.independent("write", "read")
    assert g.dependencies(certain=True)["read"] == set()


def test_an_unknown_conflict_keeps_two_steps_apart():
    # An object's repr can be "q": a write of {n!r}.csv may be a write of
    # q.csv. No binding from the pool shows it, so only the contract (every
    # link counts, whatever its certainty) keeps the two out of one stage.
    steps = {
        "w1": Step(dst=(R / T(t"{Param('n')!r}.csv")).requires(Writable)),
        "w2": Step(dst=(R / "q.csv").requires(Writable)),
    }
    g = EffectGraph(steps)
    (c,) = g.conflicts
    assert c.certainty == "unknown"
    assert g.stages() == [["w1"], ["w2"]]
    assert not g.independent("w1", "w2")


def test_a_deferred_operation_relates_through_the_overlap_engine():
    steps = {
        "write": Step(dst=(R / "a" / SubPath("rest")).parent.ensures(Exists)),
        "read": Step(src=(R / "a" / "x").requires(Readable)),
    }
    (e,) = EffectGraph(steps).edges
    assert e.certainty == "sometimes"
    assert e.example().a_path == e.example().b_path


def test_a_real_cycle_has_no_order():
    a, b = R / "a.txt", R / "b.txt"
    steps = {
        "ab": Step(src=a.requires(Readable), dst=b.requires(Writable)),
        "ba": Step(src=b.requires(Readable), dst=a.requires(Writable)),
    }
    g = EffectGraph(steps)
    assert g.cycles() == [["ab", "ba"]] == g.cycles(certain=True)
    assert g.order() is None and g.stages() is None


def test_a_cycle_through_a_hazard_is_a_cycle():
    # b writes what a reads (b first), and deletes what a reads (a first).
    steps = {
        "a": Step(x=(R / "x").requires(Readable), y=(R / "y").requires(Readable)),
        "b": Step(y=(R / "y").requires(Writable), x=(R / "x").ensures(Absent)),
    }
    g = EffectGraph(steps)
    assert g.order() is None
    assert g.cycles() == [["a", "b"]] == g.cycles(certain=True)


def test_a_cycle_that_rests_on_a_possible_link_is_not_called_unavoidable():
    # "b" writes a.csv for one day only: the cycle forms on runs that write
    # the day "a" reads, and is not proved for every run.
    steps = {
        "a": Step(
            src=(R / "in" / "a.csv").requires(Readable),
            dst=(R / "out.csv").requires(Writable),
        ),
        "b": Step(
            src=(R / "out.csv").requires(Readable),
            dst=(R / "in" / T(t"{day}.csv")).requires(Writable),
        ),
    }
    g = EffectGraph(steps)
    assert [(e.producer.step, e.consumer.step, e.certainty) for e in g.edges] == [
        ("b", "a", "sometimes"),
        ("a", "b", "always"),
    ]
    assert g.order() is None and g.stages() is None
    assert g.cycles() == [["a", "b"]]
    assert g.cycles(certain=True) == []


NESTED = {
    "a step writes a directory, another reads a file in it": (
        {
            "unpack": Step(out=(R / "raw").requires(Creatable).ensures(Exists)),
            "clean": Step(src=raw.requires(Readable)),
        },
        [["unpack"], ["clean"]],
        "clean.src reads inside what unpack.out writes",
    ),
    "a step reads a directory, another writes a file in it": (
        {
            "archive": Step(src=(R / "raw").requires(Readable)),
            "ingest": Step(out=raw.ensures(Exists)),
        },
        [["ingest"], ["archive"]],
        "archive.src reads a directory holding what ingest.out writes",
    ),
    "two steps write a directory and a file in it": (
        {
            "unpack": Step(out=(R / "raw").ensures(Exists)),
            "ingest": Step(out=raw.ensures(Exists)),
        },
        [["unpack"], ["ingest"]],
        "ingest.out writes inside what unpack.out writes",
    ),
    "a step deletes a file in a directory another writes": (
        {
            "unpack": Step(out=(R / "raw").ensures(Exists)),
            "purge": Step(old=raw.ensures(Absent)),
        },
        [["unpack"], ["purge"]],
        "purge.old deletes inside what unpack.out writes",
    ),
    "a step deletes a file in a directory another reads": (
        {
            "archive": Step(src=(R / "raw").requires(Readable)),
            "purge": Step(old=raw.ensures(Absent)),
        },
        [["archive"], ["purge"]],
        "purge.old deletes inside what archive.src reads, on every run, so archive",
    ),
    "two steps delete a directory and a file in it": (
        {
            "wipe": Step(old=(R / "raw").ensures(Absent)),
            "purge": Step(old=raw.ensures(Absent)),
        },
        [["wipe"], ["purge"]],
        "purge.old deletes inside what wipe.old deletes",
    ),
    "a step declares no verbs for a directory another reads in": (
        {
            "check": Step(x=(R / "raw").requires(Exists)),
            "clean": Step(src=raw.requires(Readable)),
        },
        [["check"], ["clean"]],
        "check.x declares no verbs, so it is kept apart from clean.src",
    ),
    "a step declares no verbs for a path another writes in": (
        {
            "check": Step(x=(R / "raw").requires(Exists)),
            "ingest": Step(out=raw.ensures(Exists)),
        },
        [["check"], ["ingest"]],
        "check.x declares no verbs, so it is kept apart from ingest.out",
    ),
}


@pytest.mark.parametrize("case", NESTED.values(), ids=NESTED.keys())
def test_a_declared_path_covers_what_lies_below_it(case):
    # A declared path may be a directory: a step that writes, reads or
    # deletes it may touch anything inside it. Steps whose paths nest are
    # never independent, and never in one stage.
    steps, stages, sentence = case
    g = EffectGraph(steps)
    a, b = steps
    assert not g.independent(a, b)
    assert g.stages() == stages
    (line,) = g.explain(a, b)
    assert line.startswith(sentence) and "on every run" in line


def test_two_writers_of_one_path_are_never_in_one_stage():
    steps = {
        "first": Step(dst=(R / "out.csv").requires(Writable)),
        "second": Step(dst=(R / "out.csv").requires(Writable)),
        "other": Step(dst=(R / "else.csv").requires(Writable)),
    }
    g = EffectGraph(steps)
    assert [(c.first.step, c.second.step) for c in g.conflicts] == [("first", "second")]
    assert g.order() == ["first", "second", "other"]
    assert g.stages() == [["first", "other"], ["second"]]


def test_a_path_without_verbs_is_reported_not_guessed():
    g = EffectGraph({"s": Step(x=R / "x")})
    assert [str(p) for p in g.unassigned] == ["s.x"]
    assert g.edges == []


def test_ledger_runs_agree_with_the_declarations(tmp_path):
    steps = pipeline()
    ledger = Ledger(tmp_path / "ledger.jsonl", digests=False)
    made = ledger.record(tmp_path / "raw" / "mon.csv", operation=repr(steps["ingest"]))
    ledger.record(
        tmp_path / "clean" / "mon.parquet", [made.path], operation=repr(steps["clean"])
    )
    report = EffectGraph(steps).compare(ledger.records())
    assert report["undeclared"] == []
    assert ("clean", "featurise") in report["unobserved"]
    assert ("ingest", "clean") not in report["unobserved"]


def test_an_observed_dependency_the_declarations_rule_out(tmp_path):
    steps = pipeline()
    ledger = Ledger(tmp_path / "ledger.jsonl", digests=False)
    made = ledger.record(
        tmp_path / "reports" / "mon.html", operation=repr(steps["report"])
    )
    ledger.record(
        tmp_path / "raw" / "mon.csv", [made.path], operation=repr(steps["ingest"])
    )
    assert EffectGraph(steps).compare(ledger.records())["undeclared"] == [
        ("report", "ingest")
    ]


def test_steps_a_ledger_cannot_tell_apart_are_refused():
    s = Step(x=raw.requires(Readable))
    with pytest.raises(ValueError, match="cannot tell them apart"):
        EffectGraph({"a": s, "b": Step(x=raw.requires(Readable))}).compare([])


def test_the_experimental_graph_could_not_order_this_pipeline():
    # What the relation adds: prefix cancellation under one root. The
    # experimental graph, on shared bindings, found a cycle here.
    from wend._experimental.effects import EffectGraph as Old

    assert Old(pipeline(), shared=True).order() is None
    assert EffectGraph(pipeline()).order() is not None


def test_different_defaults_of_one_head_are_not_indexed_apart():
    # Unbound, p + y and p/y + z nest, though their literal tails differ.
    a = P(Param("root", default="p")) / "y"
    b = P(Param("root", default="p/y")) / "z"
    g = EffectGraph(
        {"w": Step(out=b.ensures(Exists)), "l": Step(d=a.requires(Listable))}
    )
    (e,) = g.edges
    assert e.certainty == "sometimes"
    ex = e.example()
    assert (ex.a_path, ex.b_path) == ("p/y/z", "p/y")


VERBS = [Readable, Listable, Writable, Exists, Absent, None]


@st.composite
def steps(draw):
    out = {}
    for i in range(draw(st.integers(2, 5))):
        paths = {}
        for j in range(draw(st.integers(1, 3))):
            e = draw(expressions())
            verb = VERBS[draw(st.integers(0, len(VERBS) - 1))]
            if verb is None:
                e = e.requires(Exists)  # a check, which declares no verb
            elif verb in (Readable, Listable, Writable):
                e = e.requires(verb)
            else:
                e = e.ensures(verb)
            paths[f"p{j}"] = e
        out[f"s{i}"] = Step(paths)
    return out


def bindings(names, n=300, seed=0):
    """Up to ``n`` bindings of ``names`` from the overlap tests' pool: the
    first in order, then random ones."""
    names = sorted(names)
    first = itertools.islice(itertools.product(*(POOL[k] for k in names)), n // 2)
    rng = random.Random(seed)
    rand = (tuple(rng.choice(POOL[k]) for k in names) for _ in range(n // 2))
    for combo in itertools.chain(first, rand):
        yield dict(zip(names, combo, strict=True))


def render(port, env):
    try:
        return port.expr.render(
            {k: v for k, v in env.items() if k in port.expr.param_names}
        )
    except WendError, ValueError:
        return None


def changes(port):
    return port.supplies or port.deletes or not port.verbs


@settings(max_examples=150, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(s=steps())
def test_order_and_stages_hold_for_every_rendered_run(s):
    # The oracle: render every port under pooled bindings, and compare the
    # paths as strings. Wherever a written path touches a read one, the
    # writer must come first; wherever a deleted path touches a read one,
    # the reader must; and two steps whose paths touch, where either changes
    # its path (or declares no verbs), must never share a stage.
    g = EffectGraph(s)
    order, stages = g.order(), g.stages()
    assert (order is None) == bool(g.cycles()) == (stages is None)
    names = set().union(*(p.expr.param_names for p in g.ports))
    before: set[tuple[str, str]] = set()
    apart: set[frozenset[str]] = set()
    for env in bindings(names):
        paths = [(p, render(p, env)) for p in g.ports]
        for (x, px), (y, py) in itertools.permutations(paths, 2):
            if x.step == y.step or px is None or py is None:
                continue
            if lexically(px, py) is None:
                continue
            if x.is_input and y.supplies:
                before.add((y.step, x.step))
            if x.is_input and y.deletes:
                before.add((x.step, y.step))
            if changes(x) or changes(y):
                apart.add(frozenset((x.step, y.step)))
    if order is None:
        return
    assert stages is not None
    pos = {step: n for n, step in enumerate(order)}
    assert all(pos[u] < pos[v] for u, v in before), (before, order)
    stage = {step: n for n, group in enumerate(stages) for step in group}
    assert all(stage[u] < stage[v] for u, v in before), (before, stages)
    for pair in apart:
        u, v = sorted(pair)
        assert stage[u] != stage[v], (pair, stages)
        assert not g.independent(u, v)


def everything(g):
    return (
        [(str(e.producer), str(e.consumer), e.via, e.certainty) for e in g.edges],
        [(str(h.reader), str(h.deleter), h.certainty) for h in g.hazards],
        [(str(c.first), str(c.second), c.certainty) for c in g.conflicts],
    )


@settings(max_examples=150, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(s=steps(), shared=st.booleans())
def test_the_index_never_changes_a_link(s, shared):
    with mock.patch.object(EffectGraph, "_apart", lambda self, a, b: False):
        full = everything(EffectGraph(s, shared=shared))
    assert everything(EffectGraph(s, shared=shared)) == full
