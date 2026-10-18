"""Fit one head's rear cap and upper neck to the reference outline at the hero camera, from
the analytic picture-plane outline: the head's z = 0 section and the neck's discs, smooth-
unioned. Only the listed local parameters move; everything else stays as it is."""
import json, sys
import numpy as np
from scipy.optimize import least_squares
sys.path.insert(0, __file__.rsplit("/", 1)[0])
import snakefit as sf
import headmodel as hm
from scipy import ndimage

params_in, params_out, name = sys.argv[1], sys.argv[2], sys.argv[3]
p = json.load(open(params_in))
e = np.radians(p["cam"]["elev"]); k_blend = p.get("neck_blend", 12.0)
i = 0 if name == "yellow" else 1
m = sf.build(p, 3000); s = m["s"]; L = s[-1]
sw = np.asarray(p.get("swell", [1.0]), float); g = lambda x: np.interp(x, np.linspace(0, L, len(sw)), sw)
P, dd = (m["PY"], s) if name == "yellow" else (m["PB"], L - s)
nk0 = p["necks"][i]; h0 = p["head_profiles"][i]
J, TJ, KJ = hm.strand_at(P, dd, nk0["join_s"])
rJ = float(p["a"] * g(nk0["join_s"] if name == "yellow" else L - nk0["join_s"]))
to_w = lambda Q: np.column_stack([Q[:, 0], -Q[:, 1] / np.cos(e), np.zeros(len(Q))])
to_img = lambda W: np.column_stack([W[:, 0], -(W[:, 1] * np.cos(e) - W[:, 2] * np.sin(e))])
smin = lambda a, b, k: np.minimum(a, b) - np.maximum(k - np.abs(a - b), 0) ** 2 / (4 * k)

# the reference: the head-and-neck component's row extents
_, lab = sf.ref_labels("ref/reference.png", 1.0)
seed = (405, 305) if name == "yellow" else (1060, 300)
cc, _ = ndimage.label(lab == (2 if name == "yellow" else 1))
A = ndimage.binary_fill_holes(cc == cc[seed[1], seed[0]])
cfg = json.loads(sys.argv[4])
rows_back, rows_front = np.arange(*cfg["back"]), np.arange(*cfg["front"])
x0_, x1_ = cfg["x"]
def ext(mask, ys, side):
    out = []
    for y in ys:
        r = np.nonzero(mask[y, x0_:x1_])[0]
        out.append(x0_ + (r.min() if side == "min" else r.max()) if len(r) else np.nan)
    return np.array(out, float)
# which side is the back: for yellow (facing left) the back is the right-hand edge
back_side, front_side = ("max", "min") if name == "yellow" else ("min", "max")
ref_back, ref_front = ext(A, rows_back, back_side), ext(A, rows_front, front_side)

keys = cfg["keys"]
def unpack(x):
    h = json.loads(json.dumps(h0)); nk = dict(nk0)
    for k_, v in zip(keys, x):
        if k_ == "dR":   # move the rear point along the axis, tip fixed
            R0, d, n, Lh = hm.head_frame(h0, e)
            d_img = to_img((R0 + d * v)[None])[0]; h["rear"] = d_img.tolist()
        elif k_.startswith("U") or k_.startswith("D") or k_.startswith("Lo"):
            arr, j = k_.rstrip("0123456789"), int(k_[len(k_.rstrip("0123456789")):])
            h[arr][j] = v
        else: nk[k_] = v
    return h, nk

xs = np.arange(x0_, x1_, 0.5)
def outline_rows(h, nk, ys, side):
    X, Y = np.meshgrid(xs, ys.astype(float))
    Q = np.column_stack([X.ravel(), Y.ravel()])
    hd = hm.head_distance(h, e, to_w(Q))
    # first-order distance (the field's gradient) so the blend acts over k as it does in 3D
    eps = 0.5
    gx = (hm.head_distance(h, e, to_w(Q + [eps, 0])) - hm.head_distance(h, e, to_w(Q - [eps, 0]))) / (2 * eps)
    gy = (hm.head_distance(h, e, to_w(Q + [0, eps])) - hm.head_distance(h, e, to_w(Q - [0, eps]))) / (2 * eps)
    hd = hd / np.maximum(np.hypot(gx, gy), 0.2)
    C, r = hm.neck_curve(nk, h, e, J, TJ, KJ, rJ + 0.3, n=70); c = to_img(C)
    nd = (np.linalg.norm(Q[:, None] - c[None], axis=2) - r[None]).min(1)
    F = smin(hd, nd, k_blend).reshape(X.shape)
    out = []
    for row in F:
        idx = np.nonzero(row < 0)[0]
        if not len(idx): out.append(np.nan); continue
        j = idx[0] if side == "min" else idx[-1]
        j2 = j - 1 if side == "min" else j + 1
        if 0 <= j2 < len(row): out.append(xs[j] + (xs[j2] - xs[j]) * (-row[j]) / (row[j2] - row[j]))
        else: out.append(xs[j])
    return np.array(out)

x_init = np.array([0.0 if k_ == "dR" else (h0[k_.rstrip("0123456789")][int(k_[len(k_.rstrip("0123456789")):])] if k_[0] in "UDL" else nk0.get(k_, 0.0)) for k_ in keys])
scale = np.array(cfg["scale"])
def res(x):
    h, nk = unpack(x)
    rb = outline_rows(h, nk, rows_back, back_side) - ref_back
    rf = outline_rows(h, nk, rows_front, front_side) - ref_front
    r = np.r_[rb, rf]; r = np.where(np.isfinite(r), r, 10.0)
    return np.r_[r, 0.3 * (x - x_init) / scale]
r0 = res(x_init)[:len(rows_back) + len(rows_front)]
fit = least_squares(res, x_init, x_scale=scale, diff_step=0.02, max_nfev=200)
r1 = res(fit.x)[:len(rows_back) + len(rows_front)]
nb = len(rows_back)
print("params", dict(zip(keys, np.round(x_init, 2))), "->", dict(zip(keys, np.round(fit.x, 2))))
print(f"back  rows: mean |err| {np.abs(r0[:nb]).mean():.2f} max {np.abs(r0[:nb]).max():.2f} -> {np.abs(r1[:nb]).mean():.2f} max {np.abs(r1[:nb]).max():.2f}")
print(f"front rows: mean |err| {np.abs(r0[nb:]).mean():.2f} max {np.abs(r0[nb:]).max():.2f} -> {np.abs(r1[nb:]).mean():.2f} max {np.abs(r1[nb:]).max():.2f}")
for y, a, b in zip(rows_back[::3], r0[:nb][::3], r1[:nb][::3]): print("  back", y, round(a, 1), round(b, 1))
h, nk = unpack(fit.x)
p["head_profiles"][i] = h; p["necks"][i] = nk
json.dump(p, open(params_out, "w"), indent=1)
