"""Cost and precision of wend.relate and wend.effects.EffectGraph.

Run with: uv run python bench/effects.py

Relations: the median of 5 calls (ms) per pair, after a warm-up call.
Graphs: a chain of N steps under one {root}, each reading the stage before it
and writing its own, with every fifth step listing a stage five back and a
final step deleting the first stage; built once each with the public graph
and with the experimental one it replaces, both with shared bindings.
Machine-specific: compare rows within one run.
"""

from __future__ import annotations

import statistics
import time

from wend import Absent, Exists, Listable, P, Param, Readable, Step, SubPath, T, relate
from wend._experimental.effects import EffectGraph as Experimental
from wend.effects import EffectGraph


root, day, other = Param("root"), Param("day", type=str), Param("other", type=str)
R = P(root)


def ms(fn, repeats=5):
    fn()
    times = []
    for _ in range(repeats):
        t = time.perf_counter()
        fn()
        times.append((time.perf_counter() - t) * 1e3)
    return statistics.median(times)


def stage(i):
    return R / f"stage{i}" / T(t"{day}.parquet")


def chain(n):
    steps = {"s0": Step(out=stage(0).ensures(Exists))}
    for i in range(1, n - 1):
        paths = {
            "src": stage(i - 1).requires(Readable),
            "dst": stage(i).ensures(Exists),
        }
        if i % 5 == 0:
            paths["seen"] = (R / f"stage{i - 5}").requires(Listable)
        steps[f"s{i}"] = Step(paths)
    steps["purge"] = Step(old=stage(0).ensures(Absent))
    return steps


PAIRS = {
    "disjoint stages": (R / "raw" / T(t"{day}.csv"), R / "clean" / T(t"{day}.csv")),
    "one family, two spellings": (
        R / "raw" / T(t"{day}.csv"),
        (R / "raw").joinpath(T(t"{Param('day')}.csv")),
    ),
    "a file inside its directory": (R / "raw" / T(t"{day}.csv"), R / "raw"),
    "another day's file": (R / "raw" / T(t"{day}.csv"), R / "raw" / T(t"{other}.csv")),
    "a SubPath below a directory": (R / "raw" / SubPath("rest"), R / "raw"),
    "a root against a literal": (R / "x", P("/data") / "x"),
}


def main():
    print("relate(a, b), shared bindings")
    print(f"{'pair':32} {'ms':>7}  kind")
    for name, (a, b) in PAIRS.items():
        t = ms(lambda a=a, b=b: relate(a, b))
        print(f"{name:32} {t:7.2f}  {relate(a, b).kind}")

    print("\nEffectGraph on a chain of N steps under one root")
    print(
        f"{'N':>4} {'ports':>6} {'graph ms':>9} {'links':>6} {'certain':>8} {'order':>6}"
        f" | {'experimental ms':>16} {'links':>6} {'order':>6}"
    )
    for n in (10, 50, 100, 200):
        steps = chain(n)
        t = ms(lambda steps=steps: EffectGraph(steps), repeats=3)
        g = EffectGraph(steps)
        nlinks = len(g.edges) + len(g.hazards) + len(g.conflicts)
        certain = sum(1 for e in g.edges if e.certainty == "always")
        to = ms(lambda steps=steps: Experimental(steps, shared=True), repeats=1)
        old = Experimental(steps, shared=True)
        olinks = len(old.edges) + len(old.hazards) + len(old.conflicts)
        print(
            f"{n:4} {len(g.ports):6} {t:9.1f} {nlinks:6} {certain:8}"
            f" {'yes' if g.order() else 'none':>6} | {to:16.1f} {olinks:6}"
            f" {'yes' if old.order() else 'none':>6}"
        )


if __name__ == "__main__":
    main()
