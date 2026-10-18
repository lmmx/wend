"""Head-to-neck continuity: measurements, and a coupled refit of the rear head and upper neck.

measure: continuity at J (neck curve against the body strand); the rendered rear contour
         against the reference rear contour (position, tangent direction, curvature).
fit:     refit, together, the head's rear (rear point, rear upper and lower profile
         controls) and the neck's upper part (Q, its direction, alpha, r_top), so that the
         union's outline matches the reference from the crown down the nape and the throat,
         in position and in direction. Same field as the renderer (headmodel.py).
"""
import json, sys
import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage, optimize
from skimage import measure
sys.path.insert(0, __file__.rsplit("/", 1)[0])
import snakefit as sf
import headmodel as hm

mode, params_path = sys.argv[1], sys.argv[2]
p = json.load(open(params_path))
R = json.load(open("heads2/headref.json"))
e = np.radians(p["cam"]["elev"])
m = sf.build(p, 3000); s = m["s"]; L = s[-1]
sw = np.asarray(p.get("swell", [1.0]), float)
g = lambda x: np.interp(x, np.linspace(0, L, len(sw)), sw)
to_w = lambda P: np.column_stack([P[:, 0], -P[:, 1] / np.cos(e), np.zeros(len(P))])
to_img = lambda W: np.column_stack([W[:, 0], -(W[:, 1] * np.cos(e) - W[:, 2] * np.sin(e))])
STRANDS = {"yellow": (m["PY"], s, 0), "blue": (m["PB"], L - s, 1)}
smin = lambda a, b, k: np.minimum(a, b) - np.maximum(k - np.abs(a - b), 0) ** 2 / (4 * k)


def neck_of(name):
    P, dd, i = STRANDS[name]
    h, nk = p["head_profiles"][i], p["necks"][i]
    J, TJ, KJ = hm.strand_at(P, dd, nk["join_s"])
    rJ = float(p["a"] * g(nk["join_s"] if name == "yellow" else L - nk["join_s"]))
    return h, nk, J, TJ, KJ, rJ


def union2d(name, h, nk, J, TJ, KJ, rJ, X):
    """The outline field in the picture plane: the head's z = 0 section, smooth-unioned with the
    neck's projected discs. X are image points (n, 2)."""
    hd = hm.head_distance(h, e, to_w(X))
    C, r = hm.neck_curve(nk, h, e, J, TJ, KJ, rJ + 0.3, n=90)
    I = to_img(C)
    nd = np.full(len(X), np.inf)
    for k in range(0, len(X), 4000):
        dd = np.linalg.norm(X[k:k + 4000, None] - I[None], axis=2) - r[None]
        nd[k:k + 4000] = dd.min(1)
    return smin(hd, nd, p.get("neck_blend", 12.0))


def contour_curvature(C, sigma=2.0):
    C = np.column_stack([ndimage.gaussian_filter1d(C[:, k], sigma, mode="wrap") for k in (0, 1)])
    d1 = np.gradient(C, axis=0); d2 = np.gradient(d1, axis=0)
    k = (d1[:, 0] * d2[:, 1] - d1[:, 1] * d2[:, 0]) / np.maximum(np.linalg.norm(d1, axis=1) ** 3, 1e-9)
    return C, k


def rear_segment(name, C, outer):
    """The reference's rear contour: from the crown top, back and down the nape to where the
    wrap hides it (blue); for yellow, crown top to the wrap."""
    lm = R[name]["landmarks"]
    i0 = np.argmin(np.linalg.norm(C - np.asarray(lm["crown_top"]), axis=1))
    fw = 1 if R[name]["axis"]["tip"][0] > R[name]["axis"]["rear"][0] else -1
    n = len(C)
    step = 1 if fw * (C[(i0 + 5) % n, 0] - C[i0, 0]) < 0 else -1  # towards the back
    seg = []
    for k in range(n):
        i = (i0 + step * k) % n
        if not outer[i] and k > 5: break
        seg.append(i)
    return np.asarray(seg)


if mode == "measure":
    out_img = sys.argv[3]
    report = {}
    sheet_parts = []
    for name in ("yellow", "blue"):
        h, nk, J, TJ, KJ, rJ = neck_of(name)
        # continuity at J
        C, r = hm.neck_curve(nk, h, e, J, TJ, KJ, rJ, n=400)
        tan = C[-1] - C[-2]; tan /= np.linalg.norm(tan)
        sp = np.linalg.norm(np.gradient(C, axis=0), axis=1)
        T = np.gradient(C, axis=0) / sp[:, None]
        kv = np.gradient(T, axis=0) / sp[:, None]
        angle = float(np.degrees(np.arccos(np.clip(tan @ TJ, -1, 1))))
        k_end = kv[-3]
        report[name] = {"J": {"tangent_angle_deg": round(angle, 2), "curvature_neck": round(float(np.linalg.norm(k_end)), 5),
                              "curvature_strand": round(float(np.linalg.norm(KJ)), 5),
                              "curvature_vector_diff": round(float(np.linalg.norm(k_end - KJ)), 5),
                              "radius_neck_end": round(float(r[-1]), 2), "radius_strand": round(rJ, 2)}}
        # the outline field's zero set near the head, against the reference rear contour
        Cr = np.asarray(R[name]["contour"]); outer = np.asarray(R[name]["outer"])
        seg = rear_segment(name, Cr, outer)
        x0, y0 = Cr[:, 0].min() - 30, Cr[:, 1].min() - 30
        xs, ys = np.meshgrid(np.arange(x0, x0 + 300, 1.0), np.arange(y0, y0 + 320, 1.0))
        F = union2d(name, h, nk, J, TJ, KJ, rJ, np.column_stack([xs.ravel(), ys.ravel()])).reshape(xs.shape)
        cs = max(measure.find_contours(F, 0.0), key=len)[:, ::-1] + [x0, y0]
        Cm, km = contour_curvature(cs, 2.0)
        Cref, kref = contour_curvature(Cr, 2.0)
        # along the reference rear segment: nearest model contour point; position, direction, curvature
        rows = []
        for i in seg:
            j = np.argmin(np.linalg.norm(Cm - Cref[i], axis=1))
            tr = Cref[(i + 1) % len(Cref)] - Cref[i - 1]; tm = Cm[(j + 1) % len(Cm)] - Cm[j - 1]
            ang = np.degrees(np.arctan2(tr[0] * tm[1] - tr[1] * tm[0], tr @ tm))
            ang = (ang + 90) % 180 - 90
            rows.append((np.linalg.norm(Cm[j] - Cref[i]), ang, kref[i], km[j]))
        rows = np.asarray(rows)
        report[name]["rear_contour"] = {"points": len(rows), "position_mean_px": round(float(rows[:, 0].mean()), 2),
                                        "position_max_px": round(float(rows[:, 0].max()), 2),
                                        "direction_mean_abs_deg": round(float(np.abs(rows[:, 1]).mean()), 2),
                                        "direction_max_abs_deg": round(float(np.abs(rows[:, 1]).max()), 2),
                                        "curvature_ref_max": round(float(np.abs(rows[:, 2]).max()), 4),
                                        "curvature_model_max": round(float(np.abs(rows[:, 3]).max()), 4)}
        # debug drawing: the rear contours at 2x, with curvature combs
        box = (int(Cr[seg, 0].min()) - 40, int(Cr[seg, 1].min()) - 30, int(Cr[seg, 0].max()) + 60, int(Cr[seg, 1].max()) + 30)
        S = 3
        im = Image.new("RGB", ((box[2] - box[0]) * S, (box[3] - box[1]) * S), "white")
        dr = ImageDraw.Draw(im)
        X = lambda q: ((q[0] - box[0]) * S, (q[1] - box[1]) * S)
        def comb(P, k, col):
            Tn = np.gradient(P, axis=0); Tn /= np.linalg.norm(Tn, axis=1, keepdims=True)
            Nn = np.column_stack([-Tn[:, 1], Tn[:, 0]])
            for q, kk, nn in zip(P[::2], k[::2], Nn[::2]):
                dr.line([X(q), X(q + nn * kk * 900)], fill=col, width=1)
            dr.line([X(q) for q in P], fill=col, width=3)
        segm = np.asarray([np.argmin(np.linalg.norm(Cm - Cref[i], axis=1)) for i in seg])
        jm = np.arange(segm.min(), segm.max() + 1) if segm.max() - segm.min() < len(Cm) / 2 else segm
        comb(Cref[seg], kref[seg], (220, 0, 0))
        comb(Cm[jm], km[jm], (0, 90, 220))
        dr.text((8, 8), f"{name} rear contour: red reference, blue model; combs show curvature", fill=(0, 0, 0))
        im.save(out_img.replace(".png", f"-{name}.png"))
    print(json.dumps(report, indent=1))

if mode == "fit":
    name, out_path = sys.argv[3], sys.argv[4]
    i = 0 if name == "yellow" else 1
    h0, nk0, J, TJ, KJ, rJ = neck_of(name)
    Cr = np.asarray(R[name]["contour"]); outer = np.asarray(R[name]["outer"])
    seg = rear_segment(name, Cr, outer)
    # also the throat: outer points below the chin
    chin = np.asarray(R[name]["landmarks"]["chin_throat"])
    throat = np.nonzero(outer & (Cr[:, 1] > chin[1]) & (np.abs(Cr[:, 0] - chin[0]) < 60))[0]
    idx = np.r_[seg, throat]
    Pts = Cr[idx]
    Tr = Cr[(idx + 1) % len(Cr)] - Cr[idx - 1]; Tr /= np.linalg.norm(Tr, axis=1, keepdims=True)
    Nref = np.column_stack([Tr[:, 1], -Tr[:, 0]])
    # outward reference normals: the side away from the component
    probe = Pts + 3 * Nref
    from matplotlib.path import Path as MPath
    inside = MPath(Cr).contains_points(probe)
    Nref[inside] *= -1
    def apply(x):
        h = json.loads(json.dumps(h0)); nk = dict(nk0)
        h["rear"] = [h0["rear"][0] + x[0], h0["rear"][1] + x[1]]
        h["U"][0], h["U"][1] = x[2], x[3]
        h["Lo"][0], h["Lo"][1] = x[4], x[5]
        nk["tQ"], nk["vQ"], nk["angQ"], nk["alpha"], nk["r_top"] = x[6], x[7], x[8], x[9], x[10]
        return h, nk
    def residuals(x):
        h, nk = apply(x)
        F = union2d(name, h, nk, J, TJ, KJ, rJ, Pts)
        # direction: the field's gradient against the reference outward normal
        eps = 0.75
        gx = (union2d(name, h, nk, J, TJ, KJ, rJ, Pts + [eps, 0]) - union2d(name, h, nk, J, TJ, KJ, rJ, Pts - [eps, 0])) / (2 * eps)
        gy = (union2d(name, h, nk, J, TJ, KJ, rJ, Pts + [0, eps]) - union2d(name, h, nk, J, TJ, KJ, rJ, Pts - [0, eps])) / (2 * eps)
        G = np.column_stack([gx, gy]); G /= np.maximum(np.linalg.norm(G, axis=1, keepdims=True), 1e-9)
        dirn = 1 - np.sum(G * Nref, axis=1)
        # the neck must not bend tighter than 1.3x its radius
        C, r = hm.neck_curve(nk, h, e, J, TJ, KJ, rJ, n=90)
        T = np.gradient(C, axis=0); A2 = np.gradient(T, axis=0)
        kk = np.linalg.norm(np.cross(T, A2), axis=1) / np.maximum(np.linalg.norm(T, axis=1) ** 3, 1e-9)
        return np.r_[F, 25 * dirn, 20 * np.maximum(0, kk * r * 1.3 - 1)]
    x0 = np.array([0, 0, h0["U"][0], h0["U"][1], h0["Lo"][0], h0["Lo"][1], nk0["tQ"], nk0["vQ"], nk0["angQ"], nk0["alpha"], nk0["r_top"]], float)
    lo = x0 + [-25, -25, -60, -60, -60, -60, -0.1, -40, -60, -40, -6]
    hi = x0 + [25, 25, 60, 60, 60, 60, 0.15, 40, 60, 80, 4]
    lo[6] = max(lo[6], 0.0); lo[2:6] = np.maximum(lo[2:6], 20)
    r0 = residuals(x0)
    sol = optimize.least_squares(residuals, x0, bounds=(lo, hi), x_scale=[3, 3, 10, 10, 10, 10, 0.03, 5, 5, 10, 2])
    r1 = residuals(sol.x)
    n_ = len(Pts)
    print(name, "outline rms", round(float(np.sqrt(np.mean(r0[:n_] ** 2))), 2), "->", round(float(np.sqrt(np.mean(r1[:n_] ** 2))), 2),
          "| direction term", round(float(np.mean(r0[n_:2 * n_] / 25)), 4), "->", round(float(np.mean(r1[n_:2 * n_] / 25)), 4))
    h, nk = apply(sol.x)
    q = json.loads(json.dumps(p))
    q["head_profiles"][i] = h; q["necks"][i] = nk
    json.dump(q, open(out_path, "w"), indent=1)
    print("changed:", {k: round(float(v), 2) for k, v in zip(["d_rear_x", "d_rear_y", "U0", "U1", "Lo0", "Lo1", "tQ", "vQ", "angQ", "alpha", "r_top"], sol.x - x0 * [0, 0, 1, 1, 1, 1, 1, 1, 1, 1, 1] * 0) })
