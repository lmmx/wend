from pathlib import Path
from wend import P

def test_with_name():
    expr = P("/tmp/data.txt").with_name("other.csv")

    assert expr.resolve() == Path("/tmp/other.csv")
