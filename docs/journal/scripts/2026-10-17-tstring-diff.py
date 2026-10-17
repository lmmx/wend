"""Differential probe: a template formatted as an f-string, then PurePosixPath,
against wend's render. Prints every pair that differs.

    uv run python docs/journal/scripts/2026-10-17-tstring-diff.py
"""

from pathlib import Path, PurePosixPath
from string.templatelib import convert

from wend import Param, T, WendError
from wend._params import MARKER_RE, lookup_marker


def native(tmpl, env):
    out = []
    for item in tmpl:
        if isinstance(item, str):
            out.append(item)
            continue
        v = item.value
        if isinstance(v, Param):
            v = env[v.name]
        spec = MARKER_RE.sub(
            lambda m: format(env[lookup_marker(m.group(1)).name], ""), item.format_spec
        )
        out.append(format(convert(v, item.conversion), spec))
    return "".join(out)


x, y, root, w = Param("x"), Param("y"), Param("root"), Param("w")
CASES = [
    (
        t"{root}/data",
        [
            {"root": v}
            for v in ["/a", "a/b", "", "/a/", Path("/p"), ".", "..", "a/../b", 3]
        ],
    ),
    (
        t"data/{x}",
        [
            {"x": v}
            for v in [
                "a",
                "",
                "a/b",
                ".",
                "..",
                "/abs",
                3,
                None,
                Path("q"),
                "a b",
                b"q",
            ]
        ],
    ),
    (t"data/{x}.csv", [{"x": v} for v in ["a", "", "a/b", ".", "..", "a.b", 3]]),
    (t"data/{x!r}", [{"x": v} for v in ["a", "it's"]]),
    (t"data/{x!a}", [{"x": "é"}]),
    (t"data/{x:>5}", [{"x": v} for v in ["ab", "", "abcdef"]]),
    (t"data/{x:.0}", [{"x": "abc"}]),
    (t"data/{x:d}", [{"x": v} for v in [7, -1, True]]),
    (t"data/{x:03d}.bin", [{"x": v} for v in [7, -1, 1000, True]]),
    (t"data/{x:.2f}", [{"x": v} for v in [1.5, float("nan")]]),
    (t"data/{x=}", [{"x": "a"}]),
    (t"data/{x:{w}}", [{"x": "ab", "w": 4}]),
    (
        t"{x}{y}",
        [
            {"x": a, "y": b}
            for a, b in [("a", "b"), ("", "b"), ("/a", "b"), ("a/", "b")]
        ],
    ),
    (t"{root}{x}", [{"root": a, "x": b} for a, b in [("/a", "b"), ("/a/", "b")]]),
    (t"data//{x}", [{"x": "a"}]),
    (t"./data/{x}", [{"x": "a"}]),
    (t"data/{x}/", [{"x": "a"}]),
]

same = total = 0
for tmpl, envs in CASES:
    e = T(tmpl)
    for env in envs:
        total += 1
        try:
            n = native(tmpl, env)
            ref = str(PurePosixPath(n)) if n else "<empty>"
        except Exception as ex:  # noqa: BLE001
            ref = f"<{type(ex).__name__}>"
        try:
            got = e.render(env)
        except WendError as ex:
            got = f"<{type(ex).__name__}>"
        if ref == got:
            same += 1
        else:
            print(f"{e.pattern:20} {env!r:32} f-string={ref:20} wend={got}")
print(f"{same} of {total} agree")
