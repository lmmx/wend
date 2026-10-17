"""Sharded datasets: generate expected shard paths, find what exists, report gaps.

One expression is the single source of truth for the layout. It renders the
manifest, discovers the files on disk with typed bindings, and maps each
shard to its metadata sidecar.
"""

import tempfile
from pathlib import Path

from wend import Lens, Param, Segment, T


root = Param("root")
dataset, split = Segment("dataset"), Segment("split", choices={"train", "test"})
idx, total = Param("idx", type=int), Param("total", type=int)

shard = root / dataset / split / T(t"shard-{idx:05d}-of-{total:05d}.parquet")
sidecar = Lens(shard, shard.with_suffix(".json"))

with tempfile.TemporaryDirectory() as tmp:
    # The writer: render every expected path for one dataset in one call.
    layout = shard.bind(root=tmp, dataset="tiny", total=4)
    expected = {
        (s, i): p
        for s in ("train", "test")
        for i, p in enumerate(layout.compile().columns(split=[s] * 4, idx=range(4)))
    }
    print(
        f"{len(expected)} shards expected, e.g. {Path(expected['train', 0]).relative_to(tmp)}"
    )

    # Simulate a partial write, plus a stray file that does not fit the layout.
    for key in [("train", 0), ("train", 1), ("train", 3), ("test", 0)]:
        Path(expected[key]).parent.mkdir(parents=True, exist_ok=True)
        Path(expected[key]).touch()
    Path(tmp, "tiny", "train", "shard-2.parquet").touch()

    # The reader: discover what exists, with typed bindings, no regexes.
    found = {(m["split"], m["idx"]): m for m in layout.glob()}
    missing = sorted(set(expected) - set(found))
    print("found:", sorted(found))
    print("missing:", missing)

    # Every shard has a sidecar path derived from the same layout.
    m = found["train", 1]
    print("sidecar:", sidecar(m.path).relative_to(tmp))

    # Values that would break the layout are rejected, not silently joined.
    try:
        layout.render(split="../../etc", idx=0)
    except ValueError as e:
        print("rejected:", e)

    try:
        import polars as pl

        from wend.frame import resolve_frame

        frame = pl.DataFrame({"split": ["train"] * 3, "idx": [0, 1, 2]})
        print("polars:", [Path(p).name for p in resolve_frame(layout, frame)])
    except ImportError:
        pass
