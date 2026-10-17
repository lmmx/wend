"""Benchmarks across workloads, with baselines.

Run with: uv run python bench/bench.py [--quick]

Every timing is the median of R repeats (min and max shown), each repeat timing
a loop of N calls; values are nanoseconds per item. Absolute numbers are
machine-specific: compare rows within one run. The environment is printed
first.
"""

from __future__ import annotations

import os
import platform
import re
import statistics
import sys
import tempfile
import timeit
from pathlib import Path

from wend import P, Param, Segment, SubPath, T


QUICK = "--quick" in sys.argv
R = 3 if QUICK else 7


def env_line() -> str:
    cpu = platform.processor() or "unknown"
    if os.path.exists("/proc/cpuinfo"):
        for ln in open("/proc/cpuinfo"):
            if ln.startswith("model name"):
                cpu = ln.split(":", 1)[1].strip()
                break
    try:
        import polars as pl

        plv = pl.__version__
    except ImportError:
        plv = "absent"
    return (
        f"Python {sys.version.split()[0]} | polars {plv} | {platform.platform()} | "
        f"{cpu} | {os.cpu_count()} CPUs"
    )


def bench(fn, number: int) -> tuple[float, float, float]:
    ts = [t / number * 1e9 for t in timeit.repeat(fn, number=number, repeat=R)]
    return statistics.median(ts), min(ts), max(ts)


def table(title: str, rows: list[tuple[str, tuple[float, float, float]]]) -> None:
    print(f"\n### {title}\n")
    print("| case | median ns/item | min | max |")
    print("|---|---:|---:|---:|")
    for name, (med, lo, hi) in rows:
        print(f"| {name} | {med:,.0f} | {lo:,.0f} | {hi:,.0f} |")


root, split = Param("root"), Segment("split")
idx, total = Param("idx", type=int), Param("total", type=int)
shard = root / "data" / split / T(t"chunk_{idx:04d}-of-{total:04d}.parquet")
B = {"root": "/mnt/storage", "split": "train", "idx": 7, "total": 100}
OUT = "/mnt/storage/data/train/chunk_0007-of-0100.parquet"
compiled = shard.compile()
assert compiled.render(B) == shard.render(B) == OUT


def single() -> None:
    n = 2_000 if QUICK else 20_000
    rows = [
        ("wend render (interpreter)", bench(lambda: shard.render(B), n)),
        ("wend resolve -> Path (interpreter)", bench(lambda: shard.resolve(B), n)),
        ("wend compiled render -> str", bench(lambda: compiled.render(B), n)),
        ("wend compiled call -> Path", bench(lambda: compiled(B), n)),
        (
            "baseline: eager pathlib joins",
            bench(
                lambda: (
                    Path(B["root"])
                    / "data"
                    / B["split"]
                    / f"chunk_{B['idx']:04d}-of-{B['total']:04d}.parquet"
                ),
                n,
            ),
        ),
        (
            "baseline: f-string -> str (no validation)",
            bench(
                lambda: (
                    f"{B['root']}/data/{B['split']}/chunk_{B['idx']:04d}-of-{B['total']:04d}.parquet"
                ),
                n,
            ),
        ),
        (
            "baseline: os.path.join (no validation)",
            bench(
                lambda: os.path.join(
                    B["root"],
                    "data",
                    B["split"],
                    f"chunk_{B['idx']:04d}-of-{B['total']:04d}.parquet",
                ),
                n,
            ),
        ),
    ]
    table("Single resolution (README shard expression)", rows)


def batch() -> None:
    n = 10_000 if QUICK else 100_000
    data = [
        {"root": "/mnt/storage", "split": "train", "idx": i, "total": n}
        for i in range(n)
    ]
    rows = [
        (
            "wend compiled.many(rows) -> list[str]",
            bench(lambda: compiled.many(data), 1),
        ),
        (
            "baseline: list comprehension f-string",
            bench(
                lambda: [
                    f"{r['root']}/data/{r['split']}/chunk_{r['idx']:04d}-of-{r['total']:04d}.parquet"
                    for r in data
                ],
                1,
            ),
        ),
    ]
    try:
        import polars as pl

        from wend.frame import resolve_frame, to_polars

        df = pl.DataFrame(data)
        assert resolve_frame(shard, df).to_list()[:3] == compiled.many(data[:3])
        lowered = to_polars(shard, df.schema)
        rows.append(
            (
                "wend.frame.resolve_frame (validated)",
                bench(lambda: resolve_frame(shard, df), 1),
            )
        )
        rows.append(
            (
                "wend.frame to_polars select (no validation)",
                bench(lambda: df.select(lowered), 1),
            )
        )
    except ImportError:
        pass
    rows = [(name, tuple(x / n for x in t)) for name, t in rows]  # type: ignore[misc]
    table(f"Batch resolution ({n:,} rows; per row)", rows)


def matching() -> None:
    n = 2_000 if QUICK else 10_000
    rx = re.compile(
        r"(?P<root>.*)/data/(?P<split>[^/]+)/chunk_(?P<idx>\d{4})-of-(?P<total>\d{4})\.parquet"
    )

    def regex_baseline():
        m = rx.fullmatch(OUT)
        d = m.groupdict()
        return d["root"], d["split"], int(d["idx"]), int(d["total"])

    bound = shard.bind(root="/mnt/storage")
    rows = [
        ("wend match (head unbound)", bench(lambda: shard.match(OUT), n)),
        ("wend match (root bound)", bench(lambda: bound.match(OUT), n)),
        (
            "baseline: hand-written regex + int() (no round-trip check)",
            bench(regex_baseline, n),
        ),
    ]
    table("Matching one path to typed bindings", rows)


def discovery() -> None:
    dirs, files = (5, 200) if QUICK else (20, 500)
    with tempfile.TemporaryDirectory() as tmp:
        for d in range(dirs):
            p = Path(tmp, "data", f"split{d}")
            p.mkdir(parents=True)
            for i in range(files):
                (p / f"chunk_{i:04d}-of-{files:04d}.parquet").touch()
            (p / "README.md").touch()
        total_files = dirs * files
        rx = re.compile(r"chunk_(\d{4})-of-(\d{4})\.parquet")

        def pathlib_glob():
            out = []
            for f in Path(tmp, "data").glob("*/chunk_*-of-*.parquet"):
                m = rx.fullmatch(f.name)
                if m:
                    out.append((f.parent.name, int(m[1]), int(m[2])))
            return out

        def os_walk():
            out = []
            for dp, _, fs in os.walk(os.path.join(tmp, "data")):
                for f in fs:
                    m = rx.fullmatch(f)
                    if m:
                        out.append((os.path.basename(dp), int(m[1]), int(m[2])))
            return out

        def wend_glob():
            return list(shard.glob(root=tmp))

        assert len(wend_glob()) == len(pathlib_glob()) == total_files
        rows = [
            ("wend glob (typed, verified)", bench(wend_glob, 1)),
            ("baseline: Path.glob + regex", bench(pathlib_glob, 1)),
            ("baseline: os.walk + regex", bench(os_walk, 1)),
        ]
        rows = [(name, tuple(x / total_files for x in t)) for name, t in rows]  # type: ignore[misc]
        table(f"Filesystem discovery ({total_files:,} matching files; per file)", rows)


def symbolic() -> None:
    n = 2_000 if QUICK else 10_000
    rows = [
        (
            "construct shard expression",
            bench(
                lambda: (
                    root / "data" / split / T(t"chunk_{idx:04d}-of-{total:04d}.parquet")
                ),
                n,
            ),
        ),
        (
            "bind(root=..., total=...)",
            bench(lambda: shard.bind(root="/mnt", total=100), n),
        ),
        (
            "parent / suffix / with_suffix",
            bench(lambda: (shard.parent, shard.suffix, shard.with_suffix(".json")), n),
        ),
        (
            "compile() (cached on the expression)",
            bench(lambda: shard.compile(), n // 10),
        ),
        (
            "construct + render nested SubPath",
            bench(lambda: (P("/srv") / SubPath("rel") / "x").render(rel="a/b"), n),
        ),
    ]
    table("Symbolic operations", rows)


if __name__ == "__main__":
    print(env_line())
    single()
    batch()
    matching()
    discovery()
    symbolic()
