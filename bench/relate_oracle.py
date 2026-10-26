"""relate against the language oracle (src/wend/_experimental/lang_oracle.py) on
#119's samples, under independent bindings or, with --shared, shared ones: how many pairs the oracle decides, where the two disagree, and
how many "unknown" answers the oracle settles. Every possible relation the
oracle reports comes with bindings, rendered here by wend itself.

    PYTHONPATH=src:tests python bench/relate_oracle.py [--shared] [examples] [out.json]
"""

import collections
import json
import sys
import time

from hypothesis import HealthCheck, Phase, given, settings


sys.path.insert(0, "tests")
from lang_oracle_test import renderings, shared_renderings  # noqa: E402
from relate_test import pairs, renamed, under_one_head  # noqa: E402

from wend import relate  # noqa: E402
from wend._experimental.lang_oracle import (  # noqa: E402
    Side,
    Unsupported,
    _lang,
    nonempty,
    relate_independent,
    relate_shared,
)
from wend._relate import lexically  # noqa: E402


HOWS = ("same", "inside", "contains")


def confirmed(a, b, how, env):
    try:
        pa = a.render({k: v for k, v in env["a"].items() if k in a.param_names})
        pb = b.render({k: v for k, v in env["b"].items() if k in b.param_names})
    except Exception as e:  # noqa: BLE001
        return f"render failed: {type(e).__name__}: {e}"
    return True if lexically(pa, pb) == how else f"renders {pa!r}, {pb!r}"


def renders_nothing(e):
    """Whether ``e`` renders on no binding: its language, read with each use
    of a name apart, holds every rendering and is empty. Then every relation
    is vacuously "always" and "never" at once (SEMANTICS §15.2)."""
    try:
        return not nonempty(_lang(e, Side("a")))
    except Unsupported:
        return False


def rendered_pair(a, b, shared, limit=400):
    """A pair of paths ``a`` and ``b`` render on one pooled binding (shared),
    or on a pooled binding each (independent); None if the pool has none."""
    if shared:
        return next(iter(shared_renderings(a, b, limit)), None)
    pa = next(iter(renderings(a, limit)), None)
    pb = next(iter(renderings(b, limit)), None)
    return None if pa is None or pb is None else (pa, pb)


def vacuity(a, b, how, shared):
    """Where relate answers "always" and the oracle "never", at most one is
    right unless no binding renders both, when both are (SEMANTICS §15.2).
    A pooled binding that renders both shows which is wrong; an empty
    language proves that none renders; otherwise it is unresolved."""
    pair = rendered_pair(a, b, shared)
    if pair is not None:
        wrong = "oracle" if lexically(*pair) == how else "relate"
        return f"CONTRADICTION ({wrong} wrong): renders {pair[0]!r}, {pair[1]!r}"
    if renders_nothing(a) or renders_nothing(b):
        return "relate always, oracle never: vacuous, a side renders nothing"
    return "relate always, oracle never: unresolved, no pooled binding renders both"


def run(n, shared=False):
    decide = relate_shared if shared else relate_independent
    tally = collections.Counter()
    rows = []
    for strategy in (pairs, renamed, under_one_head):

        @settings(
            max_examples=n,
            deadline=None,
            database=None,
            derandomize=True,
            suppress_health_check=list(HealthCheck),
            phases=[Phase.generate],
        )
        @given(strategy())
        def one(pair):
            a, b = pair
            name = strategy.__name__
            tally[(name, "pairs")] += 1
            r = relate(a, b, shared=shared)
            t0 = time.perf_counter()
            try:
                o = decide(a, b)
            except Unsupported as e:
                tally[(name, "unsupported")] += 1
                tally[("unsupported", str(e))] += 1
                return
            tally[(name, "seconds")] += time.perf_counter() - t0
            tally[(name, "supported")] += 1
            for how in HOWS:
                mine, exact = r[how], o[how]
                tally[(name, f"oracle {exact}")] += 1
                if exact in ("sometimes", "always", "possible"):
                    ok = confirmed(a, b, how, o.examples[how])
                    if ok is not True:
                        tally[(name, "oracle witness fails")] += 1
                        rows.append(
                            dict(
                                kind="oracle witness fails",
                                a=a.pattern,
                                b=b.pattern,
                                how=how,
                                detail=ok,
                            )
                        )
                wrong = (
                    (mine == "never" and exact in ("sometimes", "always", "possible"))
                    or (mine == "always" and exact in ("never", "sometimes"))
                    or (mine == "sometimes" and exact == "never")
                )
                if wrong and mine == "always" and exact == "never":
                    kind = vacuity(a, b, how, shared)
                    tally[(name, kind.split(":")[0] if kind[0] == "C" else kind)] += 1
                    if not kind.endswith("renders nothing"):
                        rows.append(dict(kind=kind, a=a.pattern, b=b.pattern, how=how))
                    continue
                if wrong:
                    kind = f"CONTRADICTION relate {mine}, oracle {exact}"
                    detail = (
                        confirmed(a, b, how, o.examples[how])
                        if exact != "never"
                        else None
                    )
                    rows.append(
                        dict(
                            kind=kind,
                            a=a.pattern,
                            b=b.pattern,
                            how=how,
                            detail=str(detail),
                        )
                    )
                    tally[(name, kind)] += 1
                elif mine == exact:
                    tally[(name, "agree")] += 1
                else:
                    tally[(name, f"relate {mine}, oracle {exact}")] += 1

        one()
    return tally, rows


if __name__ == "__main__":
    shared = "--shared" in sys.argv
    args = [x for x in sys.argv[1:] if x != "--shared"]
    n = int(args[0]) if args else 1500
    tally, rows = run(n, shared)
    for k, v in sorted(tally.items(), key=lambda kv: str(kv[0])):
        print(k, round(v, 2) if isinstance(v, float) else v)
    if len(args) > 1:
        json.dump(rows, open(args[1], "w"), indent=1)
    for r in rows[:30]:
        print(r)
