from pathlib import PurePosixPath

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from wend import InvalidBindingError, MissingBindingError, P, Param, SubPath, T


pl = pytest.importorskip("polars")
from wend.frame import resolve_frame, to_polars  # noqa: E402


root, split, idx = Param("root"), Param("split"), Param("idx")
shard = root / "data" / split / T(t"chunk_{idx:04d}.parquet")


def test_resolve_frame_matches_render():
    df = pl.DataFrame(
        {"root": ["/mnt", "rel", "."], "split": ["a", "b", "c"], "idx": [1, 22, -3]}
    )
    got = resolve_frame(shard, df).to_list()
    assert got == [shard.render(r) for r in df.iter_rows(named=True)]


def test_validation_reports_row():
    df = pl.DataFrame({"root": ["/mnt", "/mnt"], "split": ["a", "../x"], "idx": [1, 2]})
    with pytest.raises(InvalidBindingError, match="Row 1"):
        resolve_frame(shard, df)
    with pytest.raises(MissingBindingError):
        resolve_frame(shard, df.drop("idx"))


def test_unsupported_formatting_is_refused():
    with pytest.raises(NotImplementedError):
        to_polars(T(t"x{idx:x}"), pl.Schema({"idx": pl.Int64}))
    with pytest.raises(NotImplementedError):
        to_polars(T(t"x{idx!r}"))


def test_lazy_frames_and_embedding():
    lf = pl.LazyFrame({"root": ["/r"], "split": ["s"], "idx": [5]})
    assert resolve_frame(shard, lf).to_list() == ["/r/data/s/chunk_0005.parquet"]
    out = lf.with_columns(path=to_polars(shard)).collect()
    assert out["path"][0] == "/r/data/s/chunk_0005.parquet"


name = st.text(alphabet="abz019_-.", min_size=1, max_size=4).filter(
    lambda s: s not in (".", "..")
)


@settings(max_examples=150, deadline=None)
@given(
    st.lists(
        st.tuples(
            st.sampled_from(["/m", "rel", ".", "/", "//n", "a/b"]),
            name,
            st.lists(name, max_size=2).map(lambda xs: "/".join(xs) or "."),
            st.integers(-50, 99999),
        ),
        min_size=1,
        max_size=8,
    )
)
def test_polars_equals_interpreter(rows):
    e = root / SubPath("sub") / split / T(t"{split}_{idx:05d}.bin")
    df = pl.DataFrame(rows, schema=["root", "split", "sub", "idx"], orient="row")
    assert resolve_frame(e, df).to_list() == [
        e.render(r) for r in df.iter_rows(named=True)
    ]
    e2 = P("/") / SubPath("sub")
    assert resolve_frame(e2, df).to_list() == [
        e2.render(r) for r in df.iter_rows(named=True)
    ]


hostile = st.one_of(
    name,
    st.sampled_from(["", ".", "..", "a/b", "../x", "/abs", "a//b", "x\x00", "a/./b"]),
)


@settings(max_examples=300, deadline=None)
@given(
    st.lists(
        st.tuples(
            st.sampled_from(["/m", "rel", ".", "/", "//n", "a/b", "a/", "", "/x/./y"]),
            hostile,
            st.one_of(
                st.lists(name, max_size=2).map(lambda xs: "/".join(xs) or "."), hostile
            ),
            st.integers(-50, 99999),
        ),
        min_size=1,
        max_size=6,
    )
)
def test_polars_never_disagrees_with_render(rows):
    e = root / SubPath("sub") / split / T(t"{split}_{idx:05d}.bin")
    df = pl.DataFrame(rows, schema=["root", "split", "sub", "idx"], orient="row")
    rendered = []
    for r in df.iter_rows(named=True):
        try:
            rendered.append(e.render(r))
        except InvalidBindingError:
            rendered.append(None)
    try:
        got = resolve_frame(e, df).to_list()
    except InvalidBindingError:
        # Allowed when some row is invalid for render, or when a path column is
        # not canonical (a documented restriction of the Polars backend).
        canonical = all(
            str(PurePosixPath(r["root"])) == r["root"] for r in df.iter_rows(named=True)
        ) and all(
            str(PurePosixPath(r["sub"])) == r["sub"]
            for r in df.iter_rows(named=True)
            if "\x00" not in r["sub"]
        )
        assert None in rendered or not canonical
        return
    assert None not in rendered, "resolve_frame accepted a row that render rejects"
    assert got == rendered
