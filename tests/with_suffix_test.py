from pathlib import Path

from wend import Param, WithSuffixExpr


def test_suffix_chain_collapse():
    root = Param("root")

    expr = (root / "file.txt").with_suffix(".tmp").with_suffix(".json")

    # Only the last suffix survives
    assert isinstance(expr, WithSuffixExpr)
    assert expr.resolve({"root": "/x"}) == Path("/x/file.json")
