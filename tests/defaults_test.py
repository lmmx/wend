"""Parameter defaults (docs/SEMANTICS.md §3.1)."""

import copy
import pickle
from pathlib import PurePosixPath

import pytest

from wend import (
    Absolute,
    AnyPath,
    InvalidBindingError,
    Lens,
    MissingBindingError,
    NotStaticError,
    P,
    Param,
    ParamConflictError,
    Segment,
    SubPath,
    T,
    Under,
)


root = Param("root")
split = Segment("split", default="train")
idx = Param("idx", type=int)
total = Param("total", type=int, default=100)
shard = root / "data" / split / T(t"chunk_{idx:04d}-of-{total:04d}.parquet")


# -- declaration ----------------------------------------------------------------


def test_a_default_is_part_of_the_declaration():
    assert total.has_default and total.default == 100
    assert not idx.has_default
    assert repr(total) == "Param('total', type=int, default=100)"
    assert total == Param("total", type=int, default=100)
    assert hash(total) == hash(Param("total", type=int, default=100))
    assert total != Param("total", type=int)
    assert total != Param("total", type=int, default=10)


def test_params_differing_only_in_default_conflict():
    with pytest.raises(ParamConflictError):
        T(t"{Param('n', default=1)}") / T(t"{Param('n', default=2)}")
    with pytest.raises(ParamConflictError):
        P("a") / Param("n") / Param("n", default="x")


def test_equal_but_differently_rendered_defaults_are_different_declarations():
    # 1 == True == 1.0, but they render as "1", "True" and "1.0"
    one, true = Param("n", default=1), Param("n", default=True)
    assert one != true and one != Param("n", default=1.0)
    # the template cache keys on declarations, so it must not mix them up
    assert T(t"x{one}").render() == "x1"
    assert T(t"x{true}").render() == "xTrue"
    assert T(t"x{Param('m', default=0.0)}").render() == "x0.0"
    assert T(t"x{Param('m', default=-0.0)}").render() == "x-0.0"


@pytest.mark.parametrize(
    "make",
    [
        lambda: Param("n", type=int, default="3"),  # type
        lambda: Param("s", choices={"a", "b"}, default="c"),  # choices
        lambda: Segment("s", default="a/b"),  # one segment
        lambda: Segment("s", default=".."),
        lambda: Segment("s", default=""),
        lambda: SubPath("s", default="../x"),  # no ..
        lambda: SubPath("s", default="/abs"),  # relative
        lambda: Absolute("a", default="rel"),  # absolute
        lambda: AnyPath("a", default=3),  # a path
        lambda: Param("a", default=b"bytes"),  # text
        lambda: Param("a", default="x\x00y"),  # no NUL
    ],
)
def test_a_default_must_be_a_valid_binding(make):
    with pytest.raises(InvalidBindingError, match="Invalid default"):
        make()


def test_a_default_must_be_hashable():
    with pytest.raises(TypeError, match="hashable"):
        Param("a", default=["x"])


def test_an_auto_default_is_checked_again_where_it_is_used():
    # valid as a head path, not as a segment: AUTO's kind is its position
    d = Param("d", default="/srv/data")
    assert P(d).render() == "/srv/data"
    with pytest.raises(InvalidBindingError):
        (P("base") / d).render()


def test_defaults_survive_pickling_and_copies():
    for clone in (pickle.loads(pickle.dumps(total)), copy.deepcopy(total)):
        assert clone == total and clone.default == 100
    plain = pickle.loads(pickle.dumps(idx))
    assert not plain.has_default and plain == idx
    e = pickle.loads(pickle.dumps(shard))
    assert e.defaults == shard.defaults and e.render(root="/m", idx=1) == shard.render(
        root="/m", idx=1
    )


# -- rendering --------------------------------------------------------------------


def test_render_uses_the_default_of_an_unbound_parameter():
    assert shard.required_params() == {"root", "idx"}
    assert shard.defaults == {"split": "train", "total": 100}
    want = "/mnt/data/train/chunk_0007-of-0100.parquet"
    assert shard.render(root="/mnt", idx=7) == want
    assert str(shard.resolve(root="/mnt", idx=7)) == want
    assert shard.compile().render(root="/mnt", idx=7) == want
    assert shard.compile().many([{"root": "/mnt", "idx": 7}]) == [want]
    assert shard.compile().columns(root=["/mnt"], idx=[7]) == [want]
    # an explicit binding wins
    assert shard.render(root="/mnt", idx=7, split="test", total=8) == (
        "/mnt/data/test/chunk_0007-of-0008.parquet"
    )


def test_compiled_renderers_see_param_keys_before_defaults():
    c = shard.compile()
    assert c.render({root: "/m", idx: 1, total: 5}) == shard.render(
        root="/m", idx=1, total=5
    )
    assert c.render({root: "/m", idx: 1, split: "x"}).endswith(
        "/x/chunk_0001-of-0100.parquet"
    )


def test_none_is_a_binding_not_an_absent_one():
    e = P("a") / Segment("s", default="d")
    assert e.render(s=None) == "a/None"  # §3: a segment formats None
    with pytest.raises(InvalidBindingError):
        shard.render(root="/m", idx=1, total=None)  # type=int


def test_missing_bindings_list_only_parameters_without_defaults():
    with pytest.raises(MissingBindingError) as info:
        shard.render(idx=1)
    assert info.value.missing == {"root"}


def test_defaults_reach_nested_specs_and_text():
    w = Param("w", type=int, default=3)
    e = T(t"c{idx:0{w}d}")
    assert e.render(idx=7) == "c007" and e.render(idx=7, w=5) == "c00007"
    assert e.compile().render(idx=7) == "c007"
    assert e.name.render(idx=7) == "c007"
    assert e.required_params() == {"idx"}


def test_defaults_in_deferred_operations():
    rel = SubPath("rel", default="a/b.txt")
    e = (P("/srv") / rel).parent / "x"
    assert e.render() == "/srv/a/x"
    assert (P("/srv") / rel).suffix.render() == ".txt"
    assert e.compile().render(rel="c/d") == "/srv/c/x"


def test_a_default_head():
    base = Absolute("base", default="/srv")
    e = base / "static" / Param("name")
    assert e.render(name="a.png") == "/srv/static/a.png"
    assert e.render(base="/opt", name="a.png") == "/opt/static/a.png"


def test_containment_bases_render_with_the_same_defaults():
    base = Absolute("base", default="/srv")
    e = (P(base) / AnyPath("rel")).requires(Under(P(base)))
    assert e.render(rel="a") == "/srv/a"
    for render in (e.render, e.compile().render):
        with pytest.raises(InvalidBindingError):
            render(rel="../etc")


def test_a_lens_target_fills_its_defaults():
    v = Segment("v", default="v1")
    lens = Lens(
        P("src") / T(t"{Param('n')}.md"), P("site") / v / T(t"{Param('n')}.html")
    )
    assert str(lens("src/a.md")) == "site/v1/a.html"
    assert str(lens("src/a.md", v="v2")) == "site/v2/a.html"


# -- binding --------------------------------------------------------------------


def test_bind_leaves_defaulted_parameters_free():
    b = shard.bind(root="/mnt")
    assert b.pattern == "/mnt/data/{split}/chunk_{idx:04d}-of-{total:04d}.parquet"
    assert b.defaults == {"split": "train", "total": 100}
    assert b.required_params() == {"idx"}
    assert b.render(idx=1) == shard.render(root="/mnt", idx=1)


def test_binding_the_defaults_applies_them_explicitly():
    b = shard.bind(shard.defaults)
    assert b.pattern == "{root}/data/train/chunk_{idx:04d}-of-0100.parquet"
    assert b.defaults == {}


def test_renaming_takes_the_new_declaration():
    e = shard.bind(total=Param("n", type=int))
    assert e.required_params() == {"root", "idx", "n"}


# -- matching and discovery ---------------------------------------------------------


def test_matching_reads_a_defaulted_part_from_the_path():
    m = shard.match("/mnt/data/test/chunk_0003-of-0010.parquet")
    assert m == {"root": "/mnt", "split": "test", "idx": 3, "total": 10}
    # the default is returned when the path holds it, not filled in
    m = shard.match("/mnt/data/train/chunk_0003-of-0100.parquet")
    assert m == {"root": "/mnt", "split": "train", "idx": 3, "total": 100}


def test_a_default_does_not_make_a_part_optional():
    assert shard.match("/mnt/data/chunk_0003-of-0100.parquet") is None
    assert shard.match("/mnt/data/train/chunk_0003.parquet") is None


def test_glob_discovers_defaulted_parameters_rather_than_fixing_them(tmp_path):
    for s in ("train", "test"):
        d = tmp_path / "data" / s
        d.mkdir(parents=True)
        (d / "chunk_0001-of-0002.parquet").touch()
    found = sorted((m["split"], m["total"]) for m in shard.glob(root=str(tmp_path)))
    assert found == [("test", 2), ("train", 2)]
    head = Absolute("base", default=str(tmp_path)) / "data" / split
    with pytest.raises(NotStaticError, match="does not apply defaults"):
        list(head.glob())
    assert len(list(head.glob(base=str(tmp_path)))) == 2
    # binding every default fixes split too
    assert [m.path for m in head.bind(head.defaults).glob()] == [
        str(tmp_path / "data" / "train")
    ]


# -- elsewhere ---------------------------------------------------------------------


def test_a_schema_source_keeps_defaults():
    from wend.schema import _param_source

    assert _param_source(total)[0] == "Param('total', type=int, default=100)"
    assert _param_source(split)[0] == "Segment('split', default='train')"


def test_resolve_frame_fills_absent_columns_with_defaults():
    pl = pytest.importorskip("polars")
    from wend.frame import resolve_frame

    df = pl.DataFrame({"root": ["/m", "/n"], "idx": [1, 2]})
    got = resolve_frame(shard, df).to_list()
    assert got == [shard.render(r) for r in df.iter_rows(named=True)]
    # a column that is present wins, nulls included
    df2 = df.with_columns(pl.Series("total", [5, None]))
    with pytest.raises(InvalidBindingError, match="null"):
        resolve_frame(shard, df2)
    with pytest.raises(MissingBindingError):
        resolve_frame(shard, df.drop("idx"))
    pathy = P(AnyPath("r", default=PurePosixPath("/p"))) / Param("x")
    assert resolve_frame(pathy, pl.DataFrame({"x": ["a"]})).to_list() == ["/p/a"]
    floaty = T(t"{Param('f', default=1.5)}")
    with pytest.raises(NotImplementedError, match="default"):
        resolve_frame(floaty, pl.DataFrame({"x": ["a"]}))
