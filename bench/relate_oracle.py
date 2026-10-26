"""relate(shared=False) against the language oracle (src/wend/_experimental/lang_oracle.py) on
#119's samples: how many pairs the oracle decides, where the two disagree, and
how many "unknown" answers the oracle settles. Every possible relation the
oracle reports comes with bindings, rendered here by wend itself.

    PYTHONPATH=src:tests python bench/relate_oracle.py [examples] [out.json]
"""

import collections
import json
import sys
import time

from hypothesis import HealthCheck, Phase, given, settings


sys.path.insert(0, "tests")
from relate_test import pairs, renamed, under_one_head  # noqa: E402

from wend import relate  # noqa: E402
from wend._experimental.lang_oracle import Unsupported, relate_independent  # noqa: E402
from wend._relate import lexically  # noqa: E402


HOWS = ("same", "inside", "contains")


def confirmed(a, b, how, env):
    try:
        pa, pb = a.render(env["a"]), b.render(env["b"])
    except Exception as e:  # noqa: BLE001
        return f"render failed: {type(e).__name__}: {e}"
    return True if lexically(pa, pb) == how else f"renders {pa!r}, {pb!r}"


def run(n):
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
            r = relate(a, b, shared=False)
            t0 = time.perf_counter()
            try:
                o = relate_independent(a, b)
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
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 1500
    tally, rows = run(n)
    for k, v in sorted(tally.items(), key=lambda kv: str(kv[0])):
        print(k, round(v, 2) if isinstance(v, float) else v)
    if len(sys.argv) > 2:
        json.dump(rows, open(sys.argv[2], "w"), indent=1)
    for r in rows[:30]:
        print(r)
