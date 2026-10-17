from hypothesis import given, settings
from hypothesis import strategies as st

from wend import P
from wend.infer import _int_spec, infer


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
name = st.one_of(
    segment,
    st.builds(
        lambda a, n, b: f"{a}{n}{b}", segment, st.integers(0, 120).map(str), segment
    ),
)


@settings(max_examples=300, deadline=None)
@given(
    st.lists(
        st.lists(name, min_size=1, max_size=4).map("/".join),
        min_size=1,
        max_size=40,
        unique=True,
    )
)
def test_every_observed_path_is_covered(paths):
    # a path that is a prefix of another is a directory, not a file
    files = [p for p in paths if not any(q.startswith(p + "/") for q in paths)]
    schema = infer(files)
    assert schema.check(files) == []
    assert sum(lay.count for lay in schema.layouts) == len(files)
    for lay in schema.layouts:
        assert lay.expr.is_absolute() is False
        assert P("/root") / lay.expr == lay.under("/root")


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
