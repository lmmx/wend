"""wend._experimental.families against the disk: random pipelines over path
families whose bindings can collide, analysed once before any binding
exists, then run under several shared bindings in a real directory.

At every step whose predecessors completed: every atom the analysis knows
holds on disk for that binding; a refuted atom makes the step fail; and two
adjacent steps the analysis calls independent give the same outcomes and
the same tree in either order."""

import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from hypothesis import HealthCheck, example, given, settings
from hypothesis import strategies as st
from knowledge_test import ROLES, _apply, _fits, snapshot

from wend import Dir, Exists, Listable, P, Param, Step, SubPath, T
from wend._experimental.families import (
    FamilyKnowledge,
    analyse_families,
    coincide,
    independent,
    must_equal,
    relation,
    snapshots,
)
from wend._experimental.knowledge import Fact, Tracker, holds
from wend.errors import ConditionError, WendError


root, day, name, base = Param("root"), Param("day"), Param("name"), Param("base")
FAMILIES = {
    "raw_day": P(root) / "raw" / T(t"{day}.csv"),
    # the same family, built another way and with day declared str
    "raw_day2": (P(root) / "raw").joinpath(T(t"{Param('day', type=str)}.csv")),
    "raw_name": P(root) / "raw" / T(t"{name}.csv"),
    "out_day": P(root) / "out" / T(t"{day}.parquet"),
    "raw": P(root) / "raw",
    "out": P(root) / "out",
    "deep": P(root) / "tmp" / T(t"{day}") / "x",
    "top": P(root) / T(t"{name}"),  # the raw directory when name is "raw"
    "sub": P(root) / "raw" / SubPath("rel"),  # raw itself when rel is empty
    # another head: raw_day when base is the raw directory
    "base_day": P(base) / T(t"{day}.csv"),
    # deferred (overlap says MAYBE): raw_name, by another route
    "via_suffix": (P(root) / "raw" / T(t"{name}.tmp")).with_suffix(".csv"),
    # MAYBE against sub, and above it when name is raw
    "up": (P(root) / T(t"{name}") / SubPath("rel")).parent,
    # day defaulted two ways: different paths where day is unbound
    "raw_dmon": P(root) / "raw" / T(t"{Param('day', default='mon')}.csv"),
    "raw_dtue": P(root) / "raw" / T(t"{Param('day', default='tue')}.csv"),
}
ENVS = [
    {"day": "mon", "name": "a", "rel": "q/z", "base": "."},
    # raw_name and via_suffix are raw_day; sub is too; base_day is too
    {"day": "mon", "name": "mon", "rel": "mon.csv", "base": "raw"},
    {"day": "tue", "name": "raw", "rel": ".", "base": "out"},  # top is raw; sub is raw
    {
        "name": "tue",
        "rel": "tue.csv",
        "base": "raw",
    },  # day unbound: the defaults differ
]


@contextmanager
def run_root() -> Iterator[str]:
    """A run's root, one level below the directory that is cleaned up. A
    pipeline may delete its root and make a file in its place (ROOT_REPLACED):
    the cleanup must not depend on what the run left there."""
    with tempfile.TemporaryDirectory() as d:
        root = Path(d) / "root"
        root.mkdir()
        yield str(root)


def bound(env0: dict, d: str) -> dict:
    env = {**env0, "root": d}
    if "base" in env:
        env["base"] = str(Path(d) / env["base"])
    return env


ports = st.lists(
    st.tuples(st.sampled_from(sorted(ROLES)), st.sampled_from(sorted(FAMILIES))),
    min_size=1,
    max_size=2,
    unique_by=lambda t: t[1],
)
pipelines = st.lists(ports, min_size=1, max_size=6)
trees = st.fixed_dictionaries(
    {
        "raw": st.booleans(),
        "out": st.booleans(),
        "files": st.lists(
            st.sampled_from(["raw/mon.csv", "raw/tue.csv", "out/mon.parquet", "a"]),
            unique=True,
        ),
    }
)

SURVEY = Step(r=P(root).requires(Dir, Exists, Listable))


def _rel(fam: str, env: dict) -> str:
    out = FAMILIES[fam].render({**env, "root": "R", "base": "R/" + env["base"]})
    return out[2:] if out.startswith("R/") else out


@st.composite
def modelled(draw):
    """A tree, and a pipeline that mostly fits it as earlier steps leave it
    under the first binding (one port in five at random); the other
    bindings are where families collide."""
    tree = draw(trees)
    model = {d: "dir" for d in ("raw", "out") if tree["raw" if d == "raw" else "out"]}
    for f in tree["files"]:
        parent = f.rsplit("/", 1)[0] if "/" in f else None
        if parent is None or model.get(parent) == "dir":
            model[f] = "file"
    env = ENVS[0]
    pipeline = []
    for _ in range(draw(st.integers(1, 6))):
        step, used = [], set()
        for _ in range(draw(st.integers(1, 2))):
            if draw(st.integers(0, 4)) == 0:
                choice = (
                    draw(st.sampled_from(sorted(ROLES))),
                    draw(st.sampled_from(sorted(FAMILIES))),
                )
            else:
                fits = [
                    (r, f)
                    for r in sorted(ROLES)
                    for f in sorted(FAMILIES)
                    if _rel(f, env) not in used and _fits(r, _rel(f, env), model)
                ]
                if not fits:
                    break
                choice = draw(st.sampled_from(fits))
            if _rel(choice[1], env) in used:
                continue
            step.append(choice)
            used.add(_rel(choice[1], env))
        for r, f in step:
            if _fits(r, _rel(f, env), model):
                _apply(r, _rel(f, env), model)
        if step:
            pipeline.append(step)
    return pipeline, tree


cases = st.one_of(st.tuples(pipelines, trees), modelled())


def build(pipeline):
    steps, bodies = [("survey", SURVEY)], [[]]
    for i, ps in enumerate(pipeline):
        paths, b = {}, []
        for j, (role, fam) in enumerate(ps):
            pre, post, body = ROLES[role]
            e = FAMILIES[fam].requires(*pre)
            if post:
                e = e.ensures(*post)
            paths[f"p{j}"] = e
            b.append((f"p{j}", body))
        steps.append((f"s{i}", Step(paths)))
        bodies.append(b)
    return steps, bodies


def make_tree(root_dir: Path, t: dict) -> None:
    for d in ("raw", "out"):
        if t[d]:
            (root_dir / d).mkdir()
    for f in t["files"]:
        p = root_dir / f
        if p.parent.is_dir() or p.parent == root_dir:
            p.write_text("x")


def run(root_dir, steps, bodies, env, order=None, check=None):
    order = order or list(range(len(steps)))
    t = Tracker()
    done = {}
    for i in order:
        name_, step = steps[i]
        if check:
            check(i, done)
        try:
            with t.run(name_, step, env) as p:
                for port, body in bodies[i]:
                    body(p[port])
        except ConditionError, OSError, WendError:
            done[i] = False
            continue
        done[i] = True
    return done


SETTINGS = settings(
    max_examples=250, deadline=None, suppress_health_check=list(HealthCheck)
)


# Found by a full-suite run (research index, "the intermittent failure"):
# where name is "raw" and rel is ".", "up" renders to the run's root, so the
# pipeline deletes its root and creates a file in its place.
ROOT_REPLACED = (
    [[("create", "base_day"), ("delete", "up")], [("create", "up")]],
    {"raw": False, "out": False, "files": []},
)


@SETTINGS
@given(cases)
@example(case=ROOT_REPLACED)
def test_what_the_analysis_knows_holds_and_what_it_refutes_fails(case):
    pipeline, tree = case
    steps, bodies = build(pipeline)
    entries = analyse_families(steps)
    by_step: dict[str, list] = {}
    for e in entries:
        by_step.setdefault(e.step, []).append(e)
    for env0 in ENVS:
        with run_root() as d:
            env = bound(env0, d)
            make_tree(Path(d), tree)

            def check(i, done):
                if not all(done.get(j) for j in range(i)):
                    return
                for e in by_step[steps[i][0]]:
                    try:
                        path = e.expr.render(env)
                    except WendError, ValueError, TypeError:
                        continue
                    for atom in e.known:
                        assert holds(Fact(atom, path)) is not False, (
                            steps[i][0],
                            atom,
                            path,
                            env0,
                        )

            done = run(Path(d), steps, bodies, env, check=check)
            for i, (n, _) in enumerate(steps):
                if all(done.get(j) for j in range(i)) and any(
                    e.refuted for e in by_step[n]
                ):
                    assert not done[i], (n, env0)


@SETTINGS
@given(cases)
@example(case=ROOT_REPLACED)
def test_adjacent_independent_steps_commute(case):
    pipeline, tree = case
    steps, bodies = build(pipeline)
    ks = snapshots(steps)
    for i in range(1, len(steps) - 1):
        if not independent(steps[i][1], steps[i + 1][1], ks[i]):
            continue
        order = list(range(len(steps)))
        order[i], order[i + 1] = order[i + 1], order[i]
        for env0 in ENVS:
            results = []
            for o in (None, order):
                with run_root() as d:
                    env = bound(env0, d)
                    make_tree(Path(d), tree)
                    done = run(Path(d), steps, bodies, env, order=o)
                    results.append((done, snapshot(Path(d))))
            (d1, t1), (d2, t2) = results
            if not all(d1.get(j) for j in range(i)):
                continue  # independence was judged assuming these completed
            assert d1 == d2 and t1 == t2, (steps[i][0], steps[i + 1][0], env0)


def test_must_equal_sees_through_construction_and_declaration():
    assert must_equal(FAMILIES["raw_day"], FAMILIES["raw_day2"])
    assert not must_equal(FAMILIES["raw_day"], FAMILIES["raw_name"])


def test_relations_under_shared_bindings():
    f = FAMILIES
    assert relation(f["raw_day"], f["out_day"]) == "no"
    assert coincide(f["raw_day"], f["raw_name"]) == "yes"  # when name == day
    assert relation(f["raw"], f["raw_day"]) == "yes"  # above it
    assert coincide(f["sub"], f["raw"]) == "maybe"  # an empty SubPath
    assert relation(f["out"], f["deep"]) == "no"


def _facts_after(steps):
    return snapshots(steps + [("end", Step())])[-1]


def test_a_mutation_related_only_by_maybe_still_forgets(tmp_path):
    # up and sub are MAYBE-related, and up is above sub when name is raw: a
    # deletion of up must forget what was known about sub.
    from wend import Absent as Gone
    from wend import Exists

    k = _facts_after(
        [
            ("read", Step(x=FAMILIES["sub"].requires(Exists))),
            ("drop", Step(x=FAMILIES["up"].requires(Exists).ensures(Gone))),
        ]
    )
    assert not k.knows("exists", FAMILIES["sub"])


def test_different_defaults_are_different_paths():
    from wend import Absent, Creatable, Exists, File, Readable

    steps = [
        (
            "make",
            Step(
                x=FAMILIES["raw_dmon"].requires(Absent, Creatable).ensures(File, Exists)
            ),
        ),
        ("read", Step(x=FAMILIES["raw_dtue"].requires(File, Exists, Readable))),
    ]
    (entry,) = [e for e in analyse_families(steps) if e.step == "read"]
    assert entry.known == frozenset()  # tue.csv, where day is unbound


# -- what the analysis knows, not only that it is sound ----------------------
#
# Every property above checks soundness: what is known is true. An analysis
# that learns nothing passes them all (found by the journal audit). These
# tests pin down what the analysis does know, refute and find independent,
# and the two rules no generated property could reach.


def _worked_pipeline():
    from wend import Absent, Creatable, File, Readable

    def reads(e):
        return e.requires(File, Exists, Readable)

    def makes(e):
        return e.requires(Absent, Creatable).ensures(File, Exists)

    raw = P(root) / "raw" / T(t"{day}.csv")
    features = P(root) / "features" / T(t"{day}.parquet")
    return [
        ("survey", Step(root=P(root).requires(Dir, Exists, Listable))),
        (
            "ingest",
            Step(src=reads(P(root) / "inbox" / T(t"{day}.csv")), dst=makes(raw)),
        ),
        ("validate", Step(src=reads(raw))),
        ("featurise", Step(src=reads(raw), dst=makes(features))),
        ("train", Step(all=(P(root) / "features").requires(Dir, Exists, Listable))),
        (
            "report",
            Step(src=reads(features), dst=makes(P(root) / "reports" / T(t"{day}.md"))),
        ),
        ("cleanup", Step(raw=raw.requires(Exists).ensures(Absent))),
        ("audit", Step(src=reads(raw))),
    ]


def test_the_worked_pipeline_knows_refutes_and_commutes_what_its_table_shows():
    # docs/journal/scripts/2026-10-22-families-demo.py prints this table
    steps = _worked_pipeline()
    got = {
        (e.step, e.port): (set(e.known), set(e.refuted))
        for e in analyse_families(steps)
    }
    nothing: tuple[set[str], set[str]] = (set(), set())
    assert got == {
        ("survey", "root"): nothing,
        ("ingest", "src"): nothing,
        ("ingest", "dst"): nothing,
        ("validate", "src"): ({"exists", "file"}, set()),
        ("featurise", "src"): ({"exists", "file", "read"}, set()),
        ("featurise", "dst"): nothing,
        ("train", "all"): ({"dir", "exists"}, set()),
        ("report", "src"): ({"exists", "file"}, set()),
        ("report", "dst"): nothing,
        ("cleanup", "raw"): ({"exists"}, set()),
        ("audit", "src"): (set(), {"exists", "read"}),
    }
    ks = snapshots(steps)
    commute = {
        (steps[i][0], steps[i + 1][0])
        for i in range(len(steps) - 1)
        if independent(steps[i][1], steps[i + 1][1], ks[i])
    }
    assert commute == {
        ("validate", "featurise"),
        ("train", "report"),
        ("report", "cleanup"),
    }


def test_making_a_path_forgets_creatability_below_the_parents_it_may_make():
    beside = P(root) / "a" / T(t"{day}.txt")
    k = FamilyKnowledge()
    k.learn(frozenset({"create"}), beside)
    k.forget(P(root) / "a" / "b" / T(t"{day}.csv"))  # may make {root}/a
    assert not k.knows("create", beside)
    k = FamilyKnowledge()
    k.learn(frozenset({"exists", "dir"}), P(root) / "a")
    k.learn(frozenset({"create"}), beside)
    k.forget(P(root) / "a" / "b" / T(t"{day}.csv"))  # {root}/a exists: not made
    assert k.knows("create", beside)


def test_independence_sees_the_parents_a_creation_may_make():
    from wend import Absent, Creatable, File

    def makes(e):
        return e.requires(Absent, Creatable).ensures(File, Exists)

    deep = Step(dst=makes(P(root) / "a" / "b" / T(t"{day}.csv")))
    beside = Step(dst=makes(P(root) / "a" / T(t"{day}.txt")))
    # Making the deep file may make {root}/a, on which creating the other
    # depends: their order can matter.
    assert not independent(deep, beside)
    k = FamilyKnowledge()
    k.learn(frozenset({"exists", "dir"}), P(root) / "a")
    assert independent(deep, beside, k)
