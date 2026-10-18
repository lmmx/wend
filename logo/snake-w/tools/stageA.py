"""Stage A: a well-conditioned head field with the same zero set. Compares three fields:
  base   the current estimate (rho - 1) * min(rz, (u - l) / 2);
  norm   base / max(|grad base|, 0.2), the first-order distance correction, guarded;
  exact  the distance to the swept surface itself, from a dense sampling of the surface in
         (t, phi), with the sign of base.
Measured where it matters: near the zero set at the blue rear point (the nape), at both snout
poles, and on the cheek as a control; the blend at the blue nape; and the error surface nets
would make placing vertices on 2.5 px grid edges near the poles.
"""
import json, sys
import numpy as np
from scipy.spatial import cKDTree
from scipy import ndimage
from skimage import measure
sys.path.insert(0, __file__.rsplit("/", 1)[0])
import snakefit as sf
import headmodel as hm

p = json.load(open(sys.argv[1]))
e = np.radians(p["cam"]["elev"])
k_blend = p.get("neck_blend", 12.0)
smin = lambda a, b, k: np.minimum(a, b) - np.maximum(k - np.abs(a - b), 0) ** 2 / (4 * k)
m = sf.build(p, 3000); s = m["s"]; L = s[-1]
sw = np.asarray(p.get("swell", [1.0]), float)
g = lambda x: np.interp(x, np.linspace(0, L, len(sw)), sw)
to_w = lambda P: np.column_stack([P[:, 0], -P[:, 1] / np.cos(e), np.zeros(len(P))])
to_img = lambda W: np.column_stack([W[:, 0], -(W[:, 1] * np.cos(e) - W[:, 2] * np.sin(e))])


def surface_samples(h, nt=900, nphi=420):
    R0, d, n, Lh = hm.head_frame(h, e)
    sgrid = np.linspace(0, 1, nt)
    t = (1 - np.cos(np.pi * sgrid)) / 2                     # denser near both ends
    t = np.clip(t, 1e-6, 1 - 1e-6)
    u, l, rz = hm.head_profiles(h, t)
    mline = l + h["beta"] * (u - l); hu, hl = u - mline, mline - l
    phi = np.linspace(0, 2 * np.pi, nphi, endpoint=False)
    c, sn = np.cos(phi), np.sin(phi); q = h["q"]
    a_ = np.sign(c) * np.abs(c) ** (2 / q); b_ = np.sign(sn) * np.abs(sn) ** (2 / q)
    V = mline[:, None] + np.where(a_[None] >= 0, hu[:, None], hl[:, None]) * a_[None]
    Z = rz[:, None] * b_[None]
    X = R0[None, None] + d[None, None] * (t * Lh)[:, None, None] + n[None, None] * V[..., None] + np.array([0, 0, 1.0]) * Z[..., None]
    X = X.reshape(-1, 3)
    tips = np.vstack([R0, R0 + d * Lh])
    return np.vstack([X, tips])


class Fields:
    def __init__(self, h):
        self.h = h
        self.tree = cKDTree(surface_samples(h))
    def base(self, P): return hm.head_distance(self.h, e, P)
    def grad(self, f, P, eps=0.25):
        return np.column_stack([(f(P + dv) - f(P - dv)) / (2 * eps) for dv in np.eye(3) * eps])
    def norm(self, P):
        g_ = np.linalg.norm(self.grad(self.base, P, 0.5), axis=1)
        return self.base(P) / np.maximum(g_, 0.2)
    def meridian(self, P): return hm.head_distance_meridian(self.h, e, P)
    def sections(self, P): return hm.head_distance_sections(self.h, e, P, band=30.0)
    def exact(self, P):
        dist, _ = self.tree.query(P)
        return np.sign(self.base(P)) * dist


def band_points(F, centre, radius, n=6000, band=3.0, seed=0):
    rng = np.random.default_rng(seed)
    P = centre[None] + rng.normal(size=(n * 8, 3)) * radius
    d = F.exact(P)
    return P[np.abs(d) < band][:n]


def neck_parts(name):
    i = 0 if name == "yellow" else 1
    P, dd = (m["PY"], s) if name == "yellow" else (m["PB"], L - s)
    h, nk = p["head_profiles"][i], p["necks"][i]
    J, TJ, KJ = hm.strand_at(P, dd, nk["join_s"])
    rJ = float(p["a"] * g(nk["join_s"] if name == "yellow" else L - nk["join_s"]))
    return h, nk, J, TJ, KJ, rJ


report = {}
for name in ("yellow", "blue"):
    h, nk, J, TJ, KJ, rJ = neck_parts(name)
    F = Fields(h)
    R0, d, n, Lh = hm.head_frame(h, e)
    rep = {}
    for region, centre, rad in (("rear point", R0, 12.0), ("snout pole", R0 + d * Lh, 10.0), ("cheek (control)", R0 + d * 0.55 * Lh + np.array([0, 0, 1.0]) * 45, 12.0)):
        P = band_points(F, centre, rad)
        row = {}
        for fname in ("base", "norm", "sections", "exact"):
            f = getattr(F, fname)
            gm = np.linalg.norm(F.grad(f, P), axis=1)
            # value against the true distance, in the band
            err = np.abs(f(P) - F.exact(P))
            row[fname] = dict(grad_median=round(float(np.median(gm)), 2), grad_p95=round(float(np.percentile(gm, 95)), 2),
                              grad_max=round(float(gm.max()), 2), value_err_p95_px=round(float(np.percentile(err, 95)), 2))
        rep[region] = row
    # surface-nets vertex placement near the snout pole and the rear point: edges of a 2.5 px
    # grid crossing the surface; linear interpolation of the field against the true crossing
    for region, centre in (("snout pole", R0 + d * Lh), ("rear point", R0)):
        rng = np.random.default_rng(1)
        starts = centre[None] + rng.uniform(-12, 12, size=(40000, 3))
        out = {}
        for fname in ("base", "norm", "sections", "exact"):
            f = getattr(F, fname)
            errs = []
            for ax in range(3):
                a = starts; b = starts + np.eye(3)[ax] * 2.5
                fa, fb = f(a), f(b)
                cross = (fa < 0) != (fb < 0)
                if not cross.any(): continue
                tl = fa[cross] / (fa[cross] - fb[cross])
                # true crossing: bisection on the sign of base (the zero set all three share)
                lo_, hi_ = np.zeros(cross.sum()), np.ones(cross.sum())
                A, B = a[cross], b[cross]; sa = np.sign(F.base(A))
                for _ in range(30):
                    mid = (lo_ + hi_) / 2
                    sm = np.sign(F.base(A + (B - A) * mid[:, None]))
                    same = sm == sa
                    lo_ = np.where(same, mid, lo_); hi_ = np.where(same, hi_, mid)
                errs.append(np.abs(tl - (lo_ + hi_) / 2) * 2.5)
            errs = np.concatenate(errs)
            out[fname] = dict(mean_px=round(float(errs.mean()), 3), p99_px=round(float(np.percentile(errs, 99)), 3), max_px=round(float(errs.max()), 3))
        rep[f"surface-nets crossing error near {region}"] = out
    # the blend at the blue nape: the blended outline in the picture plane, per field
    if name == "blue":
        R0i = to_img(R0[None])[0]
        Cn, rn = hm.neck_curve(nk, h, e, J, TJ, KJ, rJ + 0.3, n=160); c = to_img(Cn)
        win, step = 30.0, 0.2
        xs, ys = np.meshgrid(np.arange(R0i[0] - win, R0i[0] + win, step), np.arange(R0i[1] - win, R0i[1] + win, step))
        Q = np.column_stack([xs.ravel(), ys.ravel()])
        nd = (np.linalg.norm(Q[:, None] - c[None], axis=2) - rn[None]).min(1)
        blend = {}
        for fname in ("base", "norm", "sections", "exact"):
            hd = getattr(F, fname)(to_w(Q))
            Fu = smin(hd, nd, k_blend).reshape(xs.shape)
            cont = max(measure.find_contours(Fu, 0.0), key=len)[:, ::-1] * step + [R0i[0] - win, R0i[1] - win]
            dd_ = np.r_[0, np.cumsum(np.linalg.norm(np.diff(cont, axis=0), axis=1))]
            tt = np.arange(0, dd_[-1], 0.25); C2 = np.column_stack([np.interp(tt, dd_, cont[:, k]) for k in (0, 1)])[20:-20]
            d1 = np.gradient(C2, 0.25, axis=0); d2 = np.gradient(d1, 0.25, axis=0)
            kap = np.abs(d1[:, 0] * d2[:, 1] - d1[:, 1] * d2[:, 0]) / np.linalg.norm(d1, axis=1) ** 3
            Cs = np.column_stack([ndimage.gaussian_filter1d(C2[::4, k], 2.5, mode="nearest") for k in (0, 1)])
            e1 = np.gradient(Cs, axis=0); e2 = np.gradient(e1, axis=0)
            ks = np.abs(e1[:, 0] * e2[:, 1] - e1[:, 1] * e2[:, 0]) / np.linalg.norm(e1, axis=1) ** 3
            # where the blend acts: along the outline, the stretch with |head - neck| < k
            act = np.abs(getattr(F, fname)(to_w(C2)) - (np.linalg.norm(C2[:, None] - c[None], axis=2) - rn[None]).min(1)) < k_blend
            blend[fname] = dict(fillet_radius_px=round(float(1 / kap.max()), 2), peak_curvature_raw=round(float(kap.max()), 3),
                                peak_curvature_smoothed_like_reference=round(float(ks[3:-3].max()), 4),
                                blend_active_length_px=round(float(act.sum() * 0.25), 1))
        rep["blend at the nape"] = blend
    report[name] = rep
print(json.dumps(report, indent=1))
