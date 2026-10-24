"""The changelog's part in a release (docs/CHANGELOG.md).

    python docs/scripts/changelog.py release VERSION
        Title the "Unreleased" notes VERSION, with a fresh "Unreleased" above
        them (`just release`, in the release commit).
    python docs/scripts/changelog.py notes VERSION
        Print VERSION's notes for its GitHub Release, or a pointer to the
        migration guide when the changelog has none (the GitHub Release
        workflow, which follows them with the pull requests the release
        includes).

Standard library only: it runs on the CI runner's Python, not the project's.
"""

from __future__ import annotations

import sys
from pathlib import Path


CHANGELOG = Path(__file__).resolve().parent.parent / "CHANGELOG.md"
UNRELEASED = "Unreleased"
NO_NOTES = (
    "Changes in behaviour, if any, are in "
    "[docs/MIGRATING.md](https://github.com/lmmx/wend/blob/master/docs/MIGRATING.md)."
)


def _heading(line: str) -> str | None:
    """The title of a version's heading (``## 0.3.0``), or None."""
    if line.startswith("## "):
        return line[3:].strip()
    return None


def section(text: str, title: str) -> str | None:
    """The notes under ``## {title}``, up to the next such heading, or None
    when there is no heading or nothing under it."""
    lines = text.splitlines()
    starts = [i for i, line in enumerate(lines) if _heading(line) == title]
    if not starts:
        return None
    body = []
    for line in lines[starts[0] + 1 :]:
        if _heading(line) is not None:
            break
        body.append(line)
    notes = "\n".join(body).strip()
    return notes or None


def release(text: str, version: str) -> str:
    """The changelog with its "Unreleased" notes titled ``version``. Notes
    already titled ``version`` are left as they are, and so is a changelog
    with no "Unreleased" heading."""
    lines = text.splitlines(keepends=True)
    titles = [_heading(line) for line in lines]
    if version in titles or UNRELEASED not in titles:
        return text
    i = titles.index(UNRELEASED)
    return "".join(
        lines[:i] + [f"## {UNRELEASED}\n", "\n", f"## {version}\n"] + lines[i + 1 :]
    )


def notes(text: str, version: str) -> str:
    """The body for ``version``'s GitHub Release, before the list of pull
    requests: its section, with each heading one level up (a section's
    ``### New`` is the release's ``## New``, beside GitHub's
    ``## What's Changed``), or a pointer to the migration guide."""
    body = section(text, version)
    if body is None:
        return NO_NOTES
    out, fenced = [], False
    for line in body.splitlines():
        if line.lstrip().startswith("```"):
            fenced = not fenced
        elif not fenced and line.startswith("###"):
            line = line[1:]
        out.append(line)
    return "\n".join(out)


def main(argv: list[str]) -> int:
    if len(argv) != 2 or argv[0] not in ("release", "notes"):
        print(__doc__, file=sys.stderr)
        return 2
    command, version = argv
    text = CHANGELOG.read_text(encoding="utf-8")
    if command == "release":
        CHANGELOG.write_text(release(text, version), encoding="utf-8")
    else:
        print(notes(text, version))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
