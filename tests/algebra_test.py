from pathlib import Path, PurePosixPath

import pytest

from wend import (
    Absolute,
    AnyPath,
    InvalidBindingError,
    MissingBindingError,
    NotStaticError,
    P,
    Param,
    ParamConflictError,
    PathOperationError,
    Segment,
    SubPath,
    T,
)


root, dataset, idx, total = (
    Param("root"),
    Param("dataset"),
    Param("idx"),
    Param("total"),
)
chunk = root / "data" / dataset / T(t"chunk_{idx:04d}-of-{total:04d}.parquet")
B = {"root": "/mnt/storage", "dataset": "train", "idx": 7, "total": 100}


def test_readme_example_resolves():
    assert chunk.required_params() == {"root", "dataset", "idx", "total"}
    assert chunk.resolve(B) == Path(
        "/mnt/storage/data/train/chunk_0007-of-0100.parquet"
    )
    assert chunk.render(**B) == "/mnt/storage/data/train/chunk_0007-of-0100.parquet"


def test_pattern_mirrors_t_string_source():
    assert (
        chunk.pattern == "{root}/data/{dataset}/chunk_{idx:04d}-of-{total:04d}.parquet"
    )
    assert repr(P("/a") / T(t"{{lit}}_{idx}")) == "PathExpr('/a/{{lit}}_{idx}')"


def test_literals_normalise_like_pathlib():
    for s in ["a//b/./c/", "/x/./y", "//net/share", "///z", ".", ""]:
        assert P(s).render() == str(PurePosixPath(s))


def test_templates_split_on_literal_separators():
    e = T(t"{root}/chunks/{idx:03}.txt")
    assert e.parts and len(e.parts) == 2
    assert e.render(root="/data", idx=5) == "/data/chunks/005.txt"
    assert T(t"/abs/{dataset}").is_absolute() is True


def test_missing_bindings_error_lists_names():
    with pytest.raises(MissingBindingError, match="Missing bindings") as info:
        (root / dataset).render(root="/data")
    assert info.value.missing == {"dataset"}


def test_extra_bindings_are_ignored():
    assert (root / "x").render(root="/r", unused=1) == "/r/x"


# -- kinds ---------------------------------------------------------------


def test_param_after_head_defaults_to_segment_and_rejects_traversal():
    e = P("/srv/static") / Param("asset")
    assert e.render(asset="logo.png") == "/srv/static/logo.png"
    for bad in ["../etc/passwd", "a/b", "..", ".", "", "/etc/passwd"]:
        with pytest.raises(InvalidBindingError):
            e.render(asset=bad)


def test_subpath_accepts_multiple_segments_but_not_dotdot_or_absolute():
    e = P("/srv") / SubPath("rel") / "index.html"
    assert e.render(rel="a/b") == "/srv/a/b/index.html"
    assert e.render(rel=".") == "/srv/index.html"
    for bad in ["../x", "/abs", "a/../b"]:
        with pytest.raises(InvalidBindingError):
            e.render(rel=bad)


def test_absolute_kind():
    e = Absolute("base") / "x"
    assert e.is_absolute() is True
    with pytest.raises(InvalidBindingError):
        e.render(base="rel")
    assert (P("/ignored") / Absolute("base")).render(base="/b") == "/b"


def test_anypath_keeps_pathlib_join_semantics_mid_expression():
    e = P("/a") / AnyPath("p") / "z"
    assert e.render(p="b/c") == "/a/b/c/z"
    assert e.render(p="/abs") == "/abs/z"


def test_typed_and_choice_params():
    split = Segment("split", choices={"train", "test"})
    n = Param("n", type=int)
    e = P("/d") / split / T(t"{n:03d}.bin")
    assert e.render(split="train", n=4) == "/d/train/004.bin"
    with pytest.raises(InvalidBindingError):
        e.render(split="valid", n=4)
    with pytest.raises(InvalidBindingError):
        e.render(split="train", n="4")


def test_conflicting_declarations_are_rejected():
    with pytest.raises(ParamConflictError):
        Param("x") / Param("x", type=int)


def test_fstring_misuse_is_caught():
    with pytest.raises(TypeError, match="t-string"):
        P("/a") / f"chunk_{idx}"


def test_field_values_cannot_inject_separators():
    e = P("/a") / T(t"{dataset}.csv")
    with pytest.raises(InvalidBindingError):
        e.render(dataset="x/y")


def test_conversions_are_applied():
    assert T(t"f_{dataset!r}").render(dataset="a") == "f_'a'"
    assert T(t"f_{dataset!a}").render(dataset="é") == "f_'\\xe9'"


def test_dynamic_format_spec():
    width = Param("width")
    e = T(t"x_{idx:0{width}d}")
    assert e.render(idx=3, width=5) == "x_00003"
    assert e.bind(width=2).render(idx=3) == "x_03"


# -- structural operations -----------------------------------------------


def test_parent_is_structural_and_drops_unused_params():
    assert chunk.parent.pattern == "{root}/data/{dataset}"
    assert chunk.parent.required_params() == {"root", "dataset"}


def test_parent_of_subpath_is_deferred_not_guessed():
    e = root / SubPath("rel")
    assert e.parent.pattern == "parent({root}/{rel...})"
    assert e.parent.render(root="/x", rel="a/b") == "/x/a"


def test_parents_static():
    e = P("/a") / dataset / "f.txt"
    assert [x.pattern for x in e.parents] == ["/a/{dataset}", "/a", "/"]
    with pytest.raises(NotStaticError):
        (root / "x").parents  # noqa: B018


def test_suffix_and_stem_are_static_when_decidable():
    assert chunk.suffix.literal == ".parquet"
    assert chunk.stem.pattern == "chunk_{idx:04d}-of-{total:04d}"
    e = P("/a") / T(t"{dataset}")
    assert e.suffix.pattern == "{suffix(/a/{dataset})}"
    assert e.suffix.render(dataset="x.tar.gz") == ".gz"
    assert T(t"run_{idx:d}").suffix.literal == ""


def test_with_suffix_chain_matches_pathlib():
    e = root / "a.tar.gz"
    assert e.with_suffix("").with_suffix(".json").render(root="/x") == "/x/a.json"
    e = root / "a.txt"
    assert (
        e.with_suffix(".tar.gz").with_suffix(".json").render(root="/x")
        == "/x/a.tar.json"
    )


def test_with_name_and_stem():
    assert (
        chunk.with_name("schema.json").render(B)
        == "/mnt/storage/data/train/schema.json"
    )
    assert chunk.with_stem("meta").render(B) == "/mnt/storage/data/train/meta.parquet"
    with pytest.raises(PathOperationError):
        P("/").with_name("x")
    with pytest.raises(PathOperationError):
        chunk.with_name("a/b")


def test_with_name_from_another_expression():
    src = P("/in") / T(t"{dataset}.csv")
    out = (P("/out") / "x").with_name(src.stem + ".json")
    assert out.render(dataset="sales") == "/out/sales.json"


def test_relative_to_is_static_for_structural_prefixes():
    rel = chunk.relative_to(root / "data")
    assert rel.pattern == "{dataset}/chunk_{idx:04d}-of-{total:04d}.parquet"
    assert chunk.is_relative_to(root) is True
    with pytest.raises(PathOperationError):
        P("/a/b").relative_to("/c")


# -- binding -------------------------------------------------------------


def test_partial_binding_folds():
    e = chunk.bind(root="/mnt", total=100)
    assert e.pattern == "/mnt/data/{dataset}/chunk_{idx:04d}-of-0100.parquet"
    assert e.required_params() == {"dataset", "idx"}


def test_binding_a_path_rebases():
    cfg = root / "config" / "settings.yaml"
    assert cfg.bind(root=P("/tmp/test")).render() == "/tmp/test/config/settings.yaml"
    assert cfg.rebase(root, "/elsewhere").render() == "/elsewhere/config/settings.yaml"


def test_binding_a_param_renames():
    e = chunk.bind(idx=Param("i"))
    assert "i" in e.required_params() and "idx" not in e.required_params()


def test_binding_unlocks_deferred_operations():
    e = (root / SubPath("rel")).parent / "x"
    assert e.bind(rel="a/b").pattern == "{root}/a/x"


def test_resolve_accepts_param_keys_and_cls():
    assert chunk.resolve(
        {root: "/m", dataset: "d", idx: 1, total: 2}, cls=str
    ).endswith("0001-of-0002.parquet")


def test_not_pathlike_by_design():
    with pytest.raises(TypeError):
        open(chunk)  # noqa: SIM115
    assert Path("/base") / P("x") == P("/base/x")


def test_used_expressions_pickle_and_copy():
    import copy
    import pickle

    e = chunk.bind(root="/m")
    e.compile()
    e.match("/m/data/x/chunk_0001-of-0002.parquet")
    for clone in (pickle.loads(pickle.dumps(e)), copy.deepcopy(e), copy.copy(e)):
        assert clone == e
        assert clone.render(dataset="x", idx=1, total=2) == e.render(
            dataset="x", idx=1, total=2
        )
        assert clone.match("/m/data/x/chunk_0001-of-0002.parquet") == {
            "dataset": "x",
            "idx": 1,
            "total": 2,
        }
    w = pickle.loads(pickle.dumps(Param("w")))
    assert T(t"x_{idx:0{w}d}").render(idx=3, w=4) == "x_0003"
