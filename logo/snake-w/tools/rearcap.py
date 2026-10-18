"""Blunt the blue rear cap: fit the first U controls (and the rear point) so the head's upper
outline follows the reference's rear crown arc; D near the rear raised by the same factor so
the 3D rear is a dome, not a wedge."""
import json, sys
import numpy as np
from scipy.optimize import least_squares
sys.path.insert(0, __file__.rsplit("/", 1)[0])
import headmodel as hm
p = json.load(open(sys.argv[1])); out = sys.argv[2]
R = json.load(open("heads2/headref.json"))["blue"]
e = np.radians(p["cam"]["elev"])
h0 = p["head_profiles"][1]
to_img = lambda W: np.column_stack([W[:, 0], -(W[:, 1] * np.cos(e) - W[:, 2] * np.sin(e))])
C = np.asarray(R["contour"]); outer = np.asarray(R["outer"], bool)
sel = outer & (C[:, 0] < 1075) & (C[:, 1] < 352) & (C[:, 1] > 270)
Pr = C[sel]
print("reference rear-crown points", len(Pr))
def outline(h, t=np.linspace(0, 0.55, 400)):
    R0, d, n, Lh = hm.head_frame(h, e)
    u, _, _ = hm.head_profiles(h, t)
    return to_img(R0[None] + d[None] * (t * Lh)[:, None] + n[None] * u[:, None])
def make(x):
    h = json.loads(json.dumps(h0))
    h["U"][0], h["U"][1], h["U"][2] = x[0], x[1], x[2]
    return h
def res(x):
    O = outline(make(x))
    dd = np.linalg.norm(Pr[:, None] - O[None], axis=2).min(1)
    return np.r_[dd, 0.02 * (x - np.array(h0["U"][:3]))]
x0 = np.array(h0["U"][:3], float)
r0 = res(x0)[:len(Pr)]
fit = least_squares(res, x0, bounds=([30, 30, 30], [260, 260, 260]))
r1 = res(fit.x)[:len(Pr)]
print("U[:3]", x0.round(1), "->", fit.x.round(1), " rear-crown error mean/max", r0.mean().round(2), r0.max().round(2), "->", r1.mean().round(2), r1.max().round(2))
h = make(fit.x)
# depth: the same blunting near the rear, so sections there stay as round as further forward
f = fit.x / x0
h["D"][0] *= f[0]; h["D"][1] *= f[1]; h["D"][2] *= np.sqrt(f[2])
print("D[:3]", np.round(h0["D"][:3], 1), "->", np.round(h["D"][:3], 1))
p["head_profiles"][1] = h
json.dump(p, open(out, "w"), indent=1)
