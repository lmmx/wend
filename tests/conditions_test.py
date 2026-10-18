"""Conditions (docs/SEMANTICS.md §10): declared, checked, carried and reported."""

import itertools
import os
import pickle
from pathlib import PurePosixPath

import pytest
from connectivity_test import _reachable
from contract_test import build, envs, terms
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from wend import AnyPath, P, Param, PathOperationError, SubPath, T
from wend.conditions import (
    Absent,
    Creatable,
    Dir,
    Exists,
    File,
    Listable,
    Readable,
    Step,
    Under,
    Writable,
    contained,
)
from wend.errors import (
    CapabilityError,
    ConditionError,
    ContainmentError,
    InvalidBindingError,
    MissingPathError,
    PathExistsError,
    WrongKindError,
)


root = Param("root")
name = Param("name")
rel = AnyPath("rel")


# -- declaring ----------------------------------------------------------------


def test_conditions_are_metadata():
    e = (P(root) / "a.csv").requires(File, Exists).ensures(Readable)
    plain = P(root) / "a.csv"
    assert e == plain and hash(e) == hash(plain)
    assert e.conditions.requires == (File, Exists)
    assert e.conditions.ensures == (Readable,)
    assert plain.conditions is None
    assert (
        repr(e)
        == "PathExpr('{root}/a.csv', requires=(File, Exists), ensures=(Readable))"
    )
    # the derivation is kept: the declared path still knows its base
    assert e.base == P(root)
    assert e.requires(File).conditions.requires == (File, Exists)  # no duplicates


def test_contradictions_and_bad_declarations_are_refused():
    with pytest.raises(PathOperationError, match="both Exists and Absent"):
        P("a").requires(Exists).requires(Absent)
    with pytest.raises(PathOperationError, match="both File and Dir"):
        P("a").ensures(File, Dir)
    with pytest.raises(PathOperationError, match="both File and Listable"):
        P("a").requires(File, Listable)
    P("a").requires(Absent).ensures(Exists)  # phases are separate
    with pytest.raises(TypeError):
        P("a").requires("Exists")
    with pytest.raises(PathOperationError, match="does not have"):
        P("/x").requires(Under(P(root)))  # the base needs a binding the path lacks


def test_nothing_can_be_joined_below_a_file():
    f = (P(root) / "data.csv").requires(File)
    for build_below in (
        lambda: f / "x",
        lambda: f.child("x"),
        lambda: f.joinpath("x", "y"),
        lambda: P("x").under(f),
    ):
        with pytest.raises(PathOperationError, match="declared a File"):
            build_below()
    assert f.sibling("schema.json") == P(root) / "schema.json"
    assert f.with_suffix(".parquet") == P(root) / "data.parquet"


def test_conditions_stay_with_the_expression_they_were_declared_on():
    e = (P(root) / "a.csv").requires(File, Exists, Under(P(root)))
    for derived in (e.parent, e.sibling("b"), e.with_suffix(".x"), e.with_name("c")):
        assert derived.conditions is None
    # binding and rebasing keep them, moving the base of Under along
    bound = e.bind(root="/srv")
    assert bound.conditions.requires == (File, Exists, Under(P("/srv")))
    moved = e.rebase(P(root), P("/tmp"))
    assert moved.conditions.requires == (File, Exists, Under(P("/tmp")))
    assert e.rebase(P("/q")).conditions.requires[-1] == Under(P("/q"))
    assert e.bind(other=1) is e


def test_an_argument_returned_unchanged_loses_its_conditions():
    e = P("/a/b.txt").requires(Exists)
    same = e.with_suffix(".txt")
    assert same == e and same.conditions is None and same.derivation.op == "with_suffix"


def test_conditions_survive_pickling():
    e = (P(root) / rel).requires(Under(P(root)), Exists).ensures(Readable)
    back = pickle.loads(pickle.dumps(e))
    assert back.conditions == e.conditions
    assert back.conditions.requires[1] is Exists
    with pytest.raises(ContainmentError):
        back.render(root="/srv", rel="../x")


# -- containment at render ----------------------------------------------------


def test_render_keeps_bindings_under_the_declared_base():
    e = (P(root) / rel).requires(Under(P(root)))
    assert e.render(root="/srv", rel="a/b") == "/srv/a/b"
    assert e.render(root="/srv", rel=".") == "/srv"
    for bad in ("../etc", "/etc/passwd", "a/../../x", "a/../b"):
        with pytest.raises(ContainmentError) as info:
            e.render(root="/srv", rel=bad)
        assert isinstance(info.value, InvalidBindingError)  # a binding problem
    # every route that renders enforces it
    with pytest.raises(ContainmentError):
        e.compile().render(root="/srv", rel="../x")
    with pytest.raises(ContainmentError):
        e.resolve(root="/srv", rel="../x")
    assert e.compile().many([{"root": "/srv", "rel": "a"}]) == ["/srv/a"]


def test_containment_matches_the_lexical_rule():
    cases = {
        ("/srv/a", "/srv"): True,
        ("/srv", "/srv"): True,
        ("/srvx", "/srv"): False,
        ("/srv/../x", "/srv"): False,
        ("a/b", "."): True,
        ("/a", "."): False,
        ("a", "/"): False,
        ("/a", "/"): True,
        ("//a", "/"): False,
        ("../d/x", "../d"): True,
        ("..", "."): False,
    }
    for (path, base), want in cases.items():
        assert contained(path, base) is want, (path, base)


def _contained_by_parts(path, base):
    if path == base:
        return True
    p, b = PurePosixPath(path), PurePosixPath(base)
    n = len(b.parts)
    return p.anchor == b.anchor and p.parts[:n] == b.parts and ".." not in p.parts[n:]


def test_containment_on_strings_equals_containment_on_parts():
    canonical = sorted(
        {
            str(PurePosixPath("".join(t)))
            for n in range(7)
            for t in itertools.product("/.a", repeat=n)
        }
    )
    for path in canonical:
        for base in canonical:
            assert contained(path, base) == _contained_by_parts(path, base), (
                path,
                base,
            )


def test_match_and_glob_only_find_contained_paths(tmp_path):
    (tmp_path / "in").mkdir()
    (tmp_path / "in" / "a.txt").write_text("")
    (tmp_path / "out.txt").write_text("")
    e = P(Param("top")) / SubPath("s") / Param("f")
    found = {(m["s"], m["f"]) for m in e.glob(top=tmp_path, kind="file")}
    assert found == {(".", "out.txt"), ("in", "a.txt")}
    inside = e.requires(Under(P(tmp_path / "in")))
    assert [(m["s"], m["f"]) for m in inside.glob(top=tmp_path, kind="file")] == [
        ("in", "a.txt")
    ]
    srv = P(Param("p")).requires(Under(P("/srv")))
    assert srv.match("/srv/x") == {"p": "/srv/x"}
    assert srv.match("/etc/x") is None


def test_resolve_frame_checks_containment_on_every_row():
    pl = pytest.importorskip("polars")
    from wend.frame import resolve_frame

    e = (P(Param("p")) / "x.txt").requires(Under(P("/srv")))
    ok = pl.DataFrame({"p": ["/srv", "/srv/b"]})
    assert resolve_frame(e, ok).to_list() == ["/srv/x.txt", "/srv/b/x.txt"]
    bad = pl.DataFrame({"p": ["/srv", "/srv/../etc"]})
    with pytest.raises(ContainmentError, match="row 1"):
        resolve_frame(e, bad)


# -- checking -----------------------------------------------------------------


@pytest.fixture
def tree(tmp_path):
    (tmp_path / "raw").mkdir()
    (tmp_path / "raw" / "a.csv").write_text("x")
    (tmp_path / "out").mkdir()
    os.symlink(tmp_path / "missing", tmp_path / "out" / "dangling")
    os.symlink("/", tmp_path / "raw" / "escape")
    return tmp_path


def test_existence_and_kind(tree):
    src = (P(root) / "raw" / T(t"{name}.csv")).requires(File, Exists, Readable)
    assert src.check(root=tree, name="a") == tree / "raw" / "a.csv"
    with pytest.raises(MissingPathError) as info:
        src.check(root=tree, name="b")
    assert isinstance(info.value, FileNotFoundError)
    assert info.value.path == f"{tree}/raw/b.csv" and info.value.condition is Exists
    with pytest.raises(WrongKindError):
        (P(root) / "raw").requires(File).check(root=tree)
    with pytest.raises(WrongKindError):
        (P(root) / "raw" / "a.csv").requires(Dir).check(root=tree)
    # File and Dir say what a path is if it exists
    (P(root) / "raw" / "new.csv").requires(File).check(root=tree)


def test_absent_means_nothing_at_the_name(tree):
    dst = (P(root) / "out" / T(t"{name}.parquet")).requires(Absent, Creatable)
    assert dst.check(root=tree, name="a") == tree / "out" / "a.parquet"
    with pytest.raises(PathExistsError) as info:
        (P(root) / "out" / "dangling").requires(Absent).check(root=tree)
    assert isinstance(info.value, FileExistsError)
    with pytest.raises(MissingPathError):  # a broken link does not exist either
        (P(root) / "out" / "dangling").requires(Exists).check(root=tree)


def test_creatable_looks_for_the_nearest_existing_directory(tree):
    deep = (P(root) / "out" / "x" / "y" / "z.bin").requires(Creatable, Writable)
    deep.check(root=tree)
    with pytest.raises(CapabilityError, match="is not a directory"):
        (P(root) / "raw" / "a.csv" / "below").requires(Creatable).check(root=tree)


def test_capabilities_use_the_process_permissions(tree, monkeypatch):
    # The suite may run as root, for whom os.access grants nearly everything.
    denied: set[int] = set()
    monkeypatch.setattr(os, "access", lambda p, mode: not (mode & sum(denied)))
    readable = (P(root) / "raw" / "a.csv").requires(Readable)
    listable = (P(root) / "raw").requires(Listable)
    writable = (P(root) / "out" / "new").requires(Writable)
    for e in (readable, listable, writable):
        e.check(root=tree)
    denied.add(os.R_OK)
    for e in (readable, listable):
        with pytest.raises(CapabilityError) as info:
            e.check(root=tree)
        assert isinstance(info.value, PermissionError)
    denied.clear()
    denied.add(os.W_OK)
    with pytest.raises(CapabilityError, match="cannot be created"):
        writable.check(root=tree)
    with pytest.raises(WrongKindError):
        (P(root) / "raw" / "a.csv").requires(Listable).check(root=tree)


def test_under_resolves_symlinks_when_checked(tree):
    e = (P(root) / "raw" / rel).requires(Under(P(root) / "raw"))
    assert e.render(root=tree, rel="escape/etc") == f"{tree}/raw/escape/etc"
    with pytest.raises(ContainmentError, match="resolves outside"):
        e.check(root=tree, rel="escape/etc")
    e.check(root=tree, rel="a.csv")


def test_postconditions_are_checked_by_confirm(tree):
    dst = (P(root) / "out" / "r.txt").requires(Absent).ensures(File, Exists)
    dst.check(root=tree)
    with pytest.raises(MissingPathError):
        dst.confirm(root=tree)
    (tree / "out" / "r.txt").write_text("done")
    dst.confirm(root=tree)
    with pytest.raises(PathExistsError):
        dst.check(root=tree)


# -- steps and effects --------------------------------------------------------


def test_a_step_declares_pre_and_postconditions_once(tree):
    src = (P(root) / "raw" / T(t"{name}.csv")).requires(File, Exists, Readable)
    dst = (P(root) / "out" / T(t"{name}.txt")).requires(Absent, Creatable)
    convert = Step(src=src, dst=dst.ensures(File, Exists))
    with convert(root=tree, name="a") as p:
        p["dst"].write_text(p["src"].read_text().upper())
    assert (tree / "out" / "a.txt").read_text() == "X"
    with pytest.raises(PathExistsError):  # the output exists now
        with convert(root=tree, name="a"):
            pass
    with pytest.raises(MissingPathError):  # the body did not produce it
        with Step(dst=dst.ensures(Exists))(root=tree, name="b"):
            pass
    with pytest.raises(RuntimeError):  # a failing body skips the postconditions
        with Step(dst=dst.ensures(Exists))(root=tree, name="c"):
            raise RuntimeError
    assert convert.param_names == {"root", "name"}


def test_effects_report_what_a_step_declares():
    src = (P(root) / T(t"{name}.csv")).requires(Exists, Readable)
    tmp = (P(root) / "tmp").requires(Exists).ensures(Absent)
    dst = (P(root) / T(t"{name}.out")).requires(Absent).ensures(Exists)
    cache = P(root) / "cache"
    report = {
        e.name: e.verbs for e in Step(src=src, tmp=tmp, dst=dst, cache=cache).effects()
    }
    assert report == {
        "src": {"read"},
        "tmp": {"delete"},
        "dst": {"create"},
        "cache": set(),
    }
    assert repr(Step(src=src).effects()[0]) == "<src: read {root}/{name}.csv>"


def test_errors_share_a_base():
    for cls in (
        MissingPathError,
        PathExistsError,
        WrongKindError,
        CapabilityError,
        ContainmentError,
    ):
        assert issubclass(cls, ConditionError)


# -- properties ---------------------------------------------------------------

_FAILS = (PathOperationError, TypeError, ValueError)


@settings(max_examples=500, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(terms, envs, st.data())
def test_render_with_under_is_render_restricted_to_contained_paths(term, env, data):
    """Soundness and completeness of render's containment check, on every term
    the contract generates: ``e.requires(Under(b))`` renders exactly when ``e``
    renders to a path lexically under ``b``, and to the same string."""
    try:
        e = build(term)
    except _FAILS:
        return
    bases = [P("."), P("/")]
    for s in _reachable(term):
        try:
            b = build(s)
        except _FAILS:
            continue
        if b.param_names <= e.param_names:
            bases.append(b)
    if not bases:
        return
    b = data.draw(st.sampled_from(bases))
    guarded = e.requires(Under(b))
    try:
        want = e.render(env)
        base = b.render(env)
    except _FAILS:
        return
    expect_ok = contained(want, base)
    for render in (guarded.render, guarded.compile().render):
        try:
            got = render(env)
        except ContainmentError:
            assert not expect_ok, (term, want, base)
        else:
            assert expect_ok and got == want, (term, want, base)
