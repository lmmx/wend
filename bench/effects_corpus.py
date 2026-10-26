"""Precision of wend.effects.EffectGraph on realistic pipelines.

Run with: uv run python bench/effects_corpus.py [--builtin] [--thorough]

Eight pipelines of the shapes data and build pipelines take: the example's
seven steps, date-partitioned files compacted by month, training checkpoints
evaluated and collected, a build, outputs named after one input by changed
suffixes and stems, shards with manifests, work published from a scratch
directory, and a mirror kept by SubPaths. For each: its links by certainty,
its stages, its obligations by status, and every link that stays unknown.
A link left unknown is one the graph could neither prove nor rule out: the
count to bring down, where it can be, soundly. ``--builtin`` builds each graph
with builtin_values=True, and ``--thorough`` with thorough=True.
"""

import collections
import pathlib
import sys


sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "examples"))
import pipeline_effects as ex

from wend import (
    Absent,
    Creatable,
    Exists,
    File,
    Listable,
    P,
    Param,
    Readable,
    Step,
    SubPath,
    T,
    Writable,
)
from wend.effects import EffectGraph


def reads(e):
    return e.requires(File, Exists, Readable)


def makes(e):
    return e.requires(Absent, Creatable).ensures(File, Exists)


def writes(e):
    return e.requires(Writable).ensures(File, Exists)


root, day, year, month = (
    Param("root"),
    Param("day", type=str),
    Param("year", type=int),
    Param("month", type=int),
)
run, step, split, idx, job, name, mod = (
    Param("run", type=str),
    Param("step", type=int),
    Param("split", choices={"train", "valid"}),
    Param("idx", type=int),
    Param("job", type=str),
    Param("name", type=str),
    Param("mod", type=str),
)
R = P(root)
PIPES = {}
PIPES["example"] = ex.steps
part = R / "data" / T(t"{year:04d}") / T(t"{month:02d}")
PIPES["partitions"] = {
    "land": Step(o=makes(part / T(t"{day}.parquet"))),
    "compact": Step(
        i=part.requires(Listable),
        o=makes(R / "data" / T(t"{year:04d}") / T(t"{month:02d}.parquet")),
    ),
    "prune": Step(o=(part / T(t"{day}.parquet")).requires(Exists).ensures(Absent)),
    "index": Step(
        i=reads(R / "data" / T(t"{year:04d}") / T(t"{month:02d}.parquet")),
        o=writes(R / "index.json"),
    ),
}
ck = P(run) / "ckpt"
PIPES["checkpoints"] = {
    "train": Step(
        o=makes(ck / T(t"{step:06d}.pt")),
        log=writes(P(run) / "logs" / T(t"{step}.json")),
    ),
    "eval": Step(
        i=reads(ck / T(t"{step:06d}.pt")), o=makes(P(run) / "eval" / T(t"{step}.json"))
    ),
    "select": Step(
        i=(P(run) / "eval").requires(Listable), o=writes(P(run) / "best.pt")
    ),
    "gc": Step(o=(ck / T(t"{step:06d}.pt")).requires(Exists).ensures(Absent)),
}
PIPES["build"] = {
    "compile": Step(
        i=reads(P("src") / T(t"{mod}.py")), o=writes(P("build") / T(t"{mod}.pyc"))
    ),
    "package": Step(
        i=P("build").requires(Listable), o=makes(P("dist") / T(t"{name}.whl"))
    ),
    "clean": Step(o=P("build").requires(Exists).ensures(Absent)),
}
raw = R / "raw" / T(t"{day}.csv")
PIPES["renames"] = {
    "convert": Step(i=reads(raw), o=makes(raw.with_suffix(".parquet"))),
    "meta": Step(i=reads(raw), o=makes(raw.with_suffix(".meta.json"))),
    "stats": Step(i=reads(raw), o=writes(raw.with_stem("summary"))),
    "check": Step(i=reads(raw.with_suffix(".parquet")), o=makes(raw.with_name("ok"))),
}
PIPES["shards"] = {
    "shard": Step(o=makes(R / "shards" / T(t"{split}") / T(t"{idx:05d}.tar"))),
    "manifest": Step(
        i=(R / "shards" / T(t"{split}")).requires(Listable),
        o=writes(R / "shards" / T(t"{split}.json")),
    ),
    "verify": Step(i=reads(R / "shards" / T(t"{split}.json"))),
}
PIPES["publish"] = {
    "work": Step(o=makes(R / "tmp" / T(t"{job}") / T(t"{name}"))),
    "publish": Step(
        i=reads(R / "tmp" / T(t"{job}") / T(t"{name}")),
        o=makes(R / "out" / T(t"{name}")),
    ),
    "tidy": Step(o=(R / "tmp" / T(t"{job}")).requires(Exists).ensures(Absent)),
    "serve": Step(i=(R / "out").requires(Listable)),
}
PIPES["subpaths"] = {
    "sync": Step(o=writes(R / "mirror" / SubPath("rel"))),
    "scan": Step(i=reads(R / "mirror" / SubPath("rel"))),
    "drop": Step(o=(R / "mirror" / SubPath("old")).requires(Exists).ensures(Absent)),
}
# --builtin assumes bound values are of builtin types (builtin_values=True).
builtin = "--builtin" in sys.argv
thorough = "--thorough" in sys.argv
tot = collections.Counter()
for k, steps in PIPES.items():
    g = EffectGraph(
        steps,
        existing=[R] if k not in ("build", "checkpoints") else [],
        builtin_values=builtin,
        thorough=thorough,
    )
    links = [*g.edges, *g.hazards, *g.conflicts]
    c = collections.Counter(l.certainty for l in links)
    tot.update(c)
    unk = [str(l) for l in links if l.certainty == "unknown"]
    obs = (
        collections.Counter(o.status for o in g.obligations())
        if g.stages()
        else "cycle"
    )
    print(
        f"{k:12} links {dict(c)}  stages {g.stages()}  obligations {dict(obs) if obs != 'cycle' else obs}"
    )
    for u in unk[:6]:
        print("     unknown:", u)
print("total", dict(tot))
