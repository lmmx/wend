"""A render-free predictor of each visible lobe's centroid, orientation and size.

The spine lies in the picture plane and the camera is nearly frontal, so at each station s
the view direction lies in the cross-section, and which strand is visible across the rope is
a 1-D question: at lateral offset l (along the in-plane normal N), each strand's front
surface is z_k(l) = z_k + sqrt(a_k^2 - (l - l_k)^2), and the nearer one wins. With a sigmoid
in place of the hard choice, that is a smooth label map over (s, l). A lobe is one strand's
share of it within its anchor's window along s; its centroid and second moments are sums of
the projected points weighted by that share and by the area element ds dl (1 - kappa l),
clipped at 0 where the inside of a tight bend folds over. No pixels, no z-buffer: every step
is array arithmetic, so it ports to JAX as is.

Checked here against the lobes measured on the actual render (lobecmp's extraction)."""
import json, sys, time
import numpy as np
sys.path.insert(0, __file__.rsplit("/", 1)[0])
import snakefit as sf
import lobecmp_lib as lc

def predict(p, n=3000, nl=96, tau=1.5, erode=4.0):
    m = sf.build(p, n)
    s, C, L = m["s"], m["C"], m["s"][-1]
    e = np.radians(p["cam"]["elev"])
    T = np.gradient(C, s, axis=0); T /= np.linalg.norm(T, axis=1, keepdims=True)
    N = np.column_stack([-T[:, 1], T[:, 0], np.zeros(n + 1 if len(s) == n + 1 else len(s))])
    kap = np.einsum("ij,ij->i", np.gradient(T, s, axis=0), N)          # signed spine curvature
    z = np.array([0, 0, 1.0])
    out = {}
    for name, P, r in (("yellow", m["PY"], m["rY"]), ("blue", m["PB"], m["rB"])):
        out[name] = ((P - C) @ np.eye(3)[:, :3]).T, r
    lY, zY = np.einsum("ij,ij->i", m["PY"] - C, N), (m["PY"] - C) @ z
    lB, zB = np.einsum("ij,ij->i", m["PB"] - C, N), (m["PB"] - C) @ z
    rY, rB = m["rY"], m["rB"]
    W = (np.maximum(np.abs(lY) + rY, np.abs(lB) + rB)).max()
    l = np.linspace(-W, W, nl); dl = l[1] - l[0]
    fY = rY[:, None] ** 2 - (l[None] - lY[:, None]) ** 2
    fB = rB[:, None] ** 2 - (l[None] - lB[:, None]) ** 2
    hY = zY[:, None] + np.sqrt(np.maximum(fY, 0)); hB = zB[:, None] + np.sqrt(np.maximum(fB, 0))
    # covered: inside the strand's disc, softly, by `erode` px less (lobecmp erodes its masks)
    cY = 1 / (1 + np.exp(-(np.sqrt(np.maximum(fY, 0) + 1e-9) * np.sign(fY) - erode) / tau))
    cB = 1 / (1 + np.exp(-(np.sqrt(np.maximum(fB, 0) + 1e-9) * np.sign(fB) - erode) / tau))
    # in front: the nearer surface where both are present, by `erode` px of depth
    fr = 1 / (1 + np.exp(-(hY - hB) / tau))
    vis = {"yellow": cY * np.where(cB > 1e-3, 1 / (1 + np.exp(-(hY - hB - erode) / tau)), 1.0),
           "blue": cB * np.where(cY > 1e-3, 1 / (1 + np.exp(-(hB - hY - erode) / tau)), 1.0)}
    ds = np.gradient(s)
    area = ds[:, None] * dl * np.maximum(1 - kap[:, None] * l[None], 0)
    X = C[:, None, :] + l[None, :, None] * N[:, None, :]
    xy, _ = sf.project(X.reshape(-1, 3), p["cam"]); xy = xy.reshape(len(s), nl, 2)
    A = m["anchor_s"]; order = np.argsort(A)
    lobes = []
    for j, i in enumerate(order):
        lo = (A[order[j - 1]] + A[i]) / 2 if j > 0 else A[i] - 60
        hi = (A[order[j + 1]] + A[i]) / 2 if j < len(order) - 1 else A[i] + 60
        th = p["anchor_xy"][i][2]
        colour = "blue" if np.sin(th) > 0 else "yellow"
        wgt = vis[colour] * area * ((s > lo) & (s < hi))[:, None]
        Wt = wgt.sum()
        c = (wgt[..., None] * xy).sum((0, 1)) / Wt
        d = xy - c
        cov = np.einsum("ijk,ijl,ij->kl", d, d, wgt) / Wt
        ev, evec = np.linalg.eigh(cov)
        lobes.append(dict(anchor=int(i), colour=colour, cx=c[0], cy=c[1], area=Wt,
                          angle=float(np.degrees(np.arctan2(evec[1, 1], evec[0, 1]))) % 180,
                          sd_major=float(np.sqrt(ev[1])), sd_minor=float(np.sqrt(ev[0]))))
    return lobes

if __name__ == "__main__":
    params, render = sys.argv[1], sys.argv[2]
    p = json.load(open(params))
    t0 = time.time(); pred = predict(p); dt = time.time() - t0
    meas = [l for l in lc.lobes_of(render) if not l["head"]]
    for l in meas:
        ys, xs = np.nonzero(l["mask"]); X = np.column_stack([xs, ys]) - [l["cx"], l["cy"]]
        ev, evec = np.linalg.eigh(np.cov(X.T)); l["sd_major"], l["sd_minor"] = np.sqrt(ev[1]), np.sqrt(ev[0])
    print(f"predictor: {dt*1000:.0f} ms for {len(pred)} lobes (numpy, n=3000 x 96)")
    print(f"{'anchor':>6} {'colour':6} {'measured centre':>16} {'centre err':>10} {'angle err':>9} {'major x':>7} {'minor x':>7} {'area x':>6}")
    errs = []
    for q in pred:
        cand = [l for l in meas if l["colour"] == q["colour"]]
        l = min(cand, key=lambda l: np.hypot(l["cx"] - q["cx"], l["cy"] - q["cy"]))
        dc = np.hypot(l["cx"] - q["cx"], l["cy"] - q["cy"])
        da = (q["angle"] - l["angle"] + 90) % 180 - 90
        elong = l["sd_major"] / l["sd_minor"]
        errs.append((dc, abs(da) if elong > 1.3 else np.nan, q["sd_major"] / l["sd_major"], q["sd_minor"] / l["sd_minor"], q["area"] / l["area"]))
        print(f"{q['anchor']:6d} {q['colour']:6} ({l['cx']:5.0f},{l['cy']:4.0f}) {dc:10.1f} {da:+9.0f} {q['sd_major']/l['sd_major']:7.2f} {q['sd_minor']/l['sd_minor']:7.2f} {q['area']/l['area']:6.2f}" + ("" if elong > 1.3 else "  (round: angle undefined)"))
    E = np.array(errs)
    print(f"median centre err {np.nanmedian(E[:,0]):.1f} px (max {np.nanmax(E[:,0]):.1f}); median |angle err| {np.nanmedian(E[:,1]):.0f} deg; "
          f"major ratio median {np.nanmedian(E[:,2]):.2f}, minor {np.nanmedian(E[:,3]):.2f}, area {np.nanmedian(E[:,4]):.2f}")
