"""The right arm's bounded edge-correspondence fit (owner-approved, 2026-10-20; auto/r37/EDGES.md).

Targets: the contact boundaries L14|L15, L15|L16 and L16|H2, matched to the reference's whole curve:
position at corresponding points, tangent direction, curvature, both endpoints and arc length
(a shorter edge only helps when it keeps the reference's shape and ends). Guards: the right arm's
other reliable boundary (L12|L13) and the lobes' IoU, strays, clay and junction creases, the
silhouette (as lobefit). Only existing smooth parameters (tools/collarfit.py's arm windows: blue
s 262-355, yellow s 1252 to its tail):
  dR       strand separation (helix radius), px
  bead_k   radius evenness (1 = the incumbent's bead, 0 = even)
  r_scale  tube radius over the windows, relative
  yfloor   the yellow tail held at this share of its lobe's radius (0 = as it is)
No pitch change, no new handles or overlays. Flat renders (ffd_worker), one per evaluation.
Usage (from the logo root): edgefit.py INC_SPEC OUT_DIR [--gens 14] [--workers 3]"""
import argparse, copy, json, os, sys, time
import numpy as np
from scipy import ndimage
from scipy.spatial import cKDTree
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import strandspline as SS
import collarfit as CF
import edges as E
import geodiag as G
import lobekit as K
from lobefit import cma

NAMES = ["dR", "bead_k", "r_scale", "yfloor"]
X0 = np.array([0.0, 1.0, 0.0, 0.0]); SCALE = np.array([3.0, 0.25, 0.04, 0.3])
LO = np.array([-2.0, 0.0, -0.15, 0.0]); HI = np.array([12.0, 1.0, 0.10, 1.05])
TARGETS = ["L14|L15", "L15|L16", "L16|H2"]; GUARDS = ["L12|L13"]
FEATS_R = ["L12", "L13", "L14", "L15", "L16", "H2"]


def build(inc, x):
    dR, k, rs, yf = np.clip(np.asarray(x, float), LO, HI)
    spec, _ = CF.apply(inc, [0, 0, 0, 0, 0, yf, k, dR], parts=("yellow_tail", "arm"))
    if rs:
        for name in ("yellow", "blue"):
            st = spec[name]; u = np.r_[np.arange(st["s0"], st["s1"], 0.5), st["s1"]]; _, r = SS.evaluate(st, u)
            r2 = r * (1 + rs * CF.arm_weight(name, u))
            tr = SS.knots(st["s0"], st["s1"], st["rseg"]); st["rctrl"] = CF.lsq_fit(tr, u, r2, np.zeros(st["rseg"] + 3), np.arange(st["rseg"] + 3)).tolist()
    spec["_edgefit"] = dict(x=[float(v) for v in (dR, k, rs, yf)], names=NAMES)
    return spec


def contact(L, a, b):
    """lobe a's boundary next to lobe b, as an ordered curve (edges.py's definition)"""
    if a not in L or b not in L: return None
    m = L[a]; bd = m & ~ndimage.binary_erosion(m); sel = bd & (ndimage.distance_transform_edt(~L[b]) < 3)
    P, wh = E.order(np.c_[np.nonzero(sel)[::-1]])
    return None if P is None else (P, float(np.hypot(*np.diff(P, axis=0).T).sum()), wh)


def ref_edges():
    M = G.masks(G.REF); L = E.lobes_of(M, ref=True)
    return {k: contact(L, *k.split("|")) for k in TARGETS + GUARDS}


def cand_edges(png):
    M = G.masks(png); L = {}
    for f in FEATS_R:
        C = G.match(M["lobes"][G.FCOL[f]], G.LAB == G.FEATS.index(f) + 1)
        if C is not None: L[f] = C
    return {k: contact(L, *k.split("|")) for k in TARGETS + GUARDS}


def edge_cost(er, ec):
    """whole-curve mismatch of one boundary (px-scaled), and its parts"""
    if ec is None: return 6.0, dict(missing=True)
    (Pr, lr, _), (Pc, lc, _) = er, ec
    R, _ = E.resample(Pr); C, _ = E.resample(Pc)
    if np.linalg.norm(C[::-1] - R, axis=1).mean() < np.linalg.norm(C - R, axis=1).mean(): C = C[::-1]
    pos = np.linalg.norm(C - R, axis=1).mean()
    ends = 0.5 * (np.linalg.norm(C[0] - R[0]) + np.linalg.norm(C[-1] - R[-1]))
    Tr, Tc = np.gradient(R, axis=0), np.gradient(C, axis=0)
    cos = (Tr * Tc).sum(1) / np.maximum(np.linalg.norm(Tr, axis=1) * np.linalg.norm(Tc, axis=1), 1e-9)
    dtan = np.degrees(np.arccos(np.clip(cos, -1, 1))).mean()
    kr = ndimage.gaussian_filter1d(E.curvature(R), 2); kc = ndimage.gaussian_filter1d(E.curvature(C), 2); dk = 1000 * np.sqrt(np.mean((kc - kr) ** 2))
    dl = lc / lr - 1
    cost = pos / 8 + ends / 10 + dtan / 10 + dk / 10 + 3 * abs(dl)
    return float(cost), dict(pos=float(pos), ends=float(ends), dtan=float(dtan), dkap=float(dk), dlen=float(dl))


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("spec"); ap.add_argument("out"); ap.add_argument("--gens", type=int, default=14); ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--extra", default="hybrid-r28-hybR.json")
    A = ap.parse_args(); os.makedirs(A.out, exist_ok=True)
    inc = json.load(open(A.spec)); RE = ref_edges()
    W = [K.Worker(i, os.path.abspath(".")) for i in range(A.workers)]
    sc = K.Scorer([880, 250, 1180, 780], FEATS_R)
    from PIL import Image
    def measure(spec, wi, tag):
        w = W[wi % len(W)]
        p, s = os.path.abspath(f"{A.out}/w{w.wid}-{tag}.png"), os.path.abspath(f"{A.out}/w{w.wid}-{tag}-s.png")
        r = w.call(spec_obj=spec, out=p, clip=[0, 0, 1448, 1086], box=[0, 0, 1448, 1086], shade=s, extra=A.extra)
        im = np.asarray(Image.open(p).convert("RGB")); sh = np.asarray(Image.open(s).convert("L"))
        m, ex = sc.measure(im[250:780, 880:1180], sh[250:780, 880:1180])
        return cand_edges(p), m, ex, r.get("fold_box", 0.0)
    e0, m0, x0_, f0 = measure(inc, 0, "inc")
    base = {k: edge_cost(RE[k], e0[k]) for k in TARGETS + GUARDS}
    def J(meas):
        ec, m, ex, fold = meas
        parts = {k: edge_cost(RE[k], ec[k]) for k in TARGETS + GUARDS}
        c = sum(parts[k][0] for k in TARGETS)
        pen = sum(max(0.0, parts[k][0] - base[k][0] - 0.2) for k in GUARDS)
        for g in ("H2", "L12", "L13"):
            pen += 5 * max(0.0, m0[g]["iou"] - m[g]["iou"] - 0.005)
        for g in ("L14", "L15", "L16"):
            pen += 3 * max(0.0, m0[g]["iou"] - m[g]["iou"] - 0.02)
        pen += max(0.0, ex["stray"] - x0_["stray"] - 20) / 60 + 6 * max(0.0, x0_["sil"] - ex["sil"] - 0.002)
        for g, cr in ex["crease"].items(): pen += 0.5 * max(0.0, cr / max(x0_["crease"].get(g, 0.6), 0.6) - 1.3)
        for jk, cr in ex["junction"].items(): pen += 0.5 * max(0.0, cr / max(x0_["junction"].get(jk, 0.6), 0.6) - 1.15)
        pen += max(0.0, fold - f0 - 200) / 2000
        return c + pen, c, pen, {k: v[1] for k, v in parts.items()}
    j0 = J((e0, m0, x0_, f0))
    print("incumbent:", round(j0[0], 3), json.dumps({k: {q: round(v, 2) for q, v in d.items()} for k, d in j0[3].items()}), flush=True)
    logf = open(f"{A.out}/fit.log", "a")
    def f(z, wi):
        x = np.clip(X0 + z * SCALE, LO, HI); meas = measure(build(inc, x), wi, "c"); j = J(meas)
        return j[0], j, {k: round(v["iou"], 3) for k, v in meas[1].items()}
    def log(g, best, F, sigma):
        x = np.clip(X0 + best[1] * SCALE, LO, HI)
        msg = f"gen {g}: best {best[0]:.3f} (edges {best[2][1][1]:.3f} pen {best[2][1][2]:.3f}) {dict(zip(NAMES, np.round(x, 3).tolist()))} iou {best[2][2]} " + json.dumps({k: {q: round(v, 2) for q, v in d.items()} for k, d in best[2][1][3].items()})
        print(msg, flush=True); logf.write(msg + "\n"); logf.flush()
    t0 = time.time()
    best = cma(f, len(NAMES), 0.7, (LO - X0) / SCALE, (HI - X0) / SCALE, A.gens, A.workers, seed=38, log=log, m0=(np.array([4.0, 0.6, 0.0, 0.9]) - X0) / SCALE)
    x = np.clip(X0 + best[1] * SCALE, LO, HI)
    json.dump(build(inc, x), open(f"{A.out}/spec.json", "w"))
    json.dump(dict(x=x.tolist(), names=NAMES, J=best[0], parts=best[2][1][3], inc=dict(J=j0[0], parts=j0[3]), minutes=(time.time() - t0) / 60), open(f"{A.out}/fit.json", "w"), indent=1, default=float)
    print("done", dict(zip(NAMES, np.round(x, 3).tolist())), flush=True)
    for w in W: w.close()


if __name__ == "__main__":
    main()
