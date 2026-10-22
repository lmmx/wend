"""A day-partitioned pipeline analysed before any binding exists, then run
for two days in a temporary directory (docs/journal/2026-10-22-symbolic-families.md).

    uv run python docs/journal/scripts/2026-10-22-families-demo.py
"""

import tempfile
from pathlib import Path

from wend import (
    Absent,
    Creatable,
    Dir,
    Exists,
    File,
    Listable,
    P,
    Param,
    Readable,
    Step,
    T,
)
from wend._experimental.families import analyse_families, independent, snapshots
from wend._experimental.knowledge import Tracker
from wend.errors import ConditionError


root, day = Param("root"), Param("day")


def reads(e):
    return e.requires(File, Exists, Readable)


def makes(e):
    return e.requires(Absent, Creatable).ensures(File, Exists)


inbox = P(root) / "inbox" / T(t"{day}.csv")
raw = P(root) / "raw" / T(t"{day}.csv")
features = P(root) / "features" / T(t"{day}.parquet")
report = P(root) / "reports" / T(t"{day}.md")

steps = [
    ("survey", Step(root=P(root).requires(Dir, Exists, Listable))),
    ("ingest", Step(src=reads(inbox), dst=makes(raw))),
    ("validate", Step(src=reads(raw))),
    ("featurise", Step(src=reads(raw), dst=makes(features))),
    ("train", Step(all=(P(root) / "features").requires(Dir, Exists, Listable))),
    ("report", Step(src=reads(features), dst=makes(report))),
    ("cleanup", Step(raw=raw.requires(Exists).ensures(Absent))),
    ("audit", Step(src=reads(raw))),
]

print("Before any binding:")
for e in analyse_families(steps):
    flags = []
    if e.known:
        flags.append(f"known {sorted(e.known)}")
    if e.refuted:
        flags.append(f"REFUTED {sorted(e.refuted)}: fails for every binding")
    if e.possibly_refuted:
        flags.append(f"may fail {sorted(e.possibly_refuted)}")
    print(f"  {e.step:9s} {e.port:4s} {e.expr.pattern:28s} {'; '.join(flags) or '-'}")
ks = snapshots(steps)
print("Adjacent steps that commute:")
for i in range(len(steps) - 1):
    if independent(steps[i][1], steps[i + 1][1], ks[i]):
        print(f"  {steps[i][0]} | {steps[i + 1][0]}")

for d in ("mon", "tue"):
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "inbox").mkdir()
        (Path(tmp) / "inbox" / f"{d}.csv").write_text("x")
        t = Tracker(elide=True)
        outcome = []
        for name, step in steps:
            try:
                with t.run(name, step, {"root": tmp, "day": d}) as p:
                    for port, path in p.items():
                        e = step.paths[port]
                        if "create" in e.declares.verbs:
                            path.parent.mkdir(parents=True, exist_ok=True)
                            path.write_text("y")
                        elif "delete" in e.declares.verbs:
                            path.unlink()
                outcome.append(f"{name} ok")
            except ConditionError as x:
                outcome.append(f"{name} FAILED ({type(x).__name__})")
                break
        elided = sum(len(x.known) for x in t.entries)
        print(f"day={d}: {', '.join(outcome)}; checks elided: {elided}")
