"""Match the rope's width and centring along the spine, by fixed-point iteration.

For samples along the spine, measure how far the silhouette reaches on each side (along
the in-plane normal), in the reference and in the model. Then shift the spine by half
the difference of the side extents, and scale the strands' radius and offset by the
ratio of the widths. Each round is one render.
"""
import json, sys
import numpy as np
from scipy import ndimage
sys.path.insert(0, __file__.rsplit("/", 1)[0])
import snakefit as sf

start, out, rounds = sys.argv[1], sys.argv[2], int(sys.argv[3])
K = int(sys.argv[4]) if len(sys.argv) > 4 else 48
p = json.load(open(start))
SC = 0.5
small, full = sf.ref_labels("ref/reference.png", SC)
loss = sf.Loss(*sf.ref_labels("ref/reference.png", sf.SCALE)[:1], sf.SCALE)

def extents(lab, C2, T2, ss, skip):
    """Side extents of the silhouette along the normal, at spine points C2 (image px)."""
    sil = ndimage.binary_closing(lab > 0, iterations=2)
    H, W = sil.shape
    ep, em = np.full(len(C2), np.nan), np.full(len(C2), np.nan)
    steps = np.arange(0, 160, 1.0)
    for i, (c, t) in enumerate(zip(C2, T2)):
        if ss[i] < skip[0] or ss[i] > skip[1]: continue
        nrm = np.array([-t[1], t[0]])
        for sgn, arr in ((1, ep), (-1, em)):
            q = (c[None] + sgn * steps[:, None] * nrm[None]) * SC
            xi, yi = np.round(q[:, 0]).astype(int), np.round(q[:, 1]).astype(int)
            ok = (xi >= 0) & (xi < W) & (yi >= 0) & (yi < H)
            inside = np.zeros(len(steps), bool); inside[ok] = sil[yi[ok], xi[ok]]
            outside = np.nonzero(~inside)[0]
            arr[i] = steps[outside[0]] if len(outside) else steps[-1]
    return ep, em

best = (np.inf, p)
GAIN = float(sys.argv[5]) if len(sys.argv) > 5 else 0.5
for rnd in range(rounds + 1):
    cur = loss(p)
    if cur < best[0]: best = (cur, json.loads(json.dumps(p)))
    lab, m = sf.render_labels(p, small.shape, SC, 1400)
    C, s = m["C"], m["s"]
    sx, _ = sf.project(C, p["cam"]); C2 = sx * p["cam"]["zoom"] + np.array(p["cam"]["offset"])
    T2 = np.gradient(C2, axis=0); T2 /= np.linalg.norm(T2, axis=1, keepdims=True)
    L = s[-1]
    skip = (130, L - 130)
    rp, rm = extents(small, C2, T2, s, skip)
    mp, mm = extents(lab, C2, T2, s, skip)
    print(f"round {rnd}: loss {cur:.3f}  width err {np.nanmean(np.abs((rp + rm) - (mp + mm))):.1f}px  centre err {np.nanmean(np.abs((rp - rm) - (mp - mm)) / 2):.1f}px", flush=True)
    if rnd == rounds: break
    good = ~np.isnan(rp)
    dc = np.where(good, ((rp - rm) - (mp - mm)) / 2, 0.0)
    ratio = np.where(good, (rp + rm) / np.maximum(mp + mm, 1), 1.0)
    # smooth over about a lobe, then sample at K knots
    dc = ndimage.gaussian_filter1d(dc, 25, mode="nearest"); ratio = ndimage.gaussian_filter1d(ratio, 25, mode="nearest")
    kn = np.linspace(0, L, K)
    # the image normal (-t_y, t_x) in image coords; the model's offset uses the world normal
    # (-T_y, T_x) with world y = -image y, which is the opposite side
    off = np.asarray(p.get("spine_offsets", [0.0] * K), float)
    if len(off) != K: off = np.interp(kn, np.linspace(0, L, len(off)), off)
    p["spine_offsets"] = (off - GAIN * np.interp(kn, s, dc)).tolist()
    sw = np.asarray(p.get("swell", [1.0] * K), float)
    if len(sw) != K: sw = np.interp(kn, np.linspace(0, L, len(sw)), sw)
    p["swell"] = np.clip(sw * (1 + GAIN * (np.interp(kn, s, ratio) - 1)), 0.7, 1.4).tolist()
print("best", round(best[0], 3)); p = best[1]
json.dump(p, open(out + ".json", "w"), indent=1)
sf.overlay(p, full if False else sf.ref_labels("ref/reference.png", 1.0)[1], out + ".png")
