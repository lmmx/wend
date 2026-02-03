import pytest

from wend import Param


def test_missing_bindings_raises():
    root = Param("root")
    dataset = Param("dataset")

    expr = root / dataset

    with pytest.raises(ValueError, match="Missing bindings"):
        expr.resolve({"root": "/data"})
