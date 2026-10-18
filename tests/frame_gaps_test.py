"""Differential tests: Polars resolution against render, on hostile inputs.

For every frame, ``resolve_frame`` must either return exactly what ``render``
returns row by row, or raise for a row that ``render`` rejects; and
``to_polars`` must agree with ``render`` on every row that ``render`` accepts.
Where Polars cannot be exact the lowering raises NotImplementedError.

Raise the example counts with WEND_FRAME_EXAMPLES=5000 (for instance).
"""

import itertools
import os
import re
from pathlib import PurePosixPath
from string.templatelib import Interpolation, Template

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from wend import (
    Absolute,
    AnyPath,
    InvalidBindingError,
    P,
    Param,
    PathOperationError,
    Segment,
    SubPath,
    T,
)


pl = pytest.importorskip("polars")
from wend.frame import resolve_frame, to_polars  # noqa: E402


EXAMPLES = int(os.environ.get("WEND_FRAME_EXAMPLES", "0"))


def examples(n: int) -> settings:
    return settings(
        max_examples=EXAMPLES or n,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large],
    )


REJECTED = (InvalidBindingError, PathOperationError)


def rendered(e, df):
    out = []
    for r in df.iter_rows(named=True):
        try:
            out.append(e.render(r))
        except REJECTED:
            out.append(None)
    return out


def agrees(e, df) -> bool:
    """Assert the contract; return whether every row was accepted."""
    want = rendered(e, df)
    lowered = df.select(to_polars(e, df.schema).alias("p"))["p"].to_list()
    for i, (w, g) in enumerate(zip(want, lowered)):
        if w is not None:
            assert g == w, f"to_polars row {i}: {g!r} != render {w!r}"
    try:
        got = resolve_frame(e, df).to_list()
    except REJECTED as err:
        m = re.match(r"Row (\d+)", str(err))
        assert m is not None, err
        row = int(m[1])
        assert want[row] is None, (
            f"resolve_frame rejected row {row} ({err}), render gave {want[row]!r}"
        )
        return False
    assert None not in want, "resolve_frame accepted a row that render rejects"
    assert got == want
    return True


def template(*items) -> Template:
    return Template(*items)


def field(param, spec="", conv=None) -> Interpolation:
    return Interpolation(param, param.name, conv, spec)


# ---------------------------------------------------------------------------
# Canonical path columns
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    ["a/", "./a", "a//b", "/a/./b", "//x", "///x", "", ".", "./", "//", "///", "/."],
)
def test_non_canonical_heads_render_like_render(value):
    e = Param("root") / "data"
    df = pl.DataFrame({"root": [value, "/m"]})
    assert resolve_frame(e, df).to_list() == [e.render(root=value), "/m/data"]


def test_canonicalisation_is_exhaustively_exact():
    alphabet = "/.a\n"
    values = [
        "".join(t) for n in range(8) for t in itertools.product(alphabet, repeat=n)
    ]
    df = pl.DataFrame({"root": values})
    got = resolve_frame(P(Param("root")), df).to_list()
    assert got == [str(PurePosixPath(v)) for v in values]
    sub = P("x") / SubPath("sub")
    assert agrees(sub, df.rename({"root": "sub"})) is False  # "/..." and ".." rows
    ok = [v for v in values if not v.startswith("/") and ".." not in v.split("/")]
    assert agrees(sub, pl.DataFrame({"sub": ok}))


def test_columns_that_skip_normalisation_are_canonical():
    # resolve_frame leaves a path column as it is when no value is flagged.
    from wend.frame import _maybe_noncanonical

    values = ["".join(t) for n in range(10) for t in itertools.product("/.a", repeat=n)]
    flagged = (
        pl.DataFrame({"s": values})
        .select(_maybe_noncanonical(pl.col("s")))
        .to_series()
        .to_list()
    )
    for v, f in zip(values, flagged):
        assert f or str(PurePosixPath(v)) == v, v
    df = pl.DataFrame({"root": [v for v, f in zip(values, flagged) if not f]})
    assert resolve_frame(P(Param("root")), df).to_list() == df["root"].to_list()


path_text = st.one_of(
    st.lists(
        st.sampled_from(
            ["", "/", "//", ".", "..", "a", "b.c", " ", "\x00", "é", "\n", ".x", "~"]
        ),
        max_size=7,
    ).map("".join),
    st.text(max_size=6),
)
seg_text = st.one_of(
    st.sampled_from(["a", "b.c", "..", ".", "", "x/y", "\x00", " ", "é", ".h"]),
    st.text(max_size=4),
)


@examples(200)
@given(
    st.lists(
        st.tuples(path_text, path_text, seg_text, st.integers(-(2**63), 2**63 - 1)),
        min_size=1,
        max_size=6,
    ),
    st.sampled_from(["path", "absolute", "subpath-only"]),
)
def test_path_columns_never_disagree(rows, shape):
    df = pl.DataFrame(
        rows, schema=["root", "sub", "seg", "n"], orient="row"
    ).with_columns(pl.col("n").cast(pl.Int64))
    if shape == "path":
        e = Param("root") / SubPath("sub") / Segment("seg") / T(t"{Param('n'):_x}.bin")
    elif shape == "absolute":
        e = Absolute("root") / "x" / SubPath("sub")
    else:
        e = P("base") / SubPath("sub") / SubPath("seg")
    agrees(e, df)


# ---------------------------------------------------------------------------
# Format specs
# ---------------------------------------------------------------------------

FILLS = ["", " ", "0", "*", "/", ".", "\x00", "é", "{", "<", "=", "9", "_", ",", "\n"]
WIDTHS = ["", "0", "1", "2", "5", "8", "9", "10", "13", "21", "40", "05", "007"]


@st.composite
def int_specs(draw):
    align = draw(st.sampled_from(["", "<", ">", "=", "^"]))
    fill = draw(st.sampled_from(FILLS)) if align else ""
    sign = draw(st.sampled_from(["", "+", "-", " "]))
    alt = draw(st.sampled_from(["", "#"]))
    zero = draw(st.sampled_from(["", "0"]))
    width = draw(st.sampled_from(WIDTHS))
    typ = draw(st.sampled_from(["", "d", "b", "o", "x", "X"]))
    grouping = draw(st.sampled_from(["", ",", "_"] if typ in ("", "d") else ["", "_"]))
    return f"{fill}{align}{sign}{alt}{zero}{width}{grouping}{typ}"


@st.composite
def str_specs(draw):
    align = draw(st.sampled_from(["", "<", ">", "^"]))
    fill = draw(st.sampled_from(FILLS)) if align else ""
    zero = draw(st.sampled_from(["", "0"]))
    width = draw(st.sampled_from(WIDTHS))
    precision = draw(st.sampled_from(["", ".0", ".1", ".2", ".5", ".12"]))
    typ = draw(st.sampled_from(["", "s"]))
    return f"{fill}{align}{zero}{width}{precision}{typ}"


any_spec = st.text(alphabet="<>=^+- z#0123456789,_.bcdeEfFgGnosxX%*/\x00é", max_size=9)

INT_DTYPES = {
    "Int8": (pl.Int8, -(2**7), 2**7 - 1),
    "Int16": (pl.Int16, -(2**15), 2**15 - 1),
    "Int32": (pl.Int32, -(2**31), 2**31 - 1),
    "Int64": (pl.Int64, -(2**63), 2**63 - 1),
    "UInt8": (pl.UInt8, 0, 2**8 - 1),
    "UInt16": (pl.UInt16, 0, 2**16 - 1),
    "UInt32": (pl.UInt32, 0, 2**32 - 1),
    "UInt64": (pl.UInt64, 0, 2**64 - 1),
    "Int128": (pl.Int128, -(2**127), 2**127 - 1),
    "UInt128": (pl.UInt128, 0, 2**128 - 1),
}


@st.composite
def int_columns(draw):
    name = draw(st.sampled_from(sorted(INT_DTYPES)))
    dtype, lo, hi = INT_DTYPES[name]
    edges = st.sampled_from([lo, hi, 0, 1, -1, lo + 1, hi - 1, 7, -7, 1000, -1000])
    values = draw(
        st.lists(
            st.one_of(st.integers(lo, hi), edges.filter(lambda v: lo <= v <= hi)),
            min_size=1,
            max_size=8,
        )
    )
    return pl.DataFrame({"v": values}, schema={"v": dtype})


def int_exprs(spec, conv=None, declared=None):
    v = Param("v", type=declared)
    return [
        T(template("n", field(v, spec, conv), ".bin")),
        P("/out") / T(template(field(v, spec, conv))),
    ]


@examples(400)
@given(int_columns(), int_specs(), st.sampled_from([None, int]))
def test_integer_specs_are_exact(df, spec, declared):
    wide = df.schema["v"] in (pl.Int128, pl.UInt128)
    for e in int_exprs(spec, declared=declared):
        try:
            agrees(e, df)
        except NotImplementedError:
            # Every spec drawn here is lowered, except bases other than ten
            # on 128-bit columns.
            assert wide and spec[-1:] in ("b", "o", "x", "X")


@examples(150)
@given(int_columns(), str_specs(), st.sampled_from(["s", "r", "a"]))
def test_integer_conversions_are_exact(df, spec, conv):
    for e in int_exprs(spec, conv):
        agrees(e, df)


@examples(200)
@given(int_columns(), any_spec, st.sampled_from([None, "s", "r"]))
def test_any_integer_spec_is_exact_or_refused(df, spec, conv):
    for e in int_exprs(spec, conv):
        try:
            agrees(e, df)
        except NotImplementedError:
            pass


strings = st.lists(
    st.one_of(
        st.text(max_size=8),
        st.sampled_from(["", ".", "..", "a/b", "\x00", "é́", "ab", "  "]),
    ),
    min_size=1,
    max_size=8,
)


@examples(400)
@given(strings, str_specs(), st.sampled_from([None, "s"]))
def test_string_specs_are_exact(values, spec, conv):
    df = pl.DataFrame({"v": values}, schema={"v": pl.String})
    for e in int_exprs(spec, conv):
        agrees(e, df)


@examples(200)
@given(strings, any_spec, st.sampled_from([None, "s", "r", "a"]))
def test_any_string_spec_is_exact_or_refused(values, spec, conv):
    df = pl.DataFrame({"v": values}, schema={"v": pl.String})
    for e in int_exprs(spec, conv):
        try:
            agrees(e, df)
        except NotImplementedError:
            pass


@examples(200)
@given(
    st.lists(st.booleans(), min_size=1, max_size=6),
    st.one_of(int_specs(), str_specs(), any_spec),
    st.sampled_from([None, "s", "r", "a"]),
    st.sampled_from([None, bool, int]),
)
def test_boolean_columns_are_exact_or_refused(values, spec, conv, declared):
    df = pl.DataFrame({"v": values}, schema={"v": pl.Boolean})
    for e in int_exprs(spec, conv, declared) + [P("/b") / Param("v", type=declared)]:
        try:
            agrees(e, df)
        except NotImplementedError:
            assert spec  # an empty spec on a bool is always lowered


def test_choices_and_declared_types_follow_param_check():
    v = Param("v", choices={300, 1, -1})
    df = pl.DataFrame({"v": [1, 44]}, schema={"v": pl.Int8})
    assert agrees(T(t"x{v:03d}"), df.head(1))
    assert not agrees(T(t"x{v:03d}"), df)  # 44 is not a choice; 300 cannot occur
    b = Param("b", choices={True})
    assert not agrees(P("x") / b, pl.DataFrame({"b": [True, False]}))
    flag = Param("b", type=int)  # bool is an int subclass, as for isinstance
    assert agrees(T(t"x{flag:+}"), pl.DataFrame({"b": [True, False]}))


def test_the_first_failing_row_is_reported():
    df = pl.DataFrame({"a": ["ok"] * 100_000 + ["x/y"] * 3 + ["ok"]})
    with pytest.raises(InvalidBindingError, match=r"^Row 100000: "):
        resolve_frame(P("/") / Param("a"), df)


def test_constant_expressions_have_one_row_per_input_row():
    df = pl.DataFrame({"x": [1, 2, 3]})
    assert resolve_frame(P("/a") / "b", df).to_list() == ["/a/b"] * 3
    out = df.with_columns(to_polars(P("/a") / "b"))
    assert out["path"].to_list() == ["/a/b"] * 3


def test_formats_match_python_examples():
    df = pl.DataFrame({"v": [255, -255, 0, 1234567]})
    for spec in ["#010_x", "+08,", "^+#12X", "=+9", "0=12_o", "_b", " 09", "x<9"]:
        assert agrees(T(template("f", field(Param("v"), spec))), df), spec
    s = pl.DataFrame({"v": ["ab", "abcdef", "é"]})
    for spec in ["^7", "*^6", ".2", "x>8.3", "05", "\n<4s"]:
        assert agrees(T(template("f", field(Param("v"), spec))), s), spec
    b = pl.DataFrame({"v": [True, False]})
    assert resolve_frame(P("x") / Param("v"), b).to_list() == ["x/True", "x/False"]
    assert resolve_frame(T(t"x{Param('v'):>3}"), b).to_list() == ["x  1", "x  0"]
    assert resolve_frame(T(t"x{Param('v')!s:>6}"), b).to_list() == [
        "x  True",
        "x False",
    ]


WIDTH = Param("w")


@pytest.mark.parametrize(
    ("make", "schema"),
    [
        (lambda: T(t"x{Param('v'):.2f}"), {"v": pl.Int64}),
        (lambda: T(t"x{Param('v'):c}"), {"v": pl.Int64}),
        (lambda: T(t"x{Param('v'):n}"), {"v": pl.Int64}),
        (lambda: T(t"x{Param('v'):x}"), {"v": pl.Int128}),
        (lambda: T(t"x{Param('v')}"), {"v": pl.Float64}),
        (lambda: P("x") / Param("v"), {"v": pl.Float64}),
        (lambda: T(t"x{Param('v')!r}"), {"v": pl.String}),
        (lambda: T(t"x{Param('v')!a}"), {"v": pl.String}),
        (lambda: T(t"x{Param('v'):+}"), {"v": pl.String}),
        (lambda: T(t"x{Param('v'):=5}"), {"v": pl.String}),
        (lambda: T(t"x{Param('v'):{WIDTH}}"), {"v": pl.Int64, "w": pl.Int64}),
        (lambda: T(t"x{Param('v', type=float)}"), {"v": pl.Int64}),
        (lambda: T(t"x{Param('v', choices={1, 'a'})}"), {"v": pl.Int64}),
        (lambda: P(Param("v")), {"v": pl.Int64}),
        (lambda: (P("/a") / SubPath("v")).relative_to(P("/a") / "b"), {"v": pl.String}),
    ],
)
def test_inexact_lowerings_are_refused(make, schema):
    with pytest.raises(NotImplementedError, match=r"compile\(\)\.many"):
        to_polars(make(), pl.Schema(schema))


# ---------------------------------------------------------------------------
# Deferred operations
# ---------------------------------------------------------------------------

root, sub, seg, nm = Param("root"), SubPath("sub"), Segment("seg"), Param("nm")
DEFERRED = {
    "parent of head": P(root).parent,
    "parent of splice": (root / sub).parent,
    "grandparent": (P("/base") / sub).parent.parent,
    "parent then segment": (root / sub).parent / "x" / seg,
    "with_suffix ''": (root / sub).with_suffix(""),
    "with_suffix .x": P(root).with_suffix(".x"),
    "with_suffix .": (P("/b") / sub).with_suffix("."),
    "with_suffix .tar.gz": (P("r") / seg).with_suffix(".tar.gz"),
    "with_suffix ..x": (root / sub).with_suffix("..x"),
    "with_name literal": (root / sub).with_name("n.txt"),
    "with_name dots": P(root).with_name(".."),
    "with_name field": (root / sub).with_name(nm),
    "with_name text": (P("/b") / sub).with_name(T(t"{nm}.{seg}").name),
    "with_stem literal": (root / sub).with_stem("s"),
    "with_stem field": (P("/b") / sub).with_stem(nm),
    "with_stem padded": (root / sub).with_stem(T(t"{nm:_^6}").name),
    "with_stem slash": (root / sub).with_stem("a/b"),
    "with_stem then join": (root / sub).with_stem(nm) / "z",
    "name": P("/o") / T(t"{(root / sub).name}"),
    "stem and suffix": P("/o") / T(t"{(root / sub).stem}-{(root / sub).suffix}"),
    "formatted name": P("/o") / T(t"{(P('/b') / sub).name:*>9}"),
    "join path": P("a") / AnyPath("nm"),
    "join after splice": (root / sub) / AnyPath("nm") / seg,
    "suffix then parent": (root / sub).with_suffix(".q").parent,
}


@examples(300)
@given(
    st.sampled_from(sorted(DEFERRED)),
    st.lists(
        st.tuples(path_text, path_text, seg_text, seg_text), min_size=1, max_size=6
    ),
)
def test_deferred_operations_never_disagree(key, rows):
    df = pl.DataFrame(rows, schema=["root", "sub", "seg", "nm"], orient="row")
    agrees(DEFERRED[key], df)


@pytest.mark.parametrize("key", sorted(DEFERRED))
def test_deferred_operations_on_nice_rows(key):
    df = pl.DataFrame(
        {
            "root": ["/data", "rel/x.tar.gz", "//h", "a/"],
            "sub": ["s/t.txt", ".cfg", "u.v.w", "./q"],
            "seg": ["k", "k.l", "m", "..n"],
            "nm": ["new", "n.e", "z", ".dot"],
        }
    )
    # pathlib refuses a stem containing a separator on every row.
    assert agrees(DEFERRED[key], df) is (key != "with_stem slash"), key
