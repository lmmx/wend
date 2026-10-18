"""Cross-sections and curvature of the heads and necks, from the analytic fields (headmodel.py).

Sections: perpendicular to the head axis at the muzzle, cheek and rear cranium; perpendicular
to the neck centreline at the upper and lower neck. In each: the head field's zero set
(magenta), the neck field's (cyan) and their smooth union, the mesh (black), with its
curvature. Also the curvature along the head (crown line and cheek line, against t, with the
Catmull-Rom knots marked), the end caps' sections as they close, and how far the head field is
from a distance near each end.
"""
import json, sys
import numpy as np
from PIL import Image, ImageDraw
from skimage import measure
sys.path.insert(0, __file__.rsplit("/", 1)[0])
import snakefit as sf
import headmodel as hm

params_path, out = sys.argv[1], sys.argv[2]
p = json.load(open(params_path))
e = np.radians(p["cam"]["elev"])
m = sf.build(p, 3000); s = m["s"]; L = s[-1]
sw = np.asarray(p.get("swell", [1.0]), float)
g = lambda x: np.interp(x, np.linspace(0, L, len(sw)), sw)
smin = lambda a, b, k: np.minimum(a, b) - np.maximum(k - np.abs(a - b), 0) ** 2 / (4 * k)
k_blend = p.get("neck_blend", 12.0)


def sd_round_cone(P, a, b, r1, r2):
    ba = b - a; l2 = ba @ ba; rr = r1 - r2; a2 = l2 - rr * rr; il2 = 1 / l2
    pa = P - a; y = pa @ ba; z = y - l2
    xv = pa * l2 - np.outer(y, ba); x2 = np.sum(xv * xv, 1); y2 = y * y * l2; z2 = z * z * l2
    k = np.sign(rr) * rr * rr * x2
    out = (np.sqrt(np.maximum(x2 * a2 * il2, 0)) + y * rr) * il2 - r1
    out = np.where(np.sign(y) * a2 * y2 < k, np.sqrt(x2 + y2) * il2 - r1, out)
    return np.where(np.sign(z) * a2 * z2 > k, np.sqrt(x2 + z2) * il2 - r2, out)


def neck_chain(name):
    i = 0 if name == "yellow" else 1
    P, dd = (m["PY"], s) if name == "yellow" else (m["PB"], L - s)
    h, nk = p["head_profiles"][i], p["necks"][i]
    J, TJ, KJ = hm.strand_at(P, dd, nk["join_s"])
    sJ = nk["join_s"] if name == "yellow" else L - nk["join_s"]
    rJ = float(p["a"] * g(sJ))
    C, r = hm.neck_curve(nk, h, e, J, TJ, KJ, rJ + 0.3, n=48)
    # the dive past J along the strand (as in geometry.js)
    order = np.argsort(dd); D = dd[order]; Pp = P[order]
    sl = np.r_[0, np.cumsum(np.linalg.norm(np.diff(Pp, axis=0), axis=1))]
    arcJ = np.interp(nk["join_s"], D, sl)
    extra_c, extra_r = [], []
    for past in np.arange(4, 30.1, 3.0):
        q = np.array([np.interp(arcJ + past, sl, Pp[:, k]) for k in range(3)])
        ss = np.interp(arcJ + past, sl, s[order] if name == "yellow" else s[order])
        extra_c.append(q); extra_r.append(rJ + 0.3 - 1.8 * min(1, (past / 30) ** 2 * (3 - 2 * past / 30)))
    C = np.vstack([C, extra_c]); r = np.r_[r, extra_r]
    return h, nk, C, r


def neck_d(Pts, C, r):
    return np.min([sd_round_cone(Pts, C[i], C[i + 1], r[i], r[i + 1]) for i in range(len(C) - 1)], axis=0)


def section(name, origin, e1, e2, half=80, step=0.25):
    h, nk, C, r = neck_chain(name)
    a, b = np.meshgrid(np.arange(-half, half, step), np.arange(-half, half, step))
    Pts = origin[None] + a.ravel()[:, None] * e1[None] + b.ravel()[:, None] * e2[None]
    hd = hm.head_distance(h, e, Pts).reshape(a.shape)
    nd = neck_d(Pts, C, r).reshape(a.shape)
    return a, b, hd, nd, smin(hd, nd, k_blend)


def curv_of(cnt, step):
    P = cnt * step
    d = np.r_[0, np.cumsum(np.linalg.norm(np.diff(P, axis=0), axis=1))]
    t = np.arange(0, d[-1], 0.5); P = np.column_stack([np.interp(t, d, P[:, k]) for k in (0, 1)])
    from scipy import ndimage
    P = np.column_stack([ndimage.gaussian_filter1d(P[:, k], 2, mode="wrap") for k in (0, 1)])
    d1 = np.gradient(P, 0.5, axis=0); d2 = np.gradient(d1, 0.5, axis=0)
    return P, (d1[:, 0] * d2[:, 1] - d1[:, 1] * d2[:, 0]) / np.maximum(np.linalg.norm(d1, axis=1) ** 3, 1e-9)


report = {}
tiles = []
for name in ("yellow", "blue"):
    h, nk, C, r = neck_chain(name)
    R0, d, n, Lh = hm.head_frame(h, e)
    z = np.array([0, 0, 1.0])
    stations = []
    for lab_, t in (("muzzle t=0.85", 0.85), ("cheek t=0.55", 0.55), ("rear cranium t=0.15", 0.15), ("rear cap t=0.04", 0.04), ("snout cap t=0.97", 0.97)):
        stations.append((lab_, R0 + d * t * Lh, n, z))       # section plane: up (v) and depth (z)
    for lab_, tau in (("upper neck", 0.25), ("lower neck", 0.7)):
        i = int(tau * 47)
        T = C[i + 1] - C[i - 1]; T /= np.linalg.norm(T)
        e1 = np.cross(z, T); e1 /= np.linalg.norm(e1); e2 = np.cross(T, e1)
        stations.append((lab_ + f" tau={tau}", C[i], e1, e2))
    report[name] = {}
    for lab_, o, e1, e2 in stations:
        a, b, hd, nd, F = section(name, o, e1, e2)
        S = 3
        im = Image.new("RGB", (a.shape[1] * S // 4, a.shape[0] * S // 4), "white"); dr = ImageDraw.Draw(im)
        X = lambda q: (q[1] * S / 4, im.height - q[0] * S / 4)
        # head axis (horizontal: the plane's first axis is up for head stations) - draw the zero sets
        stats = {}
        for field, col, w in ((hd, (200, 0, 200), 1), (nd, (0, 150, 255), 1), (F, (0, 0, 0), 2)):
            for cnt in measure.find_contours(field, 0.0):
                # (row, col) = (b index, a index); a is e1, b is e2
                dr.line([X((q[0], q[1])) for q in cnt], fill=col, width=w)
        cs = measure.find_contours(F, 0.0)
        if cs:
            cnt = max(cs, key=len)
            P, kap = curv_of(cnt[:, ::-1], 0.25)
            closed = np.linalg.norm(cnt[0] - cnt[-1]) < 2
            kk = kap[5:-5] if not closed else kap
            stats = dict(width_e1=round(float(np.ptp(P[:, 0])), 1), height_e2=round(float(np.ptp(P[:, 1])), 1),
                         curvature_min=round(float(np.abs(kk).min()), 4), curvature_max=round(float(np.abs(kk).max()), 4),
                         curvature_ratio_max_to_median=round(float(np.abs(kk).max() / np.median(np.abs(kk))), 1),
                         concave_fraction=round(float(np.mean(kk * np.sign(np.median(kk)) < 0)), 3))
        report[name][lab_] = stats
        dr.rectangle([0, 0, im.width, 30], fill=(255, 255, 255))
        dr.text((4, 2), f"{name} {lab_}", fill=(0, 0, 0))
        if stats: dr.text((4, 15), f"w {stats['width_e1']} h {stats['height_e2']}  curv min {stats['curvature_min']} max {stats['curvature_max']}", fill=(0, 0, 0))
        tiles.append(im)
    # longitudinal curvature: crown line (v = u, z = 0) and cheek line (v = m, z = rz), against t
    t = np.linspace(0.002, 0.998, 4000)
    u, l, rz = hm.head_profiles(h, t)
    mm = l + h["beta"] * (u - l)
    for lab_, v_, z_ in (("crown line", u, 0 * u), ("cheek line", mm, rz), ("jaw line", l, 0 * l)):
        X3 = R0[None] + d[None] * (t * Lh)[:, None] + n[None] * v_[:, None] + z[None] * z_[:, None]
        d1 = np.gradient(X3, axis=0); d2 = np.gradient(d1, axis=0)
        kap = np.linalg.norm(np.cross(d1, d2), axis=1) / np.linalg.norm(d1, axis=1) ** 3
        # jumps in curvature at the Catmull-Rom knots (t = k/6): C1 splines have discontinuous curvature there
        jumps = []
        for kn in np.arange(1, 6) / 6:
            i = np.searchsorted(t, kn)
            jumps.append(abs(kap[i + 6] - kap[i - 6]) / max(np.median(kap), 1e-9))
        report[name][lab_] = dict(curvature_median=round(float(np.median(kap)), 4),
                                  curvature_at_rear_end=round(float(kap[30]), 3), curvature_at_snout_end=round(float(kap[-30]), 3),
                                  max_knot_jump_relative=round(float(max(jumps)), 2))
    # how far the head field is from a distance near each end (|grad| should be 1)
    for lab_, tt in (("rear end", 0.01), ("snout end", 0.99)):
        o = R0 + d * tt * Lh
        pts = o[None] + np.random.default_rng(0).normal(size=(400, 3)) * 6
        G = np.column_stack([(hm.head_distance(h, e, pts + dv) - hm.head_distance(h, e, pts - dv)) / 0.04 for dv in np.eye(3) * 0.02])
        report[name][f"field gradient near {lab_}"] = dict(median=round(float(np.median(np.linalg.norm(G, axis=1))), 2), max=round(float(np.linalg.norm(G, axis=1).max()), 2))
print(json.dumps(report, indent=1))
cols = 7
Wt = max(t.width for t in tiles); Ht = max(t.height for t in tiles)
sheet = Image.new("RGB", (Wt * cols, Ht * 2), "white")
for i, t in enumerate(tiles): sheet.paste(t, ((i % cols) * Wt, (i // cols) * Ht))
sheet.save(out)
