from pathlib import Path
from wend import Param

def test_param_resolution():
    root = Param("root")
    expr = root / "file.txt"

    path = expr.resolve({"root": "/tmp"})
    assert path == Path("/tmp/file.txt")
