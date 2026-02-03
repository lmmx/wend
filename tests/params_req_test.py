from wend import Param


def test_required_params_simple():
    root = Param("root")
    dataset = Param("dataset")

    expr = root / "data" / dataset

    assert expr.required_params() == {"root", "dataset"}
