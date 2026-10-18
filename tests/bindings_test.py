"""Bindings from objects: dataclass, attrs and Pydantic instances, named tuples
and plain objects bind by field name wherever a mapping is accepted."""

import argparse
import dataclasses
from collections import namedtuple
from pathlib import Path
from types import MappingProxyType, SimpleNamespace

import attrs
import pytest

from wend import (
    Lens,
    MissingBindingError,
    P,
    Param,
    Segment,
    Step,
    SubPath,
    T,
    bindings,
)


root, split, idx = Param("root"), Segment("split"), Param("idx", type=int)
shard = root / "data" / split / T(t"chunk_{idx:04d}.parquet")
WANT = "/mnt/data/train/chunk_0007.parquet"


@dataclasses.dataclass
class Run:
    root: str
    split: str
    idx: int = 7
    note: str = "unused"


@attrs.define
class AttrsRun:
    root: str
    split: str
    idx: int = 7


Row = namedtuple("Row", "root split idx")


class Plain:
    def __init__(self) -> None:
        self.root, self.split, self.idx = "/mnt", "train", 7


def _sources():
    pydantic = pytest.importorskip("pydantic")

    class Model(pydantic.BaseModel):
        root: str
        split: str
        idx: int = 7

    return [
        Run("/mnt", "train"),
        AttrsRun("/mnt", "train"),
        Model(root="/mnt", split="train"),
        Row("/mnt", "train", 7),
        SimpleNamespace(root="/mnt", split="train", idx=7),
        argparse.Namespace(root="/mnt", split="train", idx=7),
        Plain(),
        MappingProxyType({"root": "/mnt", "split": "train", "idx": 7}),
    ]


def test_an_object_binds_by_field_name_everywhere():
    for src in _sources():
        assert bindings(src)["root"] == "/mnt", src
        assert shard.render(src) == WANT, src
        assert str(shard.resolve(src)) == WANT
        assert shard.bind(src).render() == WANT
        compiled = shard.compile()
        assert compiled.render(src) == WANT
        assert str(compiled(src)) == WANT
        assert compiled.many([src, src]) == [WANT, WANT]
        assert (shard | shard.with_suffix(".json")).renderings(src)[0] == WANT
        assert shard.name.render(src) == "chunk_0007.parquet"


def test_keywords_override_an_object():
    run = Run("/mnt", "train")
    assert shard.render(run, idx=3).endswith("chunk_0003.parquet")
    assert shard.compile().render(run, split="test").startswith("/mnt/data/test/")
    assert bindings(run, idx=1) == {
        "root": "/mnt",
        "split": "train",
        "idx": 1,
        "note": "unused",
    }


def test_bindings_normalises_param_keys():
    assert bindings({root: "/m"}, idx=1) == {"root": "/m", "idx": 1}
    assert bindings() == {}


def test_only_declared_fields_bind():
    @dataclasses.dataclass
    class WithExtras:
        root: str

        @property
        def split(self) -> str:  # a property is not a field
            return "train"

        def idx(self) -> int:  # nor is a method
            return 7

    with pytest.raises(MissingBindingError) as info:
        shard.render(WithExtras("/mnt"))
    assert info.value.missing == {"split", "idx"}
    # a parameter named like a tuple method is not bound to the method
    count = Param("count")
    assert bindings(Row("/m", "s", 1)).keys() == {"root", "split", "idx"}
    with pytest.raises(MissingBindingError):
        (P("a") / count).render(Row("/m", "s", 1))


def test_an_unset_dataclass_field_binds_nothing():
    @dataclasses.dataclass
    class Lazy:
        root: str
        split: str = dataclasses.field(init=False)

    assert bindings(Lazy("/m")) == {"root": "/m"}


def test_things_that_are_not_bindings_are_rejected():
    for bad in ("/mnt", b"x", Path("/mnt"), 3, Run, [("root", "/m")]):
        with pytest.raises(TypeError, match="Cannot take bindings"):
            shard.render(bad)
    with pytest.raises(TypeError, match="pass an instance"):
        bindings(Run)


def test_objects_reach_glob_lenses_steps_and_checks(tmp_path):
    (tmp_path / "data" / "train").mkdir(parents=True)
    (tmp_path / "data" / "train" / "chunk_0007.parquet").touch()
    src = SimpleNamespace(root=str(tmp_path))
    assert [m["idx"] for m in shard.glob(src)] == [7]
    assert [m["idx"] for m in shard.glob(src, split="train")] == [7]
    run = Run(str(tmp_path), "train")
    assert shard.check(run) == tmp_path / "data/train/chunk_0007.parquet"
    step = Step(src=shard)
    assert step.check(run)["src"] == tmp_path / "data/train/chunk_0007.parquet"
    lens = Lens(P("src") / SubPath("rel"), P("out") / SubPath("rel")).bind(
        SimpleNamespace(rel="a/b")
    )
    assert lens.target.render() == "out/a/b"


def test_a_pydantic_computed_field_can_render_from_its_own_model():
    """Part 1's PathVar example: the model supplies the bindings."""
    pydantic = pytest.importorskip("pydantic")

    ROOT = Param("root")
    CONFIG, DATA = ROOT / "config.yaml", ROOT / "data"

    class Paths(pydantic.BaseModel):
        root: Path

        @pydantic.computed_field
        @property
        def config(self) -> Path:
            return CONFIG.resolve(self)  # computed fields do not bind: no recursion

    paths = Paths(root=Path("/actual/root"))
    assert paths.config == Path("/actual/root/config.yaml")
    assert DATA.resolve(paths) == Path("/actual/root/data")
    assert bindings(paths) == {"root": Path("/actual/root")}
    extra = pydantic.create_model(
        "Extra", __config__=pydantic.ConfigDict(extra="allow"), root=(str, ...)
    )(root="/r", split="s")
    assert bindings(extra) == {"root": "/r", "split": "s"}
