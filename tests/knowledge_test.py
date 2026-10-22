"""wend._experimental.knowledge, run against a real directory: random trees
and random pipelines of steps whose bodies do exactly what they declare.

Checked at every step's entry: every known fact holds on disk (soundness,
under the closed world); a required atom the static analysis says is
refuted makes the step's check fail; and eliding the checks of known atoms
never changes which steps complete or the final tree."""

import shutil
import tempfile
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from wend import (
    Absent,
    Creatable,
    Dir,
    Exists,
    File,
    Listable,
    P,
    Readable,
    Step,
    Writable,
)
from wend._experimental.knowledge import Fact, Knowledge, Tracker, analyse, holds
from wend.errors import ConditionError


# A role: what a port declares, and a body that does exactly that.
def _read(p: Path) -> None:
    p.read_bytes()


def _create(p: Path) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("new")


def _write(p: Path) -> None:
    p.write_text("more")


def _delete(p: Path) -> None:
    if p.is_dir() and not p.is_symlink():
        shutil.rmtree(p)
    else:
        p.unlink()


def _list(p: Path) -> None:
    list(p.iterdir())


def _mkdir(p: Path) -> None:
    p.mkdir(parents=True)


ROLES = {
    "read": ((File, Exists, Readable), (), _read),
    "create": ((Absent, Creatable), (File, Exists), _create),
    "write": ((File, Exists, Writable), (File, Exists), _write),
    "delete": ((Exists,), (Absent,), _delete),
    "list": ((Dir, Exists, Listable), (), _list),
    "mkdir": ((Absent, Creatable), (Dir, Exists), _mkdir),
}
NAMES = ["a", "b", "d", "d/x", "d/y", "e/z", "e/w"]

trees = st.fixed_dictionaries(
    {
        "a": st.sampled_from([None, "file", "dir"]),
        "b": st.sampled_from([None, "file"]),
        "d": st.sampled_from([None, "file", "dir"]),
        "dx": st.booleans(),
    }
)
ports = st.lists(
    st.tuples(st.sampled_from(sorted(ROLES)), st.sampled_from(NAMES)),
    min_size=1,
    max_size=2,
    unique_by=lambda t: t[1],
)
random_pipelines = st.lists(ports, min_size=2, max_size=7)


def _parent(name: str) -> str | None:
    return name.rsplit("/", 1)[0] if "/" in name else None


def _fits(role: str, name: str, model: dict) -> bool:
    kind, parent = model.get(name), _parent(name)
    blocked = parent is not None and model.get(parent) == "file"
    return {
        "read": kind == "file",
        "write": kind == "file",
        "create": kind is None and not blocked,
        "mkdir": kind is None and not blocked,
        "delete": kind is not None,
        "list": kind == "dir",
    }[role]


def _apply(role: str, name: str, model: dict) -> None:
    if role in ("create", "mkdir"):
        parts = name.split("/")
        for i in range(1, len(parts)):
            model.setdefault("/".join(parts[:i]), "dir")
        model[name] = "file" if role == "create" else "dir"
    elif role == "delete":
        for k in [k for k in model if k == name or k.startswith(name + "/")]:
            del model[k]


@st.composite
def modelled(draw, tree):
    """Pipelines whose steps mostly fit the tree as earlier steps leave it
    (one port in five is drawn at random, to keep failures in play)."""
    model = {
        n: k for n, k in (("a", tree["a"]), ("b", tree["b"]), ("d", tree["d"])) if k
    }
    if tree["dx"] and tree["d"] == "dir":
        model["d/x"] = "file"
    out = []
    for _ in range(draw(st.integers(2, 7))):
        step, used = [], set()
        for _ in range(draw(st.integers(1, 2))):
            names = [n for n in NAMES if n not in used]
            if draw(st.integers(0, 4)) == 0:
                role, name = (
                    draw(st.sampled_from(sorted(ROLES))),
                    draw(st.sampled_from(names)),
                )
            else:
                fits = [
                    (r, n) for r in sorted(ROLES) for n in names if _fits(r, n, model)
                ]
                if not fits:
                    break
                role, name = draw(st.sampled_from(fits))
            step.append((role, name))
            used.add(name)
        if step:
            for role, name in step:
                if _fits(role, name, model):
                    _apply(role, name, model)
            out.append(step)
    return out


cases = st.one_of(
    st.tuples(trees, random_pipelines),
    trees.flatmap(lambda t: st.tuples(st.just(t), modelled(t))),
)


def make_tree(root: Path, t: dict) -> None:
    for name in ("a", "b", "d"):
        kind = t[name]
        if kind == "file":
            (root / name).write_text("x")
        elif kind == "dir":
            (root / name).mkdir()
    if t["dx"] and t["d"] == "dir":
        (root / "d" / "x").write_text("x")


def steps_of(root: Path, pipeline) -> list[tuple[str, Step, list]]:
    out = []
    for i, ps in enumerate(pipeline):
        paths, bodies = {}, []
        for j, (role, name) in enumerate(ps):
            pre, post, body = ROLES[role]
            e = P(str(root / name)).requires(*pre)
            if post:
                e = e.ensures(*post)
            paths[f"p{j}"] = e
            bodies.append((f"p{j}", body))
        out.append((f"s{i}", Step(paths), bodies))
    return out


def execute(root: Path, steps, *, elide: bool, honest: bool = True, check=None):
    """Run the steps in order; return which completed and the tracker."""
    t = Tracker(elide=elide)
    completed = []
    for name, step, bodies in steps:
        if check:
            check(t)
        try:
            with t.run(name, step, {}) as p:
                for port, body in bodies:
                    body(p[port])
                if not honest:
                    victim = root / "b"  # an undeclared deletion
                    if victim.is_file():
                        victim.unlink()
        except ConditionError, OSError:
            completed.append(False)
            continue
        completed.append(True)
    return completed, t


def snapshot(root: Path) -> list[tuple[str, str]]:
    return sorted(
        (str(p.relative_to(root)), "dir" if p.is_dir() else "file")
        for p in root.rglob("*")
    )


SETTINGS = settings(
    max_examples=400, deadline=None, suppress_health_check=list(HealthCheck)
)


def all_known_facts_hold(t: Tracker) -> None:
    for f in t.knowledge.facts:
        assert holds(f) is not False, f"known {f} does not hold"


@SETTINGS
@given(cases)
def test_every_known_fact_holds_at_every_entry(case):
    tree, pipeline = case
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        make_tree(root, tree)
        steps = steps_of(root, pipeline)
        execute(root, steps, elide=False, check=all_known_facts_hold)


@SETTINGS
@given(cases)
def test_a_refuted_requirement_fails_and_known_ones_are_what_ran(case):
    tree, pipeline = case
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        make_tree(root, tree)
        steps = steps_of(root, pipeline)
        predicted = analyse([(n, s) for n, s, _ in steps])
        completed, t = execute(root, steps, elide=False)
        by_step = {}
        for e in predicted:
            by_step.setdefault(e.step, []).append(e)
        ran = {(e.step, e.port): e for e in t.entries}
        for i, (name, _, _) in enumerate(steps):
            if not all(completed[:i]):
                break  # the analysis assumes every earlier step completed
            for e in by_step[name]:
                if e.refuted:
                    assert not completed[i], (name, e)
                elif (name, e.port) in ran:
                    assert ran[(name, e.port)].known == e.known


@SETTINGS
@given(cases)
def test_eliding_known_checks_changes_nothing(case):
    tree, pipeline = case
    results = []
    for elide in (False, True):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            make_tree(root, tree)
            steps = steps_of(root, pipeline)
            completed, _ = execute(root, steps, elide=elide)
            results.append((completed, snapshot(root)))
    assert results[0] == results[1]


def test_an_undeclared_effect_breaks_the_closed_world(tmp_path):
    (tmp_path / "b").write_text("x")
    read_b = Step(p0=P(str(tmp_path / "b")).requires(File, Exists, Readable))
    touch_a = Step(
        p0=P(str(tmp_path / "a")).requires(Absent, Creatable).ensures(Exists)
    )
    steps = [("s0", read_b, [("p0", _read)]), ("s1", touch_a, [("p0", _create)])]
    _, t = execute(tmp_path, steps, elide=False, honest=False)
    stale = [f for f in t.knowledge.facts if holds(f) is False]
    assert Fact("exists", str(tmp_path / "b")) in stale  # known, and false


def test_a_mutation_forgets_the_path_its_parents_and_children(tmp_path):
    d = tmp_path / "d"
    d.mkdir()
    (d / "x").write_text("x")
    listed = Step(p0=P(str(d)).requires(Dir, Exists, Listable))
    child = Step(p0=P(str(d / "x")).requires(File, Exists, Readable))
    drop = Step(p0=P(str(d)).requires(Exists).ensures(Absent))
    t = Tracker()
    for name, s in (("l", listed), ("c", child)):
        with t.run(name, s, {}):
            pass
    assert t.knowledge.knows("exists", str(d / "x"))
    with t.run("drop", drop, {}) as p:
        shutil.rmtree(p["p0"])
    assert not t.knowledge.knows("exists", str(d / "x"))
    assert t.knowledge.knows("absent", str(d))


def test_making_a_path_forgets_whether_its_missing_neighbours_are_creatable():
    # mkdir -p of e/z can make e, with permissions that decide whether e/w
    # can be created; e/w is neither above nor below e/z.
    k = Knowledge()
    k.learn(frozenset({"create", "absent"}), "/r/e/w")
    k.learn(frozenset({"create", "absent"}), "/r/a")
    k.forget("/r/e/z")
    assert not k.knows("create", "/r/e/w")
    assert k.knows("absent", "/r/e/w")
    assert not k.knows("create", "/r/a")  # /r is not known to exist either
    k.learn(frozenset({"exists"}), "/r")
    k.learn(frozenset({"create"}), "/r/a")
    k.forget("/r/e/z")
    assert k.knows("create", "/r/a")  # only e may be made now


@pytest.mark.parametrize("missing", [True, False])
def test_file_and_dir_exclude_each_other_only_for_an_existing_path(tmp_path, missing):
    p = tmp_path / "q"
    if not missing:
        p.mkdir()
    t = Tracker()
    with t.run(
        "s",
        Step(x=P(str(p)).requires(Dir) if missing else P(str(p)).requires(Dir, Exists)),
        {},
    ):
        pass
    assert bool(t.knowledge.refutes("file", str(p))) is (not missing)
