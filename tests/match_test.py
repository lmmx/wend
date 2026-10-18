import pytest

from wend import AmbiguousMatchError, NotInvertibleError, P, Param, SubPath, T
from wend._match import _expr_plan, seg_plan


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


# -- Fast-path shapes (docs/SEMANTICS.md §8) ---------------------------------

stem, rel = Param("stem"), SubPath("rel")
model, epoch = Param("model"), Param("epoch", type=int)


def test_subpath_with_a_fixed_head_and_tail_takes_the_fast_path():
    src = (root / rel / T(t"{stem}.py")).bind(root="/src")
    assert _expr_plan(src) is not None
    assert src.match("/src/a/b/c.py") == {"rel": "a/b", "stem": "c"}
    assert src.match("/src/c.py") == {"rel": ".", "stem": "c"}
    assert src.match("/src/a/../c.py") is None  # a SubPath has no ".."
    assert src.match("/other/c.py") is None
    blobs = P("/mnt") / "data" / rel / "x" / T(t"chunk_{idx:04d}.bin")
    assert blobs.match("/mnt/data/a/b/x/chunk_0003.bin") == {"rel": "a/b", "idx": 3}
    assert blobs.match("/mnt/data/x/chunk_0003.bin") == {"rel": ".", "idx": 3}
    assert blobs.match("/mnt/data/x/x/chunk_0003.bin") == {"rel": "x", "idx": 3}


@pytest.mark.parametrize(
    "head", ["/mnt/storage", "/", "//", "//net", "//net/x", ".", "a", "a/b"]
)
def test_fast_path_head_extent(head):
    path = chunk.render(root=head, dataset="d", idx=1, total=2)
    assert _expr_plan(chunk) is not None
    assert chunk.match(path) == {"root": head, "dataset": "d", "idx": 1, "total": 2}
    assert chunk.match_all(path) == chunk.match_all(path, fast=False)


def test_head_param_with_subpath_stays_on_the_full_search():
    src = root / rel / T(t"{stem}.py")
    assert _expr_plan(src) is None
    with pytest.raises(AmbiguousMatchError):
        src.match("/src/a/c.py")
    assert src.match("c.py") == {"root": ".", "rel": ".", "stem": "c"}


def test_string_field_before_a_right_bounded_tail():
    ckpt = P("/ckpt") / T(t"{model}_epoch{epoch:03d}.pt")
    assert _expr_plan(ckpt) is not None
    assert ckpt.match("/ckpt/resnet_50_epoch007.pt") == {
        "model": "resnet_50",
        "epoch": 7,
    }
    assert ckpt.match("/ckpt/a_epoch1_epoch-12.pt") == {
        "model": "a_epoch1",
        "epoch": -12,
    }
    # A "-" before an int could be the int's sign: left to the full search.
    dashed = T(t"{model}-{epoch:d}")
    assert _expr_plan(dashed) is None
    with pytest.raises(AmbiguousMatchError):
        dashed.match("x--5")


def test_hex_octal_and_binary_fields():
    n = Param("n", type=int)
    e = T(t"obj_{n:04x}.{idx:o}-{total:b}")
    assert _expr_plan(e) is not None
    assert e.match("obj_00ff.17-101") == {"n": 255, "idx": 15, "total": 5}
    assert e.match("obj_-00f.-17--101") == {"n": -15, "idx": -15, "total": -5}
    assert e.match("obj_00FF.17-101") is None  # x is lowercase
    # "b" is a hex digit, so the split between the fields is not forced.
    assert _expr_plan(T(t"{n:x}b{idx:x}")) is None


def test_choices_fields_compile_to_alternations():
    split = Param("split", choices={"train", "test", "val"})
    e = P("/d") / T(t"{split}_{stem}.csv")
    assert _expr_plan(e) is not None
    assert e.match("/d/test_a_b.csv") == {"split": "test", "stem": "a_b"}
    assert e.match("/d/dev_a.csv") is None
    # "a" + "_" begins "a_b": a text "a_b_c" splits two ways.
    nested = Param("nested", choices={"a", "a_b"})
    assert _expr_plan(T(t"{nested}_{stem}")) is None


def test_untyped_zero_padded_spec_parses_as_str():
    u = Param("u")
    e = T(t"x{u:05}")
    assert _expr_plan(e) is None
    assert e.match("x00003") == {"u": "00003"}


def test_fast_path_reads_newlines_and_long_numbers():
    e = P("/r") / T(t"{stem}.txt")
    assert e.match("/r/a\nb.txt") == {"stem": "a\nb"}
    n = Param("n", type=int)
    assert T(t"x{n:d}").match("x" + "1" * 5000) is None  # beyond int()'s limit


def test_glob_uses_the_same_segment_plans(tmp_path):
    n = Param("n", type=int)
    split = Param("split", choices={"train", "test"})
    layouts = [
        P(tmp_path) / T(t"{split}_{stem}") / T(t"{model}_{n:03x}.bin"),
        P(tmp_path) / T(t"{split}_{stem}") / T(t"{model}.bin"),
    ]
    dirs = ["train_1", "test_a_b", "dev_x"]
    names = ["a_00f.bin", "a\nb_0ff.bin", "a_b_-01.bin", "x_1.bin", "a_00F.bin"]
    for d in dirs:
        (tmp_path / d).mkdir()
        for f in names:
            (tmp_path / d / f).touch()
    for e in layouts:
        assert all(seg_plan(p) is not None for p in e.parts[-2:])
        found = {m.path: dict(m) for m in e.glob()}
        assert found, e
        for d in dirs:
            for f in names:
                path = f"{tmp_path}/{d}/{f}"
                want = e.match_all(path, fast=False)
                assert ([found[path]] if path in found else []) == want, path
