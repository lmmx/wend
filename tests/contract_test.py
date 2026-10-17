"""Contract tests: wend against a reference evaluator for docs/SEMANTICS.md.

The reference evaluator below is written from the contract alone. It evaluates
*terms* (nested tuples) strictly with pathlib, and imports only wend's
parameter declarations, never its expressions, evaluator, matcher or compiler.
Random terms are trees (not just left-deep chains), so the position rule for
parameters and nested joins are exercised.
"""

from __future__ import annotations

import os
from pathlib import PurePosixPath
from string.templatelib import Interpolation, Template

from wend import Kind, Param


class Invalid(Exception):
    """The reference rejects a binding (contract §3, §4)."""


class OpError(Exception):
    """pathlib rejects an operation (contract §5)."""


EMPTY = PurePosixPath(".")


def _checked(p: Param, v):
    if p.type is not None and not isinstance(v, p.type):
        raise Invalid(f"{p.name}: type")
    if p.choices is not None and v not in p.choices:
        raise Invalid(f"{p.name}: choices")
    return v


def _path_string(p: Param, v) -> str:
    _checked(p, v)
    if isinstance(v, str):
        s = v
    elif isinstance(v, os.PathLike) and isinstance(os.fspath(v), str):
        s = os.fspath(v)
    else:
        raise Invalid(f"{p.name}: not a path")
    if "\x00" in s:
        raise Invalid(f"{p.name}: NUL")
    return s


def _segment_string(p: Param, v) -> str:
    """§3: a segment takes a path string, or any other value formatted as f"{v}"."""
    _checked(p, v)
    if isinstance(v, (str, os.PathLike)):
        return _path_string(p, v)
    if isinstance(v, (bytes, bytearray)):
        raise Invalid(f"{p.name}: bytes")
    try:
        s = format(v, "")
    except (TypeError, ValueError) as e:
        raise Invalid(f"{p.name}: format: {e}") from None
    if "\x00" in s:
        raise Invalid(f"{p.name}: NUL")
    return s


def operand(p: Param, env: dict, at_head: bool) -> PurePosixPath:
    kind = p.kind
    if kind is Kind.AUTO:
        kind = Kind.PATH if at_head else Kind.SEGMENT
    if kind is Kind.SEGMENT:
        s = _segment_string(p, env[p.name])
        if "/" in s or s in ("", ".", ".."):
            raise Invalid(f"{p.name}: not a segment")
        return PurePosixPath(s)
    s = _path_string(p, env[p.name])
    q = PurePosixPath(s)
    if kind is Kind.PATH:
        return q
    if kind is Kind.ABSOLUTE:
        if not q.is_absolute():
            raise Invalid(f"{p.name}: not absolute")
        return q
    if q.is_absolute() or ".." in q.parts:
        raise Invalid(f"{p.name}: not a relative sub-path")
    return q


def _convert(v, conversion):
    if conversion is None:
        return v
    return {"r": repr, "s": str, "a": ascii}[conversion](v)


def _field(x: Interpolation, env: dict) -> str:
    v = x.value
    if isinstance(v, Param):
        v = _checked(v, env[v.name])
    try:
        s = format(_convert(v, x.conversion), x.format_spec)
    except (TypeError, ValueError) as e:
        raise Invalid(f"format: {e}") from None
    if "/" in s or "\x00" in s:
        raise Invalid("field contains a separator or NUL")
    return s


def _is_path_like(v) -> bool:
    return isinstance(v, (Param, str, os.PathLike, Template))


def template(t: Template, env: dict, at_head: bool) -> PurePosixPath:
    segments: list[list] = [[]]
    anchor = ""
    for i, item in enumerate(t):
        if isinstance(item, str):
            if i == 0 and item.startswith("/"):
                anchor = (
                    "//"
                    if item.startswith("//") and not item.startswith("///")
                    else "/"
                )
            chunks = item.split("/")
            segments[-1].append(chunks[0])
            segments.extend([c] for c in chunks[1:])
        else:
            segments[-1].append(item)
    result = PurePosixPath(anchor) if anchor else EMPTY
    head = at_head and not anchor
    for seg in segments:
        items = [x for x in seg if x != ""]
        if not items:
            continue
        if all(isinstance(x, str) for x in items):
            text = "".join(items)
            if text == ".":
                continue
            result, head = result / text, False
            continue
        if (
            len(items) == 1
            and items[0].conversion is None
            and not items[0].format_spec
            and _is_path_like(items[0].value)
        ):
            v = items[0].value
            if isinstance(v, Param):
                sub = operand(v, env, head)
            elif isinstance(v, Template):
                sub = template(v, env, head)
            else:
                sub = PurePosixPath(os.fspath(v))
            result, head = result / sub, False
            continue
        text = "".join(x if isinstance(x, str) else _field(x, env) for x in items)
        if text in ("", ".", ".."):
            raise Invalid(f"segment renders to {text!r}")
        result, head = result / text, False
    return result


def _has_params(term) -> bool:
    kind = term[0]
    if kind == "param":
        return True
    if kind == "tpl":
        return any(isinstance(x.value, Param) for x in term[1].interpolations)
    if kind == "lit":
        return False
    return any(isinstance(t, tuple) and _has_params(t) for t in term[1:])


def _operand_len(p: Param, at_head: bool) -> int | None:
    kind = p.kind
    if kind is Kind.AUTO:
        kind = Kind.PATH if at_head else Kind.SEGMENT
    return 1 if kind is Kind.SEGMENT else None


def _template_len(t: Template, at_head: bool) -> int | None:
    if t.strings[0].startswith("/"):
        return None
    segments: list[list] = [[]]
    for item in t:
        if isinstance(item, str):
            chunks = item.split("/")
            segments[-1].append(chunks[0])
            segments.extend([c] for c in chunks[1:])
        else:
            segments[-1].append(item)
    n, head = 0, at_head
    for seg in segments:
        items = [x for x in seg if x != ""]
        if not items or (
            all(isinstance(x, str) for x in items) and "".join(items) == "."
        ):
            continue
        if (
            len(items) == 1
            and not isinstance(items[0], str)
            and items[0].conversion is None
            and not items[0].format_spec
            and _is_path_like(items[0].value)
        ):
            v = items[0].value
            if isinstance(v, Param):
                k = _operand_len(v, head)
            elif isinstance(v, Template):
                k = _template_len(v, head)
            else:
                q = PurePosixPath(os.fspath(v))
                k = None if q.is_absolute() else len(q.parts)
            if k is None:
                return None
            n += k
        else:
            n += 1
        head = False
    return n


def static_len(term, at_head: bool) -> int | None:
    """§2: the number of segments of a relative term, when its structure fixes
    it for every binding (None when it depends on a binding or is absolute)."""
    if not _has_params(term):
        try:
            q = evaluate(term, {}, at_head)
        except Invalid, OpError:
            return None
        return None if q.is_absolute() else len(q.parts)
    kind = term[0]
    if kind == "param":
        return _operand_len(term[1], at_head)
    if kind == "tpl":
        return _template_len(term[1], at_head)
    if kind == "join":
        a = static_len(term[1], at_head)
        if a is None:
            return None
        b = static_len(term[2], at_head and a == 0)
        return None if b is None else a + b
    if kind == "parent":
        a = static_len(term[1], at_head)
        return None if a is None else max(a - 1, 0)
    if kind in ("with_suffix", "with_name", "with_stem"):
        return static_len(term[1], at_head)
    if kind == "relative_to":
        a, b = term[1], term[2]
        if a == b:
            return 0
        if a[0] == "join" and a[1] == b:
            return static_len(a[2], at_head and is_empty(b, at_head))
    return None


def is_empty(term, at_head: bool) -> bool:
    """§2: statically the empty relative path."""
    return static_len(term, at_head) == 0


def evaluate(term, env: dict, at_head: bool = True):
    kind = term[0]
    try:
        if kind == "lit":
            return PurePosixPath(term[1])
        if kind == "param":
            return operand(term[1], env, at_head)
        if kind == "tpl":
            return template(term[1], env, at_head)
        if kind == "join":
            a = evaluate(term[1], env, at_head)
            b = evaluate(term[2], env, at_head and is_empty(term[1], at_head))
            return a / b
        if kind == "parent":
            return evaluate(term[1], env, at_head).parent
        if kind in ("with_suffix", "with_name", "with_stem"):
            return getattr(evaluate(term[1], env, at_head), kind)(term[2])
        if kind == "relative_to":
            return evaluate(term[1], env, at_head).relative_to(
                evaluate(term[2], env, True)
            )
        if kind in ("name", "stem", "suffix"):
            return getattr(evaluate(term[1], env, at_head), kind)
    except ValueError as e:
        raise OpError(str(e)) from None
    raise AssertionError(kind)


def elimination_free(term) -> bool:
    """Only joins of relative literals, non-head-sensitive operands and templates."""
    kind = term[0]
    if kind == "lit":
        return not PurePosixPath(term[1]).is_absolute()
    if kind == "param":
        return term[1].kind in (Kind.AUTO, Kind.SEGMENT, Kind.SUBPATH)
    if kind == "tpl":
        return not term[1].strings[0].startswith("/")
    if kind == "join":
        return elimination_free(term[1]) and elimination_free(term[2])
    return False


# ---------------------------------------------------------------------------
# Building the same term with wend
# ---------------------------------------------------------------------------

import string  # noqa: E402

import pytest  # noqa: E402
from hypothesis import HealthCheck, event, given, settings  # noqa: E402
from hypothesis import strategies as st  # noqa: E402

from wend import (  # noqa: E402
    InvalidBindingError,
    MissingBindingError,
    P,
    PathOperationError,
    SubPath,
    T,
    WendError,
)


ROOT = Param("root")
SEG = Param("seg")
SUB = SubPath("sub")
N = Param("n", type=int)
W = Param("w", type=str)

TEMPLATES = [
    t"chunk_{N:04d}.parquet",
    t"{W}.csv",
    t"{W}_{N}",
    t"{N:d}",
    t"{W}.{N:02d}",
    t"{W!r}",
    t"x{N:x}",
    t"{SEG}/{W}.txt",
    t"{ROOT}/data",
    t"./{SEG}",
    t"/anchored/{W}",
    t"{W:>4}",
    t"",
]
LITERALS = [
    "a",
    "b.txt",
    "c/d",
    "..",
    ".",
    "",
    "/abs",
    ".hid",
    "x.tar.gz",
    "a.",
    "e/./f",
    "//net",
]
SUFFIXES = ["", ".json", ".tar.gz", ".", "json", "a/b"]
NAMES = ["new.txt", "", ".", "a/b", "..", ".rc", "z"]
STEMS = ["st", "", ".s"]


def build(term):
    kind = term[0]
    if kind == "lit":
        return P(term[1])
    if kind == "param":
        return P(term[1])
    if kind == "tpl":
        return T(term[1])
    if kind == "join":
        return build(term[1]) / build(term[2])
    if kind == "parent":
        return build(term[1]).parent
    if kind in ("with_suffix", "with_name", "with_stem"):
        return getattr(build(term[1]), kind)(term[2])
    if kind == "relative_to":
        return build(term[1]).relative_to(build(term[2]))
    raise AssertionError(kind)


leaves = st.one_of(
    st.tuples(st.just("lit"), st.sampled_from(LITERALS)),
    st.tuples(st.just("param"), st.sampled_from([ROOT, SEG, SUB])),
    st.tuples(st.just("tpl"), st.sampled_from(TEMPLATES)),
)
terms = st.recursive(
    leaves,
    lambda kids: st.one_of(
        st.tuples(st.just("join"), kids, kids),
        st.tuples(st.just("parent"), kids),
        st.tuples(st.just("with_suffix"), kids, st.sampled_from(SUFFIXES)),
        st.tuples(st.just("with_name"), kids, st.sampled_from(NAMES)),
        st.tuples(st.just("with_stem"), kids, st.sampled_from(STEMS)),
        st.tuples(st.just("relative_to"), kids, kids),
    ),
    max_leaves=7,
)

name = st.text(alphabet="abz019_-.", min_size=1, max_size=5).filter(
    lambda s: s not in (".", "..")
)
hostile = st.one_of(
    st.text(alphabet="ab./\\\x00 ", max_size=5),
    st.sampled_from(
        [
            "..",
            "../x",
            "/etc/passwd",
            "a/../b",
            "",
            ".",
            "x\x00y",
            "∕slash",
            "a//b",
            "a/./b",
        ]
    ),
    st.builds(PurePosixPath, st.sampled_from(["p", "q/r", "/abs"])),
    st.integers(-3, 3),
    st.just(b"bytes"),
    st.sampled_from([None, 1.5, True, ["a"]]),
)
envs = st.fixed_dictionaries(
    {
        "root": st.one_of(
            st.sampled_from(["/mnt/x", "rel", "/", ".", "a/b", "//net", "/x.y/", ""]),
            hostile,
        ),
        "seg": st.one_of(name, hostile),
        "sub": st.one_of(
            st.lists(name, max_size=3).map(lambda xs: "/".join(xs) or "."), hostile
        ),
        "n": st.one_of(st.integers(-5, 70000), st.just("7"), st.just(True)),
        "w": st.one_of(name, hostile, st.just("x/y")),
    }
)


def ref_outcome(term, env):
    try:
        return "ok", evaluate(term, env)
    except Invalid as e:
        return "invalid", e
    except OpError as e:
        return "op", e


def wend_outcome(fn):
    try:
        return "ok", fn()
    except InvalidBindingError as e:
        return "invalid", e
    except PathOperationError as e:
        return "op", e
    except MissingBindingError as e:  # pragma: no cover - every param is bound
        return "missing", e


SETTINGS = settings(
    max_examples=1500, deadline=None, suppress_health_check=[HealthCheck.too_slow]
)


@SETTINGS
@given(terms, envs)
def test_contract(term, env):
    ref = ref_outcome(term, env)
    event(f"reference: {ref[0]}")
    event(f"elimination-free: {elimination_free(term)}")
    try:
        expr = build(term)
    except (PathOperationError, TypeError, ValueError) as e:
        event("construction rejected")
        # A construction-time rejection claims failure for every binding.
        assert ref[0] != "ok", (
            f"wend rejected {term} at construction ({e!r}); reference gave {ref[1]}"
        )
        return
    got = wend_outcome(lambda: expr.render(env))
    # Obligations 1 and 2: agreement, no spurious rejection.
    if ref[0] == "ok":
        assert got == ("ok", str(ref[1])), (
            f"{expr!r} {env}: wend {got}, reference {ref[1]}"
        )
        for attr in ("name", "stem", "suffix"):
            assert getattr(expr, attr).render(env) == getattr(ref[1], attr), attr
    # Obligation 3: strictness for terms that cannot discard anything.
    if elimination_free(term):
        assert (got[0] == "ok") == (ref[0] == "ok"), (
            f"{expr!r} {env}: wend {got}, reference {ref}"
        )
    # Obligation 5: errors are typed (anything else would have propagated).
    assert got[0] != "missing"


@SETTINGS
@given(terms, envs)
def test_compiled_obeys_the_contract_too(term, env):
    ref = ref_outcome(term, env)
    try:
        expr = build(term)
    except PathOperationError, TypeError, ValueError:
        return
    got = wend_outcome(lambda: expr.compile().render(env))
    if ref[0] == "ok":
        assert got == ("ok", str(ref[1]))
    if elimination_free(term):
        assert (got[0] == "ok") == (ref[0] == "ok")


SAFE_LITERALS = [x for x in LITERALS if ".." not in x and not x.startswith("/")]
SAFE_TEMPLATES = [x for x in TEMPLATES if not x.strings[0].startswith("/")]
SAFE_NAMES = [x for x in NAMES if x != ".."]  # literal arguments are trusted
safe_terms = st.recursive(
    st.one_of(
        st.tuples(st.just("lit"), st.sampled_from(SAFE_LITERALS)),
        st.tuples(st.just("param"), st.sampled_from([ROOT, SEG, SUB])),
        st.tuples(st.just("tpl"), st.sampled_from(SAFE_TEMPLATES)),
    ),
    lambda kids: st.one_of(
        st.tuples(st.just("join"), kids, kids),
        st.tuples(st.just("parent"), kids),
        st.tuples(st.just("with_suffix"), kids, st.sampled_from(SUFFIXES)),
        st.tuples(st.just("with_name"), kids, st.sampled_from(SAFE_NAMES)),
        st.tuples(st.just("with_stem"), kids, st.sampled_from(STEMS)),
    ),
    max_leaves=7,
)


@SETTINGS
@given(safe_terms, envs)
def test_bindings_cannot_escape_a_literal_base(term, env):
    """§3: below a literal base, no binding of an AUTO, Segment or SubPath
    parameter leads outside it, however the term was composed."""
    try:
        expr = P("/base") / build(term)
    except PathOperationError, TypeError, ValueError:
        return
    got = wend_outcome(lambda: expr.render(env))
    if got[0] == "ok":
        out = PurePosixPath(got[1])
        assert out == PurePosixPath("/base") or out.is_relative_to("/base"), (
            expr,
            env,
            out,
        )
        assert ".." not in out.parts, (expr, env, out)


@pytest.mark.parametrize(
    "bad",
    ["'", '"', "\\", "\n", "{", "}", "');import os;('", "__import__('os')", "é", "\t"],
)
def test_generated_code_is_injection_safe(bad):
    """Literal text, spec text and parameter names reach generated code only via repr()."""
    p = Param(f"p{bad}")
    e = P(f"/a{bad}") / Param(f"x{bad}") / T(t"{p}{bad}.txt") / f"lit{bad}"
    env = {f"x{bad}": "seg", f"p{bad}": "v"}
    assert (
        e.compile().render(env) == e.render(env) == f"/a{bad}/seg/v{bad}.txt/lit{bad}"
    )
    assert e.match(e.render(env)) == env


def test_wend_errors_are_wend_errors():
    assert issubclass(InvalidBindingError, (WendError, ValueError))
    assert issubclass(PathOperationError, (WendError, ValueError))
    assert set(string.ascii_letters) <= set(string.printable)
