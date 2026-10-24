"""Two pipelines analysed before any binding, then run confined to their root
with the known checks elided, and run again with another writer replacing a
stage directory by a link to a copy outside the root, with data of its own
(docs/journal/2026-10-22-confined-runs.md).

    uv run python docs/journal/scripts/2026-10-22-confined-demo.py
"""

import shutil
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
from wend._experimental.confined import Confined, Plain, run
from wend._experimental.families import analyse_families


root, day, table, date = Param("root"), Param("day"), Param("table"), Param("date")


def reads(e):
    return e.requires(File, Exists, Readable)


def makes(e):
    return e.requires(Absent, Creatable).ensures(File, Exists)


def lists(e):
    return e.requires(Dir, Exists, Listable)


def drops(e):
    return e.requires(Exists).ensures(Absent)


def day_pipeline():
    inbox = P(root) / "inbox" / T(t"{day}.csv")
    raw = P(root) / "raw" / T(t"{day}.csv")
    features = P(root) / "features" / T(t"{day}.parquet")
    report = P(root) / "reports" / T(t"{day}.md")
    return [
        ("survey", Step(root=lists(P(root)))),
        ("ingest", Step(src=reads(inbox), dst=makes(raw))),
        ("validate", Step(src=reads(raw))),
        ("featurise", Step(src=reads(raw), dst=makes(features))),
        ("train", Step(all=lists(P(root) / "features"))),
        ("report", Step(src=reads(features), dst=makes(report))),
        ("cleanup", Step(raw=drops(raw))),
    ]


def medallion_pipeline():
    bronze = P(root) / "bronze" / T(t"{table}") / T(t"{date}.json")
    silver = P(root) / "silver" / T(t"{table}") / T(t"{date}.parquet")
    gold = P(root) / "gold" / T(t"{table}.parquet")
    return [
        (
            "land",
            Step(
                src=reads(P(root) / "landing" / T(t"{table}-{date}.json")),
                dst=makes(bronze),
            ),
        ),
        ("refine", Step(src=reads(bronze), dst=makes(silver))),
        ("check", Step(src=reads(silver))),
        ("partitions", Step(all=lists(P(root) / "silver" / T(t"{table}")))),
        ("aggregate", Step(src=reads(silver), dst=makes(gold))),
        ("expire", Step(old=drops(bronze))),
    ]


READS: list[bytes] = []


def body(role):
    return {
        "read": lambda io, rel: READS.append(io.read_bytes(rel)),
        "make": lambda io, rel: io.create(rel, b"x"),
        "list": lambda io, rel: io.listdir(rel),
        "drop": lambda io, rel: io.delete(rel),
    }[role]


def bodies_of(steps):
    out = []
    for _, s in steps:
        b = []
        for port, e in s.paths.items():
            d = e.declares
            role = (
                "drop"
                if "absent" in d.ensures
                else "make"
                if "absent" in d.requires
                else "list"
                if "list" in d.requires
                else "read"
            )
            b.append((port, body(role)))
        out.append(b)
    return out


def show(title, steps):
    print(f"\n== {title}: before any binding")
    entries = analyse_families(steps)
    for e in entries:
        flags = []
        if e.known:
            flags.append(f"known {sorted(e.known)}")
        if e.refuted:
            flags.append(f"REFUTED {sorted(e.refuted)}")
        print(
            f"  {e.step:10s} {e.port:4s} {e.expr.pattern:36s} {'; '.join(flags) or '-'}"
        )
    plan = {(e.step, e.port): e.known for e in entries}
    total = sum(len(e.expr.declares.requires) for e in entries)
    print(
        f"  {sum(len(k) for k in plan.values())} of {total} required checks elided, for every binding"
    )
    return plan


def seed(r: Path, files):
    for f in files:
        (r / f).parent.mkdir(parents=True, exist_ok=True)
        (r / f).write_text("x")


def files_in(d: Path) -> dict[str, bytes]:
    return {str(p.relative_to(d)): p.read_bytes() for p in d.rglob("*") if p.is_file()}


def mirror_stage(r: Path, outside: Path, stage: str, at: int, planted: dict):
    """Before step ``at``: copy ``stage`` outside, with the writer's data in
    every file, and put a link to the copy in its place. ``planted`` gets
    what is outside once the writer is done."""

    def between(point, i):
        if (point, i) == ("step", at) and (r / stage).is_dir():
            shutil.copytree(r / stage, outside / stage)
            for f in (outside / stage).rglob("*"):
                if f.is_file():
                    f.write_bytes(b"EVIL")
            shutil.rmtree(r / stage)
            (r / stage).symlink_to(outside / stage)
            planted.update(files_in(outside))

    return between


for title, steps, envs, files, stage, at in (
    (
        "day pipeline",
        day_pipeline(),
        [{"day": d} for d in ("mon", "tue", "wed")],
        lambda env: [f"inbox/{env['day']}.csv"],
        "raw",
        2,
    ),
    (
        "medallion pipeline",
        medallion_pipeline(),
        [
            {"table": t, "date": d}
            for t in ("orders", "users")
            for d in ("2026-10-21", "2026-10-22")
        ],
        lambda env: [f"landing/{env['table']}-{env['date']}.json"],
        "silver",
        2,
    ),
):
    plan = show(title, steps)
    bodies = bodies_of(steps)
    for env0 in envs:
        with tempfile.TemporaryDirectory() as d:
            r = Path(d) / "root"
            r.mkdir()
            seed(r, files(env0))
            io = Confined(str(r))
            done = run(steps, bodies, {**env0, "root": str(r)}, io, elide=plan)
            io.close()
            print(f"  run {env0}: {sum(done)}/{len(done)} steps completed")
    env0 = envs[0]
    print(
        f"  {env0}, another writer linking {stage}/ to a copy outside before {steps[at][0]}:"
    )
    for kind in ("plain", "confined"):
        with tempfile.TemporaryDirectory() as d:
            r, outside = Path(d) / "root", Path(d) / "outside"
            r.mkdir()
            outside.mkdir()
            seed(r, files(env0))
            io = Confined(str(r)) if kind == "confined" else Plain(str(r))
            READS.clear()
            planted: dict = {}
            done = run(
                steps,
                bodies,
                {**env0, "root": str(r)},
                io,
                elide=plan,
                between=mirror_stage(r, outside, stage, at, planted),
            )
            io.close()
            now = files_in(outside)
            deleted = sorted(set(planted) - set(now))
            written = sorted(k for k in now if planted.get(k) != now[k])
            failed = [steps[i][0] for i, ok in enumerate(done) if not ok]
            print(
                f"    {kind:8s} read the writer's data {READS.count(b'EVIL')}x;"
                f" outside the root, deleted {deleted or '-'}, wrote {written or '-'};"
                f" failed: {', '.join(failed) or '-'}"
            )
