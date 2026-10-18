"""Lineage: where a path came from, as a plan and as an artefact.

A raw upload is cleaned and summarised. The expressions remember how they
were derived and what they were tagged with; a ledger remembers which files
were made from which, so a changed input points at what to rebuild. A cache
named after its input's contents shows content addressing.
"""

import tempfile
from pathlib import Path

from wend import Absent, Creatable, Exists, File, P, Param, Readable, Step, T
from wend.lineage import Ledger, content_key, explain, tags


root, day = Param("root"), Param("day")

raw = (P(root) / "raw" / T(t"{day}.csv")).tag(source="upload")
clean = raw.with_suffix(".parquet").tag(stage="clean")
report = clean.cousin("../reports", T(t"{day}.md"))

# The plan's past: how the report path is derived, and the tags along the way.
print(explain(report))
print("tags:", tags(report))

clean_step = Step(
    raw=raw.requires(File, Exists, Readable),
    clean=clean.requires(Absent, Creatable).ensures(File, Exists),
)
report_step = Step(
    clean=clean.requires(File, Exists, Readable),
    report=report.requires(Absent, Creatable).ensures(File, Exists),
)

with tempfile.TemporaryDirectory() as tmp:
    base = Path(tmp)
    (base / "raw").mkdir()
    (base / "raw" / "mon.csv").write_text("id,value\n1,3\n2,4\n")
    ledger = Ledger(base / ".lineage.jsonl")

    # The artefacts' past: each step records what it made from what.
    with ledger.run(clean_step, root=base, day="mon") as p:
        p["clean"].write_text(p["raw"].read_text().upper())
    with ledger.run(report_step, root=base, day="mon") as p:
        p["report"].parent.mkdir(parents=True, exist_ok=True)
        p["report"].write_text(f"{len(p['clean'].read_text().splitlines()) - 1} rows\n")

    out = base / "reports" / "mon.md"
    print(
        "\nreport made from:",
        [Path(p).relative_to(base).as_posix() for p in ledger.upstream(out)],
    )
    print("provenance:", ledger.provenance(out).operation[:40] + "...")

    # The upload is corrected: what is out of date, and what depends on it?
    (base / "raw" / "mon.csv").write_text("id,value\n1,3\n2,5\n")
    print(
        "\nclean is stale because of:",
        [Path(p).name for p in ledger.stale(base / "raw" / "mon.parquet")],
    )
    print(
        "to rebuild:",
        [
            Path(p).relative_to(base).as_posix()
            for p in ledger.downstream(base / "raw" / "mon.csv")
        ],
    )

    # Content addressing: a cache named after what it was computed from.
    key = Param("key")
    cache = P(root) / "cache" / T(t"{key}") / "features.json"
    cached = cache.render(root=base, key=content_key(base / "raw" / "mon.csv"))
    print("\ncache path:", Path(cached).relative_to(base).as_posix())
    print(
        "still names its input:",
        cache.match(cached)["key"] == content_key(base / "raw" / "mon.csv"),
    )
