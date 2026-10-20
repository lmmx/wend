"""Stage 1 of the left scarf (2026-10-20, auto/r33/NAPE.md): the yellow neck's join to its body.

The yellow tube's radius peaks at the head's neck join (r 47.8 px at s 165, between the neck's
40 px inside the head and 38 px at s 205), so the neck, which takes its end radius from the tube
there (rJ), flares into a ring at the join: the step the blue scarf hides. This holds the tube's
radius at a level `r_hold` over s 125-215 (ramped in over s0 .. s0 + ramp, out over 200-215), so
neck and tube meet without a ring. The centreline is untouched; only the radius controls are
refitted (same knots: exact outside the window). The head bake must be redone (its key covers
the strand's stations to the join + 60).
Usage (from the logo root): neckjoin.py INC_SPEC OUT_SPEC [--hold 40.5] [--end 200,215]"""
import argparse, copy, json, os, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import strandspline as SS
from collarfit import lsq_fit

ap = argparse.ArgumentParser(); ap.add_argument("spec"); ap.add_argument("out")
ap.add_argument("--hold", type=float, default=40.5); ap.add_argument("--end", default="200,215")
A = ap.parse_args()
spec = json.load(open(A.spec)); st = spec["yellow"]; e0, e1 = (float(v) for v in A.end.split(","))
u = np.r_[np.arange(st["s0"], st["s1"], 0.5), st["s1"]]
_, r = SS.evaluate(st, u)
w = 1 - SS.smoothstep(e0, e1, u)
r2 = r + w * (A.hold - r)
tr = SS.knots(st["s0"], st["s1"], st["rseg"])
out = copy.deepcopy(spec)
out["yellow"]["rctrl"] = lsq_fit(tr, u, r2, np.zeros(st["rseg"] + 3), np.arange(st["rseg"] + 3)).tolist()
_, rn = SS.evaluate(out["yellow"], u)
keep = u > e1 + 30
print(json.dumps(dict(hold=A.hold, end=[e0, e1], max_change=float(np.abs(rn - r).max()), err_outside=float(np.abs(rn - r)[keep].max()),
                      r_at=[(float(s), round(float(np.interp(s, u, rn)), 1)) for s in (125, 145, 165, 185, 205, 225)])))
json.dump(out, open(A.out, "w"))
