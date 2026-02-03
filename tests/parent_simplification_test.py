from pathlib import Path

from wend import JoinExpr, Param


def test_parent_simplifies_join():
    root = Param("root")
    expr = root / "a" / "b"

    parent = expr.parent

    # "b" is dropped structurally
    assert isinstance(parent, JoinExpr)
    assert parent.resolve({"root": "/x"}) == Path("/x/a")
