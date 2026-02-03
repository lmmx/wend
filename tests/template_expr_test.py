from pathlib import Path
from wend import Param, T

def test_template_resolution():
    idx = Param("idx")

    expr = T(t"file_{idx:03d}.dat")

    assert expr.resolve({"idx": 5}) == Path("file_005.dat")
