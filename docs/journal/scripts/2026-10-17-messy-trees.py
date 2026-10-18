"""Inference, match and glob round trips on real and synthetic trees.

Run from the repository root:

    uv run python docs/journal/scripts/2026-10-17-messy-trees.py [DIR ...]

With no arguments it builds the synthetic layouts below in temporary
directories. For each tree it reports: paths and layouts, paths no layout
matches, observed paths that glob does not find again through their own
layout, layouts whose `optional` flag or `cardinality` disagrees with a
brute-force check, duplicate patterns, and how many layouts have a SubPath.
"""

import os
import random
import sys
import tempfile
import time
import uuid
from collections import Counter
from pathlib import Path, PurePosixPath

from wend._expr import REL, PathExpr, Splice
from wend.infer import Cardinality, _observe, infer


def check(root):
    t0 = time.perf_counter()
    schema = infer(root)
    ms = 1e3 * (time.perf_counter() - t0)
    pairs = _observe(root, False)
    dirs = {p for p, d in pairs if d}
    for p, _ in pairs:
        parts = PurePosixPath(p).parts
        dirs.update("/".join(parts[:i]) for i in range(1, len(parts)))
    uncovered = [p for p, _ in pairs if not schema.match(p)]
    missed = wrong_opt = wrong_card = 0
    for lay in schema.layouts:
        mine = [
            p for p, d in pairs if d == (lay.kind == "dir") and lay.match(p) is not None
        ]
        found = {m.path for m in lay.under(root).glob()}
        missed += sum(os.path.join(root, p) not in found for p in mine)
        # A prefix ending in a SubPath matches directories at any depth.
        e, k = lay.expr, len(lay.expr.parts)
        optional = any(
            not any(m.startswith(d + "/") for m in mine)
            for j in range(1, k)
            for d in dirs
            if PathExpr(REL, e.parts[:j]).match(d) is not None
        )
        many = any(c > 1 for c in Counter(m.rpartition("/")[0] for m in mine).values())
        wrong_opt += optional != lay.optional
        card = {
            (False, False): Cardinality.ONE,
            (True, False): Cardinality.OPTIONAL,
            (False, True): Cardinality.AT_LEAST_ONE,
            (True, True): Cardinality.MANY,
        }[optional, many]
        wrong_card += card != lay.cardinality
    dups = sum(
        v - 1
        for v in Counter(
            (lay.expr.pattern, lay.kind) for lay in schema.layouts
        ).values()
    )
    deep = sum(
        any(isinstance(p, Splice) for p in lay.expr.parts) for lay in schema.layouts
    )
    print(
        f"{root}: {len(pairs)} paths, {len(schema.layouts)} layouts ({deep} SubPath), "
        f"{ms:.0f} ms; uncovered={len(uncovered)} glob-missed={missed} "
        f"optional-wrong={wrong_opt} cardinality-wrong={wrong_card} duplicates={dups}"
    )
    return schema


def synthetic():
    rnd = random.Random(7)
    hive = [
        f"warehouse/events/year={y}/month={m:02d}/day={d:02d}/"
        f"part-{k:05d}-{uuid.UUID(int=rnd.getrandbits(128))}-c000.snappy.parquet"
        for y in (2023, 2024)
        for m in (1, 2, 11, 12)
        for d in (1, 15, 28)
        for k in range(rnd.randint(1, 3))
    ]
    runs = [f"runs/r{r}/config.yaml" for r in range(6)]
    runs += [
        f"runs/r{r}/checkpoints/epoch_{e:03d}.pt"
        for r in range(6)
        if r != 2
        for e in range(1, 8)
    ]
    runs += ["runs/r4/checkpoints/epoch_7.pt", "runs/r4/checkpoints/best.pt"]
    photos = [
        f"photos/{d[:4]}/{d}/IMG_{n:04d}.{ext}"
        for d in ["2023-01-05", "2023-02-14", "2024-07-04"]
        for n in rnd.sample(range(1, 9999), 5)
        for ext in ("JPG", "xmp")
    ]
    imagenet = [
        f"train/{s}/{s}_{i}.JPEG"
        for s in ["n01440764", "n01443537", "n01484850"]
        for i in (9, 10026, 10027)
    ]
    fastq = [
        f"fastq/S{s}/S{s}_L{lane:03d}_R{r}_001.fastq.gz"
        for s in (1, 2, 10)
        for lane in (1, 2)
        for r in (1, 2)
    ]
    # Letter directories, each with its own name families and one-off names.
    terminfo = []
    for letter in "abcdefghijklmnopqrstuvwxyz0123456789":
        for family in range(rnd.randint(0, 3)):
            stem = letter + "".join(rnd.choices("aeiouxyzrst", k=rnd.randint(1, 4)))
            stem += "-" if family % 2 else ""
            for n in rnd.sample(range(1, 600), rnd.randint(2, 9)):
                terminfo.append(f"terminfo/{letter}/{stem}{n}")
        for _ in range(rnd.randint(1, 6)):
            name = letter + "".join(rnd.choices("abcdefghmnopqrstuvwxyz+-", k=6))
            terminfo.append(f"terminfo/{letter}/{name}")
    # A nested package, with caches and a data directory.
    package = ["pyproject.toml", "README.md"]

    def grow(at, depth):
        modules = ["__init__", *rnd.sample(["core", "io", "util", "api", "cli"], 3)]
        for m in modules:
            package.append(f"{at}/{m}.py")
            package.append(f"{at}/__pycache__/{m}.cpython-314.pyc")
        if depth < 3:
            for sub in rnd.sample(["plugins", "formats", "backends", "tools"], 2):
                grow(f"{at}/{sub}", depth + 1)

    grow("src/pkg", 0)
    package += ["src/pkg/data/schema.json", "src/pkg/data/defaults.toml"]
    return {
        "hive": hive,
        "ml-runs": runs,
        "photos": photos,
        "imagenet": imagenet,
        "fastq": fastq,
        "terminfo": terminfo,
        "package": package,
    }


if __name__ == "__main__":
    if sys.argv[1:]:
        for root in sys.argv[1:]:
            check(root)
    else:
        for name, files in synthetic().items():
            tmp = tempfile.mkdtemp(prefix=f"{name}-")
            for f in files:
                Path(tmp, f).parent.mkdir(parents=True, exist_ok=True)
                Path(tmp, f).touch()
            print(check(tmp))
