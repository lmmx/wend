"""Surrogate fidelity along a fit's path: control points c(a) = c0 + a (c1 - c0) for a in
0..1. At each a, the soft raster's hard labels and a real Three.js render's colour labels (the
same colour classifier as the reference's) are both scored against the reference labels in a
window, and against each other. If the surrogate is faithful, the two agreement curves move
together and the raster-vs-render agreement stays high.
Usage (from the logo root, logo/snake-w): fidelity.py start.json fit.json x0,y0,x1,y1 tag"""
import copy, json, os, subprocess, sys
import numpy as np
T = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, T)
import strandspline as S
import jaxraster as jr
import snakefit as sf
import jax.numpy as jnp
a0, a1, box, tag = json.load(open(sys.argv[1])), json.load(open(sys.argv[2])), tuple(int(v) for v in sys.argv[3].split(",")), sys.argv[4]
ELEV = np.radians(3.7746862033886837)
alphas = [0.0, 0.25, 0.5, 0.75, 1.0]
_, ref = sf.ref_labels("snakes/ref/reference.png", 1.0)
x0, y0, x1, y1 = box; R = ref[y0:y1, x0:x1]
jobs, specs = [], []
cj = json.load(open("cmp/colourjobs.json"))[0]
for a in alphas:
    sp = copy.deepcopy(a0)
    for n in ("yellow", "blue"):
        for k in ("ctrl", "rctrl"):
            sp[n][k] = (np.asarray(a0[n][k]) + a * (np.asarray(a1[n][k]) - np.asarray(a0[n][k]))).tolist()
    nm = f"spline-fid-{tag}-{a:.2f}.json"; json.dump(sp, open(f"snakes/{nm}", "w")); specs.append(sp)
    jobs.append({"out": f"../jfit/r/fid-{tag}-{a:.2f}.png", "params": "w-final.params.json", "query": {**cj["query"], "spec": nm}})
json.dump(jobs, open(f"jfit/r/fid-{tag}-jobs.json", "w"))
subprocess.run(["node", "../tools/spline_batch.mjs", f"../jfit/r/fid-{tag}-jobs.json"], cwd="snakes", check=True, capture_output=True)
grid, shape = jr.window_grid(box, 1.0)
print(f"{'alpha':>6} {'raster vs ref':>14} {'render vs ref':>14} {'raster vs render':>17}")
for a, sp in zip(alphas, specs):
    P, Rr, oh = [], [], []
    for k, n in ((1, "yellow"), (0, "blue")):
        u = np.arange(sp[n]["s0"], sp[n]["s1"], 2.0); X, r = S.evaluate(sp[n], u)
        P.append(X); Rr.append(r); o = np.zeros((len(u), 2)); o[:, k] = 1; oh.append(o)
    P, Rr, oh = np.vstack(P), np.concatenate(Rr), np.vstack(oh)
    Pw, rw, ow = jr.balls_in_window(P, Rr, oh, ELEV, box)
    pred = np.asarray(jr.soft_labels(jnp.asarray(Pw), jnp.asarray(rw), jnp.asarray(ow), grid, ELEV, tau=0.3, gamma=0.3)).argmax(1).reshape(shape)
    _, lab = sf.ref_labels(f"jfit/r/fid-{tag}-{a:.2f}.png", 1.0)
    ren = lab[y0:y1, x0:x1]
    print(f"{a:6.2f} {np.mean(pred == R):14.3f} {np.mean(ren == R):14.3f} {np.mean(pred == ren):17.3f}")
