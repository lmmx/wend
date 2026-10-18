"""Fit a two-snake double-helix W to the reference image's colour labels.

World units are reference pixels; x right, y up (y = -image_y), z towards the camera.
Everything is a canal surface (balls along a curve), splatted orthographically with a
z-buffer, so the label image (0 background, 1 blue, 2 yellow) is cheap to compute.
"""
import json, sys
import numpy as np
from PIL import Image
from scipy import ndimage, optimize

SCALE = 1 / 4  # fit resolution relative to the reference

def bspline(ctrl, n):
    """Clamped uniform cubic B-spline through the end points, sampled at n parameters."""
    P = np.vstack([ctrl[:1], ctrl[:1], ctrl, ctrl[-1:], ctrl[-1:]])
    segs = len(P) - 3
    t = np.linspace(0, segs, n, endpoint=False)
    t = np.append(t, segs - 1e-9)
    i = np.minimum(t.astype(int), segs - 1); u = (t - i)[:, None]
    b0 = (1 - u) ** 3 / 6; b1 = (3 * u**3 - 6 * u**2 + 4) / 6
    b2 = (-3 * u**3 + 3 * u**2 + 3 * u + 1) / 6; b3 = u**3 / 6
    return b0 * P[i] + b1 * P[i + 1] + b2 * P[i + 2] + b3 * P[i + 3]

def resample(C, n):
    """Resample a polyline at n points equally spaced in arc length; return points and arc lengths."""
    d = np.r_[0, np.cumsum(np.linalg.norm(np.diff(C, axis=0), axis=1))]
    s = np.linspace(0, d[-1], n)
    return np.column_stack([np.interp(s, d, C[:, k]) for k in range(C.shape[1])]), s

HEAD_KEYS = ("x", "y", "angle", "k1", "k2", "junction")
CONE_KEYS = ("bx", "by", "rb", "sx", "sy", "rs", "cut")

def apply_heads(P, hc):
    """Replace each end of the spine polyline (image coords) with a cubic Bezier from a junction
    on the neck to the snout centre: the head's own spine, smoother than the medial axis."""
    def bez(A, tA, h):
        tip = np.array([h["x"], h["y"]]); ang = np.radians(h["angle"])
        tT = np.array([np.cos(ang), np.sin(ang)])
        B = [A, A + tA * h["k1"], tip - tT * h["k2"], tip]
        u = np.linspace(0, 1, 120)[:, None]
        return (1 - u) ** 3 * B[0] + 3 * (1 - u) ** 2 * u * B[1] + 3 * (1 - u) * u**2 * B[2] + u**3 * B[3]
    d = np.r_[0, np.cumsum(np.linalg.norm(np.diff(P, axis=0), axis=1))]
    j0 = int(np.searchsorted(d, hc[0]["junction"])); j1 = int(np.searchsorted(d, d[-1] - hc[1]["junction"]))
    t0 = P[max(j0 - 4, 0)] - P[j0]; t0 /= np.linalg.norm(t0)
    t1 = P[min(j1 + 4, len(P) - 1)] - P[j1]; t1 /= np.linalg.norm(t1)
    left = bez(P[j0], t0, hc[0])[::-1]
    right = bez(P[j1], t1, hc[1])
    return np.vstack([left[:-1], P[j0:j1 + 1], right[1:]])

def pchip_slopes(x, y):
    """Fritsch-Carlson slopes: a monotone cubic through (x, y), smooth at extrema."""
    h = np.diff(x); d = np.diff(y) / h
    m = np.zeros(len(x))
    m[0], m[-1] = d[0], d[-1]
    for i in range(1, len(x) - 1):
        if d[i - 1] * d[i] <= 0: m[i] = 0.0
        else:
            w1, w2 = 2 * h[i] + h[i - 1], h[i] + 2 * h[i - 1]
            m[i] = (w1 + w2) / (w1 / d[i - 1] + w2 / d[i])
    return m

def pchip(x, y, t, m=None):
    m = pchip_slopes(x, y) if m is None else m
    i = np.clip(np.searchsorted(x, t) - 1, 0, len(x) - 2)
    h = x[i + 1] - x[i]; u = np.clip((t - x[i]) / h, 0, 1)
    h00 = 2 * u**3 - 3 * u**2 + 1; h10 = u**3 - 2 * u**2 + u; h01 = -2 * u**3 + 3 * u**2; h11 = u**3 - u**2
    return h00 * y[i] + h10 * h * m[i] + h01 * y[i + 1] + h11 * h * m[i + 1]

def smoothstep(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0, 1)
    return t * t * (3 - 2 * t)

def build(p, n=1400):
    """Sample both snakes. Returns centres (m,3), radii (m,), labels (m,)."""
    if "polyline" in p:  # a spine read off the reference, image coordinates
        P = np.asarray(p["polyline"], float)
        if "head_curves" in p: P = apply_heads(P, p["head_curves"])
        C, s = resample(np.column_stack([P[:, 0], -P[:, 1], np.zeros(len(P))]), n)
    else:
        ctrl = np.asarray(p["spine"], float)  # (k, 3): x, y, z
        C, s = resample(bspline(ctrl, 4000), n)
    L = s[-1]
    T = np.gradient(C, axis=0); T /= np.linalg.norm(T, axis=1, keepdims=True)
    if "spine_offsets" in p:  # smooth in-plane displacement of the spine, knots evenly along it
        off = np.asarray(p["spine_offsets"], float)
        kn = np.linspace(0, L, len(off))
        nrm = np.column_stack([-T[:, 1], T[:, 0], np.zeros(len(T))])
        C = C + np.interp(s, kn, off)[:, None] * nrm
        C, s = resample(C, n); L = s[-1]
        T = np.gradient(C, axis=0); T /= np.linalg.norm(T, axis=1, keepdims=True)
    # parallel-transport frame, seeded with the view direction z
    N = np.zeros_like(C); B = np.zeros_like(C)
    b = np.array([0, 0, 1.0]); b = b - T[0] * (b @ T[0]); b /= np.linalg.norm(b)
    for i in range(n):
        if i:
            b = b - T[i] * (b @ T[i]); b /= np.linalg.norm(b)
        B[i] = b; N[i] = np.cross(b, T[i])
    # twist: piecewise-linear rate in turns per unit length, knots spread over [s0, s1]
    s0, s1 = p["helix"]  # fractions of L where the two necks leave the helix
    rate = np.asarray(p["rate"], float)  # turns per 100 px at evenly spaced knots
    knots = np.linspace(s0 * L, s1 * L, len(rate))
    k = np.interp(s, knots, rate) / 100.0
    theta = p["theta0"] + 2 * np.pi * np.r_[0, np.cumsum((k[1:] + k[:-1]) / 2 * np.diff(s))]
    if "anchor_xy" in p:  # anchors at image points: each lobe's centre, projected onto the spine
        e = np.radians(p["cam"]["elev"])
        img = np.column_stack([C[:, 0], -(C[:, 1] * np.cos(e) - C[:, 2] * np.sin(e))])
        p = dict(p, anchors=[[float(s[np.argmin(((img - [x, y]) ** 2).sum(1))]), th] for x, y, th in p["anchor_xy"]])
    anchor_s = None
    if "anchors" in p:  # theta pinned at arc lengths, linear between, end slopes beyond
        A = np.asarray(p["anchors"], float).copy()
        A[:, 0] += p.get("anchor_shift", 0.0)
        if "anchor_offsets" in p: A[:, 0] += np.asarray(p["anchor_offsets"], float)
        anchor_s = A[:, 0].copy()
        order = np.argsort(A[:, 0]); A = A[order]
        mm = pchip_slopes(A[:, 0], A[:, 1]); rev = None
        if "reversal" in p:  # the twist reversal as a rounded V (as in geometry.js)
            kr = int(np.nonzero(order == p["reversal"]["anchor"])[0][0]); wr = p["reversal"]["w"]
            (ra, ta), (rc, tc), (rb, tb) = A[kr - 1], A[kr], A[kr + 1]
            c1 = (tc - ta) / (np.hypot(rc - ra, wr) - wr); c2 = (tc - tb) / (np.hypot(rb - rc, wr) - wr)
            mm[kr - 1] = c1 * (rc - ra) / np.hypot(rc - ra, wr); mm[kr + 1] = -c2 * (rb - rc) / np.hypot(rb - rc, wr)
            rev = (ra, rb, rc, tc, c1, c2, wr)
        theta = pchip(A[:, 0], A[:, 1], s, mm)
        if rev:  # (names kept apart from s0, s1 above: those are the necks' helix bounds)
            ra, rb, rc, tc, c1, c2, wr = rev
            inside = (s > ra) & (s < rb)
            theta[inside] = tc - np.where(s[inside] < rc, c1, c2) * (np.hypot(s[inside] - rc, wr) - wr)
        lo, hi = s < A[0, 0], s > A[-1, 0]
        m0 = (A[1, 1] - A[0, 1]) / (A[1, 0] - A[0, 0]); m1 = (A[-1, 1] - A[-2, 1]) / (A[-1, 0] - A[-2, 0])
        theta[lo] = A[0, 1] + m0 * (s[lo] - A[0, 0]); theta[hi] = A[-1, 1] + m1 * (s[hi] - A[-1, 0])
    u = np.cos(theta)[:, None] * N + np.sin(theta)[:, None] * B
    a, R = p["a"], p["R"]
    if "swell" in p:  # thickness profile along the spine: scales both radius and offset
        sw = np.asarray(p["swell"], float)
        g = np.interp(s, np.linspace(0, L, len(sw)), sw)
        a, R = a * g, R * g
        u = u * 1.0
    # yellow's head is at s=0, blue's at s=L. Near each head the pair shifts so the
    # head snake moves onto the spine and the tail snake wraps around its neck.
    wY = 1 - smoothstep(s0 * L - p["neck"], s0 * L + p["neck"] * 0.3, s)  # 1 at yellow neck
    wB = smoothstep(s1 * L - p["neck"] * 0.3, s1 * L + p["neck"], s)       # 1 at blue neck
    shift = ((wY - wB) * R)[:, None] * u if np.ndim(R) else (wY - wB)[:, None] * R * u
    Ru = (np.asarray(R)[:, None] if np.ndim(R) else R) * u
    PY = C - Ru + shift
    PB = C + Ru + shift
    if p.get("wrap"):  # the tail circles the neck further out than the rope's squeezed spacing
        e = 2 * p["wrap"] * Ru
        PB = PB + wY[:, None] * e; PY = PY - wB[:, None] * e
    # radii: heads swell; tails end where they disappear behind the necks
    hY, hB = p["head_len"]
    rY = a * (1 + (p["head_r"] - 1) * smoothstep(hY + 40, hY - 10, s))
    rB = a * (1 + (p["head_r"] - 1) * smoothstep(L - hB - 40, L - hB + 10, s))
    if "heads" in p:  # radius profile from the snout: rs at the snout, rm at dm, back to 1 at dn
        def prof(d, h):
            return np.where(d < h["dm"], h["rs"] + (h["rm"] - h["rs"]) * smoothstep(0, h["dm"], d),
                            h["rm"] + (1 - h["rm"]) * smoothstep(h["dm"], h["dn"], d))
        rY = a * prof(s, p["heads"][0]); rB = a * prof(L - s, p["heads"][1])
    if p.get("bead"):  # fattest mid-lobe, thinner at the sides; faded out at the necks
        w = np.clip(1 - (1 - wY) * 0 - wY - wB, 0, 1)
        bd = 1 + p["bead"] * w * (np.sin(theta) ** 2 - 0.5)
        rY = rY * bd; rB = rB * bd
    if p.get("lobes") and anchor_s is not None:  # per-lobe fullness (as in geometry.js)
        for lb in p["lobes"]:
            f = 1 + (lb["f"] - 1) * np.exp(-((s - anchor_s[lb["anchor"]]) / lb["w"]) ** 2)
            if lb["strand"] == "yellow": rY = rY * f
            else: rB = rB * f
    tailB, tailY = p["tail"]  # arc-length where each tail ends (blue near s=0, yellow near L)
    mB = s >= tailB; mY = s <= L - tailY
    tb = np.clip((s - tailB) / 30, 0, 1); ty = np.clip((L - tailY - s) / 30, 0, 1)
    rB = np.where(mB, rB * (0.75 + 0.25 * tb), 0); rY = np.where(mY, rY * (0.75 + 0.25 * ty), 0)
    # end caps, as the meshes draw them: past each end along the end tangent, with a
    # superelliptic profile (blunt snouts, round tails)
    snoutLen, snoutQ = p.get("snout", [1.0, 2.2])
    def cap(P, r, at, inward, length, q, label):
        t0 = P[at] - P[at + inward * 3]; t0 = t0 / np.linalg.norm(t0)
        ell = length * r[at]
        tt = np.linspace(0, ell, 12)[1:]
        prof = np.clip(1 - (tt / ell) ** q, 0, 1) ** (1 / q)
        return P[at] + tt[:, None] * t0, r[at] * prof, np.full(len(tt), label)
    if "head_cones" in p:
        # heads as round cones (back B to snout S, image coords), the neck strand cut at
        # `cut` from its snout end; the mesh blends the two with a smooth union
        e = np.radians(p["cam"]["elev"])
        caps = [cap(PY, rY, np.nonzero(mY)[0][-1], -1, 1.0, 2.0, 2), cap(PB, rB, np.nonzero(mB)[0][0], 1, 1.0, 2.0, 1)]
        for h, lab_, m, d in ((p["head_cones"][0], 2, mY, s), (p["head_cones"][1], 1, mB, L - s)):
            m &= d >= h["cut"]
            Bw = np.array([h["bx"], -h["by"] / np.cos(e), 0.0]); Sw = np.array([h["sx"], -h["sy"] / np.cos(e), 0.0])
            u = np.linspace(0, 1, 30)[:, None]
            caps.append((Bw + (Sw - Bw) * u, (h["rb"] + (h["rs"] - h["rb"]) * u[:, 0]), np.full(30, lab_)))
    else:
        iY = np.nonzero(mY)[0]; iB = np.nonzero(mB)[0]
        caps = [cap(PY, rY, iY[0], 1, snoutLen, snoutQ, 2), cap(PY, rY, iY[-1], -1, 1.0, 2.0, 2),
                cap(PB, rB, iB[-1], -1, snoutLen, snoutQ, 1), cap(PB, rB, iB[0], 1, 1.0, 2.0, 1)]
    centres = np.vstack([PY[mY], PB[mB]] + [c[0] for c in caps])
    radii = np.r_[rY[mY], rB[mB], np.concatenate([c[1] for c in caps])]
    labels = np.r_[np.full(mY.sum(), 2), np.full(mB.sum(), 1), np.concatenate([c[2] for c in caps])]
    return dict(C=C, s=s, centres=centres, radii=radii, labels=labels, PY=PY, PB=PB, u=u, theta=theta, rY=rY, rB=rB, anchor_s=anchor_s)

def project(X, cam):
    """Orthographic view with the camera raised by `elev` degrees: screen (x, y_img), depth."""
    e = np.radians(cam["elev"])
    yv = X[:, 1] * np.cos(e) - X[:, 2] * np.sin(e)
    depth = X[:, 1] * np.sin(e) + X[:, 2] * np.cos(e)
    return np.column_stack([X[:, 0], -yv]), depth

def splat(sx, depth, r, labels, shape, scale):
    """z-buffered ball splatting at the given scale; returns label image."""
    H, W = shape
    zb = np.full(H * W, -np.inf); lab = np.zeros(H * W, np.int8)
    rr = r * scale; cx = sx[:, 0] * scale; cy = sx[:, 1] * scale; dz = depth * scale
    R = int(np.ceil(rr.max())) + 1
    oy, ox = np.mgrid[-R:R + 1, -R:R + 1]; oy = oy.ravel(); ox = ox.ravel()
    px = np.floor(cx)[:, None].astype(int) + ox[None]; py = np.floor(cy)[:, None].astype(int) + oy[None]
    d2 = (px + 0.5 - cx[:, None]) ** 2 + (py + 0.5 - cy[:, None]) ** 2
    inside = (d2 < rr[:, None] ** 2) & (px >= 0) & (px < W) & (py >= 0) & (py < H)
    z = dz[:, None] + np.sqrt(np.maximum(rr[:, None] ** 2 - d2, 0))
    idx = (py * W + px)[inside]; zz = z[inside]; ll = np.broadcast_to(labels[:, None], z.shape)[inside]
    order = np.lexsort((zz, idx))
    idx, zz, ll = idx[order], zz[order], ll[order]
    last = np.r_[idx[1:] != idx[:-1], True]
    zb[idx[last]] = zz[last]; lab[idx[last]] = ll[last]
    return lab.reshape(H, W), zb.reshape(H, W)

def render_labels(p, shape, scale, n=1400):
    m = build(p, n)
    sx, depth = project(m["centres"], p["cam"])
    sx = sx * p["cam"]["zoom"] + np.array(p["cam"]["offset"])
    lab, zb = splat(sx, depth, m["radii"] * p["cam"]["zoom"], m["labels"], shape, scale)
    return lab, m

def ref_labels(path, scale):
    im = np.asarray(Image.open(path).convert("RGB")).astype(float)
    r, g, b = im[..., 0], im[..., 1], im[..., 2]
    mx = im.max(-1); mn = im.min(-1); sat = (mx - mn) / np.maximum(mx, 1)
    blue = (b > r + 40) & (b > g + 20) & (sat > 0.35)
    yellow = (r > b + 60) & (g > b + 40) & (sat > 0.35)
    dark = mx < 90
    lab = np.zeros(im.shape[:2], np.int8); lab[blue] = 1; lab[yellow] = 2
    # dark creases and eyes take the label of their surroundings
    obj = ndimage.binary_fill_holes(ndimage.binary_closing(blue | yellow | dark, iterations=3))
    obj = ndimage.binary_opening(obj, iterations=2)
    near = ndimage.distance_transform_edt(lab == 0, return_indices=True)[1]
    filled = lab[near[0], near[1]]
    lab = np.where(obj, filled, 0).astype(np.int8)
    H, W = int(im.shape[0] * scale), int(im.shape[1] * scale)
    small = np.asarray(Image.fromarray(lab).resize((W, H), Image.NEAREST))
    return small, lab

# ---------------------------------------------------------------- fitting

def initial():
    img = [(305, 334), (370, 328), (428, 332), (418, 400), (440, 470), (482, 600), (535, 735),
           (612, 700), (640, 560), (690, 440), (770, 450), (850, 650), (915, 745), (985, 625),
           (1030, 480), (1052, 392), (1048, 312), (1100, 296), (1162, 318)]
    return {
        "spine": [[x, -y, 0.0] for x, y in img],
        "helix": [0.13, 0.87],
        "rate": [0.6, 0.6, 0.6, 0.5, 0.0, -0.5, -0.6, -0.6, -0.6],
        "theta0": 0.0, "a": 33.0, "R": 33.0, "neck": 80.0,
        "head_r": 1.3, "head_len": [120.0, 120.0], "tail": [200.0, 200.0],
        "cam": {"elev": 8.0, "zoom": 1.0, "offset": [0.0, 0.0]},
    }

FREE = ["spine_xy", "helix", "rate", "theta0", "a", "R", "neck", "head_r", "head_len", "tail", "elev"]

def pack(p, free):
    v = []
    for f in free:
        if f == "spine_xy": v += [c for xy in p["spine"] for c in xy[:2]]
        elif f == "elev": v.append(p["cam"]["elev"])
        elif f == "heads": v += [h[k] for h in p["heads"] for k in ("rs", "rm", "dm", "dn")]
        elif f == "head_curves": v += [h[k] for h in p["head_curves"] for k in HEAD_KEYS]
        elif f == "head_cones": v += [h[k] for h in p["head_cones"] for k in CONE_KEYS]
        elif isinstance(p[f], list): v += list(p[f])
        else: v.append(p[f])
    return np.array(v, float)

def unpack(v, p, free):
    q = json.loads(json.dumps(p)); i = 0
    for f in free:
        if f == "spine_xy":
            for xy in q["spine"]: xy[0], xy[1] = v[i], v[i + 1]; i += 2
        elif f == "elev": q["cam"]["elev"] = v[i]; i += 1
        elif f == "head_cones":
            for h in q["head_cones"]:
                for k in CONE_KEYS: h[k] = v[i]; i += 1
        elif f == "head_curves":
            for h in q["head_curves"]:
                for k in HEAD_KEYS: h[k] = v[i]; i += 1
        elif f == "heads":
            for h in q["heads"]:
                for k in ("rs", "rm", "dm", "dn"): h[k] = v[i]; i += 1
        elif isinstance(q[f], list): k = len(q[f]); q[f] = list(v[i:i + k]); i += k
        else: q[f] = v[i]; i += 1
    return q

class Loss:
    def __init__(self, ref_small, scale, sil=False, pen=None):
        self.pen = pen
        if sil: ref_small = (ref_small > 0).astype(np.int8)
        self.sil = sil
        self.ref = ref_small; self.scale = scale
        self.dref = {c: ndimage.distance_transform_edt(ref_small != c) for c in (1, 2)}
        self.dbg = ndimage.distance_transform_edt(ref_small == 0)
    def __call__(self, p, n=900):
        lab, _ = render_labels(p, self.ref.shape, self.scale, n)
        if self.sil: lab = (lab > 0).astype(np.int8)
        tot = 0.0
        for c in ((1,) if self.sil else (1, 2)):
            mm = lab == c; rm = self.ref == c
            if not mm.any(): return 1e6
            dm = ndimage.distance_transform_edt(~mm)
            tot += self.dref[c][mm].mean() + dm[rm].mean()
        mis = (lab != self.ref).mean() * 100
        return tot + mis + (self.penalty(p) if self.pen else 0.0)

    def penalty(self, p, report=False):
        """Overlap between the strands beyond an allowed squeeze, and bends tighter than the tube."""
        from scipy.spatial import cKDTree
        m = build(p, 900)
        a = p["a"]; squeeze = self.pen["squeeze"]
        PY, PB, s = m["PY"], m["PB"], m["s"]
        L = s[-1]; body = (s > 160) & (s < L - 160)
        d, _ = cKDTree(PB[body]).query(PY[body])
        over = np.maximum(0, squeeze * 2 * a - d)
        bend = 0.0
        for P in (PY[body], PB[body]):
            t = np.gradient(P, axis=0); dd = np.gradient(t, axis=0)
            k = np.linalg.norm(np.cross(t, dd), axis=1) / np.maximum(np.linalg.norm(t, axis=1) ** 3, 1e-9)
            bend += (np.maximum(0, a * k - 0.9) ** 2).mean()
        val = self.pen["w_over"] * (over ** 2).mean() / a + self.pen["w_bend"] * bend
        if report: print(f"overlap mean {over.mean():.2f}px max {over.max():.1f}px, bend {bend:.4f}, penalty {val:.3f}")
        return val

def overlay(p, ref_full, path, scale=0.5):
    H, W = int(ref_full.shape[0] * scale), int(ref_full.shape[1] * scale)
    lab, m = render_labels(p, (H, W), scale, 2000)
    ref = np.asarray(Image.fromarray(ref_full).resize((W, H), Image.NEAREST))
    pal = np.array([[255, 255, 255], [40, 80, 220], [250, 200, 40]], np.uint8)
    a = pal[ref]; b = pal[lab]
    diff = np.full((H, W, 3), 255, np.uint8)
    diff[(ref != lab) & (ref > 0)] = [230, 60, 60]   # reference has colour, model differs
    diff[(ref != lab) & (ref == 0)] = [60, 160, 230]  # model spills onto background
    diff[(ref == lab) & (ref > 0)] = [200, 200, 200]
    # draw spine on the model panel
    sx, _ = project(m["C"], p["cam"]); sx = sx * p["cam"]["zoom"] + np.array(p["cam"]["offset"])
    for x, y in (sx * scale).astype(int)[::4]:
        if 0 <= x < W and 0 <= y < H: b[max(y-1,0):y+1, max(x-1,0):x+1] = [220, 0, 0]
    Image.fromarray(np.hstack([a, b, diff])).save(path)

if __name__ == "__main__":
    ref_path, out_dir = sys.argv[1], sys.argv[2]
    mode = sys.argv[3] if len(sys.argv) > 3 else "fit"
    start = sys.argv[4] if len(sys.argv) > 4 else None
    p = json.load(open(start)) if start and start != "-" else initial()
    small, full = ref_labels(ref_path, SCALE)
    loss = Loss(small, SCALE, sil=(mode == "fit" and len(sys.argv) > 7 and sys.argv[7] == "sil"))
    print("initial loss", round(loss(p), 3))
    overlay(p, full, f"{out_dir}/overlay-start.png")
    if mode == "fit":
        free = sys.argv[5].split(",") if len(sys.argv) > 5 else FREE
        v0 = pack(p, free)
        best = [loss(p), p]
        def f(v):
            q = unpack(v, p, free)
            if q["a"] <= 5 or q["R"] <= 5: return 1e6
            L = loss(q)
            if L < best[0]: best[0], best[1] = L, q
            return L
        iters = int(sys.argv[6]) if len(sys.argv) > 6 else 3
        for it in range(iters):
            res = optimize.minimize(f, pack(best[1], free), method="Powell",
                                    options={"maxfev": 4000, "xtol": 0.05, "ftol": 1e-4})
            print("pass", it, "loss", round(best[0], 3), flush=True)
            tag = sys.argv[8] if len(sys.argv) > 8 else "fit"
            json.dump(best[1], open(f"{out_dir}/{tag}.json", "w"), indent=1)
            overlay(best[1], full, f"{out_dir}/{tag}.png")
