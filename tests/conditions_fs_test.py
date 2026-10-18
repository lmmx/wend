"""Conditions on fsspec filesystems (docs/SEMANTICS.md §10).

A store has no permission bits: each capability is what the store can
report, and a condition it cannot determine raises `IndeterminateError`,
never a known failure.
"""

import os
from pathlib import Path

import pytest
from fsspec.implementations.memory import MemoryFileSystem

from wend import (
    Absent,
    CapabilityError,
    ConditionError,
    Creatable,
    Dir,
    Exists,
    File,
    IndeterminateError,
    Listable,
    MissingPathError,
    P,
    Param,
    PathExistsError,
    Query,
    Readable,
    Step,
    T,
    U,
    Under,
    Writable,
    WrongKindError,
)
from wend.conditions import check_conditions
from wend.fs import FsspecFS, LocalFS
from wend.query import larger_than


def store(cls: type = MemoryFileSystem) -> MemoryFileSystem:
    """A memory filesystem (or subclass) with its own, empty store."""
    fs = cls(skip_instance_cache=True)
    fs.store = {}
    fs.pseudo_dirs = [""]
    return fs


class Unknown(MemoryFileSystem):
    """A backend wend knows nothing about: no capability can be inferred."""

    protocol = ("stub",)


class S3Like(MemoryFileSystem):
    """A store whose object metadata takes the object's read permission."""

    protocol = ("s3",)


class ReadOnly(MemoryFileSystem):
    """A filesystem that never accepts writes, as HTTP does."""

    protocol = ("https",)


class Forbidding(MemoryFileSystem):
    """A store that refuses to show anything under ``/secret``."""

    protocol = ("s3",)

    def info(self, path, **kw):
        if "secret" in path:
            raise PermissionError(f"Access Denied: {path}")
        return super().info(path, **kw)

    def ls(self, path, detail=True, **kw):
        if "locked" in path:
            raise PermissionError(f"Access Denied: {path}")
        return super().ls(path, detail=detail, **kw)


def populate(fs: MemoryFileSystem) -> None:
    fs.pipe("/data/file.csv", b"a,b\n")
    fs.makedirs("/data/dir", exist_ok=True)
    fs.pipe("/data/dir/x.txt", b"x")


def outcome(fn, *args, **kw) -> str:
    try:
        fn(*args, **kw)
    except ConditionError as e:
        return type(e).__name__
    return "ok"


CONDITIONS = [Exists, Absent, File, Dir, Readable, Listable, Writable, Creatable]


def test_the_memory_filesystem_agrees_with_the_local_disk(tmp_path):
    """Memory is a store that reports every capability (reads are free and
    writes always succeed), so it gives the local answers wherever the
    local disk gives no permission failure."""
    mem = store()
    populate(mem)
    (tmp_path / "data" / "dir").mkdir(parents=True)
    (tmp_path / "data" / "file.csv").write_text("a,b\n")
    (tmp_path / "data" / "dir" / "x.txt").write_text("x")
    for rel in ("data/file.csv", "data/dir", "data/missing", "data/dir/new"):
        for c in CONDITIONS:
            local = outcome(check_conditions, str(tmp_path / rel), (c,), {})
            remote = outcome(check_conditions, f"/{rel}", (c,), {}, FsspecFS(mem))
            assert remote == local, (rel, c)


def test_on_a_store_a_name_below_an_object_can_be_created():
    """Keys are independent on a store: ``file.csv/x`` can be created even
    though ``file.csv`` is an object, where a local disk refuses it."""
    mem = store()
    populate(mem)
    check_conditions("/data/file.csv/x", (Creatable,), {}, FsspecFS(mem))


def test_unknown_capabilities_are_indeterminate_not_false():
    fs = store(Unknown)
    populate(fs)
    wfs = FsspecFS(fs)
    with pytest.raises(IndeterminateError, match="could not be checked") as e:
        check_conditions("/data/file.csv", (Readable,), {}, wfs)
    assert e.value.condition is Readable and not isinstance(e.value, CapabilityError)
    with pytest.raises(IndeterminateError):
        check_conditions("/data/file.csv", (Writable,), {}, wfs)
    with pytest.raises(IndeterminateError):
        check_conditions("/data/new.csv", (Creatable,), {}, wfs)
    # What the store does report is still checked.
    check_conditions("/data/dir", (Dir, Listable, Readable), {}, wfs)
    with pytest.raises(MissingPathError):
        check_conditions("/data/missing", (Readable,), {}, wfs)
    with pytest.raises(WrongKindError):
        check_conditions("/data/file.csv", (Listable,), {}, wfs)


def test_object_metadata_shows_readability_where_it_takes_read_permission():
    fs = store(S3Like)
    populate(fs)
    check_conditions("/data/file.csv", (File, Readable), {}, FsspecFS(fs))
    with pytest.raises(IndeterminateError, match="without writing"):
        check_conditions("/data/file.csv", (Writable,), {}, FsspecFS(fs))


def test_read_only_backends_refuse_writes():
    fs = store(ReadOnly)
    populate(fs)
    with pytest.raises(CapabilityError, match="read-only"):
        check_conditions("/data/file.csv", (Writable,), {}, FsspecFS(fs))
    with pytest.raises(CapabilityError, match="cannot be created"):
        check_conditions("/data/new.csv", (Creatable,), {}, FsspecFS(fs))
    check_conditions("/data/file.csv", (Creatable,), {}, FsspecFS(fs))  # exists


def test_a_path_the_store_will_not_show_is_not_absent():
    fs = store(Forbidding)
    fs.pipe("/secret/key", b"k")
    wfs = FsspecFS(fs)
    for c in (Exists, Absent, File, Readable):
        with pytest.raises(IndeterminateError, match="Access Denied"):
            check_conditions("/secret/key", (c,), {}, wfs)


def test_a_listing_the_store_refuses_is_not_listable():
    fs = store(Forbidding)
    fs.pipe("/locked/a", b"a")
    with pytest.raises(CapabilityError, match="not listable"):
        check_conditions("/locked", (Listable,), {}, FsspecFS(fs))


def test_containment_on_a_store_is_lexical():
    mem = store()
    populate(mem)
    root, name = Param("root"), Param("name")
    e = (P(root) / name).requires(Under(P(root)), Exists)
    assert e.check(root="/data", name="file.csv", fs=FsspecFS(mem)) == Path(
        "/data/file.csv"
    )


def test_expressions_and_steps_check_on_the_given_filesystem():
    mem = store()
    populate(mem)
    wfs = FsspecFS(mem)
    root, day = Param("root"), Param("day")
    src = (P(root) / "file.csv").requires(File, Exists, Readable)
    dst = (P(root) / T(t"{day}.parquet")).requires(Absent, Creatable).ensures(Exists)
    assert src.check(root="/data", fs=wfs) == Path("/data/file.csv")
    with pytest.raises(MissingPathError):
        src.check(root="/elsewhere", fs=wfs)
    step = Step(src=src, dst=dst)
    with step(root="/data", day="mon", fs=wfs) as p:
        mem.pipe(str(p["dst"]), b"out")
    with pytest.raises(PathExistsError):
        step.check(root="/data", day="mon", fs=wfs)
    assert step.confirm(root="/data", day="mon", fs=wfs)["dst"] == Path(
        "/data/mon.parquet"
    )
    # The local disk is still the default, and LocalFS names it.
    for local in (None, LocalFS()):
        with pytest.raises(MissingPathError):
            src.check(root="/data", fs=local)


def test_a_union_does_not_skip_an_alternative_it_could_not_check():
    fs = store(Forbidding)
    fs.pipe("/public/app.toml", b"")
    fs.pipe("/secret/app.toml", b"")
    wfs = FsspecFS(fs)
    both = U(P("/secret") / "app.toml", P("/public") / "app.toml")
    with pytest.raises(IndeterminateError):
        both.first(fs=wfs)
    later = U(P("/missing") / "app.toml", P("/public") / "app.toml")
    assert later.first(fs=wfs) == Path("/public/app.toml")


def test_queries_raise_rather_than_drop_what_they_cannot_determine():
    fs = store(Unknown)
    populate(fs)
    wfs = FsspecFS(fs)
    name = Param("name")
    files = P("/data") / name
    assert [m["name"] for m in Query(files).where(Exists).glob(fs=wfs)] == [
        "dir",
        "file.csv",
    ]
    with pytest.raises(IndeterminateError):
        list(Query(files).where(Writable).glob(fs=wfs))
    with pytest.raises(TypeError, match="local disk"):
        list(Query(files).where(larger_than(0)).glob(fs=wfs))


def test_the_fs_option_is_kept_apart_from_a_parameter_named_fs():
    mem = store()
    populate(mem)
    fs = Param("fs")
    e = (P("/data") / fs).requires(Exists)
    with pytest.raises(TypeError, match="both an option"):
        e.check(fs=FsspecFS(mem))
    assert e.check({"fs": "file.csv"}, fs=FsspecFS(mem)) == Path("/data/file.csv")


def test_other_filesystem_objects_are_refused():
    with pytest.raises(TypeError, match="FsspecFS"):
        check_conditions("/x", (Exists,), {}, object())


def test_a_local_path_that_cannot_be_examined_is_indeterminate(tmp_path, monkeypatch):
    target = str(tmp_path / "x")
    real = os.stat

    def stat(path, *a, **kw):
        if os.fspath(path) == target:
            raise PermissionError(13, "Permission denied", target)
        return real(path, *a, **kw)

    monkeypatch.setattr(os, "stat", stat)
    with pytest.raises(IndeterminateError, match="could not be checked") as e:
        check_conditions(target, (Exists,), {})
    assert isinstance(e.value, ConditionError)
