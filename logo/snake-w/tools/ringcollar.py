"""The right collar as a ring (2026-10-20): the yellow strand's last turn around the blue neck,
in the neck's own frame (its axis from the neck curve, tau 0.3-1; up = towards the head; e2 towards
the camera, so phi 90 deg is the front). In the incumbent the turn crosses the front while still
climbing (h -68 -> 0 px along the axis over s 1290-1340): the diagonal band; the reference's
collar crosses the front level. Over s >= ramp start the path is re-expressed (h, rho, phi) and
  h   -> (1 - c w) h + c w h_c      (flatten the climb onto a level ring at height h_c)
  rho -> rho + w (rho_c - rho) c     (the ring's distance from the neck axis)
  phi -> phi + w dphi                (where the level part crosses the front)
  r   -> r + w (r_c - r)             (an even tube: no taper in sight)
w ramps in over RAMP (hidden stations between L14 and L16). The centreline and radius controls are
refitted where the path moved (same knots).
Usage (from the logo root):
  ringcollar.py build INC_SPEC OUT_SPEC c h_c rho_c dphi r_c
  ringcollar.py fit INC_SPEC OUT_DIR [--gens 14] [--workers 3]"""
import argparse, copy, json, os, sys
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import strandspline as SS
import headmodel as hm
from collarfit import lsq_fit

NAMES = ["c", "h_c", "rho_c", "dphi", "r_c"]
X0 = np.array([0.0, 0.0, 60.0, 0.0, 42.0]); SCALE = np.array([0.3, 15.0, 8.0, 0.35, 4.0])
LO = np.array([0.0, -60.0, 40.0, -1.2, 34.0]); HI = np.array([1.0, 30.0, 85.0, 1.2, 50.0])
RAMP = (1255.0, 1295.0)


def neck_frame(params_path="snakes/w-final.params.json", strands="geo/strands.json"):
    p = json.load(open(params_path)); G = json.load(open(strands)); e = np.radians(p["cam"]["elev"])
    b = G["blue"]; J, T, K = (np.array(b["join"][k]) for k in ("J", "T", "K"))
    C, _ = hm.neck_curve(p["necks"][1], p["head_profiles"][1], e, J, T, K, 50.5, n=41)
    sel = C[12:]; c0 = sel.mean(0); D = np.linalg.svd(sel - c0)[2][0]; D = D if D[1] > 0 else -D
    ez = np.array([0, 0, 1.0]); e2 = ez - (ez @ D) * D; e2 /= np.linalg.norm(e2); e1 = np.cross(D, e2)
    return c0, D, e1, e2


FRAME = neck_frame()
if os.environ.get("RING_AXIS") == "world":
    # the ring level in the world (axis world up through the neck's centre), not across the neck,
    # which leans ~25 deg towards the camera: the reference's collar reads level in the picture
    _c0 = FRAME[0]; _D = np.array([0.0, 1.0, 0.0]); _e2 = np.array([0.0, 0.0, 1.0]); FRAME = (_c0, _D, np.cross(_D, _e2), _e2)


def apply(spec0, x):
    c, h_c, rho_c, dphi, r_c = np.clip(np.asarray(x, float), LO, HI)
    c0, D, e1, e2 = FRAME
    spec = copy.deepcopy(spec0); st = spec["yellow"]
    u = np.r_[np.arange(st["s0"], st["s1"], 0.5), st["s1"]]; X, r = SS.evaluate(spec0["yellow"], u)
    rel = X - c0; h = rel @ D; o = rel - np.outer(h, D); rho = np.linalg.norm(o, axis=1); ph = np.unwrap(np.arctan2(o @ e2, o @ e1))
    w = SS.smoothstep(*RAMP, u)
    h2 = (1 - c * w) * h + c * w * h_c; rho2 = rho + w * (rho_c - rho) * c; ph2 = ph + w * dphi
    X2 = c0 + np.outer(h2, D) + rho2[:, None] * (np.cos(ph2)[:, None] * e1 + np.sin(ph2)[:, None] * e2)
    r2 = r + w * (r_c - r)
    t = SS.knots(st["s0"], st["s1"], st["nseg"]); old = np.asarray(st["ctrl"], float)
    free = np.array([i for i in range(len(old)) if t[i + 4] > RAMP[0] - 1e-9])
    st["ctrl"] = lsq_fit(t, u, X2, old, free).tolist()
    tr = SS.knots(st["s0"], st["s1"], st["rseg"]); st["rctrl"] = lsq_fit(tr, u, r2, np.zeros(st["rseg"] + 3), np.arange(st["rseg"] + 3)).tolist()
    # the handles that shaped the old L16 (its +-90 inflation and the turn's ring) go with it
    st["disp"] = [hh for hh in st.get("disp", []) if not (1290 <= hh["s"] <= 1400)]
    spec["_ringcollar"] = dict(x=[float(v) for v in (c, h_c, rho_c, dphi, r_c)], names=NAMES)
    return spec


def fit(A):
    import time, lobekit as K
    from lobefit import cma, cost_t
    from PIL import Image
    inc = json.load(open(A.spec)); os.makedirs(A.out, exist_ok=True)
    W = [K.Worker(i, os.path.abspath(".")) for i in range(A.workers)]
    clip = [880, 250, 1180, 780]; x0, y0, x1, y1 = clip
    sc = K.Scorer(clip, ["H2", "L16", "L15", "L14", "L13", "L12"])
    full = [0, 0, 1448, 1086]
    def measure(spec, wi, tag):
        w = W[wi % len(W)]
        p, s = os.path.abspath(f"{A.out}/w{w.wid}-{tag}.png"), os.path.abspath(f"{A.out}/w{w.wid}-{tag}-s.png")
        r = w.call(spec_obj=spec, out=p, clip=full, box=full, shade=s, extra=A.extra)
        im = np.asarray(Image.open(p).convert("RGB")); sh = np.asarray(Image.open(s).convert("L"))
        m, ex = sc.measure(im[y0:y1, x0:x1], sh[y0:y1, x0:x1])
        return m, ex, r.get("fold_box", 0.0)
    m0, e0, f0 = measure(inc, 0, "inc")
    def J(meas, x):
        m, ex, fold = meas
        c = cost_t(m["L16"]) + cost_t(m["L15"]) + 0.5 * cost_t(m["H2"])
        pen = 0.0
        for g in ("L14", "L13", "L12"):
            a, b = m0[g], m[g]; pen += 5 * max(0.0, a["iou"] - b["iou"] - 0.005) + 0.05 * max(0.0, abs(b["arc"]) - abs(a["arc"]) - 2)
        pen += max(0.0, ex["stray"] - e0["stray"] - 20) / 60
        for g, cr in ex["crease"].items(): pen += 0.5 * max(0.0, cr / max(e0["crease"].get(g, 0.6), 0.6) - 1.3)
        for jk, cr in ex["junction"].items(): pen += 0.5 * max(0.0, cr / max(e0["junction"].get(jk, 0.6), 0.6) - 1.15)
        pen += 6 * max(0.0, e0["sil"] - ex["sil"] - 0.002) + max(0.0, fold - f0 - 200) / 2000
        return c + pen, c, pen
    print("incumbent J", J((m0, e0, f0), X0), {k: round(v["iou"], 3) for k, v in m0.items()}, flush=True)
    def f(z, wi):
        x = np.clip(X0 + z * SCALE, LO, HI); meas = measure(apply(inc, x), wi, "c"); j = J(meas, x)
        return j[0], j, {k: round(v["iou"], 3) for k, v in meas[0].items()}, meas[1]["stray"]
    def log(g, best, F, sigma):
        x = np.clip(X0 + best[1] * SCALE, LO, HI)
        print(f"gen {g}: best {best[0]:.3f} {dict(zip(NAMES, np.round(x, 2).tolist()))} iou {best[2][2]} stray {best[2][3]} sigma {sigma:.2f}", flush=True)
    t0 = time.time()
    best = cma(f, len(NAMES), 0.7, (LO - X0) / SCALE, (HI - X0) / SCALE, A.gens, A.workers, seed=37, log=log, m0=(np.array([1.0, -20, 75, 0, 42]) - X0) / SCALE)
    x = np.clip(X0 + best[1] * SCALE, LO, HI)
    json.dump(apply(inc, x), open(f"{A.out}/spec.json", "w"))
    json.dump(dict(x=x.tolist(), names=NAMES, J=best[0], inc_J=J((m0, e0, f0), X0)[0], minutes=(time.time() - t0) / 60), open(f"{A.out}/fit.json", "w"), indent=1)
    print("done", dict(zip(NAMES, np.round(x, 2).tolist())), flush=True)
    for w in W: w.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("cmd"); ap.add_argument("spec"); ap.add_argument("rest", nargs="*")
    ap.add_argument("--gens", type=int, default=14); ap.add_argument("--workers", type=int, default=3); ap.add_argument("--extra", default="hybrid-r28-hybR.json")
    A = ap.parse_args()
    if A.cmd == "build":
        json.dump(apply(json.load(open(A.spec)), [float(v) for v in A.rest[:5]]), open(A.rest[5], "w"))
    else:
        A.out = A.rest[0]; fit(A)
