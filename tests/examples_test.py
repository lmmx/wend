"""Every example script runs to completion."""

import runpy
from pathlib import Path

import pytest


EXAMPLES = sorted((Path(__file__).parent.parent / "examples").glob("*.py"))


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.stem)
def test_example_runs(path, capsys):
    runpy.run_path(str(path), run_name="__main__")
    assert capsys.readouterr().out


def test_demo_runs(capsys):
    runpy.run_path(str(Path(__file__).parent.parent / "demo.py"), run_name="__main__")
    assert "Resolved:" in capsys.readouterr().out
