"""Inference, match and glob round trips on real and synthetic trees.

Run from the repository root:

    uv run python docs/journal/scripts/2026-10-17-messy-trees.py [DIR ...]

With no arguments it builds the synthetic layouts below in temporary
directories. For each tree it reports: paths and layouts, paths no layout
matches, observed paths that glob does not find again through their own
layout, layouts whose `optional` flag disagrees with a brute-force check, and
duplicate patterns.
"""

import os
import random
import sys
import tempfile
import time
import uuid
from collections import Counter
from pathlib import Path, PurePosixPath

from wend.infer import _observe, infer


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
    missed = wrong_opt = 0
    for lay in schema.layouts:
        mine = [
            p for p, d in pairs if d == (lay.kind == "dir") and lay.match(p) is not None
        ]
        found = {m.path for m in lay.under(root).glob()}
        missed += sum(os.path.join(root, p) not in found for p in mine)
        e, k = lay.expr, len(lay.expr.parts)
        truth = any(
            not any(m.startswith(d + "/") for m in mine)
            for j in range(1, k)
            for d in dirs
            if d.count("/") + 1 == j and e.parents[k - 1 - j].match(d) is not None
        )
        wrong_opt += truth != lay.optional
    dups = sum(
        v - 1
        for v in Counter(
            (lay.expr.pattern, lay.kind) for lay in schema.layouts
        ).values()
    )
    print(
        f"{root}: {len(pairs)} paths, {len(schema.layouts)} layouts, {ms:.0f} ms; "
        f"uncovered={len(uncovered)} glob-missed={missed} optional-wrong={wrong_opt} duplicates={dups}"
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
    return {
        "hive": hive,
        "ml-runs": runs,
        "photos": photos,
        "imagenet": imagenet,
        "fastq": fastq,
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
