"""Adversarial inputs: traversal, absolute paths, hostile values (symlinks: fs_test.py)."""

from pathlib import Path, PurePosixPath

import pytest

from wend import InvalidBindingError, P, Param, SubPath, T


BASE = P("/srv/static")
TRAVERSALS = [
    "..",
    "../x",
    "../../etc/passwd",
    "a/../../b",
    "/etc/passwd",
    "//net/share",
    "a/b",
]


@pytest.mark.parametrize("value", TRAVERSALS + ["", ".", "x\x00y"])
def test_segment_parameters_cannot_escape(value):
    with pytest.raises(InvalidBindingError):
        (BASE / Param("name")).render(name=value)
    with pytest.raises(InvalidBindingError):
        (BASE / Param("name")).render(
            name=PurePosixPath(value) if "\x00" not in value else value
        )


@pytest.mark.parametrize("value", ["..", "../x", "a/../b", "/etc", "//x"])
def test_subpaths_cannot_escape(value):
    with pytest.raises(InvalidBindingError):
        (BASE / SubPath("rel")).render(rel=value)


def test_subpaths_are_canonicalised():
    e = BASE / SubPath("rel") / "f"
    assert e.render(rel="a/./b") == e.render(rel="a//b/") == "/srv/static/a/b/f"


@pytest.mark.parametrize("value", ["../x", "a/b", "/x"])
def test_formatted_fields_cannot_inject_separators(value):
    with pytest.raises(InvalidBindingError):
        (BASE / T(t"{Param('w')}.csv")).render(w=value)


@pytest.mark.parametrize("value", ["..", ".", ""])
def test_formatted_segments_cannot_become_dot_segments(value):
    with pytest.raises(InvalidBindingError):
        (BASE / T(t"{Param('w'):s}")).render(w=value)


def test_non_string_values_are_rejected_for_path_positions():
    for value in [5, b"bytes", None, ["a"]]:
        with pytest.raises(InvalidBindingError):
            (BASE / Param("name")).render(name=value)


def test_literal_strings_are_trusted_paths():
    # Documented: safety applies to parameter bindings. A str joined directly
    # is a literal path with pathlib semantics, so untrusted input must be
    # bound to a Param rather than joined.
    assert (BASE / "../../etc/passwd").render() == str(
        Path("/srv/static") / "../../etc/passwd"
    )
    assert (BASE / "/etc/passwd").render() == "/etc/passwd"


def test_head_parameters_are_trusted_roots():
    assert (Param("root") / "x").render(root="../up") == "../up/x"
