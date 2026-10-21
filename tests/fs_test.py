import os
import tempfile
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from wend import (
    AmbiguousMatchError,
    File,
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


@pytest.fixture
def dist(tmp_path):
    for name in ["tool-1.0.tar.gz", "readme.txt", "setup.cfg", "notes"]:
        (tmp_path / name).touch()
    return tmp_path


stem, ext = Param("stem"), Param("ext")
TAR_READINGS = {("tool-1", "0.tar.gz"), ("tool-1.0", "tar.gz"), ("tool-1.0.tar", "gz")}


def test_glob_raises_on_an_ambiguous_path_before_yielding(dist):
    found = (P(dist) / T(t"{stem}.{ext}")).glob()
    with pytest.raises(AmbiguousMatchError) as info:
        next(found)
    assert info.value.path == str(dist / "tool-1.0.tar.gz")
    assert {(c["stem"], c["ext"]) for c in info.value.candidates} == TAR_READINGS


def test_glob_skips_ambiguous_paths_on_request(dist):
    found = (P(dist) / T(t"{stem}.{ext}")).glob(ambiguous="skip")
    assert [(m["stem"], m["ext"]) for m in found] == [
        ("readme", "txt"),
        ("setup", "cfg"),
    ]


def test_glob_reports_ambiguous_paths_with_every_verified_reading(dist):
    release = root / T(t"{stem}.{ext}")
    report = []
    found = list(release.glob(root=dist, ambiguous=report.append))
    assert [m.path for m in found] == [
        str(dist / "readme.txt"),
        str(dist / "setup.cfg"),
    ]
    [error] = report
    assert isinstance(error, AmbiguousMatchError)
    assert error.path == str(dist / "tool-1.0.tar.gz")
    # Each candidate is a full binding of the globbed expression, given
    # bindings included, and renders to the path; together they are all of
    # its readings.
    assert all(c["root"] == dist for c in error.candidates)
    assert all(release.render(c) == error.path for c in error.candidates)
    assert len(error.candidates) == len(release.match_all(error.path)) == 3
    assert {(c["stem"], c["ext"]) for c in error.candidates} == TAR_READINGS


def test_glob_reports_in_path_order_before_the_first_match(dist):
    (dist / "lib-0.1.tar.gz").touch()
    events = []
    for m in (P(dist) / T(t"{stem}.{ext}")).glob(
        ambiguous=lambda error: events.append(("ambiguous", error.path))
    ):
        events.append(("match", m.path))
    assert events == [
        ("ambiguous", str(dist / "lib-0.1.tar.gz")),
        ("ambiguous", str(dist / "tool-1.0.tar.gz")),
        ("match", str(dist / "readme.txt")),
        ("match", str(dist / "setup.cfg")),
    ]


def test_a_raising_ambiguity_callback_aborts_the_walk(dist):
    def stop(error):
        raise error

    with pytest.raises(AmbiguousMatchError):
        next((P(dist) / T(t"{stem}.{ext}")).glob(ambiguous=stop))


def test_ambiguity_modes_are_checked_when_called(dist):
    e = P(dist) / T(t"{stem}.{ext}")
    with pytest.raises(ValueError, match="ambiguous must be"):
        e.glob(ambiguous="report")
    with pytest.raises(ValueError, match="ambiguous must be"):
        Lens(e, e).map([], ambiguous="collect")


def test_glob_counts_readings_its_symlink_policy_skips(tmp_path):
    (tmp_path / "outside" / "m").mkdir(parents=True)
    (tmp_path / "outside" / "m" / "f.txt").touch()
    (tmp_path / "r" / "x").mkdir(parents=True)
    (tmp_path / "r" / "x" / "f.txt").touch()
    os.symlink(tmp_path / "outside", tmp_path / "r" / "L")
    e = P(tmp_path / "r") / SubPath("a") / Param("d") / SubPath("b") / "f.txt"
    linked = str(tmp_path / "r" / "L" / "m" / "f.txt")
    assert (
        len(e.match_all(linked)) == 2
    )  # L is {d} in one reading, in {a...} in the other
    # Each policy descends L at only one of those positions, so the walk alone
    # sees one reading; the path is still ambiguous.
    for policy in ({"recurse_symlinks": True}, {"follow_symlinks": True}):
        with pytest.raises(AmbiguousMatchError):
            list(e.glob(**policy))
        report = []
        assert [m.path for m in e.glob(**policy, ambiguous=report.append)] == [
            str(tmp_path / "r" / "x" / "f.txt")
        ]
        assert [(r.path, len(r.candidates)) for r in report] == [(linked, 2)]


def test_glob_counts_readings_its_cycle_check_skips(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "x").touch()
    os.symlink(tmp_path, tmp_path / "sub" / "up")
    e = P(tmp_path) / SubPath("a") / SubPath("b") / "x"
    report = []
    found = e.glob(follow_symlinks=True, recurse_symlinks=True, ambiguous=report.append)
    assert [m.path for m in found] == [str(tmp_path / "x")]
    [error] = report
    assert error.path == str(tmp_path / "sub" / "up" / "x")
    assert {(c["a"], c["b"]) for c in error.candidates} == {
        (".", "sub/up"),
        ("sub", "up"),
        ("sub/up", "."),
    }


def test_glob_terminates_on_symlink_loops_in_subpaths(tree):
    os.symlink(tree / "data", tree / "data" / "loop")
    e = P(tree) / "data" / SubPath("rel") / T(t"chunk_{idx:04d}.parquet")
    assert len(list(e.glob())) == 4
    # Following links in the recursion still visits each directory once per path.
    assert len(list(e.glob(recurse_symlinks=True))) == 4


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


def test_lossless_lens_refuses_colliding_targets():
    a, b = Param("a"), Param("b")
    lens = Lens(T(t"in/{a}/{b}.txt"), T(t"out/{a}-{b}.txt"))
    assert lens.lossless
    assert lens("in/x/z.txt") == Path("out/x-z.txt")
    # in/x-y/z.txt and in/x/y-z.txt would both write out/x-y-z.txt
    with pytest.raises(AmbiguousMatchError):
        lens("in/x-y/z.txt")
    with pytest.raises(AmbiguousMatchError):
        dict(lens.map(["in/x/z.txt", "in/x/y-z.txt"]))


def test_lens_map_reports_paths_it_cannot_map_uniquely():
    a, b = Param("a"), Param("b")
    lens = Lens(T(t"in/{a}/{b}.txt"), T(t"out/{a}-{b}.txt"))
    paths = ["in/x/z.txt", "in/x/y-z-w.txt", "README.md", "in/y/w.txt"]
    mapped = {"in/x/z.txt": Path("out/x-z.txt"), "in/y/w.txt": Path("out/y-w.txt")}
    report = []
    assert dict(lens.map(paths, ambiguous=report.append)) == mapped
    # in/x/y-z-w.txt maps to a target that three source paths share.
    [error] = report
    assert error.path == "out/x-y-z-w.txt"
    assert all(lens.target.render(c) == error.path for c in error.candidates)
    assert {lens.source.render(c) for c in error.candidates} == {
        "in/x/y-z-w.txt",
        "in/x-y/z-w.txt",
        "in/x-y-z/w.txt",
    }
    assert dict(lens.map(paths, ambiguous="skip")) == mapped
    # The default still raises when the path is reached.
    pairs = lens.map(paths)
    assert next(pairs) == ("in/x/z.txt", Path("out/x-z.txt"))
    with pytest.raises(AmbiguousMatchError):
        next(pairs)
    # A source path that matches more than one way is reported as itself.
    meta = Lens(T(t"dist/{stem}.{ext}"), T(t"meta/{stem}/{ext}.json"))
    report = []
    pairs = meta.map(["dist/a.whl", "dist/b.tar.gz"], ambiguous=report.append)
    assert dict(pairs) == {"dist/a.whl": Path("meta/a/whl.json")}
    assert [(r.path, len(r.candidates)) for r in report] == [("dist/b.tar.gz", 2)]


def test_lens_with_extra_target_params():
    run = Param("run")
    lens = Lens(T(t"raw/{Param('day')}.csv"), T(t"out/{run}/{Param('day')}.parquet"))
    assert not lens.lossless
    assert lens("raw/2026-01-02.csv", run="r1") == Path("out/r1/2026-01-02.parquet")


def test_glob_does_not_follow_symlinks_unless_asked(tmp_path):
    (tmp_path / "root" / "data" / "a").mkdir(parents=True)
    (tmp_path / "root" / "data" / "a" / "f.txt").touch()
    (tmp_path / "outside").mkdir()
    (tmp_path / "outside" / "f.txt").touch()
    os.symlink(tmp_path / "outside", tmp_path / "root" / "data" / "b")
    e = P(tmp_path / "root") / "data" / Param("d") / T(t"{Param('x')}.txt")
    assert [m["d"] for m in e.glob()] == ["a"]
    assert sorted(m["d"] for m in e.glob(follow_symlinks=True)) == ["a", "b"]
    # A literal segment below a templated one is refused like any other entry.
    (tmp_path / "root" / "data" / "a" / "sub").symlink_to(tmp_path / "outside")
    below = P(tmp_path / "root") / "data" / Param("d") / "sub" / T(t"{Param('x')}.txt")
    assert list(below.glob()) == []
    assert [m["d"] for m in below.glob(follow_symlinks=True)] == ["a"]
    # The fixed prefix is resolved like any path, so a linked root still works.
    os.symlink(tmp_path / "outside", tmp_path / "root" / "link")
    lit = P(tmp_path / "root") / "link" / T(t"{Param('x')}.txt")
    assert [m["x"] for m in lit.glob()] == ["f"]
    linked_root = Param("r") / "data" / Param("d") / T(t"{Param('x')}.txt")
    os.symlink(tmp_path / "root", tmp_path / "alias")
    assert [m["d"] for m in linked_root.glob(r=tmp_path / "alias")] == ["a"]


def test_glob_classifies_final_symlinks_as_links_by_default(tmp_path):
    (tmp_path / "blobs").mkdir()
    (tmp_path / "blobs" / "abc").write_text("x")
    (tmp_path / "snap").mkdir()
    os.symlink(tmp_path / "blobs" / "abc", tmp_path / "snap" / "model.bin")
    (tmp_path / "snap" / "config.json").write_text("{}")
    e = P(tmp_path / "snap") / Param("name")
    assert [m["name"] for m in e.glob()] == ["config.json", "model.bin"]
    assert [m["name"] for m in e.glob(kind="file")] == ["config.json"]
    assert [m["name"] for m in e.glob(kind="file", follow_symlinks=True)] == [
        "config.json",
        "model.bin",
    ]


def test_glob_recurses_through_symlinks_only_when_asked(tmp_path):
    (tmp_path / "root").mkdir()
    (tmp_path / "outside" / "deep").mkdir(parents=True)
    (tmp_path / "outside" / "deep" / "f.txt").touch()
    (tmp_path / "root" / "g.txt").touch()
    os.symlink(tmp_path / "outside", tmp_path / "root" / "ext")
    e = P(tmp_path / "root") / SubPath("rel") / T(t"{Param('x')}.txt")
    assert [m["rel"] for m in e.glob()] == ["."]
    assert [m["rel"] for m in e.glob(follow_symlinks=True)] == ["."]
    assert sorted(m["rel"] for m in e.glob(recurse_symlinks=True)) == [".", "ext/deep"]


# -- a SubPath in the last position (#82) --------------------------------------------


@pytest.fixture
def uploads(tmp_path):
    for f in [
        "srv/uploads/ada/cv.pdf",
        "srv/uploads/ada/docs/a.txt",
        "srv/uploads/bo/x",
    ]:
        p = tmp_path / f
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x")
    (tmp_path / "srv/uploads/bo/empty").mkdir()
    return tmp_path


def test_a_trailing_subpath_reaches_files(uploads):
    e = P(uploads / "srv/uploads") / Param("user") / SubPath("file")
    base = str(uploads / "srv/uploads")
    found = {(m["user"], m["file"]): os.path.relpath(m.path, base) for m in e.glob()}
    assert found == {
        ("ada", "."): "ada",
        ("ada", "cv.pdf"): "ada/cv.pdf",
        ("ada", "docs"): "ada/docs",
        ("ada", "docs/a.txt"): "ada/docs/a.txt",
        ("bo", "."): "bo",
        ("bo", "empty"): "bo/empty",
        ("bo", "x"): "bo/x",
    }
    files = [(m["user"], m["file"]) for m in e.glob(kind="file")]
    assert files == [("ada", "cv.pdf"), ("ada", "docs/a.txt"), ("bo", "x")]
    dirs = [(m["user"], m["file"]) for m in e.glob(kind="dir")]
    assert dirs == [("ada", "."), ("ada", "docs"), ("bo", "."), ("bo", "empty")]
    # The same paths, in the same order, as pathlib's own recursive glob.
    assert [m.path for m in e.glob()] == sorted(str(p) for p in Path(base).glob("*/**"))


def test_a_trailing_subpath_at_zero_depth_and_below_a_missing_prefix(uploads):
    e = P(uploads / "srv/uploads/bo") / SubPath("rest")
    assert [m["rest"] for m in e.glob()] == [".", "empty", "x"]
    assert [m["rest"] for m in e.glob(kind="file")] == ["x"]
    assert list((P(uploads / "nope") / SubPath("rest")).glob()) == []
    # A file as the fixed prefix is itself the only path, with an empty SubPath,
    # as match reads it.
    f = P(uploads / "srv/uploads/bo/x") / SubPath("rest")
    assert [(m.path, m["rest"]) for m in f.glob()] == [
        (str(uploads / "srv/uploads/bo/x"), ".")
    ]
    assert f.match(uploads / "srv/uploads/bo/x")["rest"] == "."
    assert list(f.glob(kind="dir")) == []


def test_a_subpath_before_other_parts_still_takes_directories_only(uploads):
    # srv/uploads/ada/cv.pdf is a file: no path continues below it.
    e = P(uploads / "srv/uploads") / SubPath("rel") / "a.txt"
    assert [m["rel"] for m in e.glob()] == ["ada/docs"]
    t = P(uploads / "srv/uploads") / SubPath("rel") / T(t"{Param('name')}")
    assert {m["rel"] for m in t.glob(kind="file")} == {"ada", "ada/docs", "bo"}


def test_a_trailing_subpath_keeps_glob_symlink_policy(tmp_path):
    root = tmp_path / "root"
    (root / "real").mkdir(parents=True)
    (root / "real" / "f.txt").touch()
    (tmp_path / "outside").mkdir()
    (tmp_path / "outside" / "g.txt").touch()
    os.symlink(tmp_path / "outside", root / "dirlink")
    os.symlink(root / "real" / "f.txt", root / "filelink")
    os.symlink(tmp_path / "missing", root / "broken")
    e = P(root) / SubPath("rest")
    # By default links are yielded as themselves and never descended.
    assert [m["rest"] for m in e.glob()] == [
        ".",
        "broken",
        "dirlink",
        "filelink",
        "real",
        "real/f.txt",
    ]
    assert [m["rest"] for m in e.glob(kind="file")] == ["real/f.txt"]
    assert [m["rest"] for m in e.glob(kind="dir")] == [".", "real"]
    # follow_symlinks classifies links by their targets, still without descending.
    assert [m["rest"] for m in e.glob(kind="file", follow_symlinks=True)] == [
        "filelink",
        "real/f.txt",
    ]
    assert [m["rest"] for m in e.glob(kind="dir", follow_symlinks=True)] == [
        ".",
        "dirlink",
        "real",
    ]
    # recurse_symlinks descends a linked directory and finds the file inside.
    assert [m["rest"] for m in e.glob(kind="file", recurse_symlinks=True)] == [
        "dirlink/g.txt",
        "real/f.txt",
    ]


def test_a_trailing_subpath_terminates_on_link_cycles(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "f").touch()
    os.symlink(tmp_path, tmp_path / "a" / "up")
    e = P(tmp_path) / SubPath("rest")
    assert [m["rest"] for m in e.glob()] == [".", "a", "a/f", "a/up"]
    # Recursing through links, the link back up is yielded as itself (as match
    # reads it) but not descended, so the walk ends.
    assert [m["rest"] for m in e.glob(recurse_symlinks=True)] == [
        ".",
        "a",
        "a/f",
        "a/up",
    ]
    found = [m["rest"] for m in e.glob(recurse_symlinks=True, kind="file")]
    assert found == ["a/f"]
    assert e.match(tmp_path / "a" / "up")["rest"] == "a/up"


def test_a_trailing_subpath_with_choices_and_ambiguity(uploads):
    picked = SubPath("file", choices={"cv.pdf", "docs/a.txt"})
    e = P(uploads / "srv/uploads") / Param("user") / picked
    assert [m["file"] for m in e.glob()] == ["cv.pdf", "docs/a.txt"]
    # Two SubPaths read a file path two ways, as match_all does, so glob reports it.
    two = P(uploads / "srv/uploads/ada") / SubPath("a") / SubPath("b")
    report = []
    found = {m.path for m in two.glob(ambiguous=report.append)}
    assert str(uploads / "srv/uploads/ada/docs/a.txt") in {r.path for r in report}
    assert str(uploads / "srv/uploads/ada/docs/a.txt") not in found
    for r in report:
        assert len(r.candidates) == len(two.match_all(r.path))


def test_unions_and_queries_see_files_below_a_trailing_subpath(uploads):
    a = P(uploads / "srv/uploads/ada") / SubPath("rest")
    b = P(uploads / "srv/uploads/bo") / SubPath("rest")
    files = [m["rest"] for m in (a | b).glob(kind="file")]
    assert files == ["cv.pdf", "docs/a.txt", "x"]
    q = a.where(File)
    assert [m["rest"] for m in q.glob()] == ["cv.pdf", "docs/a.txt"]


# glob against match, on random trees: glob yields exactly the existing paths
# below the walk's start that match reads one way, and reports those it reads
# several ways.

GLOB_NAMES = ["a", "b", "1", "02", "a.txt", "x.y.z", ".h"]
glob_trees = st.lists(
    st.tuples(
        st.lists(st.sampled_from(GLOB_NAMES), min_size=1, max_size=4), st.booleans()
    ),
    max_size=14,
)
GLOB_EXPRESSIONS = [
    (lambda r: P(r) / SubPath("s"), {}),
    (lambda r: P(r) / SubPath("s"), {"kind": "file"}),
    (lambda r: P(r) / SubPath("s"), {"kind": "dir"}),
    (lambda r: P(r) / Param("a") / SubPath("s"), {}),
    (lambda r: P(r) / "a" / SubPath("s"), {"kind": "file"}),
    (lambda r: P(r) / SubPath("s") / Param("leaf"), {}),
    (lambda r: P(r) / SubPath("s") / T(t"{Param('stem')}.txt"), {}),
    (lambda r: P(r) / SubPath("s") / "a", {}),
    (lambda r: P(r) / SubPath("s") / SubPath("t"), {}),
    (lambda r: P(r) / Param("a") / T(t"{Param('n', type=int):d}"), {}),
]


def _consistent(paths):
    kinds, out = {}, []
    for parts, is_dir in paths:
        names = ["/".join(parts[: i + 1]) for i in range(len(parts))]
        want = ["dir"] * (len(parts) - 1) + ["dir" if is_dir else "file"]
        if all(kinds.get(p, k) == k for p, k in zip(names, want, strict=True)):
            kinds.update(zip(names, want, strict=True))
            out.append(("/".join(parts), is_dir))
    return out


def _existing(root):
    out = {root: "dir"}
    for d, dirs, files in os.walk(root):
        out.update({os.path.join(d, x): "dir" for x in dirs})
        out.update({os.path.join(d, x): "file" for x in files})
    return out


@settings(max_examples=80, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(paths=glob_trees)
def test_glob_agrees_with_match_on_random_trees(paths):
    with tempfile.TemporaryDirectory() as tmp:
        for p, is_dir in _consistent(paths):
            q = Path(tmp, p)
            if is_dir:
                q.mkdir(parents=True, exist_ok=True)
            else:
                q.parent.mkdir(parents=True, exist_ok=True)
                q.write_text("x")
        existing = _existing(tmp)
        for make, options in GLOB_EXPRESSIONS:
            e = make(tmp)
            want = options.get("kind")
            one, several = {}, set()
            for path, kind in existing.items():
                if want is not None and kind != want:
                    continue
                readings = e.match_all(path, limit=3)
                if len(readings) == 1:
                    one[path] = dict(readings[0])
                elif readings:
                    several.add(path)
            report = []
            found = {
                m.path: dict(m) for m in e.glob(ambiguous=report.append, **options)
            }
            assert found == one, (e, options)
            assert {r.path for r in report} == several, (e, options)
