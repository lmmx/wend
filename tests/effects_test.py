"""wend.effects.EffectGraph: what a pipeline's steps declare, related before any
binding: dependencies, hazards, conflicts, a safe order, the steps that may run
together, and how sure each link is (docs/SEMANTICS.md §15)."""

import itertools
import random
from pathlib import Path
from unittest import mock

import pytest
from families_test import (
    ENVS,
    ROOT_REPLACED,
    _worked_pipeline,
    bound,
    build,
    cases,
    make_tree,
    run,
    run_root,
)
from hypothesis import HealthCheck, example, given, settings
from hypothesis import strategies as st
from overlap_test import POOL, expressions

from wend import (
    Absent,
    Creatable,
    Dir,
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
from wend._experimental.families import analyse_families
from wend._experimental.knowledge import Fact, holds
from wend._relate import _segments, lexically
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
    g = EffectGraph(pipeline(), existing=[R])
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
    g = EffectGraph(pipeline(), existing=[R])
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
    g = EffectGraph(pipeline(), existing=[R])
    assert {k: v for k, v in g.dependencies(certain=True).items() if v} == {
        "clean": {"ingest"},
        "featurise": {"clean"},
        "train": {"featurise"},
        "report": {"clean", "train"},
    }
    assert g.external_inputs() == []
    assert [str(p) for p in g.terminal_outputs()] == ["report.out"]


def test_explanations_name_the_ports_the_certainty_and_an_example():
    g = EffectGraph(pipeline(), existing=[R])
    (line,) = g.explain("clean", "ingest")
    assert line.startswith("clean.src reads what ingest.out writes, on every run:")
    assert "{root}/raw/{day}.csv" in line and "(e.g. " in line
    lines = g.explain("purge")
    assert any("so clean runs first" in x for x in lines)
    assert any("purge.old deletes what ingest.out writes" in x for x in lines)


def test_examples_render_the_paths_they_show():
    g = EffectGraph(pipeline(), existing=[R])
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
    "a step declares nothing of a directory another reads in": (
        {
            "touch": Step(x=R / "raw"),
            "clean": Step(src=raw.requires(Readable)),
        },
        [["touch"], ["clean"]],
        "touch.x declares no verbs nor that its path exists, so it is kept apart"
        " from clean.src",
    ),
    "a step declares nothing of a directory another writes in": (
        {
            "touch": Step(x=R / "raw"),
            "ingest": Step(out=raw.ensures(Exists)),
        },
        [["touch"], ["ingest"]],
        "touch.x declares no verbs nor that its path exists, so it is kept apart"
        " from ingest.out",
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
    g = EffectGraph(steps, existing=[R])  # {root} exists: no parent is made
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


OUT = P("output")
PARENTS = {
    # Two steps create files in output/, which may be missing: each may make it.
    "both make missing parents idempotently": (
        {"a": Step(f=(OUT / "a.csv").ensures(Exists))},
        {"b": Step(f=(OUT / "b.csv").ensures(Exists))},
        [["a", "b"]],
        [["a", "b"]],
    ),
    "one checks it may create its file": (
        {"a": Step(f=(OUT / "a.csv").ensures(Exists))},
        {"b": Step(f=(OUT / "b.csv").requires(Creatable).ensures(File))},
        [["a"], ["b"]],
        [["a", "b"]],
    ),
    "one requires the directory to exist": (
        {"a": Step(f=(OUT / "a.csv").ensures(Exists))},
        {"b": Step(d=OUT.requires(Exists, Dir), f=(OUT / "b.csv").ensures(Exists))},
        [["a"], ["b"]],
        [["a", "b"]],
    ),
}


@pytest.mark.parametrize("case", PARENTS.values(), ids=PARENTS.keys())
def test_parents_a_creation_may_make(case):
    # Without ``existing``, output/ may be missing, and a creation of a.csv
    # may make it: kept apart from a creation check below it, and ordered
    # before a step that requires it. Declared existing, it is never made.
    a, b, stages, existing_stages = case
    assert EffectGraph({**a, **b}).stages() == stages
    assert EffectGraph({**a, **b}, existing=[OUT]).stages() == existing_stages


def test_a_parent_conflict_names_the_directory_and_is_never_certain():
    g = EffectGraph(
        {
            "a": Step(f=(OUT / "a.csv").ensures(Exists)),
            "b": Step(f=(OUT / "b.csv").requires(Creatable).ensures(File)),
        }
    )
    (c,) = g.conflicts
    assert (c.via, c.certainty, c.parent.pattern) == ("parent", "unknown", "output")
    assert c.example() is None
    assert g.explain("a") == [
        "a.f may make output if it is missing, and b.f checks it may create"
        " output/b.csv, which depends on whether output exists, possibly (not"
        " ruled out): output/a.csv and output/b.csv"
    ]


def test_an_existence_requirement_follows_what_may_make_it():
    g = EffectGraph(
        {
            "b": Step(d=OUT.requires(Exists, Dir)),
            "a": Step(f=(OUT / "a.csv").ensures(Exists)),
            "mk": Step(d=OUT.requires(Creatable).ensures(Dir)),
        }
    )
    deps = {(e.producer.step, e.consumer.step): (e.via, e.certainty) for e in g.edges}
    # Made as a missing parent of a.csv: only possibly. Made as the path: always.
    assert deps == {
        ("a", "b"): ("exists", "unknown"),
        ("mk", "b"): ("exists", "always"),
    }
    assert g.order() == ["a", "mk", "b"]
    assert g.dependencies(certain=True)["b"] == {"mk"}


def test_a_directory_made_exclusively_is_declared_and_then_nests():
    g = EffectGraph(
        {
            "a": Step(f=(OUT / "a.csv").ensures(Exists)),
            "mk": Step(d=OUT.requires(Absent).ensures(Exists, Dir)),
        }
    )
    (c,) = g.conflicts
    assert (c.via, c.certainty) == ("path", "always")
    assert g.stages() == [["a"], ["mk"]]


def test_a_path_given_as_existing_must_not_be_deleted():
    with pytest.raises(ValueError, match="cannot be given as existing"):
        EffectGraph({"wipe": Step(d=R.ensures(Absent))}, existing=[R / "raw"])
    # Deleting below it is no deletion of it.
    EffectGraph({"purge": Step(d=raw.ensures(Absent))}, existing=[R / "raw"])


def test_a_pipeline_with_two_writers_in_one_new_directory():
    # stats writes features/summary.json beside featurise's features/{day}.npz,
    # and both check they may create their file: until features/ is known to
    # exist, either may be making it while the other checks.
    steps = pipeline()
    steps["stats"] = Step(
        src=clean.requires(Readable),
        out=(features / "summary.json").requires(Creatable).ensures(File),
    )
    g = EffectGraph(steps, existing=[R])
    assert [(c.first.step, c.second.step, c.via) for c in g.conflicts] == [
        ("ingest", "purge", "path"),
        ("featurise", "stats", "parent"),
    ]
    assert g.stages() == [
        ["ingest"],
        ["clean"],
        ["featurise", "purge"],
        ["stats"],
        ["train"],
        ["report"],
    ]
    g = EffectGraph(steps, existing=[R, features])
    assert g.stages() == [
        ["ingest"],
        ["clean"],
        ["featurise", "purge", "stats"],
        ["train"],
        ["report"],
    ]


def test_without_existing_a_root_may_be_made_by_any_creation():
    # Every creation check under {root} conflicts with every other creation
    # there, possibly: and the pipeline's order and stages are unchanged.
    g, known = EffectGraph(pipeline()), EffectGraph(pipeline(), existing=[R])
    parents = [c for c in g.conflicts if c.via == "parent"]
    assert len(parents) == 10
    assert {(c.certainty, c.parent.pattern) for c in parents} == {("unknown", "{root}")}
    assert g.edges == known.edges and g.hazards == known.hazards
    assert (g.order(), g.stages()) == (known.order(), known.stages())


def test_outputs_named_after_their_inputs():
    # Each output is its input with another suffix or stem. On their views
    # (wend.relate) the parquet and the schema never meet the CSVs nor each
    # other, so convert and schema may run at once.
    convert = Step(
        src=raw.requires(Readable),
        dst=raw.with_suffix(".parquet").requires(Creatable).ensures(File),
    )
    schema = Step(
        src=raw.requires(Readable),
        dst=raw.with_suffix(".schema.json").requires(Creatable).ensures(File),
    )
    steps = {
        "ingest": Step(out=raw.ensures(Exists)),
        "convert": convert,
        "schema": schema,
    }
    g = EffectGraph(steps, existing=[R, R / "raw"])
    assert g.independent("convert", "schema")
    assert g.stages() == [["ingest"], ["convert", "schema"]]
    # A summary named by stem collides with the raw CSV of a day called
    # "summary": possibly, so a possible cycle, and no certain one.
    stats = Step(
        src=raw.with_suffix(".parquet").requires(Readable),
        out=raw.with_stem("summary").requires(Creatable).ensures(File),
    )
    g = EffectGraph({**steps, "stats": stats}, existing=[R, R / "raw"])
    assert g.cycles() == [["convert", "stats"]] and g.cycles(certain=True) == []
    (e,) = [
        e
        for e in g.edges
        if e.producer.step == "stats" and e.consumer.step == "convert"
    ]
    assert e.certainty == "sometimes" and e.example().a_path.endswith("raw/summary.csv")


VERBS = [Readable, Listable, Writable, Creatable, Exists, Absent, "exists", None]


@st.composite
def steps(draw):
    out = {}
    for i in range(draw(st.integers(2, 5))):
        paths = {}
        for j in range(draw(st.integers(1, 3))):
            e = draw(expressions())
            verb = VERBS[draw(st.integers(0, len(VERBS) - 1))]
            if verb == "exists":
                e = e.requires(Exists)  # requires existence, and no verb
            elif verb is None:
                pass  # declares nothing: its effect is unknown
            elif verb is Creatable:
                e = e.requires(Creatable).ensures(File)
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
    return port.supplies or port.deletes or not (port.verbs or port.observes)


def watches(port):
    """Whether the port only requires its path to exist."""
    return port.observes and not port.verbs


def parent_shared(px, py):
    """Whether two rendered paths share a directory above both, other than
    their anchor: one that may be missing."""
    (ax, sx), (ay, sy) = _segments(px), _segments(py)
    if ax != ay:
        return False
    j = 0
    while j < min(len(sx), len(sy)) and sx[j] == sy[j]:
        j += 1
    return 0 < j < min(len(sx), len(sy))


@settings(max_examples=150, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(s=steps())
def test_order_and_stages_hold_for_every_rendered_run(s):
    # The oracle: render every port under pooled bindings, and compare the
    # paths as strings. Wherever a written path touches a read one (or one
    # required to exist), the writer must come first; wherever a deleted
    # path touches a read one, the reader must; two steps whose paths touch,
    # where either changes its path (or its effect is unknown), must never
    # share a stage; nor two that create paths below a directory that may be
    # missing, where either checks it may create its own.
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
            how = lexically(px, py)
            if how is None:
                if x.supplies and y.supplies and parent_shared(px, py):
                    if x.checks_creation or y.checks_creation:
                        apart.add(frozenset((x.step, y.step)))
                continue
            # An anchor ("/", ".") exists: making a path below it makes no
            # parent an existence requirement could wait for.
            made = how != "contains" or x.is_input or _segments(px)[1]
            if (x.is_input or x.observes) and y.supplies and made:
                before.add((y.step, x.step))
            if (x.is_input or x.observes) and y.deletes:
                before.add((x.step, y.step))
            # A port that only requires an anchor to exist is not touched by a
            # change below it: the anchor exists whatever is made there.
            anchored = (watches(x) and how == "contains" and not _segments(px)[1]) or (
                watches(y) and how == "inside" and not _segments(py)[1]
            )
            if (changes(x) or changes(y)) and not anchored:
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


# -- obligations: what each requirement relies on ------------------------------


def statuses(g, schedule=None):
    got: dict[tuple[str, str], dict[str, set[str]]] = {}
    for o in g.obligations(schedule):
        by = got.setdefault((o.port.step, o.port.name), {})
        by.setdefault(o.status, set()).add(o.atom)
    return got


def test_obligations_agree_with_the_experimental_analysis_on_its_pipeline():
    steps = _worked_pipeline()
    g = EffectGraph(dict(steps))
    got = statuses(g, [n for n, _ in steps])
    for e in analyse_families(steps):
        mine = got[(e.step, e.port)]
        assert mine.get("discharged", set()) == set(e.known), e
        assert mine.get("refuted", set()) == set(e.refuted), e
    # Run by stages, the audit reads the raw file before cleanup deletes it.
    assert statuses(g)[("audit", "src")]["discharged"] == {"exists", "file"}


def test_a_fact_holds_of_another_spelling_until_a_change_may_reach_it():
    made = R / "raw" / T(t"{day}.csv")
    again = (R / "raw").joinpath(T(t"{Param('day', type=str)}.csv"))
    other = R / "raw" / T(t"{Param('name', type=str)}.csv")
    steps = {
        "make": Step(out=made.requires(Absent, Creatable).ensures(File, Exists)),
        "read": Step(src=again.requires(File, Exists, Readable)),
    }
    assert statuses(EffectGraph(steps))[("read", "src")]["discharged"] == {
        "exists",
        "file",
    }
    # A deletion that may be of the same file, for some name.
    steps = {**steps, "drop": Step(old=other.requires(Exists).ensures(Absent))}
    o = statuses(EffectGraph(steps), ["make", "drop", "read"])[("read", "src")]
    # The deletion may also have made it absent, which refutes reading it.
    assert o == {"at risk": {"exists", "file", "read"}}


def test_existence_below_a_path_and_absence_above_one():
    steps = {
        "make": Step(out=raw.requires(Absent, Creatable).ensures(File, Exists)),
        "list": Step(d=(R / "raw").requires(Dir, Exists, Listable)),
        "drop": Step(d=(R / "raw").requires(Exists).ensures(Absent)),
        "read": Step(src=raw.requires(File, Exists, Readable)),
    }
    got = statuses(EffectGraph(steps), ["make", "list", "drop", "read"])
    assert got[("list", "d")] == {"discharged": {"dir", "exists"}, "external": {"list"}}
    assert got[("drop", "d")] == {"discharged": {"exists"}}
    assert got[("read", "src")]["refuted"] == {"exists", "read"}


def test_a_promise_in_the_same_group_discharges_nothing():
    steps = {
        "make": Step(out=raw.requires(Absent, Creatable).ensures(File, Exists)),
        "read": Step(src=raw.requires(File, Exists, Readable)),
    }
    g = EffectGraph(steps)
    assert statuses(g, ["make", "read"])[("read", "src")]["discharged"] == {
        "exists",
        "file",
    }
    # Run together, read may run first: what make promises is not known yet,
    # and what read checks may be changed by make while it runs.
    assert "discharged" not in statuses(g, [["make", "read"]])[("read", "src")]


def test_a_group_given_by_hand_may_run_in_any_order():
    # stages() never groups steps that interfere; a schedule given by hand may.
    steps = {
        "make": Step(out=raw.requires(Absent, Creatable).ensures(File, Exists)),
        "drop": Step(old=raw.requires(Exists).ensures(Absent)),
        "read": Step(src=raw.requires(File, Exists, Readable)),
        "after": Step(src=raw.requires(Exists)),
    }
    g = EffectGraph(steps)
    # drop may run before read: what make promised is not known to read.
    got = statuses(g, ["make", ["drop", "read"], "after"])
    assert "discharged" not in got[("read", "src")]
    # read changes nothing, so drop's requirement holds whichever runs first.
    assert got[("drop", "old")] == {"discharged": {"exists"}}
    assert got[("after", "src")] == {"refuted": {"exists"}}
    # make and drop in either order: neither promise is known after them.
    got = statuses(g, [["make", "drop"], "read", "after"])
    assert "discharged" not in got[("read", "src")]
    assert "refuted" not in got[("read", "src")]


def test_file_and_dir_exclude_each_other_only_for_a_path_that_exists():
    # Both hold of a missing path (§10): a step that promises a directory
    # there, and no more, leaves File possible.
    d = R / "d"
    steps = {"dir": Step(d=d.ensures(Dir)), "file": Step(d=d.requires(File))}
    assert statuses(EffectGraph(steps), ["dir", "file"])[("file", "d")] == {
        "external": {"file"}
    }
    steps["dir"] = Step(d=d.ensures(Dir, Exists))
    assert statuses(EffectGraph(steps), ["dir", "file"])[("file", "d")] == {
        "refuted": {"file"}
    }


def test_a_port_that_declares_nothing_may_change_its_path():
    steps = {
        "make": Step(out=raw.requires(Absent, Creatable).ensures(File, Exists)),
        "touch": Step(x=raw),
        "read": Step(src=raw.requires(File, Exists)),
    }
    got = statuses(EffectGraph(steps), ["make", "touch", "read"])
    assert got[("read", "src")] == {"at risk": {"exists", "file"}}


def test_creating_and_writing_are_never_discharged():
    out = R / "out.txt"
    steps = {
        "check": Step(o=out.requires(Creatable)),
        "again": Step(o=out.requires(Creatable)),
    }
    assert statuses(EffectGraph(steps), ["check", "again"])[("again", "o")] == {
        "external": {"create"}
    }


def test_a_schedule_names_every_step_once():
    g = EffectGraph(pipeline())
    with pytest.raises(ValueError, match="every step once"):
        g.obligations(["ingest", "clean"])
    with pytest.raises(ValueError, match="every step once"):
        g.obligations([*g.steps, "ingest"])
    a, b = R / "a.txt", R / "b.txt"
    loop = EffectGraph(
        {
            "ab": Step(src=a.requires(Readable), dst=b.requires(Writable)),
            "ba": Step(src=b.requires(Readable), dst=a.requires(Writable)),
        }
    )
    with pytest.raises(ValueError, match="cycle"):
        loop.obligations()
    assert len(loop.obligations(["ab", "ba"])) == 4


def _obligations_hold_on_disk(case, staged):
    pipeline_, tree = case
    steps, bodies = build(pipeline_)
    names = [n for n, _ in steps]
    g = EffectGraph(dict(steps))
    if staged:
        groups = g.stages()
        if groups is None:
            return
        found = g.obligations()
        # Steps of one group may run in any order: try two.
        orders = [
            [names.index(s) for grp in groups for s in grp],
            [names.index(s) for grp in groups for s in reversed(grp)],
        ]
    else:
        groups = [[n] for n in names]
        found = g.obligations(names)
        orders = [list(range(len(steps)))]
    group = {names.index(s): k for k, grp in enumerate(groups) for s in grp}
    by_step: dict[str, list] = {}
    for o in found:
        by_step.setdefault(o.port.step, []).append(o)

    def earlier_done(i, done):
        return all(done.get(j) for j in group if group[j] < group[i])

    for env0 in ENVS:
        for order in orders:
            with run_root() as d:
                env = bound(env0, d)
                make_tree(Path(d), tree)

                def check(i, done):
                    if not earlier_done(i, done):
                        return
                    for o in by_step.get(names[i], []):
                        if o.status != "discharged":
                            continue
                        try:
                            path = o.port.expr.render(env)
                        except WendError, ValueError, TypeError:
                            continue
                        assert holds(Fact(o.atom, path)) is not False, (o, path, env0)

                done = run(Path(d), steps, bodies, env, order=order, check=check)
                for i, n in enumerate(names):
                    refuted = [o for o in by_step.get(n, []) if o.status == "refuted"]
                    if refuted and earlier_done(i, done):
                        assert not done[i], (refuted, env0)


@settings(max_examples=150, deadline=None, suppress_health_check=list(HealthCheck))
@given(case=cases)
@example(case=ROOT_REPLACED)
def test_obligations_hold_on_disk_when_run_in_order(case):
    # The oracle: random pipelines over families whose bindings collide, run
    # in a real directory under several bindings. Wherever every earlier step
    # completed, a discharged atom holds when the step starts, and a step
    # with a refuted atom fails.
    _obligations_hold_on_disk(case, staged=False)


@settings(max_examples=150, deadline=None, suppress_health_check=list(HealthCheck))
@given(case=cases)
@example(case=ROOT_REPLACED)
def test_obligations_hold_on_disk_when_run_by_stages(case):
    # The same, by stages(): a step's group-mates may run before or after it.
    _obligations_hold_on_disk(case, staged=True)
