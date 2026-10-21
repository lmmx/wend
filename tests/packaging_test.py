"""The built package: the wheel ships every module of wend but the research
prototypes, and building it from the sdist gives the same wheel contents."""

import shutil
import subprocess
import tarfile
import zipfile
from pathlib import Path

import pytest


ROOT = Path(__file__).parent.parent
UV = shutil.which("uv")


@pytest.fixture(scope="module")
def dist(tmp_path_factory):
    if UV is None:
        pytest.skip("uv is not installed")
    out = tmp_path_factory.mktemp("dist")
    # `uv build` builds the sdist, then the wheel from it, as a release does.
    subprocess.run([UV, "build", "-q", "-o", str(out), str(ROOT)], check=True)
    direct = tmp_path_factory.mktemp("direct")
    subprocess.run(
        [UV, "build", "-q", "--wheel", "-o", str(direct), str(ROOT)], check=True
    )
    return out, direct


def wheel_modules(directory):
    (wheel,) = directory.glob("*.whl")
    return {n for n in zipfile.ZipFile(wheel).namelist() if n.startswith("wend/")}


def test_the_wheel_ships_wend_without_the_research_prototypes(dist):
    out, _ = dist
    shipped = wheel_modules(out)
    source = {
        p.relative_to(ROOT / "src").as_posix()
        for p in (ROOT / "src" / "wend").rglob("*")
        if p.is_file() and p.suffix in {".py", ".typed"}
    }
    expected = {n for n in source if not n.startswith("wend/_experimental/")}
    assert {n for n in shipped if not n.endswith("/")} == expected
    assert "wend/py.typed" in shipped


def test_the_sdist_keeps_the_whole_source(dist):
    out, _ = dist
    (sdist,) = out.glob("*.tar.gz")
    names = tarfile.open(sdist).getnames()
    assert any(n.endswith("src/wend/_experimental/overlap.py") for n in names)
    assert any(n.endswith("/LICENSE") for n in names)


def test_a_wheel_from_the_sdist_matches_one_from_the_tree(dist):
    out, direct = dist
    assert wheel_modules(out) == wheel_modules(direct)
