import os
import random
import tempfile
from collections import Counter
from pathlib import Path

from hypothesis import HealthCheck, example, given, settings
from hypothesis import strategies as st

from wend import P
from wend._expr import REL, PathExpr, Splice
from wend.infer import Cardinality, _int_spec, _tokens, infer


def test_dataset_shards_generalise():
    paths = [
        f"data/{split}/chunk_{i:04d}.parquet"
        for split in ("train", "validation")
        for i in (1, 2, 3)
    ]
    schema = infer(paths)
    [lay] = schema.layouts
    assert lay.expr.pattern == "data/{data}/chunk_{chunk:04d}.parquet"
    assert lay.count == 6
    assert lay.fields["chunk"].min == 1 and lay.fields["chunk"].max == 3
    assert set(lay.fields["data"].sample) == {"train", "validation"}
    # the inferred layout is an ordinary expression: resolve, match, rename
    assert lay.expr.render(data="test", chunk=9) == "data/test/chunk_0009.parquet"
    named = lay.rename(data="split")
    assert named.expr.pattern == "data/{split}/chunk_{chunk:04d}.parquet"
    assert named.match("data/x/chunk_0042.parquet") == {"split": "x", "chunk": 42}


def test_singletons_generalise_through_merged_parents():
    paths = [
        "d/train/chunk_0001.bin",
        "d/train/chunk_0002.bin",
        "d/valid/chunk_0001.bin",
    ]
    assert [lay.expr.pattern for lay in infer(paths).layouts] == [
        "d/{d}/chunk_{chunk:04d}.bin"
    ]


def test_constant_runs_stay_literal_and_varying_runs_become_fields():
    paths = [f"shard-{i:05d}-of-00010.arrow" for i in range(10)]
    [lay] = infer(paths).layouts
    assert lay.expr.pattern == "shard-{shard:05d}-of-00010.arrow"


def test_optional_entries_are_flagged():
    paths = ["runs/run_1/model.pt", "runs/run_2/model.pt", "runs/run_2/notes.txt"]
    layouts = {lay.expr.pattern: lay for lay in infer(paths).layouts}
    assert not layouts["runs/run_{run:d}/model.pt"].optional
    notes = layouts["runs/run_{run:d}/notes.txt"]
    assert notes.optional and notes.fields["run"].sample == (2,)


def test_records_stay_records():
    paths = ["README.md", "pyproject.toml", "src/pkg/__init__.py", "tests/test_x.py"]
    pats = sorted(lay.expr.pattern for lay in infer(paths).layouts)
    assert pats == [
        "README.md",
        "pyproject.toml",
        "src/pkg/__init__.py",
        "tests/test_x.py",
    ]


def test_files_sharing_an_extension_become_a_map():
    paths = ["docs/intro.md", "docs/usage.md", "docs/api.md", "docs/logo.svg"]
    pats = sorted(lay.expr.pattern for lay in infer(paths).layouts)
    assert pats == ["docs/logo.svg", "docs/{stem}.md"]
    assert infer(paths, min_files=4).layouts[0].expr.pattern.startswith("docs/")


def test_int_spec_inference():
    assert _int_spec(["1", "12", "0"]) == "d"
    assert _int_spec(["001", "012", "123"]) == "03d"
    assert _int_spec(["001", "1234"]) == "03d"
    assert _int_spec(["01", "001"]) is None
    # one width wider than a digit reads as padding: IMG_1234 is IMG_{n:04d}
    assert _int_spec(["1234", "5678"]) == "04d"
    assert _int_spec(["7", "8"]) == "d"


def test_irregular_padding_is_split_out_not_stringified():
    paths = [f"ckpt/epoch_{e:03d}.pt" for e in range(1, 11)] + ["ckpt/epoch_7.pt"]
    pats = sorted(lay.expr.pattern for lay in infer(paths).layouts)
    assert pats == ["ckpt/epoch_7.pt", "ckpt/epoch_{epoch:03d}.pt"]


def test_sparse_partitions_join_one_map():
    # Hive-style partitions where some directories hold too few files to
    # generalise on their own, under names with no shared skeleton.
    names = iter(["ab12cd", "x9yz", "q1w2e3", "zz7", "m0n1", "k4", "r2d2c3", "pp9q"])
    paths = []
    for d in (1, 2, 3, 4):
        for _ in range(1 if d % 2 else 3):
            paths.append(f"events/day={d:02d}/part-{next(names)}.parquet")
    pats = [lay.expr.pattern for lay in infer(paths).layouts]
    assert pats == ["events/day={day:02d}/{stem}.parquet"]


def test_repeated_fields_become_one_parameter():
    synsets = ["n01440764", "n01443537", "n01484850"]
    paths = [f"train/{s}/{s}_{i}.JPEG" for s in synsets for i in (10026, 10027, 9)]
    schema = infer(paths)
    [lay] = schema.layouts
    assert lay.expr.pattern == "train/n{n:08d}/n{n:08d}_{n3:d}.JPEG"
    assert schema.check(["train/n01440764/n01443537_5.JPEG"]) != []
    pkgs = ["alpha", "beta", "gamma", "delta"]
    paths = [f"pkgs/{p}/{p}.txt" for p in pkgs] + [f"pkgs/{p}/data.bin" for p in pkgs]
    pats = sorted(lay.expr.pattern for lay in infer(paths).layouts)
    assert pats == ["pkgs/{pkgs}/data.bin", "pkgs/{pkgs}/{pkgs}.txt"]


def test_infer_from_directory(tmp_path):
    for split in ("a", "b"):
        for i in range(3):
            p = tmp_path / "data" / split / f"part-{i}.csv"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.touch()
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "HEAD").touch()
    (tmp_path / "empty").mkdir()
    schema = infer(tmp_path)
    pats = {lay.expr.pattern: lay.kind for lay in schema.layouts}
    assert pats == {"data/{data}/part-{part:d}.csv": "file", "empty": "dir"}
    lay = next(lay for lay in schema.layouts if lay.kind == "file")
    found = list(lay.under(tmp_path).glob())
    assert len(found) == 6


segment = st.text(alphabet="ab_.-", min_size=1, max_size=4).filter(
    lambda s: s not in (".", "..")
)
number = st.builds(lambda n, w: f"{n:0{w}d}", st.integers(0, 1200), st.integers(1, 5))
name = st.one_of(
    segment,
    number,
    st.builds(lambda a, n, b: f"{a}{n}{b}", segment, number, segment),
    st.builds(lambda a, n, b, m: f"{a}{n}{b}{m}", segment, number, segment, number),
)


@st.composite
def observed_trees(draw):
    """Relative paths as given to `infer`, a trailing "/" marking a directory.

    A path that is a prefix of another is a directory: listed with its "/"
    (a directory that holds paths) or left out. A listed directory that is a
    prefix of nothing is an empty directory.
    """
    paths = draw(
        st.lists(
            st.lists(name, min_size=1, max_size=4).map("/".join),
            min_size=1,
            max_size=40,
            unique=True,
        )
    )
    out = []
    for p in paths:
        if draw(st.booleans()):
            out.append(p + "/")
        elif not any(q.startswith(p + "/") for q in paths):
            out.append(p)
    return out


@settings(max_examples=300, deadline=None)
@example(["0/_", "00/_", "1/_"])  # "00" is not an instance of {n:d}
@example(["a/examples", "b/examples", "a/y", "b/y", "c/y", "c/examples/"])
@example(["r/run_1/m.pt", "r/run_2/m.pt", "r/run_3/", "r/"])
@given(observed_trees())
def test_every_observed_path_is_covered_by_its_kind(entries):
    _check_schema(entries, infer(entries))


def _observed(entries):
    """(path, is_dir) pairs of paths given to `infer`."""
    return [(e.rstrip("/"), e.endswith("/")) for e in entries]


def _mine(lay, observed):
    """The observed paths of the layout's kind that the layout matches."""
    return [
        p for p, d in observed if d == (lay.kind == "dir") and lay.match(p) is not None
    ]


def _check_schema(entries, schema):
    """The properties every inferred schema has over its observed paths.

    ``entries`` are paths as given to `infer` (a trailing "/" marks a
    directory). Each observed path is covered by a layout of its own kind, and
    the layouts' counts partition the observed paths of each kind.
    """
    observed = _observed(entries)
    assert schema.check(entries) == []
    assert schema.check(observed) == []
    for p, d in observed:
        kind = "dir" if d else "file"
        assert any(
            lay.kind == kind and lay.match(p) is not None for lay in schema.layouts
        ), (p, kind)
    assert schema.total == len(observed)
    for kind in ("file", "dir"):
        counted = sum(lay.count for lay in schema.layouts if lay.kind == kind)
        assert counted == sum(d == (kind == "dir") for _, d in observed)
    patterns = [(lay.expr.pattern, lay.kind) for lay in schema.layouts]
    assert len(patterns) == len(set(patterns))
    # Observed directories: listed ones and those holding an observed path.
    dirs = {p for p, d in observed if d} | {
        "/".join(p.split("/")[:i])
        for p, _ in observed
        for i in range(1, p.count("/") + 1)
    }
    for lay in schema.layouts:
        assert lay.kind in ("file", "dir")
        assert lay.expr.is_absolute() is False
        assert P("/root") / lay.expr == lay.under("/root")
        mine = _mine(lay, observed)
        # a layout counts observed paths of its kind that it matches
        assert 0 < lay.count <= len(mine)
        assert lay.optional == _optional_oracle(lay, mine, dirs)
        assert lay.cardinality == _cardinality_oracle(lay, mine, dirs)


def _optional_oracle(lay, mine, dirs):
    """Some directory matching a proper prefix of the pattern holds none of its paths.

    ``mine`` are the layout's paths: the observed paths of its kind that it
    matches. A prefix ending in a SubPath matches directories at any depth.
    """
    for j in range(1, len(lay.expr.parts)):
        prefix = PathExpr(REL, lay.expr.parts[:j])
        for d in dirs:
            if prefix.match(d) is None:
                continue
            if not any(f.startswith(d + "/") for f in mine):
                return True
    return False


def _cardinality_oracle(lay, mine, dirs):
    """Lower bound from the optional oracle; upper bound: some directory holds two."""
    many = any(c > 1 for c in Counter(f.rpartition("/")[0] for f in mine).values())
    if _optional_oracle(lay, mine, dirs):
        return Cardinality.MANY if many else Cardinality.OPTIONAL
    return Cardinality.AT_LEAST_ONE if many else Cardinality.ONE


def test_infer_rejects_a_missing_directory(tmp_path):
    import pytest

    with pytest.raises(NotADirectoryError):
        infer(tmp_path / "missing")


def test_non_ascii_digits_are_not_numeric_runs():
    paths = ["a٣.txt", "a٤.txt", "a٥.txt"]
    schema = infer(paths)
    assert schema.check(paths) == []
    assert all(
        "{" not in lay.expr.pattern or ":d" not in lay.expr.pattern
        for lay in schema.layouts
    )


def test_file_and_directory_conflicts_are_rejected():
    import pytest

    with pytest.raises(ValueError, match="file and as a directory"):
        infer(["a", "a/b"])
    with pytest.raises(ValueError, match="file and as a directory"):
        infer(["a/b", "a"])


# -- cardinality --------------------------------------------------------------


def test_cardinality_per_directory():
    paths = [f"runs/run_{r}/model.pt" for r in (1, 2, 3)]
    paths += ["runs/run_2/notes.txt"]
    paths += [f"runs/run_{r}/ckpt/step_{s}.pt" for r in (1, 2) for s in (10, 20)]
    paths += [f"runs/run_{r}/log_{d}.txt" for r in (1, 2, 3) for d in (1, 2)]
    lays = {lay.expr.pattern: lay for lay in infer(paths).layouts}
    model = lays["runs/run_{run:d}/model.pt"]
    assert model.cardinality is Cardinality.ONE and not model.optional
    notes = lays["runs/run_{run:d}/notes.txt"]
    assert notes.cardinality is Cardinality.OPTIONAL and notes.optional
    logs = lays["runs/run_{run:d}/log_{log:d}.txt"]
    assert logs.cardinality is Cardinality.AT_LEAST_ONE and not logs.optional
    steps = lays["runs/run_{run:d}/ckpt/step_{step:02d}.pt"]
    assert steps.cardinality is Cardinality.MANY and steps.optional
    assert Cardinality.MANY.value == "0..*" and "1..*" in repr(logs)
    # renaming keeps the flags
    assert model.rename(run="r").cardinality is Cardinality.ONE
    assert logs.rename(run="r").cardinality is Cardinality.AT_LEAST_ONE


# -- kinds --------------------------------------------------------------------


def _make(root, entries):
    """Create ``entries`` below ``root``; a trailing "/" makes a directory."""
    for e in entries:
        p = Path(root, e)
        if e.endswith("/"):
            p.mkdir(parents=True, exist_ok=True)
        else:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.touch()


def test_empty_directories_named_like_files_elsewhere():
    # a/examples and b/examples are files; c/examples and d/examples are empty
    # directories, in package directories alike enough to form one map.
    entries = [f"{p}/{f}" for p in "abcd" for f in ("copyright", "README", "log.gz")]
    entries += ["a/examples", "b/examples", "c/examples/", "d/examples/"]
    schema = infer(entries)
    _check_schema(entries, schema)
    lays = {(lay.expr.pattern, lay.kind): lay for lay in schema.layouts}
    names, examples = lays["{dir}/{name}", "file"], lays["{dir}/examples", "dir"]
    assert names.count == 10 and examples.count == 2
    assert examples.cardinality is Cardinality.OPTIONAL
    assert examples.fields["dir"].sample == ("c", "d")
    # a path matches layouts of either kind; given its kind, only its own
    assert [lay for lay, _ in schema.match("c/examples")] == [names, examples]
    assert [lay for lay, _ in schema.match("c/examples", kind="dir")] == [examples]
    assert [lay for lay, _ in schema.match("c/examples/")] == [examples]
    assert [lay for lay, _ in schema.match("a/examples", kind="file")] == [names]
    assert schema.check(["c/examples/", ("d/examples", True), "a/examples"]) == []
    assert schema.check([("a/copyright", True), ("b/examples/x", False)]) == [
        "a/copyright",
        "b/examples/x",
    ]
    # a path without a kind is checked against layouts of either kind
    assert schema.check(["e/examples"]) == []


def test_empty_example_directories_in_a_walk(tmp_path):
    # /usr/share/doc: package directories of extensionless files, some with an
    # empty examples/ directory and some with files in it.
    entries = []
    pkgs = ["apt", "bc", "sed", "nano", "mawk", "lsof", "sudo", "procps"]
    for i, pkg in enumerate(pkgs):
        entries += [f"{pkg}/{f}" for f in ("copyright", "README", "NEWS", "log.gz")]
        if i % 3 == 0:
            entries.append(f"{pkg}/examples/")
        elif i % 3 == 1:
            entries += [f"{pkg}/examples/demo.sh", f"{pkg}/examples/run.sh"]
    _make(tmp_path, entries)
    schema = infer(tmp_path)
    _check_schema(entries, schema)
    [(lay, m)] = schema.match("apt/examples", kind="dir")
    assert (lay.expr.pattern, lay.kind, lay.count) == ("{dir}/examples", "dir", 3)
    assert m == {"dir": "apt"}
    assert {m.path for m in lay.under(tmp_path).glob(kind="dir")} >= {
        str(tmp_path / p / "examples") for p in ("apt", "nano", "sudo")
    }
    [(names, _)] = schema.match("apt/examples", kind="file")
    assert (names.expr.pattern, names.count) == ("{dir}/{name}", 24)


def test_empty_directory_in_a_family_of_directories():
    # run_3 shares a skeleton with run_1 and run_2, which hold files
    paths = ["runs/run_1/model.pt", "runs/run_2/model.pt", "runs/run_3/"]
    schema = infer(paths)
    _check_schema(paths, schema)
    lays = {(lay.expr.pattern, lay.kind): lay for lay in schema.layouts}
    empty = lays["runs/run_{run:d}", "dir"]
    assert empty.count == 1 and empty.fields["run"].sample == (3,)
    model = lays["runs/run_{run:d}/model.pt", "file"]
    assert model.count == 2 and model.cardinality is Cardinality.OPTIONAL


def test_listed_directories_are_observed_paths():
    # in an iterable, a directory ending in "/" is an observed path even when
    # it holds others; duplicates and the root itself count once and not at all
    schema = infer(["a/", "a/b", "a/b", "c/", "c/", "./"])
    _check_schema(["a/", "a/b", "c/"], schema)
    assert schema.total == 3
    assert sorted((lay.expr.pattern, lay.kind) for lay in schema.layouts) == [
        ("a", "dir"),
        ("a/b", "file"),
        ("c", "dir"),
    ]


def test_match_kind_is_file_or_dir():
    import pytest

    schema = infer(["a/b", "c/"])
    assert schema.match("c", kind="file") == []
    with pytest.raises(ValueError, match="kind"):
        schema.match("a/b", kind="link")


@st.composite
def doc_trees(draw):
    """Package directories whose entries share names across kinds."""
    names = ["copyright", "README", "NEWS", "examples", "html", "log.gz"]
    entries = []
    for pkg in draw(st.lists(ident, min_size=1, max_size=10, unique=True)):
        for n in draw(st.lists(st.sampled_from(names), max_size=6, unique=True)):
            how = draw(st.sampled_from(["file", "empty", "full"]))
            if how == "file":
                entries.append(f"doc/{pkg}/{n}")
            elif how == "empty":
                entries.append(f"doc/{pkg}/{n}/")
            else:
                inner = st.lists(st.sampled_from(names), min_size=1, unique=True)
                entries += [f"doc/{pkg}/{n}/{m}" for m in draw(inner)]
    return entries


@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large],
)
@given(doc_trees())
def test_files_and_empty_directories_sharing_names(entries):
    _check_schema(entries, infer(entries))
    with tempfile.TemporaryDirectory() as tmp:
        _make(tmp, entries)
        _check_schema(entries, infer(tmp))


# -- variable depth -----------------------------------------------------------


def _package():
    """A nested package: src/pkg with sub-packages three levels down, plus records."""
    paths = ["README.md", "pyproject.toml", "tests/test_core.py", "tests/test_io.py"]

    def grow(at, depth):
        for m in ("__init__", "core", "io", "util"):
            paths.append(f"{at}/{m}.py")
            paths.append(f"{at}/__pycache__/{m}.cpython-314.pyc")
        if depth < 3:
            for sub in ("plugins", "formats"):
                grow(f"{at}/{sub}", depth + 1)

    grow("src/pkg", 0)
    paths.append("src/pkg/data/schema.json")
    return paths


def test_nested_package_infers_subpath_layouts(tmp_path):
    paths = _package()
    for p in paths:
        (tmp_path / p).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / p).touch()
    schema = infer(tmp_path)
    _check_schema(paths, schema)
    lays = {lay.expr.pattern: lay for lay in schema.layouts}
    py = lays["src/pkg/{rel...}/{stem}.py"]
    pyc = lays["src/pkg/{rel...}/__pycache__/{stem}.pyc"]
    modules = [p for p in paths if p.startswith("src/") and p.endswith(".py")]
    assert py.count == pyc.count == len(modules) == 60
    assert isinstance(py.expr.parts[2], Splice)
    assert "." in py.fields["rel"].sample  # depth 0: the package itself
    assert py.match("src/pkg/plugins/formats/core.py") == {
        "rel": "plugins/formats",
        "stem": "core",
    }
    renamed = py.rename(rel="sub", stem="module")
    assert renamed.expr.pattern == "src/pkg/{sub...}/{module}.py"
    assert renamed.match("src/pkg/core.py") == {"sub": ".", "module": "core"}
    # glob through the layouts finds every observed module and cache file
    found = {m.path for m in py.under(tmp_path).glob()}
    assert {str(tmp_path / p) for p in modules} <= found
    found = {m.path for m in pyc.under(tmp_path).glob()}
    assert {str(tmp_path / p) for p in paths if p.endswith(".pyc")} <= found
    # records stay records
    assert {"README.md", "pyproject.toml", "src/pkg/data/schema.json"} <= set(lays)
    assert all(p.startswith("src/pkg/") for p in lays if "{rel...}" in p)
    # data/ and every __pycache__/ hold no module: some directory has none
    assert py.cardinality is Cardinality.MANY


GIACOMETTI = """
Cargo.lock Cargo.toml Justfile LICENSE README.md TODO.md crates/giacometti/Cargo.toml
crates/giacometti/src/backends.rs crates/giacometti/src/backends/git.rs
crates/giacometti/src/backends/git/github_api.rs
crates/giacometti/src/backends/git/gitoxide.rs
crates/giacometti/src/backends/git/release.rs crates/giacometti/src/backends/git/shell.rs
crates/giacometti/src/backends/git/types.rs crates/giacometti/src/backends/types.rs
crates/giacometti/src/backends/uv.rs crates/giacometti/src/backends/uv/rust_crate.rs
crates/giacometti/src/backends/uv/shell.rs crates/giacometti/src/backends/uv/types.rs
crates/giacometti/src/git.rs crates/giacometti/src/git/add.rs
crates/giacometti/src/git/commit.rs crates/giacometti/src/git/push.rs
crates/giacometti/src/git/release.rs crates/giacometti/src/git/reset.rs
crates/giacometti/src/git/rev_parse.rs crates/giacometti/src/git/tag.rs
crates/giacometti/src/lib.rs crates/giacometti/src/main.rs crates/giacometti/src/policy.rs
crates/giacometti/src/release.rs crates/giacometti/src/tests.rs
crates/giacometti/src/tests/git.rs crates/giacometti/src/tests/git/rev_parse.rs
crates/giacometti/src/tests/mock.rs crates/giacometti/src/tests/mock/git.rs
docs/JOURNAL.md docs/journal/2025-01-25-outlook-doc-6.md
docs/journal/2025-01-25-uv-backends-4.md
""".split()


def test_empty_directories_fold_like_files(tmp_path):
    # an empty fixtures/ directory in every package folds as the modules do
    paths = _package()
    inits = [p for p in paths if p.endswith("/__init__.py")]
    fixtures = [p.replace("__init__.py", "fixtures/") for p in inits]
    _make(tmp_path, paths + fixtures)
    schema = infer(tmp_path)
    _check_schema(paths + fixtures, schema)
    lays = {(lay.expr.pattern, lay.kind): lay for lay in schema.layouts}
    lay = lays["src/pkg/{rel...}/fixtures", "dir"]
    assert lay.count == len(fixtures) == 15
    assert lay.match("src/pkg/plugins/fixtures") == {"rel": "plugins"}
    found = {m.path for m in lay.under(tmp_path).glob(kind="dir")}
    assert found == {str(tmp_path / p.rstrip("/")) for p in fixtures}
    assert lays["src/pkg/{rel...}/{stem}.py", "file"].count == 60


def test_code_repository_keeps_its_records():
    schema = infer(GIACOMETTI)
    _check_schema(GIACOMETTI, schema)
    # the recursive module tree folds; every other file stays a literal record
    pats = sorted(lay.expr.pattern for lay in schema.layouts)
    records = [p for p in GIACOMETTI if not p.endswith(".rs")]
    assert pats == sorted(["crates/giacometti/src/{rel...}/{stem}.rs", *records])
    assert schema.layouts[0].count == len(GIACOMETTI) - len(records)


def test_repository_root_is_not_a_recursion_root():
    # This repository's shape: a script among records at the root, and .py
    # files in several literal directories at three depths.
    paths = ["README.md", "pyproject.toml", "LICENSE", "uv.lock", "demo.py"]
    paths += [f"src/wend/{m}.py" for m in ("__init__", "_expr", "_match", "infer")]
    paths += ["src/wend/py.typed", "bench/bench.py"]
    paths += [f"{d}/{m}.py" for d in ("tests", "examples") for m in ("a", "b", "c")]
    paths += [f"docs/journal/scripts/{m}.py" for m in ("x", "y", "z")]
    paths += ["docs/SEMANTICS.md", "docs/journal/entry.md"]
    schema = infer(paths)
    _check_schema(paths, schema)
    pats = {lay.expr.pattern for lay in schema.layouts}
    assert not any("{rel" in p for p in pats), pats
    assert {"README.md", "demo.py", "bench/bench.py", "src/wend/{stem}.py"} <= pats


def test_deep_literal_trees_stay_literal():
    # the same tail at three depths, but through literal directories only
    paths = [f"a/{d}{i}.txt" for d in ("", "b/", "b/c/") for i in ("x", "y", "z")]
    pats = sorted(lay.expr.pattern for lay in infer(paths).layouts)
    assert pats == ["a/b/c/{stem}.txt", "a/b/{stem}.txt", "a/{stem}.txt"]
    # a tail without literal text ({name}) never folds
    paths = [f"r/{d}{n}" for d in ("", "x/", "y/", "x/q/", "y/q/") for n in "abc"]
    assert not any(
        isinstance(part, Splice)
        for lay in infer(paths).layouts
        for part in lay.expr.parts
    )


def test_parent_components_stay_out_of_subpaths():
    tree = [f"src/{d}{m}.py" for d in ("", "a/", "b/", "a/c/", "b/c/") for m in "xyz"]
    paths = [*tree, "src/../q/x.py", "src/a/../x.py", "src/a/../y.py"]
    schema = infer(paths)
    _check_schema(paths, schema)
    pats = {lay.expr.pattern for lay in schema.layouts}
    assert "src/{rel...}/{stem}.py" in pats and "src/../q/x.py" in pats


def test_recursion_needs_three_depths_and_a_root():
    two = [f"src/{d}{m}.py" for d in ("", "a/", "b/") for m in ("x", "y", "z")]
    assert all("{rel" not in lay.expr.pattern for lay in infer(two).layouts)
    three = two + [f"src/{d}/c/{m}.py" for d in "ab" for m in ("x", "y", "z")]
    assert [lay.expr.pattern for lay in infer(three).layouts] == [
        "src/{rel...}/{stem}.py"
    ]
    # without modules directly in src/, two depths remain below it
    rootless = [p for p in three if p.count("/") > 1]
    assert all("{rel" not in lay.expr.pattern for lay in infer(rootless).layouts)


# -- opaque families -----------------------------------------------------------


def _terminfo(letters, seed=0):
    """Letter directories, each with its own name families and one-off names."""
    rnd = random.Random(seed)
    paths = []
    for letter in letters:
        for k in range(rnd.randint(0, 3)):
            stem = letter + "".join(rnd.choices("aeiouxz", k=rnd.randint(1, 3)))
            stem += "-" * (k % 2)
            for n in rnd.sample(range(1, 500), rnd.randint(2, 6)):
                paths.append(f"terminfo/{letter}/{stem}{n}")
        for _ in range(rnd.randint(1, 4)):
            name = letter + "".join(rnd.choices("bcdfghklmnpqrstvwy+", k=5))
            paths.append(f"terminfo/{letter}/{name}")
    return sorted(set(paths))


def test_terminfo_letter_directories_collapse():
    paths = _terminfo("abcdefghijklmnopqrstuvwxyz")
    schema = infer(paths)
    _check_schema(paths, schema)
    assert [lay.expr.pattern for lay in schema.layouts] == [
        "terminfo/{terminfo}/{name}"
    ]
    # digit directories merge by skeleton, then join the letters' opaque map
    paths += _terminfo("0123456789", seed=1)
    schema = infer(paths)
    _check_schema(paths, schema)
    assert len(schema.layouts) <= 2
    # a handful of letter directories is a record, not a family
    assert len(infer(_terminfo("abc")).layouts) > 1


@settings(max_examples=40, deadline=None)
@given(st.integers(8, 20), st.integers(0, 10**6))
def test_opaque_families_collapse_to_one_layout(k, seed):
    paths = _terminfo("abcdefghijklmnopqrstuvwxyz"[:k], seed)
    schema = infer(paths)
    _check_schema(paths, schema)
    assert [lay.expr.pattern for lay in schema.layouts] == [
        "terminfo/{terminfo}/{name}"
    ]


# -- naming -------------------------------------------------------------------


def test_dates_name_fields():
    paths = [
        f"logs/{y}-{m:02d}-{d:02d}.log"
        for y in (2024, 2025)
        for m in (1, 7)
        for d in (3, 9)
    ]
    [lay] = infer(paths).layouts
    assert lay.expr.pattern == "logs/{year:04d}-{month:02d}-{day:02d}.log"
    paths = [
        f"photos/{y}/{y}{m:02d}{d:02d}_IMG.jpg"
        for y in (2023, 2024)
        for m in (2, 3)
        for d in (4, 5)
    ]
    [lay] = infer(paths).layouts
    assert lay.expr.pattern == "photos/{year:04d}/{date:08d}_IMG.jpg"
    paths = [
        f"snap/2026-10-17T{h:02d}-{m:02d}-{s:02d}.json"
        for h in (1, 9)
        for m in (5, 7)
        for s in (0, 30)
    ]
    [lay] = infer(paths).layouts
    assert lay.expr.pattern == (
        "snap/2026-10-17T{hour:02d}-{minute:02d}-{second:02d}.json"
    )


def test_uuid_and_hex_tokens_are_string_fields():
    uuids = [
        "3f2a1b4c-1234-4def-9abc-def012345678",
        "00ff00aa-0000-4000-8000-0123456789ab",
        "a0a0a0a0-1111-4222-8333-444455556666",
    ]
    paths = [f"part-{i:05d}-{u}-c000.snappy.parquet" for i, u in enumerate(uuids)]
    [lay] = infer(paths).layouts
    assert lay.expr.pattern == "part-{part:05d}-{uuid}-c000.snappy.parquet"
    assert lay.fields["uuid"].type is str and lay.fields["uuid"].distinct == 3
    digests = [
        "3b18e512dba79e4c8300dd08aeb37f8e728b8dad",
        "0123456789abcdef0123456789abcdef01234567",
        "fedcba9876543210fedcba9876543210fedcba98",
    ]
    [lay] = infer([f"cache/{d}.json" for d in digests]).layouts
    assert lay.expr.pattern == "cache/{hex}.json"


def test_tokens():
    assert _tokens("chunk_0001-of-0010.parquet") == (
        ("chunk_", "-of-", ".parquet"),
        ("d", "d"),
        ["0001", "0010"],
    )
    # one hex token; the text after it stays literal
    assert _tokens("x1-0a1b2c3d4e-v2.bin") == (
        ("x", "-", "-v2.bin"),
        ("d", "x"),
        ["1", "0a1b2c3d4e"],
    )
    # all digits, all letters, two tokens, or inside a word: not hex
    assert _tokens("20240101")[1] == ("d",)
    assert _tokens("deadbeefcafe")[1] == ()
    assert "x" not in _tokens("0a1b2c3d-0a1b2c3d4")[1]
    assert "x" not in _tokens("g0a1b2c3d4")[1]


# -- properties on generated nested trees ------------------------------------

ident = st.text(alphabet="abcdefgh_", min_size=1, max_size=5)


@st.composite
def nested_packages(draw):
    """src/pkg with modules at every level and regular sub-package names.

    Some packages hold an empty ``fixtures/`` directory.
    """
    depth = draw(st.integers(2, 4))
    subs = [
        draw(st.lists(ident, min_size=2, max_size=3, unique=True)) for _ in range(depth)
    ]
    paths = []

    def grow(at, level):
        mods = draw(st.lists(ident, min_size=3, max_size=5, unique=True))
        cache = draw(st.booleans())
        for m in mods:
            paths.append(f"{at}/{m}.py")
            if cache:
                paths.append(f"{at}/__pycache__/{m}.pyc")
        if draw(st.booleans()):
            paths.append(f"{at}/fixtures/")
        if level < depth:
            for s in subs[level]:
                grow(f"{at}/{s}", level + 1)

    grow("src/pkg", 0)
    extra = ["README.md", "src/pkg/py.typed", "docs/x.md", "src/pkg/data/a.json"]
    return sorted(set(paths + draw(st.lists(st.sampled_from(extra), unique=True))))


@settings(
    max_examples=40,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large],
)
@given(nested_packages())
def test_nested_trees_fold_into_subpath_layouts(paths):
    schema = infer(paths)
    _check_schema(paths, schema)
    modules = [p for p in paths if p.endswith(".py")]
    [py] = [lay for lay in schema.layouts if lay.expr.pattern.endswith(".py")]
    assert any(isinstance(part, Splice) for part in py.expr.parts)
    assert py.count == len(modules)
    # glob through every layout finds its observed paths again, of its kind
    with tempfile.TemporaryDirectory() as tmp:
        _make(tmp, paths)
        for lay in schema.layouts:
            found = {m.path for m in lay.under(tmp).glob(kind=lay.kind)}
            mine = _mine(lay, _observed(paths))
            assert {os.path.join(tmp, p) for p in mine} <= found
