"""Does the render-free lobe predictor track changes? For each already-rendered variant,
the predicted change of every lobe (centre, angle, size) against the change measured on its
Three.js render, both relative to the same base."""
import json, sys
import numpy as np
sys.path.insert(0, __file__.rsplit("/", 1)[0])
import lobepred as lp
import lobecmp_lib as lc

def measured(render, pred):
    meas = [l for l in lc.lobes_of(render) if not l["head"]]
    for l in meas:
        ys, xs = np.nonzero(l["mask"]); X = np.column_stack([xs, ys]) - [l["cx"], l["cy"]]
        ev, _ = np.linalg.eigh(np.cov(X.T)); l["sd_major"], l["sd_minor"] = np.sqrt(ev[1]), np.sqrt(ev[0])
    out = {}
    for q in pred:   # the measured lobe of the same colour nearest the predicted one
        cand = [l for l in meas if l["colour"] == q["colour"]]
        l = min(cand, key=lambda l: np.hypot(l["cx"] - q["cx"], l["cy"] - q["cy"]))
        out[q["anchor"]] = l
    return out

base_p, base_r = sys.argv[1], sys.argv[2]
variants = [a.split("=") for a in sys.argv[3:]]
P0 = {q["anchor"]: q for q in lp.predict(json.load(open(base_p)))}
M0 = measured(base_r, list(P0.values()))
rows = []
for name, pp, rr in variants:
    P = {q["anchor"]: q for q in lp.predict(json.load(open(pp)))}
    M = measured(rr, list(P.values()))
    for a in P:
        dp = np.array([P[a]["cx"] - P0[a]["cx"], P[a]["cy"] - P0[a]["cy"]])
        dm = np.array([M[a]["cx"] - M0[a]["cx"], M[a]["cy"] - M0[a]["cy"]])
        ang = lambda x, y: (x - y + 90) % 180 - 90
        rows.append(dict(v=name, a=a, dpx=dp[0], dpy=dp[1], dmx=dm[0], dmy=dm[1],
                         dpa=ang(P[a]["angle"], P0[a]["angle"]), dma=ang(M[a]["angle"], M0[a]["angle"]),
                         dps=np.log(P[a]["sd_minor"] / P0[a]["sd_minor"]), dms=np.log(M[a]["sd_minor"] / M0[a]["sd_minor"]),
                         dpl=np.log(P[a]["sd_major"] / P0[a]["sd_major"]), dml=np.log(M[a]["sd_major"] / M0[a]["sd_major"]),
                         round=M0[a]["sd_major"] / M0[a]["sd_minor"] < 1.3))
R = rows
def report(sel, label):
    S = [r for r in R if sel(r)]
    moved = [r for r in S if np.hypot(r["dmx"], r["dmy"]) > 1.5 or np.hypot(r["dpx"], r["dpy"]) > 1.5]
    cx = np.corrcoef([r["dpx"] for r in S] + [r["dpy"] for r in S], [r["dmx"] for r in S] + [r["dmy"] for r in S])[0, 1]
    res = np.median([np.hypot(r["dpx"] - r["dmx"], r["dpy"] - r["dmy"]) for r in moved]) if moved else np.nan
    A = [r for r in S if not r["round"] and (abs(r["dma"]) > 2 or abs(r["dpa"]) > 2)]
    ca = np.corrcoef([r["dpa"] for r in A], [r["dma"] for r in A])[0, 1] if len(A) > 2 else np.nan
    cs = np.corrcoef([r["dps"] for r in S], [r["dms"] for r in S])[0, 1]
    cl = np.corrcoef([r["dpl"] for r in S], [r["dml"] for r in S])[0, 1]
    print(f"{label:34s} n={len(S):3d}  centre-shift corr {cx:+.2f} (median miss {res:.1f} px over {len(moved)} moved)  angle-change corr {ca:+.2f} (n={len(A)})  width corr {cs:+.2f}  length corr {cl:+.2f}")
report(lambda r: True, "all variants, all lobes")
report(lambda r: r["a"] in (2, 3, 4, 5), "left-valley lobes (anchors 2-5)")
report(lambda r: r["a"] in (10, 11, 12, 13, 14), "right-valley lobes (anchors 10-14)")
report(lambda r: r["v"].startswith("lv"), "left-valley variants only")
report(lambda r: r["v"].startswith("bs"), "global bead variants only")
print("\nleft-valley variants, per lobe: predicted vs measured centre shift (px) and angle change (deg)")
for r in R:
    if r["v"].startswith("lv") and r["a"] in (2, 3, 4, 5):
        print(f"  {r['v']:5s} anchor {r['a']}: centre pred ({r['dpx']:+5.1f},{r['dpy']:+5.1f}) meas ({r['dmx']:+5.1f},{r['dmy']:+5.1f})   angle pred {r['dpa']:+4.0f} meas {r['dma']:+4.0f}" + ("  (round)" if r["round"] else ""))
