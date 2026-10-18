"""Fast screening of candidate starts with the soft raster (no fit, no Three.js): per registry
feature in a window, the IoU of the feature's colour inside its own mask against the raster's
hard labels (the raster agrees with real renders to ~0.99 of pixels). For choosing which starts
are worth a fit and a real render, not for accepting anything.
Usage (from the logo root): screen.py x0,y0,x1,y1 F1,F2,... spec.json [spec.json ...]"""
import json, os, sys
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import strandspline as S
import jaxraster as jr
import jax.numpy as jnp
from evaluate import load_registry

ELEV = np.radians(3.7746862033886837)
box = tuple(int(v) for v in sys.argv[1].split(","))
feats = sys.argv[2].split(",")
reg, lab, _ = load_registry()
ids = [f["id"] for f in reg["features"]]
x0, y0, x1, y1 = box
grid, shape = jr.window_grid(box, 1.0)
L = lab[y0:y1, x0:x1]
print("spec".ljust(28) + "".join(f"{f:>7s}" for f in feats) + "   mean")
for path in sys.argv[3:]:
    sp = json.load(open(path))
    P, R, Z, OH = [], [], [], []
    for k, n in ((1, "yellow"), (0, "blue")):
        st = sp[n]; u = np.arange(st["s0"], st["s1"], 2.0)
        X, r = S.evaluate(st, u); q = S.evaluate_sec(st, u)
        P.append(X); R.append(r * q[:, 0]); Z.append(q[:, 1] / q[:, 0])
        o = np.zeros((len(u), 2)); o[:, k] = 1; OH.append(o)
    P, R, Z, OH = map(np.concatenate if False else np.vstack, (P, [r[:, None] for r in R], [z[:, None] for z in Z], OH))
    R, Z = R[:, 0], Z[:, 0]
    keep = (P[:, 0] + R > x0 - 10) & (P[:, 0] - R < x1 + 10)
    # in chunks of pixels: a whole-frame window at every ball would not fit in memory
    g = np.asarray(grid)
    prob = np.concatenate([np.asarray(jr.soft_labels(jnp.asarray(P[keep]), jnp.asarray(R[keep]), jnp.asarray(OH[keep]), jnp.asarray(g[k:k + 4000]), ELEV, tau=0.3, gamma=0.3, zscale=jnp.asarray(Z[keep]))) for k in range(0, len(g), 4000)])
    pred = prob.argmax(1).reshape(shape)            # 0 bg, 1 blue, 2 yellow
    row = []
    for f in feats:
        i = ids.index(f); c = 1 if reg["features"][i]["colour"] == "blue" else 2
        m = L == i + 1
        # the feature's mask against the same-coloured prediction inside the feature's dilated window
        fx0, fy0, fx1, fy1 = reg["features"][i]["bbox"]
        win = np.zeros_like(m); win[max(fy0 - y0 - 15, 0):fy1 - y0 + 15, max(fx0 - x0 - 15, 0):fx1 - x0 + 15] = True
        pc = (pred == c) & win
        row.append((m & pc).sum() / max((m | (pc & ~(np.isin(L, [j + 1 for j, g in enumerate(reg["features"]) if g["colour"] == reg["features"][i]["colour"] and j != i])))).sum(), 1))
    print(os.path.basename(path)[:28].ljust(28) + "".join(f"{v:7.2f}" for v in row) + f"  {np.mean(row):.3f}")
