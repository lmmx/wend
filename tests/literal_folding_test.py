from pathlib import Path

from wend import LiteralExpr, P


def test_literal_folding_on_join():
    expr = P("/home") / "user" / "data"

    # Construction-time folding
    assert isinstance(expr, LiteralExpr)

    # Resolution still works
    assert expr.resolve() == Path("/home/user/data")
