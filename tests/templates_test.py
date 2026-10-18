"""Readymade templates (wend.templates) and anchors (wend.anchors)."""

import os
from pathlib import Path

import pytest

from wend import P, Param, PathOperationError, anchors, counter
from wend._match import _expr_plan
from wend.anchors import CWD, HOME, XDG


# -- counters ---------------------------------------------------------------------


def test_counter_patterns():
    assert counter("chunk", width=4, suffix=".parquet").pattern == (
        "chunk_{idx:04d}.parquet"
    )
    assert counter("chunk", width=3, of_total=True, suffix=".parquet").pattern == (
        "chunk_{idx:03d}-of-{total:03d}.parquet"
    )
    assert counter("log", suffix=".log").pattern == "log_{idx:d}.log"
    assert counter(width=5).pattern == "{idx:05d}"
    assert counter("part", sep="-", of_total=True, of="_of_").pattern == (
        "part-{idx:d}_of_{total:d}"
    )


def test_part_3_counter_example():
    """Future Paths part 3: a sized chunk counter and an unsized log counter."""
    root = Param("root")
    chunk_file = (
        root / "chunks" / counter("chunk", width=3, of_total=True, suffix=".parquet")
    )
    assert chunk_file.resolve({"root": Path("/data"), "idx": 1, "total": 10}) == Path(
        "/data/chunks/chunk_001-of-010.parquet"
    )
    assert chunk_file.parent.resolve(root="/data") == Path("/data/chunks")
    log_file = root / "logs" / counter("log", width=5, suffix=".parquet")
    assert log_file.render(root="/data", idx=123) == "/data/logs/log_00123.parquet"


def test_counters_match_on_the_fast_path():
    e = P("/d") / counter("chunk", width=4, of_total=True, suffix=".parquet")
    assert _expr_plan(e) is not None
    assert e.match("/d/chunk_0012-of-0100.parquet") == {"idx": 12, "total": 100}
    assert e.match("/d/chunk_12-of-0100.parquet") is None
    assert counter("log").match("log_7") == {"idx": 7}


def test_counter_parameters_can_be_declared():
    total = Param("total", type=int, default=8)
    e = counter("shard", width=2, of_total=True, total=total, idx="i")
    assert e.pattern == "shard_{i:02d}-of-{total:02d}"
    assert e.render(i=3) == "shard_03-of-08"
    assert e.required_params() == {"i"}


@pytest.mark.parametrize(
    "kw",
    [
        {"width": 0},
        {"width": -1},
        {"width": 2.0},
        {"stem": "a/b"},
        {"suffix": "/x"},
        {"sep": "/"},
    ],
)
def test_counter_rejects_what_is_not_one_counter_segment(kw):
    with pytest.raises(ValueError):
        counter(**kw)


def test_counter_rejects_other_parameters():
    with pytest.raises(TypeError):
        counter(idx=3)  # type: ignore[arg-type]
    with pytest.raises(PathOperationError):
        counter("a\x00")


# -- anchors ----------------------------------------------------------------------


def test_anchors_are_absolute_parameters_named_after_the_environment():
    assert XDG.CACHE_HOME.name == "XDG_CACHE_HOME" and HOME.name == "HOME"
    e = (P("models") / Param("name")).under(XDG.CACHE_HOME / "myapp")
    assert e.pattern == "{XDG_CACHE_HOME}/myapp/models/{name}"
    assert e.is_absolute()
    # rendering stays pure: an anchor is bound like any parameter
    assert e.render(XDG_CACHE_HOME="/tmp/c", name="bert") == "/tmp/c/myapp/models/bert"
    assert e.match("/tmp/c/myapp/models/bert") == {
        "XDG_CACHE_HOME": "/tmp/c",
        "name": "bert",
    }
    with pytest.raises(TypeError):
        XDG()


def test_xdg_follows_the_specification():
    env = {"HOME": "/home/u", "XDG_CONFIG_HOME": "/cfg", "XDG_DATA_HOME": "rel"}
    b = anchors.bindings(env)
    assert b["HOME"] == "/home/u"
    assert b["XDG_CONFIG_HOME"] == "/cfg"
    assert b["XDG_DATA_HOME"] == "/home/u/.local/share"  # relative: ignored
    assert b["XDG_STATE_HOME"] == "/home/u/.local/state"
    assert b["XDG_CACHE_HOME"] == "/home/u/.cache"
    assert anchors.bindings({"HOME": "/h", "XDG_CACHE_HOME": ""})["XDG_CACHE_HOME"] == (
        "/h/.cache"
    )
    assert b["CWD"] == os.getcwd()
    assert set(b) == {p.name for p in anchors.ANCHORS}


def test_home_falls_back_to_the_password_database():
    import pwd

    want = pwd.getpwuid(os.getuid()).pw_dir
    assert anchors.bindings({})["HOME"] == want
    assert anchors.bindings({"HOME": "relative"})["HOME"] == want


def test_anchors_read_the_process_environment_when_asked(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.chdir(tmp_path)
    b = anchors.bindings()
    assert b["XDG_STATE_HOME"] == str(tmp_path / "state")
    assert (P(CWD) / "out").render(b) == str(tmp_path / "out")
    log = XDG.STATE_HOME / "app" / "log.txt"
    assert log.render(b) == str(tmp_path / "state/app/log.txt")


def test_a_missing_working_directory_only_fails_paths_that_use_it(
    monkeypatch, tmp_path
):
    gone = tmp_path / "gone"
    gone.mkdir()
    monkeypatch.chdir(gone)
    gone.rmdir()
    b = anchors.bindings({"HOME": "/h"})
    assert "CWD" not in b
    assert (XDG.CONFIG_HOME / "x").render(b) == "/h/.config/x"
