"""Per-resolve cost of wend vs alternative lowerings of the same path expression.

This measures the wend 0.1.1 release. Run with:

    uv run --no-project --python 3.14 --with wend==0.1.1 --with polars python docs/journal/scripts/2026-10-17-resolve-bench.py

(polars is optional; the batch row is skipped without it; bench/bench.py measures the rebuild)

Timings are the minimum over 5 repeats (3 for the batch rows) of one expression shape on one
machine; absolute values are machine-specific, compare rows within a run.
"""

import os
import platform
import sys
import timeit
from pathlib import Path

from wend import Param, T


root, ds, idx, total = Param("root"), Param("dataset"), Param("idx"), Param("total")
expr = root / "data" / ds / T(t"chunk_{idx:04d}-of-{total:04d}.parquet")
b = {"root": "/mnt/storage", "dataset": "train", "idx": 7, "total": 100}
expected = "/mnt/storage/data/train/chunk_0007-of-0100.parquet"
fmt = "{root}/data/{dataset}/chunk_{idx:04d}-of-{total:04d}.parquet"

# Hand-written equivalent of what an f-string code generator would emit
ns: dict = {"Path": Path}
exec(
    "def gen_path(root, dataset, idx, total):\n"
    "    return Path(f'{root}/data/{dataset}/chunk_{idx:04d}-of-{total:04d}.parquet')\n"
    "def gen_str(root, dataset, idx, total):\n"
    "    return f'{root}/data/{dataset}/chunk_{idx:04d}-of-{total:04d}.parquet'\n",
    ns,
)
gen_path, gen_str = ns["gen_path"], ns["gen_str"]

assert str(expr.resolve(b)) == str(gen_path(**b)) == gen_str(**b) == expected

N = 100_000
SINGLE = {
    "wend expr.resolve(b)": lambda: expr.resolve(b),
    "wend expr._resolve(b, {}) (skips required_params check)": lambda: expr._resolve(
        b, {}
    ),
    "wend expr.required_params() alone": lambda: expr.required_params(),
    "eager pathlib joins + f-string leaf": lambda: (
        Path(b["root"])
        / "data"
        / b["dataset"]
        / f"chunk_{b['idx']:04d}-of-{b['total']:04d}.parquet"
    ),
    "Path(fmt.format_map(b))": lambda: Path(fmt.format_map(b)),
    "codegen f-string -> Path": lambda: gen_path(**b),
    "codegen f-string -> str": lambda: gen_str(**b),
    "Path(s) alone (lazy: no parse yet)": lambda: Path(expected),
    "str(Path(s)) (construct + parse + render)": lambda: str(Path(expected)),
}
for label, fn in SINGLE.items():
    ns_per = min(timeit.repeat(fn, number=N, repeat=5)) / N * 1e9
    print(f"{ns_per:8.0f} ns  {label}")

rows = [dict(b, idx=i) for i in range(N)]
ns_per = (
    min(timeit.repeat(lambda: [gen_str(**r) for r in rows], number=1, repeat=3))
    / N
    * 1e9
)
print(f"{ns_per:8.0f} ns  batch per item: codegen f-string -> str")
try:
    import polars as pl

    df = pl.DataFrame(rows)

    def polars_batch() -> pl.DataFrame:
        return df.select(
            pl.format(
                "{}/data/{}/chunk_{}-of-{}.parquet",
                pl.col("root"),
                pl.col("dataset"),
                pl.col("idx").cast(pl.String).str.zfill(4),
                pl.col("total").cast(pl.String).str.zfill(4),
            ).alias("path")
        )

    assert polars_batch()["path"][7] == expected
    ns_per = min(timeit.repeat(polars_batch, number=1, repeat=5)) / N * 1e9
    print(
        f"{ns_per:8.1f} ns  batch per item: polars pl.format (polars {pl.__version__})"
    )
except ImportError:
    print("     n/a    batch per item: polars pl.format (polars not installed)")
print(sys.version)
cpu = (
    next(
        (
            ln.split(":", 1)[1].strip()
            for ln in open("/proc/cpuinfo")
            if ln.startswith("model name")
        ),
        platform.processor() or "unknown",
    )
    if os.path.exists("/proc/cpuinfo")
    else platform.processor() or "unknown"
)
print(f"{platform.platform()} | {cpu} | {os.cpu_count()} CPUs")
