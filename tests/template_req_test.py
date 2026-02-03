from wend import Param, T


def test_template_required_params():
    a = Param("a")
    b = Param("b")

    expr = T(t"x_{a}_{b}")

    assert expr.required_params() == {"a", "b"}
