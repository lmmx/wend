"""Blue nape: coupled refit of the rear head and upper neck, and measurements on the actual renders.

fit <params> <out>      refit blue's rear point, rear profile controls (U0, U1, Lo0, Lo1) and the
                        neck's upper part (tQ, vQ, angQ, alpha, r_top) against the reference
                        outline: position everywhere on the head; direction and smooth
                        curvature on the rear contour. Same field as the renderer.
render <png> [<png>...] rear-contour metrics measured on rendered images.
normals <params>        renderer-style normal error on the union surface around the nape.
"""
import json, sys
import numpy as np
from scipy import ndimage, optimize
from skimage import measure
sys.path.insert(0, __file__.rsplit("/", 1)[0])
import snakefit as sf
import headmodel as hm

R = json.load(open("heads2/headref.json"))
smin = lambda a, b, k: np.minimum(a, b) - np.maximum(k - np.abs(a - b), 0) ** 2 / (4 * k)


def setup(p):
    e = np.radians(p["cam"]["elev"])
    m = sf.build(p, 3000); s = m["s"]; L = s[-1]
    sw = np.asarray(p.get("swell", [1.0]), float)
    g = lambda x: np.interp(x, np.linspace(0, L, len(sw)), sw)
    return e, m, s, L, g


def to_w(P, e): return np.column_stack([P[:, 0], -P[:, 1] / np.cos(e), np.zeros(len(P))])
def to_img(W, e): return np.column_stack([W[:, 0], -(W[:, 1] * np.cos(e) - W[:, 2] * np.sin(e))])


def smooth_curv(C, sigma=2.0):
    C = np.column_stack([ndimage.gaussian_filter1d(C[:, k], sigma, mode="wrap") for k in (0, 1)])
    d1 = np.gradient(C, axis=0); d2 = np.gradient(d1, axis=0)
    return C, (d1[:, 0] * d2[:, 1] - d1[:, 1] * d2[:, 0]) / np.maximum(np.linalg.norm(d1, axis=1) ** 3, 1e-9)


def segments(name):
    """Reference outline indices: rear (crown top, back, down the nape to the wrap), front
    (crown top forward over the snout, under the jaw to the wrap)."""
    C = np.asarray(R[name]["contour"]); outer = np.asarray(R[name]["outer"])
    n = len(C)
    i0 = np.argmin(np.linalg.norm(C - np.asarray(R[name]["landmarks"]["crown_top"]), axis=1))
    fw = 1 if R[name]["axis"]["tip"][0] > R[name]["axis"]["rear"][0] else -1
    back = 1 if fw * (C[(i0 + 5) % n, 0] - C[i0, 0]) < 0 else -1
    def walk(step):
        out = []
        for k in range(n):
            i = (i0 + step * k) % n
            if not outer[i] and k > 5: break
            out.append(i)
        return np.asarray(out)
    return C, outer, walk(back), walk(-back)


def rear_metrics(Cm, name):
    """Position / direction / curvature of a model contour (image coords) against the reference rear segment."""
    C, outer, rear, front = segments(name)
    Cref, kref = smooth_curv(C)
    Cm, km = smooth_curv(Cm)
    rows = []
    for i in rear:
        j = np.argmin(np.linalg.norm(Cm - Cref[i], axis=1))
        tr = Cref[(i + 1) % len(Cref)] - Cref[i - 1]; tm = Cm[(j + 1) % len(Cm)] - Cm[j - 1]
        ang = np.degrees(np.arctan2(tr[0] * tm[1] - tr[1] * tm[0], tr @ tm)); ang = (ang + 90) % 180 - 90
        rows.append((np.linalg.norm(Cm[j] - Cref[i]), abs(ang), abs(kref[i]), abs(km[j])))
    rows = np.asarray(rows)
    fr = np.asarray([np.linalg.norm(Cm - Cref[i], axis=1).min() for i in front])
    return dict(rear_mean_px=round(float(rows[:, 0].mean()), 2), rear_max_px=round(float(rows[:, 0].max()), 2),
                rear_dir_mean_deg=round(float(rows[:, 1].mean()), 2), rear_dir_max_deg=round(float(rows[:, 1].max()), 2),
                rear_curv_max_ref=round(float(rows[:, 2].max()), 4), rear_curv_max_model=round(float(rows[:, 3].max()), 4),
                front_mean_px=round(float(fr.mean()), 2), front_max_px=round(float(fr.max()), 2))


def render_contour(png, name):
    _, lab = sf.ref_labels(png, 1.0)
    seed = (405, 305) if name == "yellow" else (1060, 300)
    cc, _ = ndimage.label(lab == (2 if name == "yellow" else 1))
    comp = ndimage.binary_fill_holes(cc == cc[seed[1], seed[0]])
    C = max(measure.find_contours(np.pad(comp, 2).astype(float), 0.5), key=len)[:, ::-1] - 2
    d = np.r_[0, np.cumsum(np.linalg.norm(np.diff(C, axis=0), axis=1))]
    t = np.arange(0, d[-1], 1.0)
    return np.column_stack([np.interp(t, d, C[:, k]) for k in (0, 1)])


def neck_parts(p, name, e, m, s, L, g, h=None, nk=None):
    i = 0 if name == "yellow" else 1
    P, dd = (m["PY"], s) if name == "yellow" else (m["PB"], L - s)
    h = h or p["head_profiles"][i]; nk = nk or p["necks"][i]
    J, TJ, KJ = hm.strand_at(P, dd, nk["join_s"])
    rJ = float(p["a"] * g(nk["join_s"] if name == "yellow" else L - nk["join_s"]))
    return h, nk, J, TJ, KJ, rJ


def union2d(p, e, h, nk, J, TJ, KJ, rJ, X):
    hd = hm.head_distance(h, e, to_w(X, e))
    C, r = hm.neck_curve(nk, h, e, J, TJ, KJ, rJ + 0.3, n=90)
    I = to_img(C, e)
    nd = (np.linalg.norm(X[:, None] - I[None], axis=2) - r[None]).min(1)
    return smin(hd, nd, p.get("neck_blend", 12.0))


mode = sys.argv[1]

if mode == "fit":
    p = json.load(open(sys.argv[2])); out = sys.argv[3]; name = "blue"
    e, m, s, L, g = setup(p)
    h0, nk0, J, TJ, KJ, rJ = neck_parts(p, name, e, m, s, L, g)
    C, outer, rear, front = segments(name)
    # the throat: open outline below the chin, on the snout's side
    chin = np.asarray(R[name]["landmarks"]["chin_throat"])
    throat = np.nonzero(outer & (C[:, 1] > chin[1]) & (np.abs(C[:, 0] - chin[0]) < 60))[0]
    pos_idx = np.unique(np.r_[rear, front, throat])
    Ppos = C[pos_idx]
    Prear = C[rear]
    Tr = C[(rear + 1) % len(C)] - C[rear - 1]; Tr /= np.linalg.norm(Tr, axis=1, keepdims=True)
    Nrear = np.column_stack([Tr[:, 1], -Tr[:, 0]])
    from matplotlib.path import Path as MPath
    Nrear[MPath(C).contains_points(Prear + 3 * Nrear)] *= -1     # outward
    ref_ang = np.unwrap(np.arctan2(Nrear[:, 1], Nrear[:, 0]))
    ref_dd = ref_ang[2:] - 2 * ref_ang[1:-1] + ref_ang[:-2]
    names = ["d_rear_x", "d_rear_y", "U0", "U1", "Lo0", "Lo1", "tQ", "vQ", "angQ", "alpha", "r_top"]
    x0 = np.array([0, 0, h0["U"][0], h0["U"][1], h0["Lo"][0], h0["Lo"][1], nk0["tQ"], nk0["vQ"], nk0["angQ"], nk0["alpha"], nk0["r_top"]], float)
    def apply(x):
        h = json.loads(json.dumps(h0)); nk = dict(nk0)
        h["rear"] = [h0["rear"][0] + x[0], h0["rear"][1] + x[1]]
        h["U"][0], h["U"][1], h["Lo"][0], h["Lo"][1] = x[2], x[3], x[4], x[5]
        nk["tQ"], nk["vQ"], nk["angQ"], nk["alpha"], nk["r_top"] = x[6], x[7], x[8], x[9], x[10]
        return h, nk
    def residuals(x, parts=False):
        h, nk = apply(x)
        F = union2d(p, e, h, nk, J, TJ, KJ, rJ, Ppos)                       # position: on the outline
        eps = 0.75
        f = lambda X: union2d(p, e, h, nk, J, TJ, KJ, rJ, X)
        G = np.column_stack([(f(Prear + [eps, 0]) - f(Prear - [eps, 0])), (f(Prear + [0, eps]) - f(Prear - [0, eps]))])
        G /= np.maximum(np.linalg.norm(G, axis=1, keepdims=True), 1e-9)
        dirn = np.arccos(np.clip(np.sum(G * Nrear, 1), -1, 1))            # direction, radians
        ang = np.unwrap(np.arctan2(G[:, 1], G[:, 0]))
        curv = (ang[2:] - 2 * ang[1:-1] + ang[:-2]) - ref_dd               # curvature smoothness, against the reference's own
        Cn, rn = hm.neck_curve(nk, h, e, J, TJ, KJ, rJ, n=90)
        T = np.gradient(Cn, axis=0); A2 = np.gradient(T, axis=0)
        kk = np.linalg.norm(np.cross(T, A2), axis=1) / np.maximum(np.linalg.norm(T, axis=1) ** 3, 1e-9)
        bend = np.maximum(0, kk * rn * 1.3 - 1)
        # no shrinking the back of the head to dodge the shoulder: its upper rear stays at least as full
        full = np.maximum(0, [h0["U"][0] - h["U"][0] - 5, h0["U"][1] - h["U"][1] - 5])
        # the profiles stay smooth: their control values may not start to oscillate
        D2 = lambda c: np.diff(np.asarray(c, float), 2)
        prof = np.r_[D2(h["U"]) - D2(h0["U"]), D2(h["Lo"]) - D2(h0["Lo"])]
        terms = [F, 30 * dirn, 60 * curv, 20 * bend, 0.5 * np.asarray(full), 0.3 * prof]
        return terms if parts else np.concatenate(terms)
    lo = x0 + [-25, -25, -40, -40, -60, -60, -0.15, -40, -60, -40, -6]
    hi = x0 + [25, 25, 60, 60, 60, 60, 0.15, 40, 60, 80, 4]
    lo[6] = max(lo[6], 0.0); lo[2:6] = np.maximum(lo[2:6], 20)
    sol = optimize.least_squares(residuals, x0, bounds=(lo, hi), x_scale=[3, 3, 10, 10, 10, 10, 0.03, 5, 5, 10, 2], max_nfev=800, ftol=1e-10, xtol=1e-10)
    before, after = residuals(x0, True), residuals(sol.x, True)
    for lab_, k in (("outline position rms px", 0), ("rear direction mean deg", 1), ("rear curvature term rms", 2)):
        b, a = before[k], after[k]
        if k == 1: b, a = np.degrees(b / 30).mean(), np.degrees(a / 30).mean()
        elif k == 2: b, a = np.sqrt(np.mean((b / 60) ** 2)), np.sqrt(np.mean((a / 60) ** 2))
        else: b, a = np.sqrt(np.mean(b ** 2)), np.sqrt(np.mean(a ** 2))
        print(f"  model {lab_}: {b:.3f} -> {a:.3f}")
    h, nk = apply(sol.x)
    print("  changed:", {k: f"{a:.2f} -> {b:.2f}" for k, a, b in zip(names, x0, sol.x) if abs(a - b) > 1e-3})
    q = json.loads(json.dumps(p)); q["head_profiles"][1] = h; q["necks"][1] = nk
    json.dump(q, open(out, "w"), indent=1)

if mode == "render":
    for png in sys.argv[2:]:
        for name in ("yellow", "blue"):
            print(png.split("/")[-1], name, rear_metrics(render_contour(png, name), name))

if mode == "normals":
    # renderer-style normals (central differences 1.25 px) against the true normal, on the
    # union surface around the nape: the head and neck smooth union, in 3D
    p = json.load(open(sys.argv[2])); name = sys.argv[3] if len(sys.argv) > 3 else "blue"
    e, m, s, L, g = setup(p)
    h, nk, J, TJ, KJ, rJ = neck_parts(p, name, e, m, s, L, g)
    Cn, rn = hm.neck_curve(nk, h, e, J, TJ, KJ, rJ + 0.3, n=48)
    def sd_round_cone(P, a, b, r1, r2):
        ba = b - a; l2 = ba @ ba; rr = r1 - r2; a2 = l2 - rr * rr; il2 = 1 / l2
        pa = P - a; y = pa @ ba; z = y - l2
        xv = pa * l2 - np.outer(y, ba); x2 = np.sum(xv * xv, 1); y2 = y * y * l2; z2 = z * z * l2
        k = np.sign(rr) * rr * rr * x2
        out = (np.sqrt(x2 * a2 * il2) + y * rr) * il2 - r1
        out = np.where(np.sign(y) * a2 * y2 < k, np.sqrt(x2 + y2) * il2 - r1, out)
        out = np.where(np.sign(z) * a2 * z2 > k, np.sqrt(x2 + z2) * il2 - r2, out)
        return out
    def field(P):
        nd = np.min([sd_round_cone(P, Cn[i], Cn[i + 1], rn[i], rn[i + 1]) for i in range(len(Cn) - 1)], axis=0)
        return smin(hm.head_distance(h, e, P), nd, p.get("neck_blend", 12.0))
    def grad(P, eps):
        G = np.column_stack([(field(P + d) - field(P - d)) / (2 * eps) for d in np.eye(3) * eps])
        return G / np.linalg.norm(G, axis=1, keepdims=True)
    # surface points around the nape: march along rays from inside the neck top towards the back
    R0, dax, nax, Lh = hm.head_frame(h, e)
    centre = Cn[len(Cn) // 5]
    pts = []
    for el in np.radians(np.linspace(-60, 60, 25)):
        for az in np.radians(np.linspace(100, 260, 41)):
            dirn = np.cos(el) * (np.cos(az) * dax + np.sin(az) * nax) + np.sin(el) * np.array([0, 0, 1.0])
            ts = np.linspace(0, 120, 241); X = centre[None] + ts[:, None] * dirn[None]
            f = field(X); k = np.nonzero((f[:-1] < 0) & (f[1:] >= 0))[0]
            if len(k): i = k[0]; pts.append(X[i] + (X[i + 1] - X[i]) * (-f[i] / (f[i + 1] - f[i])))
    pts = np.asarray(pts)
    err = np.degrees(np.arccos(np.clip(np.sum(grad(pts, 1.25) * grad(pts, 0.02), 1), -1, 1)))
    # normal variation between neighbouring surface points: a crease shows as a jump
    from scipy.spatial import cKDTree
    Nf = grad(pts, 0.02)
    tree = cKDTree(pts); jumps = []
    for i, q in enumerate(pts):
        for j in tree.query_ball_point(q, 4.0):
            if j > i: jumps.append(np.degrees(np.arccos(np.clip(Nf[i] @ Nf[j], -1, 1))) / max(np.linalg.norm(pts[j] - q), 1e-6))
    jumps = np.asarray(jumps)
    print(f"{name} nape surface points {len(pts)}: renderer-style normal error mean {err.mean():.2f} deg, max {err.max():.2f} deg; "
          f"normal turn rate between neighbours: median {np.median(jumps):.2f} deg/px, 99th pct {np.percentile(jumps, 99):.2f}, max {jumps.max():.2f}")

if mode == "comb":
    # rear contour curvature combs from rendered images, against the reference
    from PIL import Image, ImageDraw
    name, out = sys.argv[2], sys.argv[3]; pngs = sys.argv[4:]
    C, outer, rear, front = segments(name)
    Cref, kref = smooth_curv(C)
    box = (int(C[rear, 0].min()) - 40, int(C[rear, 1].min()) - 30, int(C[rear, 0].max()) + 60, int(C[rear, 1].max()) + 30)
    S = 3
    panels = []
    for png in pngs:
        Cm, km = smooth_curv(render_contour(png, name))
        im = Image.new("RGB", ((box[2] - box[0]) * S, (box[3] - box[1]) * S), "white"); dr = ImageDraw.Draw(im)
        X = lambda q: ((q[0] - box[0]) * S, (q[1] - box[1]) * S)
        def comb(P, k, col, sign):
            T = np.gradient(P, axis=0); T /= np.linalg.norm(T, axis=1, keepdims=True)
            N = sign * np.column_stack([-T[:, 1], T[:, 0]])
            for q, kk, nn in zip(P[::2], k[::2], N[::2]): dr.line([X(q), X(q + nn * kk * 700)], fill=col, width=1)
            dr.line([X(q) for q in P], fill=col, width=3)
        js = np.asarray([np.argmin(np.linalg.norm(Cm - Cref[i], axis=1)) for i in rear])
        jr = np.arange(js.min(), js.max() + 1)
        comb(Cref[rear], kref[rear], (220, 0, 0), 1)
        # orient the model's comb the same way as the reference's
        sign = 1 if np.sign(np.median(km[jr])) == np.sign(np.median(kref[rear])) else -1
        comb(Cm[jr], km[jr], (0, 90, 220), sign)
        dr.text((8, 8), png.split("/")[-1] + ": red reference, blue render", fill=(0, 0, 0))
        panels.append(im)
    W = sum(pn.width for pn in panels); sheet = Image.new("RGB", (W, panels[0].height), "white")
    x = 0
    for pn in panels: sheet.paste(pn, (x, 0)); x += pn.width
    sheet.save(out)
