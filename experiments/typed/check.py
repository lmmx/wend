"""Run Pyright and ty on positive.py and negative.py and compare their errors
with the ``# E:`` markers: positive.py must have none, and negative.py must
have an error on exactly the marked lines, in both checkers.

    uv run python experiments/typed/check.py

The checkers' versions are pinned below and fetched with ``uvx``.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path


PYRIGHT = "pyright@1.1.407"
TY = "ty@0.0.90"
HERE = Path(__file__).resolve().parent
PYTHON = sys.executable


def pyright(files: list[Path]) -> dict[str, set[int]]:
    out = subprocess.run(
        [
            "uvx",
            "-q",
            PYRIGHT,
            "--outputjson",
            "--pythonpath",
            PYTHON,
            *map(str, files),
        ],
        capture_output=True,
        text=True,
        cwd=HERE,
    )
    report = json.loads(out.stdout)
    errs: dict[str, set[int]] = {}
    for d in report["generalDiagnostics"]:
        if d["severity"] == "error":
            errs.setdefault(Path(d["file"]).name, set()).add(
                d["range"]["start"]["line"] + 1
            )
    return errs


def ty(files: list[Path]) -> dict[str, set[int]]:
    out = subprocess.run(
        [
            "uvx",
            "-q",
            TY,
            "check",
            "--python",
            PYTHON,
            "--output-format",
            "concise",
            *map(str, files),
        ],
        capture_output=True,
        text=True,
        cwd=HERE,
    )
    errs: dict[str, set[int]] = {}
    for line in out.stdout.splitlines():
        m = re.match(r"(.+?):(\d+):\d+: error\[", line)
        if m:
            errs.setdefault(Path(m[1]).name, set()).add(int(m[2]))
    return errs


def marked(path: Path) -> set[int]:
    return {
        i for i, line in enumerate(path.read_text().splitlines(), 1) if "# E:" in line
    }


def main() -> int:
    files = [HERE / "common.py", HERE / "positive.py", HERE / "negative.py"]
    expected = {
        "common.py": set(),
        "positive.py": set(),
        "negative.py": marked(HERE / "negative.py"),
    }
    ok = True
    for checker, run in (("pyright", pyright), ("ty", ty)):
        got = run(files)
        for name, want in expected.items():
            have = got.get(name, set())
            missing, extra = sorted(want - have), sorted(have - want)
            status = "ok" if not (missing or extra) else "MISMATCH"
            ok &= status == "ok"
            print(
                f"{checker:8s} {name:12s} {status}  expected {len(want)}, got {len(have)}"
                + (f"  missing {missing}" if missing else "")
                + (f"  unexpected {extra}" if extra else "")
            )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
