"""Directory schemas (wend.schema; docs/SEMANTICS.md §12)."""

import os
import pickle

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from wend import Absolute, Dir, Exists, File, P, Param, PathOperationError, SubPath, T
from wend.infer import infer
from wend.schema import Cardinality, Entry, Tree, from_inferred


index = Param("index", type=int)
split = Param("split", choices={"train", "valid"})


class MLProject(Tree):
    data = Dir("data")
    raw = Dir(data / "raw")
    processed = Dir(data / "processed")
    models = Dir("models")
    checkpoints = File(models / T(t"model-{index:03d}.pt"), many=True, optional=True)
    config = File("config.yaml")


def _rel(problems, root):
    return sorted((p.kind, os.path.relpath(p.path, root), p.entry) for p in problems)


# -- declaring ----------------------------------------------------------------


def test_entries_are_collected_in_order():
    assert list(MLProject.entries) == [
        "data",
        "raw",
        "processed",
        "models",
        "checkpoints",
        "config",
    ]
    e = MLProject.checkpoints
    assert isinstance(e, Entry)
    assert e.kind == "file" and e.cardinality is Cardinality.MANY
    assert MLProject.config.cardinality is Cardinality.ONE
    assert File("x", many=True).cardinality is Cardinality.AT_LEAST_ONE
    assert Dir("x", optional=True).cardinality is Cardinality.OPTIONAL
    assert repr(MLProject.checkpoints) == "File('models/model-{index:03d}.pt', 0..*)"


def test_entries_are_relative_fragments():
    with pytest.raises(ValueError, match="relative"):
        File("/etc/passwd")
    with pytest.raises(ValueError, match="relative"):
        File(P(Absolute("anywhere")))
    with pytest.raises(ValueError):
        File("x", open=True)  # only directories are open
    with pytest.raises(TypeError, match="not a schema entry"):
        Exists("x")
    # a leading parameter is a segment (or a splice) under the root
    assert File(T(t"{Param('name')}.txt")).expr.pattern == "{name}.txt"
    assert File(T(t"{SubPath('rel')}/x.py")).expr.pattern == "{rel...}/x.py"


def test_subclasses_inherit_and_override_entries():
    class WithReadme(MLProject):
        readme = File("README.md", optional=True)
        config = File("config.toml")

    assert list(WithReadme.entries)[-2:] == ["config", "readme"]
    assert WithReadme.entries["config"].expr == P("config.toml")


# -- binding ------------------------------------------------------------------


def test_instances_give_typed_paths_with_conditions():
    proj = MLProject("/srv/p")
    assert proj.config == P("/srv/p/config.yaml")
    assert proj.config.conditions.requires == (File, Exists)  # required and literal
    assert proj.checkpoints.conditions.requires == (File,)
    assert proj.checkpoints.render(index=3) == "/srv/p/models/model-003.pt"
    assert MLProject("/srv/p", index=7).checkpoints == P("/srv/p/models/model-007.pt")
    with pytest.raises(PathOperationError, match="declared a File"):
        proj.config / "x"
    assert repr(MLProject("/srv/p", index=7)) == "MLProject('/srv/p', index=7)"
    assert set(proj.paths()) == set(MLProject.entries)


def test_relations_between_entries_carry_over():
    proj = MLProject("/srv/p")
    assert proj.raw.base == proj.data
    assert proj.raw.derived_from(proj.data)
    moved = proj.raw.rebase(proj.data, P("/scratch/data"))
    assert moved.render() == "/scratch/data/raw"


def test_a_symbolic_root_binds_later():
    root = Param("root")
    proj = MLProject(P(root))
    assert proj.config.pattern == "{root}/config.yaml"
    assert proj.config.render(root="/x") == "/x/config.yaml"


# -- scaffolding and validation -----------------------------------------------


def test_scaffold_then_validate(tmp_path):
    proj = MLProject(tmp_path)
    report = proj.validate()
    assert _rel(report.problems, tmp_path) == [
        ("missing", "config.yaml", "config"),
        ("missing", "data", "data"),
        ("missing", "data/processed", "processed"),
        ("missing", "data/raw", "raw"),
        ("missing", "models", "models"),
    ]
    assert not report
    planned = proj.scaffold(dry_run=True)
    assert not (tmp_path / "data").exists()
    created = proj.scaffold(files=True)
    assert created == planned + [tmp_path / "config.yaml"]
    assert proj.scaffold(files=True) == []  # nothing is overwritten or redone
    assert proj.validate().ok


def test_scaffold_expands_choices_and_skips_free_parameters(tmp_path):
    class Shards(Tree):
        split_dir = Dir(T(t"data/{split}"))
        shards = File(T(t"data/{split}/part-{index:03d}.parquet"), many=True)

    created = Shards(tmp_path).scaffold(files=True)
    assert sorted(p.relative_to(tmp_path).as_posix() for p in created) == [
        "data",
        "data/train",
        "data/valid",
    ]


def test_validate_reports_every_kind_of_problem(tmp_path):
    proj = MLProject(tmp_path)
    proj.scaffold(files=True)
    (tmp_path / "models" / "model-001.pt").write_text("")
    (tmp_path / "models" / "model-7.pt").write_text("")  # not 3 digits
    (tmp_path / "data" / "raw" / "config.yaml").write_text("")  # misfiled
    (tmp_path / "notes").mkdir()
    (tmp_path / "notes" / "todo.txt").write_text("")  # only "notes" is reported
    (tmp_path / "config.yaml").unlink()
    (tmp_path / "config.yaml").mkdir()  # a directory where a file belongs
    report = proj.validate()
    assert _rel(report.problems, tmp_path) == [
        ("extra", "models/model-7.pt", "models"),
        ("extra", "notes", None),
        ("misfiled", "data/raw/config.yaml", "config"),
        ("wrong-kind", "config.yaml", "config"),
    ]
    assert [os.path.basename(m.path) for m in report.matches["checkpoints"]] == [
        "model-001.pt"
    ]
    assert "1 misfiled" in repr(report)


def test_cardinality_is_counted_per_parent_directory(tmp_path):
    run = Param("run", type=int)

    class Runs(Tree):
        runs = Dir(T(t"runs/{run}"), many=True)
        config = File(T(t"runs/{run}/config.json"))
        ckpt = File(T(t"runs/{run}/ckpt-{index}.pt"), many=True)

    for r, files in {1: ["config.json", "ckpt-1.pt"], 2: ["ckpt-1.pt"]}.items():
        (tmp_path / "runs" / str(r)).mkdir(parents=True)
        for f in files:
            (tmp_path / "runs" / str(r) / f).write_text("")
    (tmp_path / "runs" / "3").mkdir()
    report = Runs(tmp_path).validate()
    assert _rel(report.problems, tmp_path) == [
        ("missing", "runs/2/config.json", "config"),
        ("missing", "runs/3/ckpt-{index}.pt", "ckpt"),
        ("missing", "runs/3/config.json", "config"),
    ]

    class OneCkpt(Runs):
        ckpt = File(T(t"runs/{run}/ckpt-{index}.pt"), optional=True)

    (tmp_path / "runs" / "1" / "ckpt-2.pt").write_text("")
    problems = OneCkpt(tmp_path).validate().of("too-many")
    assert [(os.path.relpath(p.path, tmp_path), p.entry) for p in problems] == [
        ("runs/1", "ckpt")
    ]


def test_open_directories_ignore_patterns_and_hidden_names(tmp_path):
    class Repo(Tree):
        src = Dir("src", open=True)
        readme = File("README.md")
        ignore = (".git",)

    (tmp_path / "src" / "deep").mkdir(parents=True)
    (tmp_path / "src" / "deep" / "x.py").write_text("")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "HEAD").write_text("")
    (tmp_path / ".env").write_text("")
    (tmp_path / "README.md").write_text("")
    assert _rel(Repo(tmp_path).validate().problems, tmp_path) == [
        ("extra", ".env", None)
    ]

    class Quiet(Repo):
        hidden = False

    assert Quiet(tmp_path).validate().ok


def test_symlinks_count_by_target_and_are_not_followed(tmp_path):
    class Links(Tree):
        data = Dir("data")
        current = File("current.csv")

    (tmp_path / "real").mkdir()
    (tmp_path / "real" / "a.csv").write_text("")
    os.symlink(tmp_path / "real", tmp_path / "data")
    os.symlink(tmp_path / "real" / "a.csv", tmp_path / "current.csv")
    os.symlink("/", tmp_path / "escape")  # never descended, never reported
    report = Links(tmp_path).validate()
    assert _rel(report.problems, tmp_path) == [("extra", "real", None)]


def test_a_missing_root_is_one_problem(tmp_path):
    report = MLProject(tmp_path / "nowhere").validate()
    assert [p.kind for p in report.problems] == ["missing"]


# -- inference round trip and source ------------------------------------------


def _tree(tmp_path, files, dirs=()):
    for f in files:
        p = tmp_path / f
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("")
    for d in dirs:
        (tmp_path / d).mkdir(parents=True, exist_ok=True)


def test_an_inferred_schema_validates_its_tree(tmp_path):
    _tree(
        tmp_path,
        [f"data/{s}/part-{i:03d}.parquet" for s in ("train", "valid") for i in range(4)]
        + [f"checkpoints/run_{r}/epoch_{e:02d}.pt" for r in (1, 2) for e in range(3)]
        + ["README.md", "checkpoints/run_1/notes.txt"],
    )
    schema = infer(tmp_path)
    cls = from_inferred(schema, "Inferred")
    assert cls(tmp_path).validate().ok
    source = cls.source()
    ns: dict = {}
    exec(source, ns)  # noqa: S102 - the source is generated above
    assert ns["Inferred"](tmp_path).validate().ok
    assert "class Inferred(Tree):" in source and "hidden = False" in source
    # and a new, unexpected file is reported against the same declaration
    (tmp_path / "data" / "train" / "part_7.parquet").write_text("")
    problems = ns["Inferred"](tmp_path).validate().problems
    assert [(p.kind, os.path.basename(p.path)) for p in problems] == [
        ("extra", "part_7.parquet")
    ]


def test_source_round_trips_declared_schemas():
    ns: dict = {}
    exec(MLProject.source(), ns)  # noqa: S102
    again = ns["MLProject"]
    assert list(again.entries) == list(MLProject.entries)
    for name, entry in MLProject.entries.items():
        other = again.entries[name]
        assert other.expr == entry.expr
        assert (other.kind, other.cardinality) == (entry.kind, entry.cardinality)


def test_schema_classes_and_entries_pickle_by_reference():
    proj = MLProject("/srv/p")
    assert pickle.loads(pickle.dumps(proj.config)) == proj.config


names = st.sampled_from(["a", "b", "img_01.png", "img_02.png", "x.csv", "readme"])
dirs = st.sampled_from(["", "d1", "d2", "d1/sub", "data/train", "data/valid"])


@settings(max_examples=60, deadline=None, suppress_health_check=list(HealthCheck))
@given(st.lists(st.tuples(dirs, names), min_size=1, max_size=25, unique=True))
def test_inferred_schemas_validate_random_trees(tmp_path_factory, entries):
    tmp = tmp_path_factory.mktemp("tree")
    _tree(tmp, [f"{d}/{n}" if d else n for d, n in entries])
    cls = from_inferred(infer(tmp))
    report = cls(tmp).validate()
    assert report.ok, report
    ns: dict = {}
    exec(cls.source(), ns)  # noqa: S102
    assert ns["Inferred"](tmp).validate().ok


def test_a_recursive_entry_is_satisfied_below_a_directory(tmp_path):
    class Pkg(Tree):
        modules = File(T(t"src/{SubPath('rel')}/{Param('stem')}.py"), many=True)

    _tree(tmp_path, ["src/a.py", "src/pkg/sub/b.py"])
    # src/pkg holds only a directory, but a module lies below it
    assert Pkg(tmp_path).validate().ok
    (tmp_path / "src" / "empty").mkdir()
    problems = Pkg(tmp_path).validate().problems
    assert [(p.kind, os.path.relpath(p.path, tmp_path)) for p in problems] == [
        ("missing", "src/empty/{stem}.py"),
        ("extra", "src/empty"),  # nothing describes an empty directory either
    ]
