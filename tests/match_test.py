import pytest

from wend import AmbiguousMatchError, NotInvertibleError, P, Param, SubPath, T


root, dataset, idx, total = (
    Param("root"),
    Param("dataset"),
    Param("idx"),
    Param("total"),
)
chunk = root / "data" / dataset / T(t"chunk_{idx:04d}-of-{total:04d}.parquet")


def test_match_extracts_typed_bindings():
    m = chunk.match("/mnt/storage/data/train/chunk_0007-of-0100.parquet")
    assert m == {"root": "/mnt/storage", "dataset": "train", "idx": 7, "total": 100}
    assert m.path == "/mnt/storage/data/train/chunk_0007-of-0100.parquet"


def test_match_rejects_non_canonical_formatting():
    # 7 formats as "0007" under :04d, so "007" is not a rendering of any binding
    assert chunk.match("/m/data/train/chunk_007-of-0100.parquet") is None
    assert chunk.match("/m/data/train/chunk_0007-of-0100.csv") is None


def test_match_with_partial_bindings():
    m = chunk.bind(root="/mnt").match("/mnt/data/x/chunk_0001-of-0002.parquet")
    assert m == {"dataset": "x", "idx": 1, "total": 2}
    assert (
        chunk.bind(root="/other").match("/mnt/data/x/chunk_0001-of-0002.parquet")
        is None
    )


def test_adjacent_fields_are_reported_as_ambiguous():
    a, b = Param("a"), Param("b")
    e = T(t"{a}{b}")
    with pytest.raises(AmbiguousMatchError) as info:
        e.match("xy")
    assert {"a": "x", "b": "y"} in info.value.candidates
    assert (
        len(e.match_all("xy")) == 3
    )  # "", "x", "xy" split points are all valid strings


def test_typed_adjacent_fields_can_be_unambiguous():
    w = Param("w")
    n = Param("n", type=int)
    assert T(t"{w}{n:03d}").match("run042") == {"w": "run", "n": 42}


def test_subpath_needs_a_bound_root_to_be_unambiguous():
    src = root / SubPath("rel") / T(t"{Param('stem')}.py")
    with pytest.raises(AmbiguousMatchError):
        src.match("/src/a/b/c.py")
    assert src.bind(root="/src").match("/src/a/b/c.py") == {"rel": "a/b", "stem": "c"}


def test_repeated_params_must_agree():
    e = P("/d") / dataset / T(t"{dataset}.json")
    assert e.match("/d/x/x.json") == {"dataset": "x"}
    assert e.match("/d/x/y.json") is None


def test_hex_and_repr_fields_invert():
    n = Param("n", type=int)
    assert T(t"obj_{n:x}").match("obj_ff") == {"n": 255}
    assert T(t"k={dataset!r}").match("k='abc'") == {"dataset": "abc"}


def test_deferred_head_is_not_invertible():
    e = (root / SubPath("rel")).parent / "x"
    with pytest.raises(NotInvertibleError):
        e.match("/a/b/x")


def test_relative_and_absolute_anchors_must_agree():
    assert P("rel") / dataset == P("rel") / dataset
    assert (P("rel") / dataset).match("/rel/x") is None
    assert (P("/rel") / dataset).match("rel/x") is None


def test_a_match_without_bindings_is_truthy():
    m = P("a/b").match("a/b")
    assert m is not None and len(m) == 0
    assert m
