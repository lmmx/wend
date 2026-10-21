"""Cost of the experimental overlap analysis and effect graphs.

Run with: uv run python bench/experimental_overlap.py

Each figure is the median of 5 repeats of one call (ms), after a warm-up
call; the shapes and render-index caches are cleared before every repeat unless stated.
Machine-specific: compare rows within one run.
"""

from __future__ import annotations

import statistics
import time

from wend import Exists, P, Param, Readable, Step, SubPath, T
from wend._experimental import overlap as O
from wend._experimental.effects import EffectGraph


def ms(fn, repeats=5, clear=True):
    fn()
    out = []
    for _ in range(repeats):
        if clear:
            O._cached_shapes.cache_clear()
            O._cached_render_index.cache_clear()
        t = time.perf_counter()
        fn()
        out.append((time.perf_counter() - t) * 1000)
    return statistics.median(out)


def row(label, value, extra=""):
    print(f"  {label:<44} {value:9.2f} ms  {extra}")


print("overlap(a, b), a and b of n segments (literal and parameter alternating):")
for n in [2, 4, 8, 16, 32]:
    a = P("r")
    b = P("r")
    for i in range(n):
        a = a / (f"s{i}" if i % 2 else Param(f"p{i}"))
        b = b / (Param(f"q{i}") if i % 2 else f"s{i}")
    v = O.overlaps(a, b).verdict
    row(f"n={n}", ms(lambda a=a, b=b: O.overlaps(a, b)), v)

print("overlap with k SubPaths on each side (alignments multiply):")
for k in [1, 2, 3, 4, 6, 8]:
    a = P("r")
    b = P("r")
    for i in range(k):
        a = a / SubPath(f"s{i}") / f"x{i}"
        b = b / f"x{i}" / SubPath(f"t{i}")
    v = O.overlaps(a, b).verdict
    row(f"k={k}", ms(lambda a=a, b=b: O.overlaps(a, b)), v)

print("overlap with a choices parameter of d values on both sides:")
for d in [4, 16, 64, 256]:
    c = Param("c", choices={f"v{i}" for i in range(d)})
    e = Param("e", choices={f"v{i}" for i in range(0, 2 * d, 2)})
    a, b = P("r") / T(t"{c}.txt"), P("r") / T(t"{e}.txt")
    v = O.overlaps(a, b).verdict
    row(f"d={d}", ms(lambda a=a, b=b: O.overlaps(a, b)), v)

print(
    "overlap of an {n:0Wd} field with a text ending in z (disjoint under builtin formatting):"
)
n = Param("n", type=int)
for w in [4, 16, 64]:
    a = P("r") / T(t"{n:0{w}d}")  # the width is a constant, so the spec is static
    b = P("r") / T(t"{Param('s')}z")
    v = O.overlaps(a, b, builtin_values=True).verdict
    row(f"width {w}", ms(lambda a=a, b=b: O.overlaps(a, b, builtin_values=True)), v)

print("a parameter repeated n times against n literal segments (equality groups):")
x = Param("x")
for k in [2, 8, 32]:
    rep = P("r")
    for _ in range(k):
        rep = rep / x
    same = "/".join(["r"] + ["v"] * k)
    differ = "/".join(["r"] + ["v"] * (k - 1) + ["w"])
    row(
        f"n={k}, all equal",
        ms(lambda e=rep, t=same: O.overlaps(e, t)),
        O.overlaps(rep, same).verdict,
    )
    row(
        f"n={k}, last differs",
        ms(lambda e=rep, t=differ: O.overlaps(e, t)),
        O.overlaps(rep, differ).verdict,
    )

print("a deferred expression over finite domains (witness search by rendering):")
rc = Param("rc", choices={"a", "/x", "b/c", "a/.."})
ci = Param("ci", choices={1, 2})
f, nn, p = Param("f", type=bool), Param("n", type=int), Param("p")
sc = SubPath("sc", choices={".", "a", "a/b"})
a = (P(rc) / T(t"{f}.txt") / T(t"v{ci:d}") / sc).parent
b = P("/") / T(t"{nn:d}.{p}") / p / T(t"{ci}{ci}")
row(
    "strict (was 1349 ms before the render index)",
    ms(lambda: O.overlaps(a, b)),
    O.overlaps(a, b).verdict,
)
row(
    "builtin values",
    ms(lambda: O.overlaps(a, b, builtin_values=True)),
    O.overlaps(a, b, builtin_values=True).verdict,
)

print("EffectGraph of a chain of N steps (stage i -> stage i+1, plus a shared log):")
day = Param("day")
for N in [10, 25, 50, 100]:
    steps = {
        f"s{i}": Step(
            src=(P("data") / f"stage{i}" / T(t"{day}.parquet")).requires(Readable),
            dst=(P("data") / f"stage{i + 1}" / T(t"{day}.parquet")).ensures(Exists),
            log=(P("logs") / f"s{i}" / T(t"{day}.log")).ensures(Exists),
        )
        for i in range(N)
    }
    g = EffectGraph(steps)
    pairs = sum(1 for p in g.ports if p.supplies) * sum(
        1 for p in g.ports if p.is_input
    )
    row(
        f"N={N} ({pairs} supplier-input pairs)",
        ms(lambda s=steps: EffectGraph(s), repeats=3),
        f"{len(g.edges)} edges, order found: {g.order() is not None}",
    )
    row(
        f"N={N}, caches kept",
        ms(lambda s=steps: EffectGraph(s), repeats=3, clear=False),
    )
