import os
from pathlib import Path

import pytest

from wend import (
    AmbiguousMatchError,
    Lens,
    NotStaticError,
    P,
    Param,
    Segment,
    SubPath,
    T,
    glob,
)


root, split, idx = Param("root"), Segment("split"), Param("idx", type=int)
shard = root / "data" / split / T(t"chunk_{idx:04d}.parquet")


@pytest.fixture
def tree(tmp_path):
    files = [
        "data/train/chunk_0001.parquet",
        "data/train/chunk_0002.parquet",
        "data/train/chunk_2.parquet",  # not canonical for :04d
        "data/train/notes.txt",
        "data/valid/chunk_0001.parquet",
        "data/valid/sub/chunk_0009.parquet",
        "other/chunk_0001.parquet",
    ]
    for f in files:
        p = tmp_path / f
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x")
    return tmp_path


def test_glob_discovers_typed_bindings(tree):
    found = list(shard.glob(root=tree))
    assert [(m["split"], m["idx"]) for m in found] == [
        ("train", 1),
        ("train", 2),
        ("valid", 1),
    ]
    assert all(Path(m.path).exists() for m in found)
    assert found[0]["root"] == tree  # given bindings are carried through
    assert shard.resolve(found[0]) == Path(found[0].path)


def test_glob_with_partial_bindings(tree):
    assert [m["idx"] for m in glob(shard, root=tree, split="valid")] == [1]


def test_glob_requires_a_bound_root():
    with pytest.raises(NotStaticError):
        list(shard.glob())


def test_glob_subpath_recursion_and_kind(tree):
    e = P(tree) / "data" / SubPath("rel") / T(t"chunk_{idx:04d}.parquet")
    found = {(m["rel"], m["idx"]) for m in e.glob()}
    assert found == {("train", 1), ("train", 2), ("valid", 1), ("valid/sub", 9)}
    dirs = [m["split"] for m in (P(tree) / "data" / split).glob(kind="dir")]
    assert dirs == ["train", "valid"]
    assert list((P(tree) / "data" / split).glob(kind="file")) == []


def test_glob_relative_to_cwd(tree, monkeypatch):
    monkeypatch.chdir(tree)
    m = next(iter((P("other") / T(t"chunk_{idx:04d}.parquet")).glob()))
    assert m.path == "other/chunk_0001.parquet" and m["idx"] == 1


def test_glob_reports_ambiguity(tree):
    a, b = Param("a"), Param("b")
    with pytest.raises(AmbiguousMatchError):
        list((P(tree) / "data" / "train" / T(t"{a}{b}.txt")).glob())


def test_glob_does_not_follow_symlink_loops_in_subpaths(tree):
    os.symlink(tree / "data", tree / "data" / "loop")
    e = P(tree) / "data" / SubPath("rel") / T(t"chunk_{idx:04d}.parquet")
    assert len(list(e.glob())) == 4
    assert len(list(e.glob(recurse_symlinks=False))) == 4


def test_lens_maps_between_layouts():
    stem = Param("stem")
    src = P("src") / SubPath("rel") / T(t"{stem}.py")
    dst = P("build") / SubPath("rel") / T(t"{stem}.cpython-314.pyc")
    lens = Lens(src, dst)
    assert lens.lossless
    assert lens("src/pkg/mod.py") == Path("build/pkg/mod.cpython-314.pyc")
    assert lens.backward("build/pkg/mod.cpython-314.pyc") == Path("src/pkg/mod.py")
    assert dict(lens.map(["src/a.py", "README.md"])) == {
        "src/a.py": Path("build/a.cpython-314.pyc")
    }


def test_lens_with_extra_target_params():
    run = Param("run")
    lens = Lens(T(t"raw/{Param('day')}.csv"), T(t"out/{run}/{Param('day')}.parquet"))
    assert not lens.lossless
    assert lens("raw/2026-01-02.csv", run="r1") == Path("out/r1/2026-01-02.parquet")


def test_glob_can_refuse_symlinks_out_of_the_tree(tmp_path):
    (tmp_path / "root" / "data" / "a").mkdir(parents=True)
    (tmp_path / "root" / "data" / "a" / "f.txt").touch()
    (tmp_path / "outside").mkdir()
    (tmp_path / "outside" / "f.txt").touch()
    os.symlink(tmp_path / "outside", tmp_path / "root" / "data" / "b")
    e = P(tmp_path / "root") / "data" / Param("d") / T(t"{Param('x')}.txt")
    assert sorted(m["d"] for m in e.glob()) == ["a", "b"]
    assert [m["d"] for m in e.glob(follow_symlinks=False)] == ["a"]
    os.symlink(tmp_path / "outside", tmp_path / "root" / "link")
    lit = P(tmp_path / "root") / "link" / T(t"{Param('x')}.txt")
    assert len(list(lit.glob())) == 1
    assert list(lit.glob(follow_symlinks=False)) == []
