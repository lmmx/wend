"""A composition move the lobe handles cannot make: the waists between lobes. The reference's
strands pinch in deeply between consecutive lobes, so each lobe reads as a separate cushion with
a dark crevice; the reconstruction's strands are a smoother rope (the blind judges' "band-like" /
"rope-like", from iteration 0 on). For each strand, the lobe-to-surface map (lobemap.py JSON) gives
its lobes' station runs; between consecutive runs lies a stretch the partner hides. This narrows
the strand's radius there, by `depth` at the gap's centre, with a C2 bump over the gap plus `pad`
stations each side, on the radius spline controls (so the strand stays one surface).
Usage (from the logo root): waists.py spec.json lobemap.json out.json depth [pad]"""
import copy, json, os, sys
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import strandspline as S
from lobekit import greville, NECK_SAFE

spec = json.load(open(sys.argv[1])); lm = json.load(open(sys.argv[2])); out = sys.argv[3]
depth = float(sys.argv[4]); pad = float(sys.argv[5]) if len(sys.argv) > 5 else 8.0
res = copy.deepcopy(spec)
for name in ("yellow", "blue"):
    runs = sorted((v["a"], v["b"], k) for k, v in lm.items() if v.get("strand") == name)
    st = res[name]
    rc = np.array(st["rctrl"], float)
    g = greville(S.knots(st["s0"], st["s1"], st["rseg"]), len(rc))
    f = np.ones_like(rc)
    gaps = []
    for (a0, b0, k0), (a1, b1, k1) in zip(runs, runs[1:]):
        if a1 <= b0:
            continue
        c, h = 0.5 * (b0 + a1), 0.5 * (a1 - b0) + pad
        if c - h < NECK_SAFE[name]:
            continue
        x = np.clip((g - c) / h, -1, 1)
        f *= 1 - depth * (1 - x * x) ** 3
        gaps.append(f"{k0}|{k1} at {c:.0f} +-{h:.0f}")
    st["rctrl"] = (rc * f).tolist()
    print(name, "; ".join(gaps))
res.setdefault("waists", []).append(dict(depth=depth, pad=pad))
json.dump(res, open(out, "w"))
