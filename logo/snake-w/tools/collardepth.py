"""The right collar's depth order (2026-10-20): on the left of the blue neck's base the reference
has the yellow collar L16 in front, its round left end coming round the neck; the render has the
yellow tail thinning behind the neck there and the blue L15's upper end in front. This moves the
yellow tail (s >= y0, ramped in over 40 stations) towards the camera by dz_y and holds its radius
at the L16 lobe's median, and moves the blue strand's upper L15 end (s in b0..b1, ramped both
ways) away from the camera by dz_b (and down, dy_b, image px). Only centreline (and the yellow
radius) controls whose support meets a changed station are refitted.
Usage (from the logo root): collardepth.py INC_SPEC OUT_SPEC dz_y dz_b [dy_b] [--y0 1330] [--b 205,300] [--floor 1.0]"""
import argparse, copy, json, os, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import strandspline as SS
from collarfit import lsq_fit
E = np.radians(3.7746862033886837)
ap = argparse.ArgumentParser(); ap.add_argument("spec"); ap.add_argument("out"); ap.add_argument("dz_y", type=float); ap.add_argument("dz_b", type=float)
ap.add_argument("dy_b", type=float, nargs="?", default=0.0); ap.add_argument("--dy_y", type=float, default=0.0); ap.add_argument("--y0", type=float, default=1330); ap.add_argument("--b", default="205,300"); ap.add_argument("--floor", type=float, default=1.0)
A = ap.parse_args()
spec = json.load(open(A.spec)); out = copy.deepcopy(spec)
def refit(st, u, X2, r2=None, win=None):
    t = SS.knots(st["s0"], st["s1"], st["nseg"]); old = np.asarray(st["ctrl"], float)
    lo, hi = u[win].min(), u[win].max()
    free = np.array([i for i in range(len(old)) if t[i + 4] > lo - 1e-9 and t[i] < hi + 1e-9])
    st["ctrl"] = lsq_fit(t, u, X2, old, free).tolist()
    if r2 is not None:
        tr = SS.knots(st["s0"], st["s1"], st["rseg"]); st["rctrl"] = lsq_fit(tr, u, r2, np.zeros(st["rseg"] + 3), np.arange(st["rseg"] + 3)).tolist()
# yellow tail: forward (world +z, towards the camera) and full radius
st = out["yellow"]; u = np.r_[np.arange(st["s0"], st["s1"], 0.5), st["s1"]]; X, r = SS.evaluate(st, u)
w = SS.smoothstep(A.y0, A.y0 + 40, u)
med = float(np.median(r[(u >= 1284) & (u <= A.y0 + 20)]))
X2 = X + np.outer(w * A.dz_y, [0, 0, 1.0]) + np.outer(w * A.dy_y / np.cos(E), [0, -1.0, 0]); r2 = r + w * np.maximum(0, A.floor * med - r) if A.floor > 0 else None
refit(st, u, X2, r2, w > 0)
# blue L15's upper end: back (world -z) and down (image +y = world -y / cos e)
st = out["blue"]; b0, b1 = (float(v) for v in A.b.split(",")); u = np.r_[np.arange(st["s0"], st["s1"], 0.5), st["s1"]]; X, _ = SS.evaluate(st, u)
w = SS.smoothstep(b0, b0 + 25, u) * (1 - SS.smoothstep(b1 - 30, b1, u))
X2 = X + np.outer(w * A.dz_b, [0, 0, 1.0]) + np.outer(w * A.dy_b / np.cos(E), [0, -1.0, 0])
if np.any(w > 0) and (A.dz_b or A.dy_b): refit(st, u, X2, None, w > 0)
json.dump(out, open(A.out, "w")); print("yellow tail median r %.1f" % med)
