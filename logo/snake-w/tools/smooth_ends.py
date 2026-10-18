"""Smooth the spine polyline near both ends (the necks and heads), so its bends stay wider than the tube."""
import json, sys
import numpy as np
from scipy import ndimage
src, dst, sigma, dend = sys.argv[1], sys.argv[2], float(sys.argv[3]), float(sys.argv[4])
p = json.load(open(src))
P = np.asarray(p["polyline"], float)
d = np.r_[0, np.cumsum(np.linalg.norm(np.diff(P, axis=0), axis=1))]
# resample at 1px so sigma is in pixels
n = int(d[-1]); t = np.linspace(0, d[-1], n)
P = np.column_stack([np.interp(t, d, P[:, k]) for k in (0, 1)])
S = ndimage.gaussian_filter1d(P, sigma, axis=0, mode="nearest")
e = np.minimum(t, t[-1] - t)
w = np.clip(1 - (e - dend / 2) / (dend / 2), 0, 1)[:, None]
w = w * w * (3 - 2 * w)
Q = (1 - w) * P + w * S
# keep the true end points: blend the very ends back towards the original tips
p["polyline"] = Q.tolist()
json.dump(p, open(dst, "w"), indent=1)
# report the tightest bend radius near each end
dQ = np.gradient(Q, axis=0); ddQ = np.gradient(dQ, axis=0)
k = np.abs(dQ[:, 0] * ddQ[:, 1] - dQ[:, 1] * ddQ[:, 0]) / np.maximum(np.linalg.norm(dQ, axis=1) ** 3, 1e-9)
print("min bend radius: left", round(1 / k[: int(dend)].max()), "right", round(1 / k[-int(dend):].max()))
