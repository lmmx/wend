"""Adversarial falsification of wend._experimental.overlap (journal entry
2026-10-20-overlap-research-89).

Random pairs of expressions (deferred operations, absolute and choice
heads, conversions, widths, nested specs, enums, floats) are compared in
both modes. Every YES witness is rendered from both sides; every NO is
attacked by rendering each side over a value pool and intersecting. The
strict-mode pool adds values the contract allows but builtin formatting
never produces (an int subclass formatting as letters, a str subclass, an
os.PathLike, 1.0 and True for choices={1}). A pool only refutes what it
contains: the builtin pool must hold every builtin value a parameter
accepts (bool is an int), or a wrong NO goes unseen.

    uv run python docs/journal/scripts/2026-10-20-overlap-falsify.py SEED N
"""
import sys, itertools, collections, random, time, enum, os
from pathlib import PurePosixPath
from wend import P, Param, SubPath, T, Absolute
from wend._experimental.overlap import overlaps
from wend.errors import WendError, NotInvertibleError

class Odd(int):
    def __format__(self, spec): return "abcd"
class Weird:
    def __format__(self, spec): return "zz"
    def __str__(self): return "zz"
class PL:
    def __fspath__(self): return "pl"
class Sly(str):
    def __format__(self, spec): return "zz"
    __hash__ = str.__hash__
class Col(enum.Enum):
    R = 1; G = 2

p, q, n, w = Param("p"), Param("q"), Param("n", type=int), Param("w", type=int)
c = Param("c", choices={"a", "b", "x.txt"})
ci = Param("ci", choices={1, 2})
s, sc = SubPath("s"), SubPath("sc", choices={".", "a", "a/b"})
root, rc, ab = Param("root"), Param("rc", choices={"a", "/x", "b/c", "a/.."}), Absolute("ab")
col, fl, f = Param("col", type=Col), Param("fl", type=float), Param("f", type=bool)
u = Param("u")  # untyped, formatted

BUILTIN_POOL = {
    "p": ["a", "b", "x.txt", "1", "...", 3, 2.5, None, True, 1 + 2j, PurePosixPath("a")], "q": ["a", "7", "x.txt", False, 7],
    "n": [0, 7, 12, -1, 100, True, False], "w": [1, 3], "c": ["a", "b", "x.txt"],
    "s": [".", "a", "a/b", "x.txt"], "sc": [".", "a", "a/b"],
    "root": ["", "a", "/", "/a", "..", "//x"], "rc": ["a", "/x", "b/c", "a/.."],
    "ab": ["/", "/a", "/a/b"], "col": [Col.R, Col.G], "fl": [0.5, 2.0],
    "f": [False, True], "u": ["a", 3, 2.5, None, True, -1], "ci": [1, 2, 1.0, True, 2.0, 1 + 0j],
}
WEIRD_POOL = {k: list(v) for k, v in BUILTIN_POOL.items()}
WEIRD_POOL["n"] += [Odd(3)]; WEIRD_POOL["p"] += [PL(), Weird()]; WEIRD_POOL["q"] += [Weird()]
WEIRD_POOL["u"] += [Weird(), Odd(5)]
WEIRD_POOL["c"] += [Sly("a")]

HEADS = [lambda: P("."), lambda: P("/"), lambda: P("data"), lambda: P(root), lambda: P("//"),
         lambda: P(rc), lambda: P(ab)]
PARTS = ["a", "x.txt", "..", "True", lambda: T(t"{f}"), lambda: T(t"{n}.txt"), lambda: p, lambda: q, lambda: c, lambda: s, lambda: sc,
         lambda: T(t"{p}.txt"), lambda: T(t"{n:02d}"), lambda: T(t"{n}"), lambda: T(t"x{p}"),
         lambda: T(t"{p}-{q}"), lambda: T(t"{c}.txt"), lambda: T(t"{f}.txt"), lambda: T(t"{n:d}.{p}"),
         lambda: T(t"{p!r}"), lambda: T(t"{p:>4}"), lambda: T(t"{p:.2}"), lambda: T(t"{n:0{w}d}"),
         lambda: T(t"{col}"), lambda: T(t"{fl:.1f}"), lambda: T(t"{u}"), lambda: T(t"{u:x<3}"),
         lambda: T(t"{n:#x}"), lambda: T(t"{n:,}"), lambda: T(t"{ci}.txt"), lambda: T(t"v{ci:d}"),
         lambda: T(t"{c}-{c}"), lambda: T(t"{ci}/{ci}") if False else T(t"{ci}{ci}")]
OPS = [lambda e: e.parent, lambda e: e.with_suffix(".json"), lambda e: e.with_name("z.txt"),
       lambda e: e.with_stem("st"), lambda e: e]

def rand_expr(rng):
    e = HEADS[rng.randrange(len(HEADS))]()
    for _ in range(rng.randrange(4)):
        part = PARTS[rng.randrange(len(PARTS))]
        e = e / (part() if callable(part) else part)
    if rng.random() < 0.3:
        try: e = OPS[rng.randrange(len(OPS))](e)
        except (WendError, ValueError): pass
    return e

def render_set(e, pool, cap=1500):
    names = sorted(e.param_names); out = set()
    for combo in itertools.islice(itertools.product(*(pool[k] for k in names)), cap):
        try: out.add(e.render(dict(zip(names, combo))))
        except (WendError, ValueError, TypeError): pass
    return out

seed, N = int(sys.argv[1]), int(sys.argv[2])
rng = random.Random(seed)
stats = collections.Counter(); bad = []; t0 = time.time(); worst = (0, None)
for _ in range(N):
    try:
        a, b = rand_expr(rng), rand_expr(rng)
        _ = a.param_names, b.param_names
    except (WendError, ValueError):
        continue
    for builtin in (False, True):
        pool = BUILTIN_POOL if builtin else WEIRD_POOL
        t = time.perf_counter()
        try:
            r = overlaps(a, b, builtin_values=builtin)
        except Exception as ex:
            bad.append(("CRASH", repr(ex)[:120], a.pattern, b.pattern)); continue
        dt = time.perf_counter() - t
        if dt > worst[0]: worst = (dt, (a.pattern, b.pattern))
        mode = "builtin" if builtin else "strict"
        stats[mode, r.verdict] += 1
        if r.verdict == "yes":
            wit = r.witness
            if a.render(wit.a) != wit.path or b.render(wit.b) != wit.path:
                bad.append(("BAD WITNESS", mode, a.pattern, b.pattern, wit))
        if r.verdict == "no":
            ra_, rb_ = render_set(a, pool), render_set(b, pool)
            stats[mode, "no checked: both sides render"] += bool(ra_ and rb_)
            if not builtin:
                weird = {"abcd", "zz", "pl", "1.0", "True", "(1+0j)"}
                stats[mode, "no checked: hostile renderings"] += any(set(x.split("/")) & weird or any(w in x for w in weird) for x in ra_ | rb_)
            common = ra_ & rb_
            if common:
                bad.append(("REFUTED NO", mode, a.pattern, b.pattern, sorted(common)[:2]))
for k, v in sorted(stats.items()): print(k, v)
print("PROBLEMS:", len(bad)); [print(" ", x) for x in bad[:15]]
print(f"seed {seed}: {N} pairs in {time.time()-t0:.1f}s; slowest call {worst[0]*1000:.1f} ms on {worst[1]}")
