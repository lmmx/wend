"""Differential probe: wend's construction-time rewrites vs eager pathlib.

Run with: uv run python docs/journal/scripts/2026-10-17-soundness-probe.py
"""

from pathlib import Path

from wend import P, Param, T


root, ds, idx = Param("root"), Param("ds"), Param("idx")

CASES = [
    # (label, wend expression, bindings, eager pathlib result)
    (
        "(root / 'a/b').parent",
        (root / "a/b").parent,
        {"root": "/x"},
        (Path("/x") / "a/b").parent,
    ),
    (
        "(root / ds).parent, ds='train/v2'",
        (root / ds).parent,
        {"root": "/x", "ds": "train/v2"},
        (Path("/x") / "train/v2").parent,
    ),
    (
        "(root / T'{ds}/c_{idx}').parent",
        (root / T(t"{ds}/c_{idx}")).parent,
        {"root": "/x", "ds": "tr", "idx": 1},
        (Path("/x") / "tr/c_1").parent,
    ),
    (
        "(root / '.').parent",
        (root / ".").parent,
        {"root": "/x"},
        (Path("/x") / ".").parent,
    ),
    (
        "(root / '/abs/f').parent",
        (root / "/abs/f").parent,
        {"root": "/x"},
        (Path("/x") / "/abs/f").parent,
    ),
    (
        "a.tar.gz .with_suffix('').with_suffix('.json')",
        (root / "a.tar.gz").with_suffix("").with_suffix(".json"),
        {"root": "/x"},
        Path("/x/a.tar.gz").with_suffix("").with_suffix(".json"),
    ),
    (
        "a.txt .with_suffix('.tar.gz').with_suffix('.json')",
        (root / "a.txt").with_suffix(".tar.gz").with_suffix(".json"),
        {"root": "/x"},
        Path("/x/a.txt").with_suffix(".tar.gz").with_suffix(".json"),
    ),
    ("T'f_{ds!r}' (conversion)", T(t"f_{ds!r}"), {"ds": "a"}, Path(f"f_{'a'!r}")),
    # Controls: rewrites that hold
    (
        "(root / 'f.txt').with_suffix('.json').parent",
        (root / "f.txt").with_suffix(".json").parent,
        {"root": "/x"},
        Path("/x"),
    ),
    ("P('/home') / 'user' (literal fold)", P("/home") / "user", {}, Path("/home/user")),
]

for label, expr, bindings, eager in CASES:
    got = expr.resolve(bindings)
    flag = "OK " if got == eager else "BUG"
    print(f"{flag} {label:52s} wend={got!s:20s} pathlib={eager}")

print("required_params of (root / ds).parent:", (root / ds).parent.required_params())
