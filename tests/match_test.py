import itertools
from decimal import Decimal
from string.templatelib import Interpolation, Template

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from wend import (
    AmbiguousMatchError,
    InvalidBindingError,
    NotInvertibleError,
    P,
    Param,
    SubPath,
    T,
)
from wend._match import _expr_plan, seg_plan
from wend._spec import implied_types, parse_spec


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


LITERAL_TEXTS = st.text(alphabet="[]{}(),:'\"1a-+ .\\", max_size=14)


@pytest.mark.filterwarnings("ignore::SyntaxWarning")  # literal_eval("'\\+'") warns
@settings(max_examples=500, deadline=None)
@given(LITERAL_TEXTS, st.sampled_from(["r", "a"]), st.sampled_from(["", ">9", "*^9"]))
def test_reading_a_literal_never_raises(text, conversion, spec):
    # Issue #55: a text that is no literal gives no candidate, whatever
    # literal_eval raises for it ("{[1]: 2}" raises TypeError).
    u = Param("u")
    e = T(Template("k", Interpolation(u, "u", conversion, spec)))
    for sol in e.match_all("k" + text):
        assert e.render(sol) == "k" + text


def test_unreadable_literals_give_no_candidate():
    u = Param("u")
    e = T(t"k{u!r}")
    for text in [
        "{[1]: 2}",  # TypeError: an unhashable key
        "{1, [2]}",
        "{(1, [2]): 3}",
        "[" * 300 + "]" * 300,  # SyntaxError: too deeply nested
        "-" * 100_000 + "1",  # MemoryError: the parser's stack
        "1" * 5000,  # beyond the digit limit
        "1+",
    ]:
        assert e.match_all("k" + text) == []
    assert T(t"k{u!a}").match("k{[1]: 2}") is None
    assert e.match("k{1: [2]}") == {"u": {1: [2]}}
    c = Param("c", choices={"a"})  # an unhashable literal is no choice
    assert T(t"k{c!r}").match("k['a']") is None
    assert T(t"k{c!r}").match("k'a'") == {"c": "a"}


def test_declared_types_that_reject_text_give_no_candidate():
    x = Param("x", type=Decimal)
    e = T(t"k{x}")
    assert e.match("kabc") is None  # Decimal raises decimal.InvalidOperation
    assert e.match("k1.50") == {"x": Decimal("1.50")}


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


def readings(expr, path, name):
    """The (type, value) pairs the full search finds for one parameter."""
    return {(type(m[name]), m[name]) for m in expr.match_all(path, fast=False)}


def test_untyped_zero_padded_spec_reads_str_and_int():
    # Issue #45: "05" fills a str with 0 on the right and an int after its
    # sign, so one path can be several bindings, and match must say so.
    u = Param("u")
    e = P("d") / T(t"{u:05}")
    assert _expr_plan(e) is None
    assert e.render(u="ab") == e.render(u="ab000") == "d/ab000"
    assert e.render(u=5) == e.render(u="00005") == "d/00005"
    assert readings(e, "d/ab000", "u") == {
        (str, "ab"),
        (str, "ab0"),
        (str, "ab00"),
        (str, "ab000"),
    }
    assert readings(e, "d/00005", "u") == {(str, "00005"), (int, 5)}
    assert readings(e, "d/-0005", "u") == {(str, "-0005"), (int, -5)}
    for path in ("d/ab000", "d/00005", "d/-0005"):
        with pytest.raises(AmbiguousMatchError):
            e.match(path)
    assert e.match("d/abcdef") == {"u": "abcdef"}  # wider than 5: not padded
    # A sign is numeric only: no str formats under "+05".
    assert T(t"x{u:+05}").match("x+0005") == {"u": 5}


def test_untyped_fields_under_options_only_numbers_take():
    # Issue #55: no str formats under a sign, "#", grouping or "=", so an
    # untyped field with one of them reads ints, as a type=int field does.
    u = Param("u")
    for spec, value in [
        ("+5", 5),
        (",", 1234567),
        ("=5", -5),
        (" ", 5),
        ("_", -10000),
        ("#", 7),
        ("x=+6", 5),
        ("+05", -3),
        ("n", 42),  # a presentation type only numbers take
        ("-#,", 1234),
    ]:
        e = P("d") / T(Template("k", Interpolation(u, "u", None, spec)))
        path = e.render(u=value)
        assert readings(e, path, "u") == {(int, value)}, spec
        with pytest.raises(InvalidBindingError):
            e.render(u="x")  # no str formats here
    assert T(t"k{u:+5}").match("k   +5") == {"u": 5}
    assert T(t"k{u:,}").match("k1,000") == {"u": 1000}
    assert T(t"k{u:,}").match("k1000") is None  # 1000 formats as 1,000
    # z and a precision are refused by ints too: only floats remain.
    for spec, value in [("z", 0.5), ("+.3", 1.25), ("z,", -1234.5)]:
        e = P("d") / T(Template("k", Interpolation(u, "u", None, spec)))
        assert readings(e, e.render(u=value), "u") == {(float, value)}, spec
    assert readings(T(t"k{u:z}"), "k0.0", "u") == {(float, 0.0)}  # -0.0 too


def test_implied_types_follow_what_formats():
    # An untyped field without a presentation type reads the first of str,
    # int and float that formats under its spec (§7), checked against format.
    options = [
        ("", "<", "=", "x^"),  # fill and alignment
        ("", "+", " "),  # sign
        ("", "z"),
        ("", "#"),
        ("", "4", "04"),  # the 0 flag and width
        ("", ",", "_"),  # grouping
        ("", ".2"),  # precision
    ]
    for parts in itertools.product(*options):
        spec = "".join(parts)
        formats = []
        for t, sample in ((str, "x"), (int, 0), (float, 0.0)):
            try:
                format(sample, spec)
            except ValueError:
                continue
            formats.append(t)
        got = implied_types(parse_spec(spec))
        assert formats, spec  # a float formats under every such spec
        assert got[0] is formats[0], (spec, got, formats)
        assert set(got) <= set(formats), (spec, got, formats)


def test_declared_type_picks_the_zero_padded_reading():
    ui = Param("u", type=int)
    e = P("d") / T(t"{ui:05}")
    assert _expr_plan(e) is not None
    assert e.match("d/00005") == {"u": 5}
    assert e.match_all("d/00005", fast=False) == [{"u": 5}]
    assert e.match("d/ab000") is None
    us = Param("u", type=str)
    e = P("d") / T(t"{us:05}")
    assert e.match("d/00005") == {"u": "00005"}
    assert readings(e, "d/50000", "u") == {
        (str, "5"),
        (str, "50"),
        (str, "500"),
        (str, "5000"),
        (str, "50000"),
    }


def test_fill_characters_may_belong_to_the_value():
    u, n = Param("u"), Param("n", type=int)
    assert readings(T(t"{u:x<5}"), "abxxx", "u") == {
        (str, "ab"),
        (str, "abx"),
        (str, "abxx"),
        (str, "abxxx"),
    }
    # "^" puts half the fill (rounded down) before the value.
    assert readings(T(t"{u:*^7}"), "**ab***", "u") == {
        (str, "ab"),
        (str, "ab*"),
        (str, "*ab*"),
        (str, "*ab**"),
        (str, "**ab**"),
        (str, "**ab***"),
    }
    assert readings(T(t"{u:x^7}"), "xxxabxx", "u") == {
        (str, "xab"),
        (str, "xxab"),
        (str, "xxabx"),
        (str, "xxxabx"),
        (str, "xxxabxx"),
    }
    assert readings(T(t"{u:5}"), "a    ", "u") == {
        (str, "a" + " " * k) for k in range(5)
    }
    assert readings(T(t"{n:1>5d}"), "11115", "n") == {
        (int, 5),
        (int, 15),
        (int, 115),
        (int, 1115),
        (int, 11115),
    }
    assert readings(T(t"{n:->4d}"), "---5", "n") == {(int, 5), (int, -5)}
    assert T(t"{n:0>5d}").match("000-5") == {"n": -5}
    assert readings(T(t"{u!s:*<4}"), "ab**", "u") == {
        (str, "ab"),
        (str, "ab*"),
        (str, "ab**"),
    }


def test_character_fields_invert():
    n = Param("n", type=int)
    assert T(t"x{n:c}").match("xq") == {"n": ord("q")}  # "q" is no int character
    assert T(t"x{n:c}_{n:d}").match("xq_113") == {"n": 113}
    assert T(t"x{n:3c}").match("x  A") == {"n": 65}
    assert T(t"x{n:03c}").match("x000") == {"n": ord("0")}


def test_bool_fields_read_true_and_false():
    # Issue #55: a bool formats as True or False under the empty spec, and as
    # the number 1 or 0 under any other; its int readings failed its type.
    q = Param("q", type=bool)
    cases = [
        ("", "True", True),
        ("", "False", False),
        ("d", "1", True),
        ("d", "0", False),
        ("05", "00001", True),
        (">3", "  0", False),
        ("+", "+1", True),
        ("=+4", "+  1", True),
        ("#x", "0x1", True),
        ("c", "\x01", True),
        ("f", "1.000000", True),
        (".0%", "0%", False),
        ("g", "1", True),
    ]
    for spec, text, value in cases:
        e = P("d") / T(Template("k", Interpolation(q, "q", None, spec)))
        assert e.render(q=value) == "d/k" + text
        assert readings(e, "d/k" + text, "q") == {(bool, value)}, spec
        assert type(e.match("d/k" + text)["q"]) is bool
    assert T(t"k{q:d}").match("k2") is None
    assert T(t"k{q:d}").match("kTrue") is None
    assert T(t"k{q}").match("k1") is None
    assert readings(P("d") / q, "d/False", "q") == {(bool, False)}  # a segment
    assert readings(T(t"k{q!s:>6}"), "k False", "q") == {(bool, False)}
    assert readings(T(t"k{q!r}"), "kTrue", "q") == {(bool, True)}


def test_typed_fields_under_float_types_and_the_str_conversion():
    n, x = Param("n", type=int), Param("x", type=float)
    # An int formats under a float presentation type as its float.
    assert readings(T(t"k{n:f}"), "k5.000000", "n") == {(int, 5)}
    assert readings(T(t"k{n:.0%}"), "k-500%", "n") == {(int, -5)}
    assert readings(T(t"k{n:g}"), "k1e+20", "n") == {(int, 10**20)}
    assert T(t"k{n:f}").match("k5.500000") is None
    # Under !s, a declared type reads the values whose str is the text.
    assert readings(T(t"k{n!s}"), "k-5", "n") == {(int, -5)}
    assert readings(T(t"k{n!s:*>4}"), "k**12", "n") == {(int, 12)}
    assert T(t"k{n!s}").match("k05") is None  # str(5) is "5"
    assert readings(T(t"k{x!s}"), "k0.5", "x") == {(float, 0.5)}
    assert T(t"k{x!s}").match("k1") is None  # str(1.0) is "1.0"


def test_a_spec_read_from_the_path_cannot_ask_for_more_than_the_text():
    """A width or precision bound from the path itself is bounded by the text:
    formatting a candidate under ``{u:999999999}`` would allocate a gigabyte."""
    w, p = Param("w", type=int), Param("p", type=int)
    u, x = Param("u"), Param("x")
    wide = T(t"{w:d}_{u:{w}}")
    assert wide.match("999999999_x") is None
    assert wide.match("3_xyz") == {"w": 3, "u": "xyz"}
    precise = T(t"{p:d}_{x:.{p}f}")
    assert precise.match("999999999_1.5") is None
    assert precise.match("2_1.50") == {"p": 2, "x": 1.5}
    # inf and nan ignore precision, so they are still read.
    assert precise.match("12_inf") == {"p": 12, "x": float("inf")}
    alt = T(t"{p:d}_{x:#.{p}g}")
    assert alt.match("999999999_1.5") is None
    assert alt.match("3_1.50") == {"p": 3, "x": 1.5}
    # Without the alternate form, g drops trailing zeros: precision is no bound.
    assert T(t"{p:d}_{x:.{p}g}").match("40_1.5") == {"p": 40, "x": 1.5}


def test_a_tuple_or_union_type_reads_each_member():
    """``type=`` takes what ``isinstance`` takes, so a field reads each member
    type in order, and verification keeps the readings that render."""
    either = Param("x", type=(int, str))
    assert T(t"k{either}").match("kab") == {"x": "ab"}
    with pytest.raises(AmbiguousMatchError):  # 5 and "5" both render k5
        T(t"k{either}").match("k5")
    maybe = Param("n", type=int | None)
    assert T(t"k{maybe}").match("kNone") == {"n": None}
    assert T(t"k{maybe:03d}").match("k007") == {"n": 7}
    assert T(t"k{maybe:03d}").match("kNone") is None  # None takes no spec
    seg = Param("n", type=int | None)
    assert (P("/r") / seg).match("/r/None") == {"n": None}
    assert (P("/r") / seg).match("/r/12") == {"n": 12}
    # The width bound still applies when every member formats by the
    # standard mini-language.
    w = Param("w", type=int)
    assert T(t"{w:d}_{maybe:{w}}").match("999999999_7") is None


def test_a_signalling_nan_is_read_without_comparing_it():
    x = Param("x", type=Decimal)
    m = T(t"k{x:>5}").match("k sNaN")
    assert m is not None and repr(m["x"]) == "Decimal('sNaN')"


_ESCAPY = st.text(alphabet="abifo'\"\\xuUN0789tnr{}+ é☃\n", max_size=12)


@settings(max_examples=400, deadline=None)
@given(text=_ESCAPY, prefix=st.sampled_from(["", "b", "r", "rb", "f", "u"]))
def test_reading_a_repr_never_warns(text, prefix):
    # Under !r a field reads its text with literal_eval, which warns about
    # escapes Python deprecates ("\+", "\d", an octal above 0o377) and about
    # a number run into a word ("1if"). repr never writes either, so such a
    # text is refused first (#65).
    import warnings

    z = Param("z")
    e = T(t"{z!r}")
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        for q in ("'", '"'):
            e.match_all(f"{prefix}{q}{text}{q}")
        e.match_all(prefix + text)  # unquoted: "1if" warns too
    assert not [w for w in caught if issubclass(w.category, SyntaxWarning)]


@pytest.mark.parametrize(
    "text",
    [
        "'\\+'",
        "'\\d'",
        "b'\\u1234'",
        "'\\400'",
        "f'\\{'",
        "f'{1if 2}'",  # an f- or t-string's braces hold code
        "t'{1if 2}'",
        "9if",
        "1if 2",
        "0in",
        "(1if 2)",
    ],
)
def test_texts_literal_eval_warns_about_are_refused_quietly(text):
    import warnings

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        assert T(t"{Param('z')!r}").match_all(text) == []
    assert not [w for w in caught if issubclass(w.category, SyntaxWarning)]


@settings(max_examples=300, deadline=None)
@given(
    v=st.one_of(
        st.text(max_size=8),
        st.binary(max_size=8),
        st.tuples(st.text(max_size=4), st.binary(max_size=4)),
    )
)
def test_every_repr_and_ascii_reads_back(v):
    z = Param("z")
    for e in (T(t"{z!r}"), T(t"{z!a}")):
        try:
            text = e.render(z=v)
        except ValueError:
            continue  # holds "/" or NUL: not a segment
        assert v in [r["z"] for r in e.match_all(text)], (e.pattern, text)


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
