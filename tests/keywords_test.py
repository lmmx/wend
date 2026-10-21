"""Options and keyword bindings share one namespace; parameters named like an
option are bound through the positional mapping."""

from pathlib import Path, PurePosixPath

import pytest

from wend import Lens, P, Param, T, glob
from wend.fs import LocalFS


kind, name = Param("kind"), Param("name")


@pytest.fixture
def tree(tmp_path):
    for f in ["raw/a.txt", "raw/b.txt", "cooked/c.txt"]:
        (tmp_path / f).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / f).touch()
    (tmp_path / "cooked" / "d.txt").mkdir()
    return tmp_path


def test_a_parameter_named_like_a_glob_option_binds_through_the_mapping(tree):
    e = P(tree) / kind / T(t"{name}.txt")
    assert [m["name"] for m in e.glob({"kind": "raw"})] == ["a", "b"]
    assert [m["name"] for m in glob(e, {kind: "raw"})] == ["a", "b"]
    # With the parameter bound in the mapping, the keyword is the option.
    assert [m["name"] for m in e.glob({"kind": "cooked"}, kind="file")] == ["c"]
    assert [m["name"] for m in e.glob({"kind": "cooked"}, kind="dir")] == ["d"]
    assert [m["kind"] for m in e.glob({"kind": "raw"}, kind="file")] == ["raw", "raw"]
    # Unbound and not named by a keyword, the parameter is discovered as usual.
    assert [(m["kind"], m["name"]) for m in e.glob()] == [
        ("cooked", "c"),
        ("cooked", "d"),
        ("raw", "a"),
        ("raw", "b"),
    ]


def test_a_keyword_naming_an_option_and_a_parameter_is_refused(tree):
    e = P(tree) / kind / T(t"{name}.txt")
    with pytest.raises(TypeError, match=r"glob\(\{'kind': \.\.\.\}\)"):
        e.glob(kind="raw")  # raised by the call, before any iteration
    with pytest.raises(TypeError, match="both an option of glob"):
        glob(e, {"name": "a"}, kind="file")
    # Renaming the parameter frees the keyword for the option.
    found = e.bind(kind=Param("k")).glob(kind="file")
    assert [(m["k"], m["name"]) for m in found] == [
        ("cooked", "c"),
        ("raw", "a"),
        ("raw", "b"),
    ]


@pytest.mark.parametrize(
    "option, value",
    [
        ("kind", "file"),
        ("follow_symlinks", True),
        ("recurse_symlinks", True),
        ("ambiguous", "skip"),
        ("fs", LocalFS()),
    ],
)
def test_every_glob_option_follows_one_rule(tree, option, value):
    e = P(tree) / Param(option) / T(t"{name}.txt")
    with pytest.raises(TypeError, match=f"{option!r} is both an option"):
        e.glob(**{option: value})
    found = e.glob({option: "raw"}, **{option: value})
    assert [(m[option], m["name"]) for m in found] == [("raw", "a"), ("raw", "b")]


@pytest.mark.parametrize(
    "option, value",
    [
        ("kind", "file"),
        ("follow_symlinks", True),
        ("recurse_symlinks", True),
        ("ambiguous", "skip"),
        ("fs", LocalFS()),
    ],
)
def test_union_and_query_glob_follow_the_same_rule(tree, option, value):
    # the parameter is in one alternative only; the union has it all the same
    u = P(tree) / Param(option) / T(t"{name}.txt") | P(tree) / "none" / name
    for source in (u, u.where(lambda m: True)):
        with pytest.raises(TypeError, match=f"{option!r} is both an option"):
            source.glob(**{option: value})  # raised by the call
        found = source.glob({option: "raw"}, **{option: value})
        assert [(m[option], m["name"]) for m in found] == [("raw", "a"), ("raw", "b")]
        # left unbound and not named by a keyword, it is discovered as usual
        found = [(m[option], m["name"]) for m in source.glob()]
        assert found == [("cooked", "c"), ("cooked", "d"), ("raw", "a"), ("raw", "b")]


def test_a_parameter_named_cls_resolves_through_the_mapping():
    img = T(t"train/{Param('cls')}/{Param('img')}.jpg")
    assert img.resolve({"cls": "n01"}, img="a") == Path("train/n01/a.jpg")
    pure = img.resolve({"cls": "n01"}, cls=PurePosixPath, img="a")
    assert type(pure) is PurePosixPath and str(pure) == "train/n01/a.jpg"
    with pytest.raises(TypeError, match=r"resolve\(\{'cls': \.\.\.\}\)"):
        img.resolve(cls="n01", img="a")
    # Without such a parameter, cls= is the result type, as before.
    assert T(t"train/{Param('img')}.jpg").resolve(img="a", cls=str) == "train/a.jpg"


def test_methods_without_options_take_any_parameter_name_by_keyword():
    names = ["kind", "cls", "mapping", "path", "ambiguous", "follow_symlinks"]
    e = P(".").joinpath(*(Param(n) for n in names))
    env = {n: n[0] for n in names}
    assert e.render(**env) == "k/c/m/p/a/f"
    assert e.bind(**env).render() == "k/c/m/p/a/f"
    assert e.compile().render(**env) == "k/c/m/p/a/f"
    assert e.compile()(**env) == Path("k/c/m/p/a/f")
    assert e.name.render(follow_symlinks="x") == "x"
    assert e.match("k/c/m/p/a/f") == env


def test_lens_takes_any_target_parameter_name():
    day = Param("day")
    lens = Lens(T(t"raw/{day}.csv"), T(t"out/{Param('path')}/{day}.parquet"))
    assert lens("raw/d1.csv", path="p") == Path("out/p/d1.parquet")
    assert lens("raw/d1.csv", {"path": "p"}) == Path("out/p/d1.parquet")
    assert lens.render("raw/d1.csv", path="p") == "out/p/d1.parquet"
    assert lens.backward("out/p/d1.parquet") == Path("raw/d1.csv")
    assert dict(lens.map(["raw/d1.csv"], path="p")) == {
        "raw/d1.csv": Path("out/p/d1.parquet")
    }


def test_lens_map_binds_a_parameter_named_ambiguous_through_the_mapping():
    day = Param("day")
    lens = Lens(T(t"raw/{day}.csv"), T(t"out/{Param('ambiguous')}/{day}.parquet"))
    with pytest.raises(TypeError, match=r"map\(paths, \{'ambiguous': \.\.\.\}\)"):
        lens.map(["raw/d1.csv"], ambiguous="r1")
    expected = {"raw/d1.csv": Path("out/r1/d1.parquet")}
    assert dict(lens.map(["raw/d1.csv"], {"ambiguous": "r1"})) == expected
    assert dict(lens.map(["raw/d1.csv"], {"ambiguous": "r1"}, ambiguous="skip")) == (
        expected
    )
    assert lens("raw/d1.csv", ambiguous="r1") == Path("out/r1/d1.parquet")
