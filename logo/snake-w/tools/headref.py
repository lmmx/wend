"""Phase 3: read each head off the reference at full resolution.

For each head (the colour component holding its eye): the outline, smoothed; which parts
of it are open silhouette and which are hidden by the other snake's wrap; landmarks; the
upper and lower profiles measured along the head's axis; and the visible neck's midline
and width. Everything is in reference pixels (image coordinates, y down).
"""
import json, sys
import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage
from skimage import measure
sys.path.insert(0, __file__.rsplit("/", 1)[0])
import snakefit as sf

ref_path, out_dir = sys.argv[1:3]
_, lab = sf.ref_labels(ref_path, 1.0)
# seed: a crown pixel (the eyes are dark navy, which the colour labels count as blue)
HEADS = {"yellow": dict(label=2, eye=(369, 336), seed=(405, 305), forward=-1),
         "blue": dict(label=1, eye=(1103, 324), seed=(1060, 300), forward=1)}


def smooth_closed(P, sigma):
    return np.column_stack([ndimage.gaussian_filter1d(P[:, k], sigma, mode="wrap") for k in (0, 1)])


def resample_closed(P, step=1.0):
    Q = np.vstack([P, P[:1]])
    d = np.r_[0, np.cumsum(np.linalg.norm(np.diff(Q, axis=0), axis=1))]
    t = np.arange(0, d[-1], step)
    return np.column_stack([np.interp(t, d, Q[:, k]) for k in (0, 1)])


out = {}
vis = Image.open(ref_path).convert("RGB")
dr = ImageDraw.Draw(vis)
for name, h in HEADS.items():
    cc, _ = ndimage.label(lab == h["label"])
    comp = cc == cc[h["seed"][1], h["seed"][0]]
    comp = ndimage.binary_fill_holes(comp)
    # the outline: subpixel contour, smoothed over ~2.5 px, resampled at 1 px
    C = measure.find_contours(np.pad(comp, 2).astype(float), 0.5)
    C = max(C, key=len)[:, ::-1] - 2  # (x, y)
    C = resample_closed(smooth_closed(resample_closed(C), 2.5))
    n = len(C)
    T = np.gradient(C, axis=0); T /= np.linalg.norm(T, axis=1, keepdims=True)
    Nout = np.column_stack([T[:, 1], -T[:, 0]])  # outward if the contour runs anticlockwise in image coords
    probe = np.round(C + 4 * Nout).astype(int)
    inside = comp[np.clip(probe[:, 1], 0, comp.shape[0] - 1), np.clip(probe[:, 0], 0, comp.shape[1] - 1)]
    if inside.mean() > 0.5: Nout = -Nout
    probe = np.round(C + 4 * Nout).astype(int)
    beyond = lab[np.clip(probe[:, 1], 0, lab.shape[0] - 1), np.clip(probe[:, 0], 0, lab.shape[1] - 1)]
    outer = beyond == 0  # open silhouette; otherwise hidden by the other colour
    outer = ndimage.binary_opening(outer, iterations=3) | ndimage.binary_closing(outer, iterations=3) & outer
    # signed curvature (positive convex)
    dd = np.gradient(T, axis=0)
    kappa = (T[:, 0] * dd[:, 1] - T[:, 1] * dd[:, 0])
    kappa = ndimage.gaussian_filter1d(kappa, 3, mode="wrap")
    if np.sum(kappa) < 0: kappa = -kappa
    f = h["forward"] * C[:, 0]          # forward coordinate
    up = -C[:, 1]                       # up coordinate
    eye_up = -h["eye"][1]
    L = {}
    o = np.nonzero(outer)[0]
    L["muzzle_front"] = int(o[np.argmax(f[o])])
    L["crown_top"] = int(o[np.argmax(up[o])])
    above = o[up[o] > eye_up - 5]
    L["crown_rear"] = int(above[np.argmin(f[above])])
    # the lower outline: from the muzzle front, the way that goes down, until the wrap hides it
    i0 = L["muzzle_front"]
    step = 1 if up[(i0 + 5) % n] < up[(i0 - 5) % n] else -1
    lower = []
    for k in range(n):
        i = (i0 + step * k) % n
        if not outer[i] and k > 10: break
        lower.append(i)
    lower = np.array(lower)
    # chin-to-throat: the first turn from convex to concave, past the snout's own curve
    conc = [i for j, i in enumerate(lower) if j > 15 and kappa[i] < -0.003]
    L["chin_throat"] = int(conc[0]) if conc else int(lower[len(lower) // 2])
    # muzzle underside: between the tip and the chin, where the outline runs most nearly
    # along the head (its tangent closest to horizontal)
    seg = lower[: list(lower).index(L["chin_throat"])]
    seg = seg[10:] if len(seg) > 20 else seg
    L["muzzle_under"] = int(seg[np.argmin(np.abs(T[seg, 1]))])
    lower_path = lower
    # the occlusion boundary: the longest run of hidden contour; its two ends are where the
    # neck enters beneath the wrap
    hid = ~outer
    runs, cur = [], []
    for i in list(range(n)) + list(range(n)):
        if hid[i % n]: cur.append(i % n)
        elif cur: runs.append(cur); cur = []
    run = max(runs, key=len)
    L["neck_entry_a"], L["neck_entry_b"] = int(run[0]), int(run[-1])
    # the visible neck: rows between the chin and the top of the occlusion boundary;
    # front and back edges, midline and width per row
    # the exposed neck runs from the chin down to the lower end of the wrap's boundary
    y_top = C[L["chin_throat"], 1]
    y_bot = max(C[L["neck_entry_a"], 1], C[L["neck_entry_b"], 1])
    rows = []
    for y in range(int(np.ceil(y_top)), int(np.floor(y_bot))):
        xs = np.nonzero(comp[y])[0]
        if len(xs) < 5: continue
        rows.append((y, xs.min(), xs.max()))
    rows = np.array(rows, float)
    widths = rows[:, 2] - rows[:, 1]
    j = int(np.argmin(widths))
    L_throat = (float((rows[j, 1] + rows[j, 2]) / 2), float(rows[j, 0]))
    # head axis: from the rear crown, at the head's mid height there, to the muzzle front
    tip = C[L["muzzle_front"]]
    rear = C[L["crown_rear"]].copy()
    # mid height at the rear: halfway between the crown's rear point and the chin's height
    rear[1] = 0.5 * (C[L["crown_rear"], 1] + C[L["chin_throat"], 1])
    d = tip - rear; Lh = float(np.linalg.norm(d)); d /= Lh
    nup = np.array([d[1], -d[0]]) if (d[1] * 1 + -d[0] * 0) * 0 == 0 else None
    nup = np.array([-d[1], d[0]]); nup = nup if nup[1] < 0 else -nup   # perpendicular, pointing up (image y down)
    # profiles: for t along the axis, the top and bottom of the component on that cross line
    ts = np.linspace(0, 1, 61)
    prof = []
    for t in ts:
        base = rear + d * t * Lh
        vs = np.arange(-160, 160, 0.5)
        pts = base[None] + vs[:, None] * nup[None]
        xi, yi = np.round(pts[:, 0]).astype(int), np.round(pts[:, 1]).astype(int)
        ok = (xi >= 0) & (xi < comp.shape[1]) & (yi >= 0) & (yi < comp.shape[0])
        ins = np.zeros(len(vs), bool); ins[ok] = comp[yi[ok], xi[ok]]
        # the run of inside samples containing (or nearest) the axis
        if not ins.any(): prof.append((t, np.nan, np.nan)); continue
        idx = np.nonzero(ins)[0]
        groups = np.split(idx, np.nonzero(np.diff(idx) > 1)[0] + 1)
        g = min(groups, key=lambda g: abs(vs[g]).min())
        prof.append((t, float(vs[g].max()), float(vs[g].min())))
    prof = np.array(prof)
    out[name] = dict(
        contour=C.round(2).tolist(), outer=outer.tolist(), kappa=kappa.round(5).tolist(),
        landmarks={k: [float(C[i, 0]), float(C[i, 1])] for k, i in L.items()} | {"throat_narrowest": list(L_throat)},
        throat_width=float(widths[j]), neck_rows=rows.tolist(),
        axis=dict(rear=rear.tolist(), tip=tip.tolist(), length=Lh, dir=d.tolist(), up=nup.tolist()),
        profile=prof.tolist(), eye=list(h["eye"]))
    # draw
    dr.line([tuple(p) for p in C[outer]], fill=(220, 0, 0), width=1)
    for i in np.nonzero(~outer)[0]: dr.point(tuple(C[i]), fill=(0, 160, 0))
    for k, (x, y) in out[name]["landmarks"].items():
        dr.ellipse([x - 4, y - 4, x + 4, y + 4], outline=(0, 0, 0), width=2); dr.text((x + 6, y - 6), k, fill=(0, 0, 0))
    dr.line([tuple(rear), tuple(tip)], fill=(120, 0, 160), width=1)
    for t, top, bot in prof:
        if np.isnan(top): continue
        base = rear + d * t * Lh
        dr.point(tuple(base + top * nup), fill=(0, 0, 255)); dr.point(tuple(base + bot * nup), fill=(255, 0, 255))
    mid = np.column_stack([(rows[:, 1] + rows[:, 2]) / 2, rows[:, 0]])
    dr.line([tuple(p) for p in mid], fill=(255, 128, 0), width=2)
    print(name, "head length", round(Lh), "axis angle", round(float(np.degrees(np.arctan2(-d[1], d[0]))), 1),
          "throat width", round(float(widths[j]), 1), "landmarks", {k: [round(v[0]), round(v[1])] for k, v in out[name]["landmarks"].items()})
json.dump(out, open(f"{out_dir}/headref.json", "w"))
for name, box in (("yellow", (270, 260, 560, 560)), ("blue", (890, 250, 1190, 560))):
    vis.crop(box).resize(((box[2] - box[0]) * 2, (box[3] - box[1]) * 2), Image.LANCZOS).save(f"{out_dir}/headref-{name}.png")
