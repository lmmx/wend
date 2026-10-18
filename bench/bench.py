"""Benchmarks across workloads, with baselines.

Run with: uv run python bench/bench.py [--quick] [workload ...]

Workloads: single, batch, matching, shapes, discovery, inference, symbolic
(all by default).

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
        # A root column that render normalises ("/mnt/./storage/" -> "/mnt/storage").
        messy = df.with_columns(root=pl.Series(["/mnt/./storage/"] * n))
        assert resolve_frame(shard, messy).to_list()[:3] == compiled.many(data[:3])
        rows.append(
            (
                "wend.frame.resolve_frame (validated)",
                bench(lambda: resolve_frame(shard, df), 1),
            )
        )
        rows.append(
            (
                "wend.frame.resolve_frame (non-canonical root column)",
                bench(lambda: resolve_frame(shard, messy), 1),
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
            "wend match_all(fast=False) (full search, head unbound)",
            bench(lambda: shard.match_all(OUT, fast=False), n),
        ),
        (
            "baseline: hand-written regex + int() (no round-trip check)",
            bench(regex_baseline, n),
        ),
    ]
    table("Matching one path to typed bindings", rows)


def shapes() -> None:
    """Matching layouts beyond the README shard: SubPath, other int bases,
    choices, and a string field before other fields."""
    n = 2_000 if QUICK else 10_000
    rel, stem = SubPath("rel"), Param("stem")
    kind = Param("kind", choices={"img", "txt", "bin"})
    model, epoch = Param("model"), Param("epoch", type=int)
    cases = [
        (
            "SubPath, fixed tail (root bound)",
            (root / "data" / rel / "x" / T(t"chunk_{idx:04d}.bin")).bind(
                root="/mnt/storage"
            ),
            "/mnt/storage/data/a/b/c/x/chunk_0007.bin",
        ),
        (
            "SubPath then a file (root bound)",
            (root / rel / T(t"{stem}.py")).bind(root="/src"),
            "/src/pkg/sub/mod.py",
        ),
        (
            "choices + hex",
            P("/objs") / split / T(t"{kind}_{idx:04x}.bin"),
            "/objs/train/img_00ff.bin",
        ),
        (
            "string before a padded int",
            P("/ckpt") / T(t"{model}_epoch{epoch:03d}.pt"),
            "/ckpt/resnet_50_epoch007.pt",
        ),
    ]
    rows = []
    for name, e, path in cases:
        assert e.match(path) is not None, name
        rows.append((f"wend match: {name}", bench(lambda e=e, p=path: e.match(p), n)))
        rows.append(
            (
                f"wend match_all(fast=False): {name}",
                bench(lambda e=e, p=path: e.match_all(p, fast=False), n),
            )
        )
    rx = re.compile(r"/mnt/storage/data/(?:(.+)/)?x/chunk_(\d{4})\.bin")

    def regex_baseline():
        m = rx.fullmatch(cases[0][2])
        return m[1] or ".", int(m[2])

    rows.append(
        (
            "baseline: hand-written regex, SubPath case (no round-trip check)",
            bench(regex_baseline, n),
        )
    )
    table("Matching other layouts", rows)


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


def inference() -> None:
    from wend.infer import infer

    n = 2_000 if QUICK else 20_000
    paths = [f"data/split{i % 20}/chunk_{i:05d}-of-{n:05d}.parquet" for i in range(n)]
    paths += [f"logs/2026-01-{d:02d}.log" for d in range(1, 29)] + [
        "README.md",
        "pyproject.toml",
    ]
    schema = infer(paths)
    assert schema.check(paths[:50]) == []
    rows = [("infer (paths given as strings)", bench(lambda: infer(paths), 1))]
    rows = [(name, tuple(x / len(paths) for x in t)) for name, t in rows]  # type: ignore[misc]
    table(
        f"Layout inference ({len(paths):,} paths -> {len(schema.layouts)} layouts; per path)",
        rows,
    )


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


WORKLOADS = {
    "single": single,
    "batch": batch,
    "matching": matching,
    "shapes": shapes,
    "discovery": discovery,
    "inference": inference,
    "symbolic": symbolic,
}

if __name__ == "__main__":
    chosen = [a for a in sys.argv[1:] if not a.startswith("--")] or list(WORKLOADS)
    unknown = sorted(set(chosen) - WORKLOADS.keys())
    if unknown:
        sys.exit(f"unknown workloads {unknown}; choose from {list(WORKLOADS)}")
    print(env_line())
    for name in chosen:
        WORKLOADS[name]()
