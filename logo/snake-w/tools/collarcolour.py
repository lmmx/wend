"""Fit the right collar's depth order and placement against colour agreement (2026-10-20).

The mask measures score the incumbent's diagonal L16 at IoU 0.86 although it reads as a different
shape: what differs is which strand is in front where (the reference's round yellow collar end
on the left of the blue neck, against the render's blue L15 climbing up there). The objective is
therefore the share of pixels in the collar window whose colour (yellow / blue / background)
disagrees with the reference, plus the usual guards (neighbour IoU, strays, clay creases,
junction creases). Parameters: collardepth.py's dz_y, dz_b, dy_b, dy_y and the yellow tail's
radius floor.
--ring: fit ringcollar.py's level ring instead (c fixed at 1: the collar crosses the front level,
as the reference's highlight shows; free h_c, rho_c, dphi, r_c), against the same colour objective.
Usage (from the logo root): collarcolour.py INC_SPEC OUT_DIR [--gens 14] [--ring]"""
import argparse, json, os, subprocess, sys, time
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import lobekit as K
import geodiag as G
from lobefit import cma
from PIL import Image

NAMES = ["dz_y", "dz_b", "dy_b", "dy_y", "floor"]
X0 = np.array([0.0, 0.0, 0.0, 0.0, 0.0]); SCALE = np.array([8.0, 8.0, 5.0, 6.0, 0.3])
LO = np.array([-10.0, -40.0, -10.0, -15.0, 0.0]); HI = np.array([40.0, 10.0, 20.0, 25.0, 1.05])
WIN = (940, 370, 1110, 590)
ap = argparse.ArgumentParser(); ap.add_argument("spec"); ap.add_argument("out"); ap.add_argument("--gens", type=int, default=14); ap.add_argument("--workers", type=int, default=3)
ap.add_argument("--extra", default="hybrid-r28-hybR.json"); ap.add_argument("--ring", action="store_true")
A = ap.parse_args()
if A.ring:
    import ringcollar as RC
    NAMES = ["h_c", "rho_c", "dphi", "r_c"]; X0 = np.array([-20.0, 72.0, 0.0, 42.0]); SCALE = np.array([10.0, 6.0, 0.25, 3.0])
    LO = np.array([-60.0, 50.0, -1.0, 34.0]); HI = np.array([25.0, 95.0, 1.0, 50.0]); os.makedirs(A.out, exist_ok=True)
ref = G.masks(G.REF)["lab"]; x0, y0, x1, y1 = WIN; RW = ref[y0:y1, x0:x1]; RW = np.where(RW == 3, 0, RW)
W = [K.Worker(i, os.path.abspath(".")) for i in range(A.workers)]
sc = K.Scorer([880, 250, 1180, 780], ["H2", "L16", "L15", "L14", "L13", "L12"])
def build(x, path):
    if A.ring:
        sp = RC.apply(json.load(open(A.spec)), [1.0, *x]); json.dump(sp, open(path, "w")); return sp
    a = [str(v) for v in x[:3]]
    subprocess.run([sys.executable, os.path.join(HERE, "collardepth.py"), A.spec, path, *a, "--dy_y", str(x[3]), "--floor", str(x[4])], check=True, capture_output=True)
    return json.load(open(path))
def measure(spec, wi, tag):
    w = W[wi % len(W)]
    p, s = os.path.abspath(f"{A.out}/w{w.wid}-{tag}.png"), os.path.abspath(f"{A.out}/w{w.wid}-{tag}-s.png")
    w.call(spec_obj=spec, out=p, clip=[0, 0, 1448, 1086], box=[0, 0, 1448, 1086], shade=s, extra=A.extra)
    M = G.masks(p); lab = np.where(M["lab"] == 3, 0, M["lab"])[y0:y1, x0:x1]
    im = np.asarray(Image.open(p).convert("RGB")); sh = np.asarray(Image.open(s).convert("L"))
    m, ex = sc.measure(im[250:780, 880:1180], sh[250:780, 880:1180])
    return float((lab != RW).mean()), m, ex
inc = json.load(open(A.spec))
d0, m0, e0 = measure(inc, 0, "inc")
def J(meas):
    d, m, ex = meas
    pen = 0.0
    for g in ("H2", "L14", "L13", "L12"):
        pen += 5 * max(0.0, m0[g]["iou"] - m[g]["iou"] - 0.005)
    pen += max(0.0, ex["stray"] - e0["stray"] - 20) / 60
    for g, cr in ex["crease"].items(): pen += 0.5 * max(0.0, cr / max(e0["crease"].get(g, 0.6), 0.6) - 1.3)
    for jk, cr in ex["junction"].items(): pen += 0.5 * max(0.0, cr / max(e0["junction"].get(jk, 0.6), 0.6) - 1.15)
    return 20 * d + pen, d, pen
print("incumbent colour disagreement %.4f" % d0, "J", J((d0, m0, e0)), flush=True)
def f(z, wi):
    x = np.clip(X0 + z * SCALE, LO, HI)
    meas = measure(build(x, os.path.abspath(f"{A.out}/cand-{wi}.json")), wi, "c"); j = J(meas)
    return j[0], j, {k: round(v["iou"], 3) for k, v in meas[1].items()}, meas[2]["stray"]
def log(g, best, F, sigma):
    x = np.clip(X0 + best[1] * SCALE, LO, HI)
    print(f"gen {g}: best {best[0]:.4f} disagree {best[2][1][1]:.4f} {dict(zip(NAMES, np.round(x, 2).tolist()))} iou {best[2][2]} stray {best[2][3]} sigma {sigma:.2f}", flush=True)
t0 = time.time()
best = cma(f, len(NAMES), 0.8, (LO - X0) / SCALE, (HI - X0) / SCALE, A.gens, A.workers, seed=38, log=log, m0=None if A.ring else (np.array([20.0, -15.0, 8.0, 5.0, 0.9]) - X0) / SCALE)
x = np.clip(X0 + best[1] * SCALE, LO, HI)
build(x, f"{A.out}/spec.json")
json.dump(dict(x=x.tolist(), names=NAMES, J=best[0], parts=best[2][1], inc=dict(disagree=d0), minutes=(time.time() - t0) / 60), open(f"{A.out}/fit.json", "w"), indent=1, default=float)
print("done", dict(zip(NAMES, np.round(x, 2).tolist())), flush=True)
for w in W: w.close()
