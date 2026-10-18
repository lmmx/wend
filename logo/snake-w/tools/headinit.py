"""Phase 3 initialisation: profile and neck parameters from the reference measurements.

Writes a new params file (the baseline is not touched) and an overlay of the fitted
outlines on the reference heads.
"""
import json, sys
import numpy as np
from PIL import Image, ImageDraw
from scipy import optimize
sys.path.insert(0, __file__.rsplit("/", 1)[0])
import snakefit as sf
import headmodel as hm

base_path, ref_json, out_path, overlay_dir = sys.argv[1:5]
p = json.load(open(base_path))
R = json.load(open(ref_json))
e = np.radians(p["cam"]["elev"])
K = 7
JOIN = {"yellow": 165.0, "blue": 198.0}  # arc from the snout: the middle of the stretch hidden behind the wrap
to_w = lambda P: np.column_stack([P[:, 0], -P[:, 1] / np.cos(e), np.zeros(len(P))])
to_img = lambda W: np.column_stack([W[:, 0], -(W[:, 1] * np.cos(e) - W[:, 2] * np.sin(e))])

m = sf.build(p, 3000)
s, L = m["s"], m["s"][-1]
sw = np.asarray(p.get("swell", [1.0]), float)
g = lambda x: np.interp(x, np.linspace(0, L, len(sw)), sw) if len(sw) > 1 else 1.0

heads, necks, report = [], [], {}
SAMPLES = {}
CENTRES = {}
from scipy import ndimage
_, LAB = sf.ref_labels('ref/reference.png', 1.0)
OUT_D = ndimage.distance_transform_edt(LAB == 0)  # distance outside the whole object
for name, P, dd in (("yellow", m["PY"], s), ("blue", m["PB"], L - s)):
    r = R[name]
    C = np.asarray(r["contour"]); outer = np.asarray(r["outer"])
    h = {"rear": list(r["axis"]["rear"]), "tip": r["axis"]["tip"], "beta": 0.45, "q": 2.25}
    # where the back of the head runs on into the back of the neck (blue), the head's rear
    # sits at the nape's backmost visible point, so the two outlines line up
    fw = 1 if r["axis"]["tip"][0] > r["axis"]["rear"][0] else -1
    cr = np.asarray(r["landmarks"]["crown_rear"])
    nape = C[outer & (C[:, 1] > cr[1]) & (C[:, 1] < cr[1] + 70) & (fw * (C[:, 0] - cr[0]) < 12)]
    if len(nape) > 10:
        h["rear"][0] = float(nape[np.argmin(fw * nape[:, 0]), 0])
    R0, d, nu, Lh = hm.head_frame(h, e)
    # measured profile points, in the head's world frame
    prof = np.asarray(r["profile"])
    rear_i, ax_i, up_i = np.asarray(r["axis"]["rear"]), np.asarray(r["axis"]["dir"]), np.asarray(r["axis"]["up"])
    # re-measure the profile along the (possibly moved) axis, from the component's outline
    comp_pts = C
    def measure_profile(rear, tip, nt=81):
        rear, tip = np.asarray(rear, float), np.asarray(tip, float)
        dd_ = tip - rear; Lh_ = np.linalg.norm(dd_); dd_ /= Lh_
        up_ = np.array([dd_[1], -dd_[0]]); up_ = up_ if up_[1] < 0 else -up_
        out_ = []
        from matplotlib.path import Path as MPath
        poly = MPath(C)
        for t in np.linspace(0, 1, nt):
            base = rear + dd_ * t * Lh_
            vs = np.arange(-160, 160, 0.5)
            pts = base[None] + vs[:, None] * up_[None]
            ins = poly.contains_points(pts)
            if not ins.any(): out_.append((t, np.nan, np.nan)); continue
            idx = np.nonzero(ins)[0]
            groups = np.split(idx, np.nonzero(np.diff(idx) > 1)[0] + 1)
            gg = min(groups, key=lambda g_: abs(vs[g_]).min())
            out_.append((t, float(vs[gg].max()), float(vs[gg].min())))
        return np.asarray(out_), rear, dd_, up_, Lh_
    prof, rear_i, ax_i, up_i, Lh_i = measure_profile(h["rear"], h["tip"])
    chin = np.asarray(r["landmarks"]["chin_throat"])
    t_chin = ((to_w(chin[None])[0] - R0) @ d) / Lh
    samples = {"U": [], "Lo": []}
    for t_img, top, bot in prof:
        if np.isnan(top): continue
        base = rear_i + ax_i * t_img * Lh_i
        for key, v in (("U", top), ("Lo", bot)):
            pt = base + v * up_i
            j = np.argmin(np.linalg.norm(C - pt, axis=1))
            if np.linalg.norm(C[j] - pt) > 2.5 or not outer[j]: continue   # hidden by the wrap
            W = to_w(pt[None])[0]
            tw, vw = ((W - R0) @ d) / Lh, (W - R0) @ nu
            if not 0.02 < tw < 0.995: continue
            if key == "Lo" and tw < t_chin: continue                       # behind the chin it is neck, not head
            samples[key].append((tw, vw))
    tk = np.linspace(0, 1, K)
    for key, sign in (("U", 1), ("Lo", -1)):
        S = np.asarray(samples[key])
        t_, v_ = S[:, 0], sign * S[:, 1]
        A = hm.catmull_basis(K, t_) * np.sqrt(t_ * (1 - t_))[:, None]
        D2 = np.diff(np.eye(K), 2, axis=0)
        lam = 0.15 * len(t_) / K
        c = np.linalg.lstsq(np.vstack([A, np.sqrt(lam) * D2]), np.r_[v_, np.zeros(K - 2)], rcond=None)[0]
        h[key] = c.round(2).tolist()
        report.setdefault(name, {})[key + "_rms"] = float(np.sqrt(np.mean((A @ c - v_) ** 2)))
    kappa = np.array([1.0, 1.02, 1.0, 0.96, 0.92, 0.88, 0.86])
    h["D"] = (kappa * (np.asarray(h["U"]) + np.asarray(h["Lo"])) / 2).round(2).tolist()
    h_samples = {k: np.asarray(v_) for k, v_ in samples.items()}
    heads.append(h)
    SAMPLES[name] = h_samples

    # the neck: its centreline and radius read off the reference, then a quintic from inside
    # the head to J (on the strand, behind the wrap) fitted to that centreline
    J, TJ, KJ = hm.strand_at(P, dd, JOIN[name])
    rJ = float(p["a"] * g(JOIN[name] if name == "yellow" else L - JOIN[name]))
    chin_y = r["landmarks"]["chin_throat"][1]
    entry_y = max(r["landmarks"]["neck_entry_a"][1], r["landmarks"]["neck_entry_b"][1])
    front, back = [], []
    for y in np.arange(chin_y + 8, entry_y, 2.0):
        row = C[np.abs(C[:, 1] - y) < 1.0]
        orow = outer[np.abs(C[:, 1] - y) < 1.0]
        if len(row) < 2: continue
        # front (throat) edge: the outline point on the snout's side; back edge: the other side
        i_f = np.argmax(fw * row[:, 0]); i_b = np.argmin(fw * row[:, 0])
        if orow[i_f]: front.append(row[i_f])
        if orow[i_b] and abs(row[i_f, 0] - row[i_b, 0]) > 20: back.append((row[i_f], row[i_b]))
    front = np.asarray(front)
    # the radius: the narrowest exposed width where both edges show, else 0.92 a
    both = len(back) >= 4
    if both:
        pairs = np.asarray(back)
        r_top = float((np.linalg.norm(pairs[:, 0] - pairs[:, 1], axis=1) / 2).min())
    else:
        r_top = 0.92 * p["a"]
    # the centreline: midpoints where both edges show; below, the front edge set in by r_top
    Tf = np.gradient(front, axis=0); Tf /= np.linalg.norm(Tf, axis=1, keepdims=True)
    nin = np.column_stack([-Tf[:, 1], Tf[:, 0]])
    if np.mean(fw * nin[:, 0]) > 0: nin = -nin  # into the neck: away from the snout side
    centres = front + r_top * nin
    if both:
        mids = np.asarray(back).mean(1)
        lowest = mids[:, 1].max()
        centres = np.vstack([mids, centres[front[:, 1] > lowest + 4]])
    R0w, dax, nax, Lh = hm.head_frame(h, e)
    def unpack(x):
        return dict(tQ=x[0], vQ=x[1], angQ=x[2], alpha=x[3], beta=x[4], r_top=r_top, tau_a=0.35, join_s=JOIN[name])
    def residuals(x):
        nk = unpack(x)
        Cn, rn = hm.neck_curve(nk, h, e, J, TJ, KJ, rJ, n=120)
        I = to_img(Cn)
        res = list(np.linalg.norm(centres[:, None] - I[None], axis=2).min(1))
        T = np.gradient(Cn, axis=0); A2 = np.gradient(T, axis=0)
        k = np.linalg.norm(np.cross(T, A2), axis=1) / np.maximum(np.linalg.norm(T, axis=1) ** 3, 1e-9)
        res += list(20 * np.maximum(0, k * rn * 1.3 - 1))
        res.append(5 * max(0.0, hm.head_distance(h, e, Cn[:1])[0] + 0.5 * r_top))
        # nothing of the neck's outline outside the object's silhouette
        T2 = I[2:] - I[:-2]; T2 = np.vstack([T2[:1], T2, T2[-1:]]); T2 /= np.linalg.norm(T2, axis=1, keepdims=True)
        Nn = np.column_stack([-T2[:, 1], T2[:, 0]])
        for sgn in (1, -1):
            E = I + sgn * rn[:, None] * Nn
            xi = np.clip(np.round(E[:, 0]).astype(int), 0, OUT_D.shape[1] - 1); yi = np.clip(np.round(E[:, 1]).astype(int), 0, OUT_D.shape[0] - 1)
            res += list(2 * OUT_D[yi, xi])
        return np.asarray(res)
    Q0 = to_w(centres[:1])[0] + (R0w + dax * 0.25 * Lh - to_w(centres[:1])[0]) * 0.6
    v = J - Q0; ang0 = np.degrees(np.arctan2(v @ nax, v @ dax))
    x0 = [float(((Q0 - R0w) @ dax) / Lh), float((Q0 - R0w) @ nax), ang0, 0.6 * np.linalg.norm(v), 0.6 * np.linalg.norm(v)]
    lo = [0.0, -0.5 * Lh, ang0 - 70, 10, 10]; hi = [0.45, 0.2 * Lh, ang0 + 70, 500, 500]
    x0 = list(np.clip(x0, np.asarray(lo) + 1e-6, np.asarray(hi) - 1e-6))
    sol = optimize.least_squares(residuals, x0, bounds=(lo, hi), x_scale=[0.1, 10, 10, 50, 50])
    nk = {k: float(v_) for k, v_ in unpack(sol.x).items()}
    necks.append(nk)
    rr = residuals(sol.x)[: len(centres)]
    report[name].update(neck_centre_rms=float(np.sqrt(np.mean(rr ** 2))), r_top=r_top, J_img=to_img(J[None])[0].round(1).tolist(), rJ=rJ,
                        centres_measured=len(centres), both_edges=both)
    CENTRES[name] = centres

q = dict(p)
q["head_profiles"] = heads
q["necks"] = necks
q["neck_blend"] = 12.0
json.dump(q, open(out_path, "w"), indent=1)
print(json.dumps(report, indent=1))
print(json.dumps({"head_profiles": heads, "necks": necks}, indent=1))

# overlay: reference crop with the fitted head outline (z = 0 section), neck edges, Q and J
ref = Image.open("ref/reference.png").convert("RGB")
for name, h, nk, (P, dd), box in zip(("yellow", "blue"), heads, necks, ((m["PY"], s), (m["PB"], L - s)),
                                     ((270, 260, 560, 560), (890, 250, 1190, 560))):
    J, TJ, KJ = hm.strand_at(P, dd, nk["join_s"])
    rJ = report[name]["rJ"]
    im = ref.crop(box).resize(((box[2] - box[0]) * 2, (box[3] - box[1]) * 2), Image.LANCZOS)
    dr = ImageDraw.Draw(im)
    X = lambda pt: ((pt[0] - box[0]) * 2, (pt[1] - box[1]) * 2)
    # head outline: sample the z = 0 section's zero set on a grid
    xs, ys = np.meshgrid(np.arange(box[0], box[2], 0.5), np.arange(box[1], box[3], 0.5))
    W = to_w(np.column_stack([xs.ravel(), ys.ravel()]))
    hd = hm.head_distance(h, e, W).reshape(xs.shape)
    Cn, rn = hm.neck_curve(nk, h, e, J, TJ, KJ, rJ)
    I = to_img(Cn)
    nd = (np.linalg.norm(np.column_stack([xs.ravel(), ys.ravel()])[:, None] - I[None], axis=2) - rn[None]).min(1).reshape(xs.shape)
    for field, col in ((hd, (200, 0, 200)), (nd, (0, 140, 255)), (np.minimum(hd, nd), (0, 0, 0))):
        edge = (field < 0) & ~((np.roll(field, 1, 0) < 0) & (np.roll(field, -1, 0) < 0) & (np.roll(field, 1, 1) < 0) & (np.roll(field, -1, 1) < 0))
        for y, x in zip(*np.nonzero(edge)):
            dr.point(X((xs[y, x], ys[y, x])), fill=col)
    dr.line([X(pt) for pt in I], fill=(0, 140, 255), width=2)
    for c_ in CENTRES[name]: dr.ellipse([X(c_)[0] - 2, X(c_)[1] - 2, X(c_)[0] + 2, X(c_)[1] + 2], fill=(255, 0, 0))
    R0, dax, nax, Lh_ = hm.head_frame(h, e)
    for key, col in (("U", (0, 170, 0)), ("Lo", (230, 120, 0))):
        for tw, vw in SAMPLES[name][key]:
            W_ = R0 + dax * tw * Lh_ + nax * vw
            pt = to_img(W_[None])[0]
            dr.ellipse([X(pt)[0] - 2, X(pt)[1] - 2, X(pt)[0] + 2, X(pt)[1] + 2], fill=col)
    for pt, lab_ in ((I[0], "Q"), (I[-1], "J")):
        dr.ellipse([X(pt)[0] - 5, X(pt)[1] - 5, X(pt)[0] + 5, X(pt)[1] + 5], outline=(0, 0, 0), width=2); dr.text((X(pt)[0] + 7, X(pt)[1]), lab_, fill=(0, 0, 0))
    im.save(f"{overlay_dir}/init-{name}.png")
