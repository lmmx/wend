"""Infer a directory tree's layout, then use it to validate and query.

The inferred layouts are ordinary expressions: they can be renamed, matched,
globbed, and used to check that new files fit the existing structure.
"""

import tempfile
from pathlib import Path

from wend.infer import infer


files = [
    f"data/{split}/part-{i:03d}.parquet"
    for split in ("train", "valid")
    for i in range(5)
]
files += [f"checkpoints/run_{r}/epoch_{e:02d}.pt" for r in (1, 2) for e in range(1, 4)]
files += ["checkpoints/run_2/notes.txt", "README.md"]

with tempfile.TemporaryDirectory() as tmp:
    for f in files:
        Path(tmp, f).parent.mkdir(parents=True, exist_ok=True)
        Path(tmp, f).touch()

    schema = infer(tmp)
    print(schema)

    shards = next(lay for lay in schema.layouts if "part" in lay.expr.pattern).rename(
        data="split"
    )
    print("\nshard layout:", shards.expr.pattern, shards.fields)

    # Validate incoming files against the inferred structure.
    incoming = [
        "data/test/part-000.parquet",
        "data/train/part_7.parquet",
        "checkpoints/run_3/epoch_01.pt",
    ]
    print("\nunexpected:", schema.check(incoming))

    # Query the tree through the layout, with typed bindings.
    late = [m["part"] for m in shards.under(tmp).glob(split="valid") if m["part"] >= 3]
    print("valid parts >= 3:", late)
