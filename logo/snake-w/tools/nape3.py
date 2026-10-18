"""Is the nape kink in the geometry, or in the measurement?

The model's rear outline in the picture plane is made of three pieces:
  A. the head's upper outline, X(t) = R0 + d t Lh + n u(t), with u(t) = U(t) sqrt(t (1 - t)),
     U a Catmull-Rom curve through 7 control values; at t = 0 it closes through the rear
     point R0 with a tangent perpendicular to the head axis;
  B. the neck's back edge: the envelope of the discs of radius r(tau) centred on the projected
     quintic neck centreline c(tau);
  C. the junction: the zero set of the polynomial smooth minimum
     smin(a, b, k) = min(a, b) - max(k - |a - b|, 0)^2 / (4k), k = neck_blend, of A's and B's
     distance fields (the head's z = 0 section and the neck's projected discs).
This finds where A and B cross on the back of the head, their tangents there (the mismatch
the blend has to round off), and the curvature of the blended outline C, from the analytic
fields on a fine grid, compared with the reference at the same sampling and smoothing, and
with the same outline taken from the rendered pixels.
"""
import json, sys
import numpy as np
from scipy import ndimage
from skimage import measure
sys.path.insert(0, __file__.rsplit("/", 1)[0])
import snakefit as sf
import headmodel as hm
import importlib.util
spec = importlib.util.spec_from_file_location("nape2", __file__.rsplit("/", 1)[0] + "/nape2.py")

params_path, render_png = sys.argv[1], sys.argv[2]
p = json.load(open(params_path))
R = json.load(open("heads2/headref.json"))
e = np.radians(p["cam"]["elev"])
m = sf.build(p, 3000); s = m["s"]; L = s[-1]
sw = np.asarray(p.get("swell", [1.0]), float)
g = lambda x: np.interp(x, np.linspace(0, L, len(sw)), sw)
to_w = lambda P: np.column_stack([P[:, 0], -P[:, 1] / np.cos(e), np.zeros(len(P))])
to_img = lambda W: np.column_stack([W[:, 0], -(W[:, 1] * np.cos(e) - W[:, 2] * np.sin(e))])
k_blend = p.get("neck_blend", 12.0)
smin = lambda a, b, k: np.minimum(a, b) - np.maximum(k - np.abs(a - b), 0) ** 2 / (4 * k)


def resample(C, step):
    d = np.r_[0, np.cumsum(np.linalg.norm(np.diff(C, axis=0), axis=1))]
    t = np.arange(0, d[-1], step)
    return np.column_stack([np.interp(t, d, C[:, k]) for k in (0, 1)])


def curvature(C, sigma_px, step):
    """Signed curvature of an open polyline sampled every `step` px, after Gaussian smoothing of sigma_px."""
    sg = sigma_px / step
    if sg > 0: C = np.column_stack([ndimage.gaussian_filter1d(C[:, k], sg, mode="nearest") for k in (0, 1)])
    d1 = np.gradient(C, step, axis=0); d2 = np.gradient(d1, step, axis=0)
    return C, (d1[:, 0] * d2[:, 1] - d1[:, 1] * d2[:, 0]) / np.maximum(np.linalg.norm(d1, axis=1) ** 3, 1e-12)


report = {}
for name, i, P, dd in (("yellow", 0, m["PY"], s), ("blue", 1, m["PB"], L - s)):
    h, nk = p["head_profiles"][i], p["necks"][i]
    J, TJ, KJ = hm.strand_at(P, dd, nk["join_s"])
    rJ = float(p["a"] * g(nk["join_s"] if name == "yellow" else L - nk["join_s"]))
    R0, dax, nax, Lh = hm.head_frame(h, e)
    # A: the head's upper outline near the rear, parametric in t (image coords)
    t = np.linspace(1e-5, 0.6, 6000)
    u, l, rz = hm.head_profiles(h, t)
    A_up = to_img(R0[None] + dax[None] * (t * Lh)[:, None] + nax[None] * u[:, None])
    A_lo = to_img(R0[None] + dax[None] * (t * Lh)[:, None] + nax[None] * l[:, None])
    A = np.vstack([A_up[::-1], A_lo])            # up the rear cap through R0 and on along the lower outline
    # B: the neck's projected back edge, the envelope of its discs
    Cn, rn = hm.neck_curve(nk, h, e, J, TJ, KJ, rJ + 0.3, n=4000)
    c = to_img(Cn); dc = np.gradient(c, axis=0); dr = np.gradient(rn)
    sp2 = np.sum(dc * dc, 1); T = dc / np.sqrt(sp2)[:, None]; Nn = np.column_stack([-T[:, 1], T[:, 0]])
    a_ = dr / np.sqrt(sp2)
    fw = 1 if h["tip"][0] > h["rear"][0] else -1
    side = -1 if np.mean(fw * Nn[:, 0]) > 0 else 1   # the side facing the back of the head
    B = c - rn[:, None] * (a_[:, None] * T) + side * rn[:, None] * np.sqrt(np.clip(1 - a_ ** 2, 0, 1))[:, None] * Nn
    # where A and B cross, on the back
    best = None
    for ia in range(0, len(A) - 1, 3):
        dist = np.linalg.norm(B - A[ia], axis=1); ib = int(np.argmin(dist))
        if best is None or dist[ib] < best[0]: best = (dist[ib], ia, ib)
    _, ia, ib = best
    X = A[ia]
    tA = A[min(ia + 3, len(A) - 1)] - A[max(ia - 3, 0)]; tA /= np.linalg.norm(tA)
    tB = B[min(ib + 3, len(B) - 1)] - B[max(ib - 3, 0)]; tB /= np.linalg.norm(tB)
    mismatch = float(np.degrees(np.arccos(np.clip(abs(tA @ tB), -1, 1))))
    _, kA = curvature(A, 0, float(np.median(np.linalg.norm(np.diff(A, axis=0), axis=1))))
    _, kB = curvature(B, 0, float(np.median(np.linalg.norm(np.diff(B, axis=0), axis=1))))
    # C: the blended outline from the analytic fields on a fine grid around the crossing
    win = 45.0; step = 0.1
    xs, ys = np.meshgrid(np.arange(X[0] - win, X[0] + win, step), np.arange(X[1] - win, X[1] + win, step))
    Q = np.column_stack([xs.ravel(), ys.ravel()])
    hd = hm.head_distance(h, e, to_w(Q))
    cc_ = to_img(hm.neck_curve(nk, h, e, J, TJ, KJ, rJ + 0.3, n=160)[0]); rr_ = hm.neck_curve(nk, h, e, J, TJ, KJ, rJ + 0.3, n=160)[1]
    nd = np.full(len(Q), np.inf)
    for k0 in range(0, len(Q), 20000):
        nd[k0:k0 + 20000] = (np.linalg.norm(Q[k0:k0 + 20000, None] - cc_[None], axis=2) - rr_[None]).min(1)
    F = smin(hd, nd, k_blend).reshape(xs.shape)
    cont = max(measure.find_contours(F, 0.0), key=len)[:, ::-1] * step + [X[0] - win, X[1] - win]
    cont = resample(cont, 0.25)
    # trim the window's ends, then curvature: raw (fine), and at the reference's smoothing
    cont = cont[40:-40]
    _, k_raw = curvature(cont, 0.0, 0.25)
    C1, k_ref_sm = curvature(resample(cont, 1.0), 2.5, 1.0)
    # the reference over the same stretch: its outline points within the window, resampled at 1 px, same smoothing
    Cr = np.asarray(R[name]["contour"]); outer = np.asarray(R[name]["outer"])
    near = np.nonzero(outer & (np.abs(Cr[:, 0] - X[0]) < win - 5) & (np.abs(Cr[:, 1] - X[1]) < win - 5))[0]
    report[name] = {"crossing_image_xy": X.round(1).tolist(),
                    "tangent_mismatch_deg": round(mismatch, 1),
                    "curvature_head_outline_at_crossing": round(float(abs(kA[ia])), 4),
                    "curvature_neck_edge_at_crossing": round(float(abs(kB[ib])), 4),
                    "blended_outline_peak_curvature_analytic_raw": round(float(np.abs(k_raw[10:-10]).max()), 4),
                    "blended_outline_peak_curvature_analytic_smoothed_like_reference": round(float(np.abs(k_ref_sm[5:-5]).max()), 4),
                    "fillet_radius_px": round(float(1 / np.abs(k_raw[10:-10]).max()), 1)}
    if len(near) > 10:
        seg = Cr[np.sort(near)]
        _, kr = curvature(resample(seg, 1.0), 2.5, 1.0)
        report[name]["reference_peak_curvature_same_window_smoothed"] = round(float(np.abs(kr[5:-5]).max()), 4)
    # the same stretch from the rendered pixels, same smoothing
    spec2 = importlib.util.spec_from_file_location("nape2mod", __file__.rsplit("/", 1)[0] + "/nape2.py")
    _, labr = sf.ref_labels(render_png, 1.0)
    seed = (405, 305) if name == "yellow" else (1060, 300)
    cc2, _ = ndimage.label(labr == (2 if name == "yellow" else 1))
    comp = ndimage.binary_fill_holes(cc2 == cc2[seed[1], seed[0]])
    Cm = max(measure.find_contours(np.pad(comp, 2).astype(float), 0.5), key=len)[:, ::-1] - 2
    sel = (np.abs(Cm[:, 0] - X[0]) < win - 5) & (np.abs(Cm[:, 1] - X[1]) < win - 5)
    idx = np.nonzero(sel)[0]
    if len(idx) > 10:
        runs = np.split(idx, np.nonzero(np.diff(idx) > 1)[0] + 1); run = max(runs, key=len)
        _, km = curvature(resample(Cm[run], 1.0), 2.5, 1.0)
        report[name]["rendered_pixels_peak_curvature_same_window_smoothed"] = round(float(np.abs(km[5:-5]).max()), 4)
print(json.dumps(report, indent=1))
