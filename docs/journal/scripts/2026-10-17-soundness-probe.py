"""Differential probe: wend's construction-time rewrites vs wend's own un-rewritten nodes and eager pathlib.

The "unrewritten" column builds the same node tree with the dataclass constructors directly,
bypassing the `.create` rewrites, so each node resolves through its own `_resolve`.

Run with: uv run python docs/journal/scripts/2026-10-17-soundness-probe.py
"""

from pathlib import Path

from wend import (
    JoinExpr,
    LiteralExpr,
    P,
    Param,
    ParamExpr,
    ParentExpr,
    T,
    TemplateExpr,
    WithSuffixExpr,
)


root, ds, idx = Param("root"), Param("ds"), Param("idx")
R = ParamExpr(root)

CASES = [
    # (label, wend expression, un-rewritten node or None, bindings, eager pathlib result)
    (
        "(root / 'a/b').parent",
        (root / "a/b").parent,
        ParentExpr(JoinExpr(R, LiteralExpr("a/b"))),
        {"root": "/x"},
        (Path("/x") / "a/b").parent,
    ),
    (
        "(root / ds).parent, ds='train/v2'",
        (root / ds).parent,
        ParentExpr(JoinExpr(R, ParamExpr(ds))),
        {"root": "/x", "ds": "train/v2"},
        (Path("/x") / "train/v2").parent,
    ),
    (
        "(root / T'{ds}/c_{idx}').parent",
        (root / T(t"{ds}/c_{idx}")).parent,
        ParentExpr(JoinExpr(R, TemplateExpr(t"{ds}/c_{idx}"))),
        {"root": "/x", "ds": "tr", "idx": 1},
        (Path("/x") / "tr/c_1").parent,
    ),
    (
        "(root / '.').parent",
        (root / ".").parent,
        ParentExpr(JoinExpr(R, LiteralExpr("."))),
        {"root": "/x"},
        (Path("/x") / ".").parent,
    ),
    (
        "(root / '/abs/f').parent",
        (root / "/abs/f").parent,
        ParentExpr(JoinExpr(R, LiteralExpr("/abs/f"))),
        {"root": "/x"},
        (Path("/x") / "/abs/f").parent,
    ),
    (
        "a.tar.gz .with_suffix('').with_suffix('.json')",
        (root / "a.tar.gz").with_suffix("").with_suffix(".json"),
        WithSuffixExpr(
            WithSuffixExpr(JoinExpr(R, LiteralExpr("a.tar.gz")), ""), ".json"
        ),
        {"root": "/x"},
        Path("/x/a.tar.gz").with_suffix("").with_suffix(".json"),
    ),
    (
        "a.txt .with_suffix('.tar.gz').with_suffix('.json')",
        (root / "a.txt").with_suffix(".tar.gz").with_suffix(".json"),
        WithSuffixExpr(
            WithSuffixExpr(JoinExpr(R, LiteralExpr("a.txt")), ".tar.gz"), ".json"
        ),
        {"root": "/x"},
        Path("/x/a.txt").with_suffix(".tar.gz").with_suffix(".json"),
    ),
    # Not a rewrite: the interpolation's conversion field is ignored at resolve time
    ("T'f_{ds!r}' (conversion)", T(t"f_{ds!r}"), None, {"ds": "a"}, Path(f"f_{'a'!r}")),
    # Controls: rewrites that hold
    (
        "(root / 'f.txt').with_suffix('.json').parent",
        (root / "f.txt").with_suffix(".json").parent,
        ParentExpr(WithSuffixExpr(JoinExpr(R, LiteralExpr("f.txt")), ".json")),
        {"root": "/x"},
        Path("/x"),
    ),
    (
        "P('/home') / 'user' (literal fold)",
        P("/home") / "user",
        None,
        {},
        Path("/home/user"),
    ),
]

print(f"    {'case':52s} {'wend':16s} {'unrewritten':16s} pathlib")
for label, expr, raw, bindings, eager in CASES:
    got = expr.resolve(bindings)
    unrw = raw.resolve(bindings) if raw is not None else None
    flag = "OK " if got == eager and (unrw is None or got == unrw) else "BUG"
    print(
        f"{flag} {label:52s} {got!s:16s} {'-' if unrw is None else str(unrw):16s} {eager}"
    )

print("required_params of (root / ds).parent:", (root / ds).parent.required_params())
