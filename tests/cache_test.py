from wend import Param


def test_resolution_is_stable():
    root = Param("root")
    expr = root / "a" / "b"

    bindings = {"root": "/x"}

    assert expr.resolve(bindings) == expr.resolve(bindings)
