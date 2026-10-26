"""What ``relate(..., thorough=True)`` settles that relate's rules leave, on
#119's samples, in each mode: how each answer moves, what it costs, and how
often the oracle's budget runs out. Every answer must refine the rules' (an
"always" or "never" kept, a "sometimes" kept or made "always"), and every
example must render; both are counted, and expected to be zero.

    PYTHONPATH=src:tests python bench/relate_thorough.py [examples] [out.json]
"""

import collections
import itertools
import json
import sys
import time

from hypothesis import HealthCheck, Phase, given, settings


sys.path.insert(0, "tests")
from relate_test import pairs, renamed, under_one_head  # noqa: E402

import wend._languages as L  # noqa: E402
from wend import relate  # noqa: E402
from wend._relate import _BUDGET, lexically  # noqa: E402


HOWS = ("same", "inside", "contains")
REFINES = {
    "always": {"always"},
    "never": {"never"},
    "sometimes": {"sometimes", "always"},
    "unknown": {"always", "sometimes", "never", "unknown"},
}
BUILTIN = (str, int, float, bool)


def exhausted(a, b, shared):
    """Whether the oracle runs out of budget on ``a`` and ``b``."""
    decide = L.relate_shared if shared else L.relate_independent
    try:
        with L.budget(_BUDGET):
            decide(a, b)
    except L.Exhausted:
        return True
    except L.Unsupported:
        return False
    return False


def run(n):
    tally = collections.Counter()
    rows = []
    for strategy, (shared, builtin) in itertools.product(
        (pairs, renamed, under_one_head),
        itertools.product((True, False), (False, True)),
    ):
        mode = (
            f"{'shared' if shared else 'independent'}{', builtin' if builtin else ''}"
        )

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
            key = (strategy.__name__, mode)
            tally[key + ("pairs",)] += 1
            t0 = time.perf_counter()
            plain = relate(a, b, shared=shared, builtin_values=builtin)
            t1 = time.perf_counter()
            r = relate(a, b, shared=shared, builtin_values=builtin, thorough=True)
            t2 = time.perf_counter()
            tally[key + ("seconds, rules",)] += t1 - t0
            tally[key + ("seconds, thorough",)] += t2 - t1
            if t2 - t1 > 2:
                tally[key + ("pairs over 2 s",)] += 1
            asked = [h for h in HOWS if plain[h] in ("unknown", "sometimes")]
            if asked and exhausted(a, b, shared):
                tally[key + ("budget exhausted",)] += 1
                rows.append(dict(kind="exhausted", mode=mode, a=a.pattern, b=b.pattern))
            for h in HOWS:
                tally[key + (f"{plain[h]} -> {r[h]}",)] += 1
                if r[h] not in REFINES[plain[h]]:
                    tally[key + ("NOT A REFINEMENT",)] += 1
                    rows.append(
                        dict(
                            kind="not a refinement",
                            mode=mode,
                            how=h,
                            a=a.pattern,
                            b=b.pattern,
                            rules=plain[h],
                            thorough=r[h],
                        )
                    )
            for ex in r.examples:
                ea = {k: v for k, v in ex.a_bindings.items() if k in a.param_names}
                eb = {k: v for k, v in ex.b_bindings.items() if k in b.param_names}
                try:
                    ok = lexically(a.render(ea), b.render(eb)) == ex.how
                except Exception:  # noqa: BLE001
                    ok = False
                if not ok:
                    tally[key + ("EXAMPLE FAILS",)] += 1
                    rows.append(
                        dict(kind="example fails", mode=mode, a=a.pattern, b=b.pattern)
                    )
                values = (*ex.a_bindings.values(), *ex.b_bindings.values())
                if not all(type(v) in BUILTIN for v in values):
                    tally[key + ("examples binding values of their own",)] += 1

        one()
    return tally, rows


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 300
    tally, rows = run(n)
    for k, v in sorted(tally.items()):
        print(k, round(v, 2) if isinstance(v, float) else v)
    if len(sys.argv) > 2:
        with open(sys.argv[2], "w") as f:
            json.dump(rows, f, indent=1)
