"""Local fit of the twist through the W's two valley bottoms: only the anchors there (arc
position and phase) and the spine offsets under them move; scored on colour-label agreement
with the reference inside a window around each valley. Everything else stays as it is."""
import json, sys, time
import numpy as np
from scipy import ndimage
from scipy.optimize import minimize
sys.path.insert(0, __file__.rsplit("/", 1)[0])
import snakefit as sf

p0 = json.load(open(sys.argv[1])); out = sys.argv[2]
cfg = json.loads(sys.argv[3])
scale = 0.5
ref_small, _ = sf.ref_labels("ref/reference.png", scale)
H, W = ref_small.shape
win = np.zeros((H, W), bool)
for x0, y0, x1, y1 in cfg["windows"]:
    win[int(y0 * scale):int(y1 * scale), int(x0 * scale):int(x1 * scale)] = True
dref = {c: ndimage.distance_transform_edt(ref_small != c) for c in (1, 2)}
# which spine knots lie under the windows
m0 = sf.build(p0, 1400); L = m0["s"][-1]
e = np.radians(p0["cam"]["elev"])
img = np.column_stack([m0["C"][:, 0], -(m0["C"][:, 1] * np.cos(e) - m0["C"][:, 2] * np.sin(e))])
kn = np.linspace(0, L, len(p0["spine_offsets"]))
inwin = lambda xy: any(x0 <= xy[0] <= x1 and y0 <= xy[1] <= y1 for x0, y0, x1, y1 in cfg["windows"])
knots = [k for k, sk in enumerate(kn) if inwin(img[np.argmin(np.abs(m0["s"] - sk))])]
anchors = cfg["anchors"]
print("spine knots moved:", knots, " anchors moved:", anchors)

def unpackv(v):
    q = json.loads(json.dumps(p0)); i = 0
    for a in anchors:
        q["anchor_offsets"][a] += v[i]; q["anchor_xy"][a][2] += v[i + 1]; i += 2
    for k in knots:
        q["spine_offsets"][k] += v[i]; i += 1
    return q
nv = 2 * len(anchors) + len(knots)
step = np.array([12.0, 0.5] * len(anchors) + [6.0] * len(knots))
def loss(v, report=False):
    q = unpackv(v * step)
    lab, _ = sf.render_labels(q, (H, W), scale, 1400)
    tot = 0.0
    for c in (1, 2):
        mm = (lab == c) & win; rm = (ref_small == c) & win
        if not mm.any(): return 1e6
        dm = ndimage.distance_transform_edt(~(lab == c))
        tot += dref[c][mm].mean() + dm[rm].mean()
    mis = (lab[win] != ref_small[win]).mean() * 100
    reg = 0.5 * np.sum(v ** 2)
    if report: return dict(chamfer=round(tot, 2), mismatch_pct=round(mis, 2))
    return tot + mis + reg
t = time.time(); l0 = loss(np.zeros(nv)); print("eval", round(time.time() - t, 3), "s; start", loss(np.zeros(nv), True))
res = minimize(loss, np.zeros(nv), method="Powell", options=dict(maxfev=cfg.get("maxfev", 1500), xtol=0.02, ftol=1e-3))
print("end", loss(res.x, True), "nfev", res.nfev)
v = res.x * step
for k_, a in enumerate(anchors): print(f"  anchor {a}: arc {v[2*k_]:+.1f} px, phase {v[2*k_+1]:+.2f} rad")
print("  spine offsets:", {k: round(float(x), 1) for k, x in zip(knots, v[2 * len(anchors):])})
json.dump(unpackv(res.x), open(out, "w"), indent=1)
