"""wend._experimental.typed at runtime: the atoms an expression declares,
annotations checked against them, and steps declared as classes. The static
half (typed.pyi) is checked by experiments/typed/check.py and
experiments/typed/soundness.py, which need Pyright and ty."""

from typing import Literal

import pytest

from wend._experimental.typed import (
    Absent,
    AnyPath,
    Checked,
    Creatable,
    Dir,
    Exists,
    File,
    IsFile,
    Listable,
    P,
    Param,
    PathExpr,
    Readable,
    Resolved,
    StepSpec,
    T,
    Under,
    Unspecified,
    Uses,
    declared_by,
    facts,
)
from wend.errors import ContainmentError, MissingPathError, PathExistsError


root, name = Param("root"), Param("name")
raw = (P(root) / "raw" / T(t"{name}.csv")).requires(File, Exists, Readable)
out = (P(root) / "out" / T(t"{name}.parquet")).requires(Absent, Creatable)
out = out.ensures(File, Exists)


def test_facts_name_each_declared_condition():
    assert facts(raw).atoms == {"file", "exists", "read"}
    assert facts(raw).kind is IsFile
    assert facts(out).atoms == {"absent", "create", "post_file", "post_exists"}
    assert facts(P(root) / "x") == (frozenset(), Unspecified)


def test_kinds_are_atoms_on_each_side():
    # A step may replace a file with a directory: both are declared.
    e = (P(root) / "x").requires(File, Exists).ensures(Dir, Exists)
    assert {"file", "post_dir"} <= facts(e).atoms
    assert facts(e).kind is IsFile  # what forbids joining below


def test_under_atoms_name_a_static_base_and_any_base():
    e = (P("/srv/static") / AnyPath("rel")).requires(Under("/srv/static"))
    assert facts(e).atoms == {"Under[str]", "Under['/srv/static']"}
    g = (P(root) / AnyPath("rel")).requires(Under(P(root)))
    assert facts(g).atoms == {"Under[str]"}
    # binding the base's parameter makes it static: the atom follows
    assert "Under['/srv']" in facts(g.bind(root="/srv")).atoms


def test_derived_expressions_declare_nothing_and_bind_rebase_keep():
    assert facts(raw.parent).atoms == frozenset()
    assert facts(raw.with_suffix(".tsv")).atoms == frozenset()
    assert facts(raw.bind(root="/d")) == facts(raw)
    assert facts(raw.rebase(P(root), P("/x"))) == facts(raw)


def test_rebase_moves_a_base_under_the_old_one():
    # So a literal base's identity does not survive rebase (typed.pyi drops it
    # to Under[str]); one outside the old base stays, and is still enforced.
    e = (P("/srv/static") / AnyPath("rel")).requires(Under("/srv/static"))
    moved = e.rebase(P("/srv/static"), P("/tmp"))
    assert facts(moved).atoms == {"Under[str]", "Under['/tmp']"}
    assert moved.render(rel="x") == "/tmp/x"
    g = (P(root) / AnyPath("rel")).requires(Under("/srv/static"))
    kept = g.rebase(P(root), P("/tmp"))  # the base is not under {root}
    assert "Under['/srv/static']" in facts(kept).atoms
    with pytest.raises(ContainmentError):
        kept.render(rel="x")  # and is still enforced


def test_an_annotation_is_checked_against_the_declaration():
    assert declared_by(Checked[Literal["read", "exists", "file"]], raw)
    assert declared_by(Checked[Literal["read"], IsFile], raw)
    assert declared_by(PathExpr, raw)  # bare: claims nothing
    assert not declared_by(Checked[Literal["write"]], raw)
    assert not declared_by(Checked[Literal["read"], IsFile], raw.parent)
    srv = (P("/srv") / AnyPath("r")).requires(Under("/srv"), Readable)
    assert declared_by(Resolved[Literal["read"] | Under[Literal["/srv"]]], srv)
    assert not declared_by(Resolved[Under[Literal["/tmp"]]], srv)


class Convert(StepSpec):
    src = Uses(raw)
    dst = Uses(out)


def test_a_step_class_exposes_declarations_and_effects():
    assert Convert.src is raw
    assert [repr(e) for e in Convert.effects()] == [
        "<src: read {root}/raw/{name}.csv>",
        "<dst: create {root}/out/{name}.parquet>",
    ]


def test_inside_with_attributes_are_checked_paths(tmp_path):
    (tmp_path / "raw").mkdir()
    (tmp_path / "raw" / "a.csv").write_text("1")
    (tmp_path / "out").mkdir()
    with Convert(root=str(tmp_path), name="a") as s:
        assert isinstance(s.src, Checked)
        assert s.src == tmp_path / "raw" / "a.csv"
        s.dst.write_bytes(s.src.read_bytes())
    assert (tmp_path / "out" / "a.parquet").read_text() == "1"


def test_entry_and_exit_check_the_conditions(tmp_path):
    with pytest.raises(MissingPathError):
        with Convert(root=str(tmp_path), name="a"):
            pass
    (tmp_path / "raw").mkdir()
    (tmp_path / "raw" / "a.csv").write_text("1")
    (tmp_path / "out").mkdir()
    with pytest.raises(MissingPathError):  # dst was not made
        with Convert(root=str(tmp_path), name="a"):
            pass
    (tmp_path / "out" / "a.parquet").write_text("")
    with pytest.raises(PathExistsError):  # dst must be absent first
        with Convert(root=str(tmp_path), name="a"):
            pass


def test_attributes_are_realised_only_inside_with():
    s = Convert(root="/d", name="a")
    with pytest.raises(AttributeError, match="only inside"):
        s.src  # noqa: B018


def test_subclasses_inherit_uses():
    class Listed(Convert):
        tree = Uses((P(root) / "raw").requires(Dir, Exists, Listable))

    assert list(Listed.step().paths) == ["src", "dst", "tree"]
