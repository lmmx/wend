"""The changelog's part in a release (docs/scripts/changelog.py): `just release`
titles the "Unreleased" notes with the new version, and the GitHub Release
workflow takes that version's notes for the release's body."""

import importlib.util
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).parent.parent
SCRIPT = ROOT / "docs" / "scripts" / "changelog.py"
_spec = importlib.util.spec_from_file_location("changelog", SCRIPT)
changelog = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(changelog)

TEXT = """# Changelog

Intro.

## Unreleased

### New

- a thing (#3)

## 0.2.0

### Fixed

- an old thing (#1)
"""


def test_release_titles_the_unreleased_notes_and_opens_new_ones():
    out = changelog.release(TEXT, "0.3.0")
    assert out.index("## Unreleased") < out.index("## 0.3.0") < out.index("## 0.2.0")
    assert changelog.section(out, "Unreleased") is None
    assert changelog.section(out, "0.3.0") == changelog.section(TEXT, "Unreleased")
    assert changelog.section(out, "0.2.0") == changelog.section(TEXT, "0.2.0")


def test_release_again_changes_nothing():
    once = changelog.release(TEXT, "0.3.0")
    assert changelog.release(once, "0.3.0") == once


def test_release_keeps_notes_already_titled_and_a_changelog_without_unreleased():
    titled = TEXT.replace("## Unreleased", "## 0.3.0")
    assert changelog.release(titled, "0.3.0") == titled
    assert changelog.release(titled, "0.4.0") == titled


def test_a_section_runs_to_the_next_version_and_keeps_its_subheadings():
    assert changelog.section(TEXT, "Unreleased") == "### New\n\n- a thing (#3)"
    assert changelog.section(TEXT, "9.9.9") is None
    assert (
        changelog.section(TEXT.replace("- a thing (#3)", ""), "Unreleased") == "### New"
    )
    assert changelog.section(changelog.release(TEXT, "0.3.0"), "Unreleased") is None


def test_notes_lift_headings_outside_code_and_fall_back_to_the_migration_guide():
    text = TEXT.replace("- a thing (#3)", "```sh\n### not a heading\n```")
    assert changelog.notes(text, "Unreleased") == (
        "## New\n\n```sh\n### not a heading\n```"
    )
    assert changelog.notes(TEXT, "9.9.9") == changelog.NO_NOTES
    assert "MIGRATING.md" in changelog.NO_NOTES


def test_the_changelog_has_unreleased_notes_and_the_released_versions():
    text = changelog.CHANGELOG.read_text(encoding="utf-8")
    titles = [line[3:].strip() for line in text.splitlines() if line.startswith("## ")]
    assert titles[0] == "Unreleased"
    assert "0.3.0" in titles and "0.2.0" in titles
    notes = changelog.notes(text, "0.3.0")
    assert notes != changelog.NO_NOTES
    assert "#111" in notes and "MIGRATING.md" in notes


def test_the_script_prints_notes_and_titles_a_changelog(tmp_path, monkeypatch):
    run = subprocess.run(
        [sys.executable, str(SCRIPT), "notes", "0.3.0"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert run.stdout.startswith("wend 0.3.0")
    copy = tmp_path / "CHANGELOG.md"
    copy.write_text(TEXT, encoding="utf-8")
    monkeypatch.setattr(changelog, "CHANGELOG", copy)
    assert changelog.main(["release", "0.3.0"]) == 0
    assert copy.read_text(encoding="utf-8") == changelog.release(TEXT, "0.3.0")
    assert changelog.main(["publish", "0.3.0"]) == 2
