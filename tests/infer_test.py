from hypothesis import example, given, settings
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


@settings(max_examples=300, deadline=None)
@example(["0/_", "00/_", "1/_"])  # "00" is not an instance of {n:d}
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
    patterns = [(lay.expr.pattern, lay.kind) for lay in schema.layouts]
    assert len(patterns) == len(set(patterns))
    dirs = {
        "/".join(f.split("/")[:i]) for f in files for i in range(1, f.count("/") + 1)
    }
    for lay in schema.layouts:
        assert lay.expr.is_absolute() is False
        assert P("/root") / lay.expr == lay.under("/root")
        assert lay.optional == _optional_oracle(lay, files, dirs)


def _optional_oracle(lay, files, dirs):
    """Some directory matching a prefix of the pattern holds none of its paths."""
    e, k = lay.expr, len(lay.expr.parts)
    mine = [f for f in files if lay.match(f) is not None]
    for j in range(1, k):
        prefix = e.parents[k - 1 - j]
        for d in dirs:
            if d.count("/") + 1 != j or prefix.match(d) is None:
                continue
            if not any(f.startswith(d + "/") for f in mine):
                return True
    return False


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
