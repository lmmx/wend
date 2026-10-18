"""A/B timing of local glob for the fs-backends entry.

    python 2026-10-18-local-glob-ab.py SRC TREE [REPEATS]

SRC is a directory holding a ``wend`` package (a checkout's ``src``, or a
copy of it from another commit); TREE is where the 30,060-file tree is
built on the first run. Run it alternately against two SRCs and compare the
minimum times, which are the least noisy statistic on a shared machine.
"""

import statistics
import sys
import time
from pathlib import Path


src, tree = sys.argv[1], Path(sys.argv[2])
repeats = int(sys.argv[3]) if len(sys.argv) > 3 else 7
sys.path.insert(0, src)

from wend import P, Param, Segment, SubPath, T  # noqa: E402


if not (tree / "done").exists():
    for split in ("train", "valid", "test"):
        for year in range(2020, 2025):
            for month in range(1, 13):
                d = tree / "data" / split / str(year) / f"{month:02d}"
                d.mkdir(parents=True, exist_ok=True)
                for i in range(167):
                    (d / f"part-{i:04d}.parquet").touch()
    (tree / "done").touch()

split, year, month, i = (
    Segment("split"),
    Param("year", type=int),
    Param("month", type=int),
    Param("i", type=int),
)
leaf = T(t"part-{i:04d}.parquet")
segments = P(tree) / "data" / split / T(t"{year:d}") / T(t"{month:02d}") / leaf
cases = {
    "segments": (segments, {}),
    "segments kind=file": (segments, {"kind": "file"}),
    "subpath": (P(tree) / "data" / SubPath("rel") / leaf, {}),
    "literal prefix": (
        P(tree) / "data" / "train" / "2021" / T(t"{month:02d}") / leaf,
        {},
    ),
}
for name, (e, opts) in cases.items():
    n = sum(1 for _ in e.glob(**opts))  # warm-up: compile, page cache
    ts = []
    for _ in range(repeats):
        t0 = time.perf_counter()
        for _ in e.glob(**opts):
            pass
        ts.append(time.perf_counter() - t0)
    print(
        f"{name:20s} n={n:6d} min={min(ts) * 1e3:8.1f} ms"
        f" median={statistics.median(ts) * 1e3:8.1f} ms"
    )
