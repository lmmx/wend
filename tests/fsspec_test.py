"""Discovery and inference on fsspec filesystems agree with the local disk.

Each tree is built twice, under ``tmp_path`` and in a fresh fsspec memory
filesystem, and every walk runs three ways: locally, on the memory store
listed directory by directory (``listing="tree"``), and on the store listed
once by prefix (``listing="flat"``).
"""

import os
import tempfile
from collections import Counter
from pathlib import Path

import pytest
from fsspec.implementations.memory import MemoryFile, MemoryFileSystem
from hypothesis import given, settings
from hypothesis import strategies as st

from wend import AmbiguousMatchError, P, Param, Segment, SubPath, T, glob
from wend.fs import FsspecFS, LocalFS, url_to_fs
from wend.infer import infer


def fresh_memory() -> MemoryFileSystem:
    """A memory filesystem with its own store (the default store is global)."""
    fs = MemoryFileSystem(skip_instance_cache=True)
    fs.store = {}
    fs.pseudo_dirs = [""]
    return fs


class Counting:
    """An fsspec filesystem that counts the calls made on it.

    Calls the wrapped filesystem makes internally are not counted, so a
    store's ``find`` counts once, as one prefix listing does.
    """

    COUNTED = {"ls", "find", "walk", "glob", "info", "isdir", "isfile", "exists"}

    def __init__(self, fs):
        self._fs = fs
        self.calls = Counter()
        self.args = []

    def __getattr__(self, name):
        attr = getattr(self._fs, name)
        if name not in self.COUNTED:
            return attr

        def counted(*args, **kwargs):
            self.calls[name] += 1
            self.args.append((name, args[0] if args else None))
            return attr(*args, **kwargs)

        return counted


def build(files, dirs, local_root, mem, mem_root):
    mem.makedirs(mem_root, exist_ok=True)  # as the local root exists
    for f in files:
        p = Path(local_root, f)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x")
        mem.pipe(f"{mem_root}/{f}", b"x")
    for d in dirs:
        Path(local_root, d).mkdir(parents=True, exist_ok=True)
        mem.makedirs(f"{mem_root}/{d}", exist_ok=True)


FILES = [
    "data/train/chunk_0001.parquet",
    "data/train/chunk_0002.parquet",
    "data/train/chunk_2.parquet",  # not canonical for :04d
    "data/train/notes.txt",
    "data/valid/chunk_0001.parquet",
    "data/valid/sub/chunk_0009.parquet",
    "data/.cache/chunk_0003.parquet",
    "dist/tool-1.0.tar.gz",
    "dist/lib-0.1.tar.gz",
    "dist/readme.txt",
    "other/chunk_0001.parquet",
]
DIRS = ["data/empty", "data/valid/.scratch"]


@pytest.fixture
def trees(tmp_path):
    """The same tree on disk and in memory: (local root, memory, memory root)."""
    mem = fresh_memory()
    build(FILES, DIRS, tmp_path, mem, "/tree")
    return str(tmp_path), mem, "/tree"


def filesystems(local_root, mem, mem_root):
    """(root, fs) for each way of walking the tree, local first."""
    return [
        (local_root, None),
        (mem_root, FsspecFS(mem, listing="tree")),
        (mem_root, FsspecFS(mem, listing="flat")),
        # Bucket-style: a relative root, as url_to_fs gives for s3://bucket/x.
        (mem_root.lstrip("/"), FsspecFS(mem, listing="flat")),
    ]


def rel(path, root):
    return "." if path == root else os.path.relpath(path, root)


def run(make, root, fs, **options):
    """Results and ambiguity reports, with paths relative to ``root``.

    ``make(root)`` gives an expression, or an expression and its bindings.
    """
    made = make(root)
    expr, mapping = made if isinstance(made, tuple) else (made, None)
    report = []
    found = [
        (rel(m.path, root), {k: v for k, v in m.items() if k != "root"})
        for m in glob(expr, mapping, fs=fs, ambiguous=report.append, **options)
    ]
    reports = [
        (rel(e.path, root), sorted(repr(c) for c in e.candidates)) for e in report
    ]
    return found, reports


split, idx = Segment("split"), Param("idx", type=int)
stem, ext, rest = Param("stem"), Param("ext"), SubPath("rest")
chunk = T(t"chunk_{idx:04d}.parquet")

EXPRESSIONS = {
    "literal prefix": (lambda r: P(r) / "data" / split / chunk, {}),
    "bound root": (lambda r: (Param("root") / "data" / split / chunk, {"root": r}), {}),
    "subpath splice": (lambda r: P(r) / "data" / rest / chunk, {}),
    "subpath to dirs": (lambda r: P(r) / "data" / rest, {"kind": "dir"}),
    "no literal prefix": (lambda r: P(r) / Param("top") / Param("name"), {}),
    "dirs": (lambda r: P(r) / "data" / Param("d"), {"kind": "dir"}),
    "files": (lambda r: P(r) / "data" / Param("d") / Param("f"), {"kind": "file"}),
    "any kind": (lambda r: P(r) / "data" / Param("d"), {}),
    "ambiguous": (lambda r: P(r) / "dist" / T(t"{stem}.{ext}"), {}),
    "literal file": (lambda r: P(r) / "data" / "train" / "notes.txt", {}),
    "missing prefix": (lambda r: P(r) / "nope" / Param("x"), {}),
    "file as prefix": (
        lambda r: P(r) / "data" / "train" / "notes.txt" / Param("x"),
        {},
    ),
    "symlink options": (
        lambda r: P(r) / rest / chunk,
        {"follow_symlinks": True, "recurse_symlinks": True},
    ),
}


@pytest.mark.parametrize("name", EXPRESSIONS)
def test_glob_on_memory_matches_the_local_disk(trees, name):
    make, options = EXPRESSIONS[name]
    results = [run(make, root, fs, **options) for root, fs in filesystems(*trees)]
    assert all(r == results[0] for r in results[1:])
    if name not in ("missing prefix", "file as prefix"):
        assert results[0][0] or results[0][1]  # the case finds something


def test_the_compared_results_are_the_expected_ones(trees):
    found, _ = run(EXPRESSIONS["literal prefix"][0], "/tree", FsspecFS(trees[1]))
    assert found == [
        # glob, unlike infer, has no notion of hidden entries.
        ("data/.cache/chunk_0003.parquet", {"split": ".cache", "idx": 3}),
        ("data/train/chunk_0001.parquet", {"split": "train", "idx": 1}),
        ("data/train/chunk_0002.parquet", {"split": "train", "idx": 2}),
        ("data/valid/chunk_0001.parquet", {"split": "valid", "idx": 1}),
    ]
    found, reports = run(EXPRESSIONS["ambiguous"][0], "/tree", FsspecFS(trees[1]))
    assert found == [("dist/readme.txt", {"stem": "readme", "ext": "txt"})]
    assert [(path, len(c)) for path, c in reports] == [
        ("dist/lib-0.1.tar.gz", 3),
        ("dist/tool-1.0.tar.gz", 3),
    ]
    found, _ = run(EXPRESSIONS["dirs"][0], "/tree", FsspecFS(trees[1]), kind="dir")
    # Hidden and empty directories included, as on disk.
    assert [f["d"] for _, f in found] == [".cache", "empty", "train", "valid"]


def test_a_walk_from_the_root_of_a_store(tmp_path, monkeypatch):
    # No fixed prefix at all: the walk starts at "." locally and at the
    # store's root in memory.
    mem = fresh_memory()
    build(FILES, DIRS, tmp_path / "tree", mem, "/tree")
    monkeypatch.chdir(tmp_path)
    e = Segment("top") / "data" / split / chunk
    local = [(m.path, dict(m)) for m in e.glob()]
    assert local[0] == (
        "tree/data/.cache/chunk_0003.parquet",
        {"top": "tree", "split": ".cache", "idx": 3},
    )
    for listing in ("tree", "flat"):
        counting = Counting(mem)
        found = [
            (m.path, dict(m)) for m in e.glob(fs=FsspecFS(counting, listing=listing))
        ]
        assert found == local
    assert counting.args == [("find", "")]  # flat: the whole store, once


def test_ambiguity_raises_by_default_on_a_store(trees):
    e = P("/tree") / "dist" / T(t"{stem}.{ext}")
    with pytest.raises(AmbiguousMatchError):
        list(e.glob(fs=FsspecFS(trees[1])))


def summary(schema):
    return schema.total, [
        (lay.expr.pattern, lay.kind, lay.count, lay.optional, lay.fields)
        for lay in schema.layouts
    ]


INFER_FILES = [
    *(f"data/{s}/part-{i:03d}.parquet" for s in ("train", "valid") for i in range(5)),
    *(f"checkpoints/run_{r}/epoch_{e:02d}.pt" for r in (1, 2) for e in range(1, 4)),
    "checkpoints/run_2/notes.txt",
    "README.md",
    ".git/HEAD",
    "data/train/.part-999.parquet.crc",
]


@pytest.mark.parametrize("include_hidden", [False, True])
def test_infer_on_memory_matches_the_local_disk(tmp_path, include_hidden):
    mem = fresh_memory()
    build(INFER_FILES, ["logs/empty"], tmp_path, mem, "/lake")
    build(["logs/only-hidden/.keep"], [], tmp_path, mem, "/lake")
    local = summary(infer(tmp_path, include_hidden=include_hidden))
    for root, fs in filesystems(str(tmp_path), mem, "/lake")[1:]:
        assert summary(infer(root, fs=fs, include_hidden=include_hidden)) == local
    assert summary(infer(tmp_path, fs=LocalFS(), include_hidden=include_hidden)) == (
        local
    )
    patterns = [p for p, *_ in local[1]]
    # Empty directories, and those holding only hidden entries unless they
    # are included, are observed like files.
    assert "logs/empty" in patterns
    assert ("logs/only-hidden" in patterns) is not include_hidden


def test_infer_with_a_filesystem_needs_a_directory(trees):
    _, mem, _ = trees
    fs = FsspecFS(mem)
    with pytest.raises(NotADirectoryError):
        infer("/tree/data/train/notes.txt", fs=fs)
    with pytest.raises(NotADirectoryError):
        infer("/nowhere", fs=fs)
    with pytest.raises(TypeError, match="directory path"):
        infer(["a/b.txt"], fs=fs)


# -- listing by prefix ---------------------------------------------------------


def partitioned():
    """A three-level partitioned layout: 2 years, 21 months, 357 days."""
    mem = fresh_memory()
    days = 0
    for year, months in ((2024, 12), (2025, 9)):
        for month in range(1, months + 1):
            for day in range(1, 18):
                mem.pipe(
                    f"/lake/events/year={year}/month={month:02d}/day={day:02d}/part-0.parquet",
                    b"",
                )
                days += 1
    # Keys beside the literal prefix, which a prefix listing never reads.
    for i in range(50):
        mem.pipe(f"/lake/other/blob-{i}.bin", b"")
    return mem, days


year, month, day = (
    Param("year", type=int),
    Param("month", type=int),
    Param("day", type=int),
)
events = (
    P("/lake")
    / "events"
    / T(t"year={year:d}")
    / T(t"month={month:02d}")
    / T(t"day={day:02d}")
    / T(t"part-{Param('part', type=int):d}.parquet")
)


def test_flat_listing_makes_one_request_for_the_literal_prefix():
    mem, days = partitioned()
    counting = Counting(mem)
    found = list(events.glob(fs=FsspecFS(counting, listing="flat")))
    assert len(found) == days == 357
    assert counting.calls == {"find": 1}
    assert counting.args == [("find", "/lake/events")]
    # A longer literal prefix narrows the listing.
    counting = Counting(mem)
    found = list(events.bind(year=2025).glob(fs=FsspecFS(counting)))
    assert len(found) == 9 * 17
    assert counting.args == [("find", "/lake/events/year=2025")]


def test_tree_listing_makes_one_request_per_directory_reached():
    mem, days = partitioned()
    counting = Counting(mem)
    tree = list(events.glob(fs=FsspecFS(counting, listing="tree")))
    flat = list(events.glob(fs=FsspecFS(mem, listing="flat")))
    assert tree == flat
    # events/, each year, each month, each day; plus one lookup for the
    # start of the walk. Kinds below come from the listings.
    assert counting.calls == {"ls": 1 + 2 + 21 + days, "info": 1}
    counting = Counting(mem)
    list(events.glob(fs=FsspecFS(counting, listing="tree"), kind="file"))
    assert counting.calls == {"ls": 1 + 2 + 21 + days, "info": 1}


def test_infer_lists_a_store_once():
    mem, days = partitioned()
    counting = Counting(mem)
    schema = infer("/lake/events", fs=FsspecFS(counting))
    assert counting.calls == {"find": 1}
    assert [lay.expr.pattern for lay in schema.layouts] == [
        "year={year:04d}/month={month:02d}/day={day:02d}/part-0.parquet"
    ]
    assert schema.total == days


# -- store semantics -------------------------------------------------------------


@pytest.mark.parametrize("listing", ["flat", "tree"])
def test_a_key_that_is_also_a_prefix_is_a_directory(listing):
    mem = fresh_memory()
    mem.pipe("/s/x/y", b"")
    mem.pipe("/s/x", b"")  # an object and a prefix of the same name
    mem.pipe("/s/z", b"")
    fs = FsspecFS(mem, listing=listing)
    e = P("/s") / Param("n")
    assert [m["n"] for m in e.glob(fs=fs)] == ["x", "z"]
    assert [m["n"] for m in e.glob(fs=fs, kind="dir")] == ["x"]
    assert [m["n"] for m in e.glob(fs=fs, kind="file")] == ["z"]


@pytest.mark.parametrize("listing", ["flat", "tree"])
def test_directory_markers_and_unrenderable_keys(listing):
    mem = fresh_memory()
    mem.pipe("/s/a/f.txt", b"")
    # An S3-style marker: an empty object whose key ends in "/".
    mem.store["/s/marker/"] = MemoryFile(mem, "/s/marker/", b"")
    # Keys with an empty or "." segment, which no expression renders.
    mem.store["/s/a//g.txt"] = MemoryFile(mem, "/s/a//g.txt", b"")
    mem.store["/s/a/./h.txt"] = MemoryFile(mem, "/s/a/./h.txt", b"")
    fs = FsspecFS(mem, listing=listing)
    assert [m["d"] for m in (P("/s") / Param("d")).glob(fs=fs, kind="dir")] == [
        "a",
        "marker",
    ]
    files = (P("/s") / SubPath("r") / Param("f")).glob(fs=fs, kind="file")
    assert [m.path for m in files] == ["/s/a/f.txt"]
    assert [lay.expr.pattern for lay in infer("/s", fs=fs).layouts] == [
        "a/f.txt",
        "marker",
    ]


class S3Like:
    """Keys in buckets, listed as s3fs 2026.9 lists them: ``find`` types
    every object as a file, so a directory marker ``bucket/m/`` is a file
    whose name ends in "/", and refuses to list the whole store."""

    protocol = "s3like"

    def __init__(self, keys):
        self.keys = keys

    @staticmethod
    def _strip_protocol(path):
        return path.removeprefix("s3like://").rstrip("/")

    def find(self, path, withdirs=False, detail=False):
        if not path:
            raise ValueError("Cannot traverse all of S3")
        below = [k for k in self.keys if k.startswith(path + "/")]
        return {k: {"name": k, "type": "file", "size": 0} for k in below}

    def ls(self, path, detail=True):
        out = {}
        pre = path + "/" if path else ""
        for k in self.keys:
            if k.startswith(pre):
                head, sep, _ = k[len(pre) :].partition("/")
                out[pre + head] = "directory" if sep else "file"
        return [{"name": n, "type": t} for n, t in out.items()]

    def info(self, path):
        if not path or any(k.startswith(path + "/") for k in self.keys):
            return {"name": path, "type": "directory"}
        if path in self.keys:
            return {"name": path, "type": "file"}
        raise FileNotFoundError(path)


@pytest.mark.parametrize("listing", ["flat", "tree"])
def test_a_marker_listed_as_an_object_is_a_directory(listing):
    fs = FsspecFS(S3Like(["b/m/", "b/x.txt"]), listing=listing)
    e = P("b") / Param("n")
    assert [m["n"] for m in e.glob(fs=fs, kind="dir")] == ["m"]
    assert [m["n"] for m in e.glob(fs=fs, kind="file")] == ["x.txt"]
    assert [lay.kind for lay in infer("b", fs=fs).layouts] == ["dir", "file"]


def test_a_store_that_cannot_list_its_root_is_walked_level_by_level():
    keys = ["b1/data/x.txt", "b2/data/y.txt", "b2/other/z.txt"]
    e = Segment("bucket") / "data" / T(t"{stem}.txt")
    for listing in ("flat", "tree"):
        found = e.glob(fs=FsspecFS(S3Like(keys), listing=listing))
        assert [(m["bucket"], m["stem"]) for m in found] == [("b1", "x"), ("b2", "y")]
    schema = infer(".", fs=FsspecFS(S3Like(keys)))  # "." is the store's root
    assert schema.total == 3


def test_url_to_fs_gives_a_filesystem_and_a_root_to_bind(tmp_path):
    mem = MemoryFileSystem()  # the global store, which url_to_fs uses
    key = "/wend-url-test/data/train/chunk_0001.parquet"
    mem.pipe(key, b"")
    try:
        fs, root = url_to_fs("memory://wend-url-test")
        assert isinstance(fs, FsspecFS) and root == "/wend-url-test"
        shard = Param("root") / "data" / split / chunk
        assert [m.path for m in shard.glob(root=root, fs=fs)] == [key]
        # A URL bound as a path reads as "memory:/wend-url-test": refused
        # when glob is called, not when it is iterated.
        with pytest.raises(ValueError, match="url_to_fs"):
            shard.glob(root="memory://wend-url-test", fs=fs)
    finally:
        mem.rm("/wend-url-test", recursive=True)
    local, path = url_to_fs(str(tmp_path))
    assert isinstance(local, LocalFS) and path == str(tmp_path)


def test_fsspec_local_filesystem_is_refused():
    from fsspec.implementations.local import LocalFileSystem

    with pytest.raises(ValueError, match="LocalFS"):
        FsspecFS(LocalFileSystem())
    with pytest.raises(ValueError, match="listing"):
        FsspecFS(fresh_memory(), listing="prefix")


def test_local_filesystem_given_explicitly_is_the_default(trees):
    local_root = trees[0]
    for make, options in EXPRESSIONS.values():
        assert run(make, local_root, LocalFS(), **options) == run(
            make, local_root, None, **options
        )


# -- random trees ------------------------------------------------------------------

NAMES = ["a", "b", "1", "01", "a.txt", "b.txt", "x-1.tar.gz", ".h"]
tree_paths = st.lists(
    st.tuples(st.lists(st.sampled_from(NAMES), min_size=1, max_size=3), st.booleans()),
    max_size=12,
)
s, e2, n = Param("s"), Param("e"), Param("n", type=int)
RANDOM_EXPRESSIONS = [
    (lambda r: P(r) / Param("a"), {}),
    (lambda r: P(r) / Param("a") / Param("b"), {"kind": "file"}),
    (lambda r: P(r) / Param("a") / Param("b"), {"kind": "dir"}),
    (lambda r: P(r) / SubPath("r") / T(t"{s}.txt"), {}),
    (lambda r: P(r) / "a" / Param("x"), {}),
    (lambda r: P(r) / Param("a") / T(t"{n:d}"), {}),
    (lambda r: P(r) / SubPath("r"), {"kind": "dir"}),
    (lambda r: P(r) / SubPath("r") / T(t"{s}.{e2}"), {}),
]


def consistent(paths):
    """Drop paths that would make a name both a file and a directory."""
    kinds = {}
    out = []
    for parts, is_dir in paths:
        names = ["/".join(parts[: i + 1]) for i in range(len(parts))]
        want = ["dir"] * (len(parts) - 1) + ["dir" if is_dir else "file"]
        if all(kinds.get(p, k) == k for p, k in zip(names, want, strict=True)):
            kinds.update(zip(names, want, strict=True))
            out.append(("/".join(parts), is_dir))
    return out


@settings(max_examples=60, deadline=None)
@given(paths=tree_paths)
def test_random_trees_glob_alike_locally_and_in_memory(paths):
    entries = consistent(paths)
    files = [p for p, d in entries if not d]
    dirs = [p for p, d in entries if d]
    with tempfile.TemporaryDirectory() as tmp:
        mem = fresh_memory()
        build(files, dirs, tmp, mem, "/t")
        for make, options in RANDOM_EXPRESSIONS:
            local = run(make, tmp, None, **options)
            for root, fs in filesystems(tmp, mem, "/t")[1:]:
                assert run(make, root, fs, **options) == local
