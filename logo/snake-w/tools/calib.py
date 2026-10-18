"""Calibrate the contact allowance on the straight parts of the rope, and see what the image
term wants in the right valley (soft-raster labels of the spline body vs reference labels)."""
import json, sys, os
import numpy as np
T = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, T)
import strandspline as S
import jaxraster as jr, jax.numpy as jnp
import snakefit as sf
from PIL import Image
spec = json.load(open(sys.argv[1])); L = spec["L"]; elev = np.radians(3.7746862033886837)
ys, bs = spec["yellow"], spec["blue"]
# spine = midpoint of yellow(s) and blue(L - s)
sh = np.arange(max(ys["s0"], L - bs["s1"]), min(ys["s1"], L - bs["s0"]), 2.0)
Y, ry = S.evaluate(ys, sh); B, rb = S.evaluate(bs, L - sh)
C = 0.5 * (Y + B)
d1 = np.gradient(C, axis=0) / 2.0; d2 = np.gradient(d1, axis=0) / 2.0
kap = np.linalg.norm(np.cross(d1, d2), axis=1) / np.linalg.norm(d1, axis=1) ** 3
from scipy.ndimage import gaussian_filter1d
kap = gaussian_filter1d(kap, 5)
print("spine bend radius by shared station (every 40):")
print("  " + "  ".join(f"{s:.0f}:{1/k:.0f}" for s, k in zip(sh[::20], kap[::20])))
straight = 1 / kap > 150
P = np.vstack([Y, B]); R = np.r_[ry, rb]; I = np.r_[np.zeros(len(sh)), np.ones(len(sh))]; St = np.r_[sh, sh]
D = np.linalg.norm(P[:, None] - P[None], axis=-1); ov = R[:, None] + R[None] - D
sep = np.abs(St[:, None] - St[None]); same = I[:, None] == I[None]
strt = np.r_[straight, straight]; both = strt[:, None] & strt[None]
print("\noverlap by shared-station separation: straight parts (p95, max) | everywhere (max)")
for lo in range(0, 140, 20):
    m = (sep >= lo) & (sep < lo + 20)
    out = []
    for nm, sm in (("same", same), ("across", ~same)):
        a = ov[m & sm & both]; b = ov[m & sm]
        out.append(f"{nm} {np.percentile(a,95):6.1f} {a.max():6.1f} | {b.max():6.1f}")
    print(f"  {lo:3d}-{lo+20:3d}: " + "    ".join(out))
# image term at the start
BOX = (800, 540, 1080, 800)
oh = np.zeros((len(P), 2)); oh[I == 1, 0] = 1; oh[I == 0, 1] = 1     # col 0 blue, col 1 yellow (as ref_labels 1, 2)
Pw, rw, ow = jr.balls_in_window(P, R, oh, elev, BOX)
grid, shape = jr.window_grid(BOX, 1.0)
prob = np.asarray(jr.soft_labels(jnp.asarray(Pw), jnp.asarray(rw), jnp.asarray(ow), grid, elev, tau=0.6, gamma=1.0))
pred = prob.argmax(1).reshape(shape)
_, lab = sf.ref_labels(os.path.join(T, "../snakes/ref/reference.png"), 1.0)
x0, y0, x1, y1 = BOX; ref = lab[y0:y1, x0:x1]
pal = np.array([[245, 245, 245], [40, 90, 220], [245, 200, 30]], np.uint8)
dis = np.where((pred != ref)[..., None], np.array([220, 40, 40], np.uint8), (pal[ref] * 0.35 + 160).astype(np.uint8))
out = np.concatenate([pal[ref], pal[pred], dis], 1)
Image.fromarray(out).resize((out.shape[1] * 2, out.shape[0] * 2), Image.NEAREST).save(sys.argv[2])
print("\nright valley: pixel agreement with reference", (pred == ref).mean().round(3),
      " blue IoU", (((pred == 1) & (ref == 1)).sum() / ((pred == 1) | (ref == 1)).sum()).round(3),
      " yellow IoU", (((pred == 2) & (ref == 2)).sum() / ((pred == 2) | (ref == 2)).sum()).round(3))
