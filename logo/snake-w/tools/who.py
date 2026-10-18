"""Which parts of the strands make each reference feature? For a spline spec, every pixel of each
registry feature's reference mask is assigned the strand section in front there (a hard z-buffer
of the sections: screen half-width r ql, front depth r qd, as regionfit.py's raster), and the
sections that cover the pixel but are hidden behind it.
Prints, per feature: the visible strand and its shared-station range (5th-95th percentile) with
the fraction of the mask it fills, and the strands / stations passing behind.
Usage (from the logo root): who.py spec.json [F1,F2,...]"""
import json, os, sys
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import strandspline as S
from evaluate import load_registry

ELEV = np.radians(3.7746862033886837)
spec = json.load(open(sys.argv[1])); L = spec["L"]
only = set(sys.argv[2].split(",")) if len(sys.argv) > 2 else None
reg, lab, _ = load_registry()
c, s = np.cos(ELEV), np.sin(ELEV)
balls = []
for k, n in enumerate(("yellow", "blue")):
    st = spec[n]; u = np.arange(st["s0"], st["s1"], 2.0)
    X, r = S.evaluate(st, u)
    if "sec" in st:
        t = S.knots(st["s0"], st["s1"], st["sec"]["seg"]); B = S.basis(u, t)
        ql, qd = B @ np.asarray(st["sec"]["ql"]), B @ np.asarray(st["sec"]["qd"])
    else:
        ql = qd = np.ones_like(u)
    sh = u if n == "yellow" else L - u
    balls.append(np.column_stack([X[:, 0], -(X[:, 1] * c - X[:, 2] * s), X[:, 1] * s + X[:, 2] * c, r * ql, r * qd, np.full_like(u, k), sh]))
Bl = np.vstack(balls)
NAMES = ("yellow", "blue")
for i, f in enumerate(reg["features"]):
    if only and f["id"] not in only:
        continue
    yy, xx = np.nonzero(lab == i + 1)
    yy, xx = yy[::3], xx[::3]
    x0, y0, x1, y1 = f["bbox"]
    sel = Bl[(Bl[:, 0] + Bl[:, 3] > x0) & (Bl[:, 0] - Bl[:, 3] < x1) & (Bl[:, 1] + Bl[:, 3] > y0) & (Bl[:, 1] - Bl[:, 3] < y1)]
    d2 = (xx[:, None] - sel[None, :, 0]) ** 2 + (yy[:, None] - sel[None, :, 1]) ** 2
    cov = d2 < sel[None, :, 3] ** 2
    zf = np.where(cov, sel[None, :, 2] + sel[None, :, 4] / sel[None, :, 3] * np.sqrt(np.maximum(sel[None, :, 3] ** 2 - d2, 0)), -1e9)
    front = np.argmax(zf, 1); any_cov = cov.any(1)
    vis = sel[front[any_cov]]
    out = [f"{f['id']} ({f['colour']}, reference):"]
    for k in (0, 1):
        m = vis[:, 5] == k
        if m.sum():
            q = np.percentile(vis[m, 6], [5, 95])
            out.append(f"  visible {NAMES[k]:6s} {m.mean() * any_cov.mean():5.0%} of the mask, stations {q[0]:.0f}..{q[1]:.0f}")
    hid = cov.copy(); hid[np.arange(len(front)), front] = False
    for k in (0, 1):
        hm = hid & (sel[None, :, 5] == k)
        frac = hm.any(1).mean()
        if frac > 0.05:
            stn = sel[np.nonzero(hm)[1], 6]
            q = np.percentile(stn, [5, 95])
            out.append(f"  behind  {NAMES[k]:6s} {frac:5.0%} of the mask, stations {q[0]:.0f}..{q[1]:.0f}")
    out.append(f"  uncovered {1 - any_cov.mean():.0%}")
    print("\n".join(out))
