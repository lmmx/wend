"""Fit a few spine offset knots so the model's outline (the union of its strands' discs, exact
for the silhouette, no rendering) follows the reference's outline inside a window. Checks the
proxy against a real render first. Usage: outlinefit.py params.json render.png out.json cfg"""
import json, sys
import numpy as np
from scipy.optimize import least_squares
from scipy import ndimage
from skimage import measure
sys.path.insert(0, __file__.rsplit("/", 1)[0])
import snakefit as sf
params_in, render, out = sys.argv[1:4]; cfg = json.loads(sys.argv[4])
p0 = json.load(open(params_in))
x0w, y0w, x1w, y1w = cfg["window"]; knots = cfg["knots"]
_, A = sf.ref_labels("ref/reference.png", 1.0)
def outline(mask):
    pts = np.vstack([c[:, ::-1] for c in measure.find_contours(mask.astype(float), 0.5) if len(c) > 30])
    return pts[(pts[:, 0] > x0w) & (pts[:, 0] < x1w) & (pts[:, 1] > y0w) & (pts[:, 1] < y1w)]
ref_pts = outline(A > 0)[::2]
def discs(p):
    m = sf.build(p, 1400)
    xy, _ = sf.project(m["centres"], p["cam"]); r = m["radii"]
    keep = (xy[:, 0] > x0w - 120) & (xy[:, 0] < x1w + 120) & (xy[:, 1] > y0w - 120) & (xy[:, 1] < y1w + 120) & (r > 0)
    return xy[keep], r[keep]
def sdist(q, xy, r):          # signed distance to the union of discs
    return (np.linalg.norm(q[:, None] - xy[None], axis=2) - r[None]).min(1)
# the proxy against the real render: the union-of-discs mask vs the render's silhouette, in the window
xy, r = discs(p0)
gx, gy = np.meshgrid(np.arange(x0w, x1w), np.arange(y0w, y1w)); G = np.column_stack([gx.ravel(), gy.ravel()]).astype(float)
proxy = (sdist(G, xy, r) < 0).reshape(gx.shape)
_, Rl = sf.ref_labels(render, 1.0); rend = Rl[y0w:y1w, x0w:x1w] > 0
print(f"proxy vs render silhouette in the window: IoU {(proxy & rend).sum() / (proxy | rend).sum():.3f}")
refm = A[y0w:y1w, x0w:x1w] > 0
print(f"start: model vs reference silhouette IoU in window {(proxy & refm).sum() / (proxy | refm).sum():.3f}")
off0 = np.array(p0["spine_offsets"], float)
def make(v):
    q = json.loads(json.dumps(p0)); o = off0.copy(); o[knots] += v; q["spine_offsets"] = o.tolist(); return q
def res(v):
    q = make(v); xy, r = discs(q)
    d = sdist(ref_pts, xy, r)
    o = off0.copy(); o[knots] += v
    smooth = np.diff(o[min(knots) - 2:max(knots) + 3], 2)
    return np.r_[d, cfg.get("smooth", 2.0) * smooth, cfg.get("reg", 0.15) * v]
r0 = res(np.zeros(len(knots)))[:len(ref_pts)]
fit = least_squares(res, np.zeros(len(knots)), diff_step=0.05, max_nfev=200)
r1 = res(fit.x)[:len(ref_pts)]
print(f"outline distance: mean {np.abs(r0).mean():.1f} px (p90 {np.percentile(np.abs(r0), 90):.1f}) -> mean {np.abs(r1).mean():.1f} (p90 {np.percentile(np.abs(r1), 90):.1f}); {fit.nfev} evaluations")
print("knot changes:", {k: round(float(v), 1) for k, v in zip(knots, fit.x)})
q = make(fit.x)
xy, r = discs(q); proxy2 = (sdist(G, xy, r) < 0).reshape(gx.shape)
print(f"end: model vs reference silhouette IoU in window {(proxy2 & refm).sum() / (proxy2 | refm).sum():.3f}")
json.dump(q, open(out, "w"), indent=1)
