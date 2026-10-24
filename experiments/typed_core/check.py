"""Run Pyright and ty on the typed core and its three guarantees (this
directory) and on the encodings compared before it (``prepost/``), and
compare their errors with the ``# E:`` markers: each file must have an
error on exactly its marked lines (none, for a file without markers), in
both checkers.

    uv run python experiments/typed_core/check.py

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


SUITES = {
    HERE: ["common.py", "positive.py", "negative.py"],
    HERE / "prepost": [
        "model_a.py",
        "uses_a.py",
        "model_c.py",
        "uses_c.py",
        "tygap.py",
    ],
}


def pyright(files: list[Path], cwd: Path) -> dict[str, set[int]]:
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
        cwd=cwd,
    )
    report = json.loads(out.stdout)
    errs: dict[str, set[int]] = {}
    for d in report["generalDiagnostics"]:
        if d["severity"] == "error":
            errs.setdefault(Path(d["file"]).name, set()).add(
                d["range"]["start"]["line"] + 1
            )
    return errs


def ty(files: list[Path], cwd: Path) -> dict[str, set[int]]:
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
        cwd=cwd,
    )
    errs: dict[str, set[int]] = {}
    for line in out.stdout.splitlines():
        m = re.match(r"(.+?):(\d+):\d+: error\[", line)
        if m:
            errs.setdefault(Path(m[1]).name, set()).add(int(m[2]))
    return errs


def marked(path: Path, checker: str) -> set[int]:
    """Lines marked ``# E:`` (an error in both checkers), and ``# E-ty:`` or
    ``# E-pyright:`` (a known gap of one checker, expected until it is fixed)."""
    return {
        i
        for i, line in enumerate(path.read_text().splitlines(), 1)
        if "# E:" in line or f"# E-{checker}:" in line
    }


def main() -> int:
    ok = True
    for where, names in SUITES.items():
        files = [where / n for n in names]
        for checker, run in (("pyright", pyright), ("ty", ty)):
            got = run(files, where)
            for f in files:
                want, have = marked(f, checker), got.get(f.name, set())
                missing, extra = sorted(want - have), sorted(have - want)
                status = "ok" if not (missing or extra) else "MISMATCH"
                ok &= status == "ok"
                print(
                    f"{checker:8s} {f.name:12s} {status}  expected {len(want)}, got {len(have)}"
                    + (f"  missing {missing}" if missing else "")
                    + (f"  unexpected {extra}" if extra else "")
                )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
