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
from relate_test import pairs, renamed, under_one_head  # noqa: E402

from wend import relate  # noqa: E402
from wend._experimental.lang_oracle import (  # noqa: E402
    Unsupported,
    language,
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
    """Whether ``e`` renders on no binding: its language, which holds every
    rendering, is empty. Then every relation is vacuously "always" and
    "never" at once (SEMANTICS §15.2)."""
    try:
        return not nonempty(language(e))
    except Unsupported:  # a name used twice in one shape: not decided here
        return False


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
                    if renders_nothing(a) or renders_nothing(b):
                        tally[
                            (name, "relate always, oracle never: renders nothing")
                        ] += 1
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
