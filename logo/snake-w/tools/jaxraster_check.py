"""Parity: does the soft rasteriser, in its hard limit, reproduce the actual Three.js render's
colour labels? Per window, IoU of blue and yellow between the two, for the dumped strands."""
import json, sys, time
import numpy as np
import jax.numpy as jnp
sys.path.insert(0, __file__.rsplit("/", 1)[0])
import jaxraster as jr
import snakefit as sf

strands, render = sys.argv[1], sys.argv[2]
S = json.load(open(strands)); elev = np.radians(S["elev"])
P, r, oh = [], [], []
for k, name in ((0, "blue"), (1, "yellow")):
    p = np.asarray(S[name]["pts"])[::4]; rr = np.asarray(S[name]["r"])[::4]
    P.append(p); r.append(rr); o = np.zeros((len(p), 2)); o[:, k] = 1; oh.append(o)
P, r, oh = np.vstack(P), np.concatenate(r), np.vstack(oh)
_, lab = sf.ref_labels(render, 1.0)
for name, box in (("left valley", (420, 560, 700, 800)), ("right valley", (800, 540, 1080, 800)), ("central arch", (600, 380, 880, 620)), ("left arm", (380, 380, 520, 660))):
    Pw, rw, ow = jr.balls_in_window(P, r, oh, elev, box)
    grid, shape = jr.window_grid(box, 1.0)
    t = time.time()
    prob = np.asarray(jr.soft_labels(jnp.asarray(Pw), jnp.asarray(rw), jnp.asarray(ow), grid, elev, tau=0.3, gamma=0.3))
    dt = time.time() - t
    pred = prob.argmax(1).reshape(shape)            # 0 bg, 1 blue, 2 yellow (as ref_labels)
    x0, y0, x1, y1 = box; ren = lab[y0:y1, x0:x1]
    iou = {c: ((pred == k) & (ren == k)).sum() / max(((pred == k) | (ren == k)).sum(), 1) for c, k in (("blue", 1), ("yellow", 2), ("silhouette", None)) if k}
    sil = ((pred > 0) & (ren > 0)).sum() / ((pred > 0) | (ren > 0)).sum()
    agree = (pred == ren).mean()
    print(f"{name:13s} balls {len(Pw):4d}  blue IoU {iou['blue']:.3f}  yellow IoU {iou['yellow']:.3f}  silhouette IoU {sil:.3f}  pixel agreement {agree:.3f}  ({dt:.2f} s incl. compile)")
