"""ATTRIBUTE + OPTIMISE one ranked feature: find the run of its strand that draws the candidate's
lobe (the surface-point buffer of the incumbent, lobekit.attribute), put a lobe handle on that
run (lobekit: 11 controls, 15 from round 16 with the end moves; supports stopping short of the
same strand's neighbouring lobes and of the necks), and fit the controls by CMA-ES on flat
renders of the real geometry.
  cost   the target's (1 - IoU) + mean boundary distance / 8 + |worst contour arc| / 15 (both
         ways from round 12, lobekit.arcs2) + p95 / 40 + |centroid offset| / 30, plus its shape
         against the reference lobe's: 0.5 |elongation difference| + |tilt| / 20 x min(1,
         elongation - 1) (|tilt| / 40 before round 12) + 4 x the solidity shortfall + the waist
         (lobekit.waist: a dip in the width profile beyond the reference's) / 10 (cost_t)
  guards every other feature inside the crop may not lose IoU (> 0.005), p95 (> 1 px), its
         worst arc (> 2 px), solidity (> 0.01) or waist (> 2 px); the crop's silhouette and negative spaces, the local fold area, the
         clay crease (target and guards), stray blobs (from round 17, lobekit.stray: px of small
         separate blobs of a colour outside the reference's features of that colour; more than
         20 px over the incumbent's, / 100) and the press depth (the deepest overlap of the two tubes
         before the press flattens them, inside the crop: a deeper press dents the partner) may
         not get worse than the incumbent's
  reg    0.01 x the squared controls in search units (lobekit.SCALE: 10 px, 8 deg, 0.1)
Writes OUT/handle.json, OUT/spec.json (the incumbent with the handle applied), OUT/fit.json
(attribution, surrogate before / after per feature, the log).
Usage (from the logo root): lobefit.py TARGET incumbent.json OUT [--gens 22] [--workers 3] [--seed 0]
  [--init handle.json --sigma 0.4 --crease-tol 1.15]: a repair fit, from a rejected handle
The flat renders use the params and head bake that FFD_PARAMS / FFD_HEADS name (the incumbent's,
or a head variant's: autoround.py sets them)."""
import argparse, json, os, sys, threading, time
import numpy as np
from PIL import Image
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import lobekit as K
from evaluate import window

ROOT = os.path.abspath(os.path.join(HERE, ".."))


def cma(f, n, sigma0, lo, hi, gens, workers, seed=0, log=None, m0=None):
    rng = np.random.default_rng(seed)
    lam = 4 + int(3 * np.log(n)); lam += (-lam) % workers
    mu = lam // 2
    w = np.log(mu + 0.5) - np.log(np.arange(1, mu + 1)); w /= w.sum(); mueff = 1 / np.sum(w ** 2)
    cc = (4 + mueff / n) / (n + 4 + 2 * mueff / n); cs = (mueff + 2) / (n + mueff + 5)
    c1 = 2 / ((n + 1.3) ** 2 + mueff); cmu = min(1 - c1, 2 * (mueff - 2 + 1 / mueff) / ((n + 2) ** 2 + mueff))
    damps = 1 + 2 * max(0, np.sqrt((mueff - 1) / (n + 1)) - 1) + cs
    chiN = np.sqrt(n) * (1 - 1 / (4 * n) + 1 / (21 * n * n))
    m = np.zeros(n) if m0 is None else np.clip(np.asarray(m0, float), lo, hi); sigma = sigma0; C = np.eye(n); pc = np.zeros(n); ps = np.zeros(n); D = np.ones(n); B = np.eye(n)
    best = (np.inf, m.copy(), None)
    for g in range(gens):
        Z = rng.standard_normal((lam, n)); Y = (B @ (D[:, None] * Z.T)).T
        X = np.clip(m + sigma * Y, lo, hi); Yc = (X - m) / sigma
        res = [None] * lam
        def run(idx, wk):
            for i in idx:
                res[i] = f(X[i], wk)
        th = [threading.Thread(target=run, args=(list(range(k, lam, workers)), k)) for k in range(workers)]
        [t.start() for t in th]; [t.join() for t in th]
        F = np.array([r[0] for r in res]); order = np.argsort(F)
        if F[order[0]] < best[0]:
            best = (F[order[0]], X[order[0]].copy(), res[order[0]])
        ymean = (w[:, None] * Yc[order[:mu]]).sum(0)
        m = m + sigma * ymean
        invsqrtC = B @ np.diag(1 / D) @ B.T
        ps = (1 - cs) * ps + np.sqrt(cs * (2 - cs) * mueff) * invsqrtC @ ymean
        hs = np.linalg.norm(ps) / np.sqrt(1 - (1 - cs) ** (2 * (g + 1))) / chiN < 1.4 + 2 / (n + 1)
        pc = (1 - cc) * pc + hs * np.sqrt(cc * (2 - cc) * mueff) * ymean
        C = (1 - c1 - cmu) * C + c1 * (np.outer(pc, pc) + (1 - hs) * cc * (2 - cc) * C) + cmu * (Yc[order[:mu]].T * w) @ Yc[order[:mu]]
        sigma *= np.exp((cs / damps) * (np.linalg.norm(ps) / chiN - 1))
        C = (C + C.T) / 2; D2, B = np.linalg.eigh(C); D = np.sqrt(np.maximum(D2, 1e-20))
        if log:
            log(g, best, F, sigma)
    return best


def cost_t(m):
    """the target's mask and outline error, plus its shape against the reference lobe's: the blind
    judges reject lobes that read as bands, wedges or tilted (rounds 1-3), which the shape terms
    measure: elongation, orientation and solidity (area / convex hull, the cushion's convexity).
    From round 12 the orientation term is |tilt| / 20 scaled by how elongated the reference lobe is
    (min(1, elongation - 1)): a long lobe's tilt is what the eye reads (the blue collar L01, 6
    degrees too upright at elongation 2.4), a round lobe's principal axis is ill-defined. From round
    13, + the waist (lobekit.waist, px) / 10: a lobe may not take its outline error by pinching"""
    return ((1 - m["iou"]) + m["mean"] / 8 + abs(m["arc"]) / 15 + m["p95"] / 40 + np.hypot(m["dx"], m["dy"]) / 30
            + 0.5 * abs(m["elong"] - m["elong_ref"]) + abs(m["tilt"]) / 20 * min(1.0, max(0.0, m["elong_ref"] - 1.0))
            + 4 * max(0.0, m["solid_ref"] - m["solid"]) + m.get("waist", 0.0) / 10)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("target"); ap.add_argument("spec"); ap.add_argument("out")
    ap.add_argument("--gens", type=int, default=22); ap.add_argument("--workers", type=int, default=3); ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--pad", type=int, default=80)
    # a repair fit (autoround.py seeds): start from a judged-closer but rejected handle, with a
    # narrower search and a tighter tolerance on the guards' clay crease
    ap.add_argument("--init"); ap.add_argument("--sigma", type=float, default=0.8); ap.add_argument("--crease-tol", type=float, default=1.4)
    # a targeted correction (autoround.py --plan, from the round's visual diagnosis): only the
    # controls the correction calls for; a neighbour fitted jointly (a junction needs both sides);
    # the contour error at the diagnosed location (x, y, radius in reference px), weighted / 5
    ap.add_argument("--controls"); ap.add_argument("--joint"); ap.add_argument("--edge")
    # the critics' structured causes (auto/causes.json, autoround.py): a failure named on this
    # target, its neighbours or their junctions tightens the guard for exactly that failure
    ap.add_argument("--causes")
    A = ap.parse_args()
    os.makedirs(A.out, exist_ok=True)
    out = os.path.abspath(A.out)
    inc = json.load(open(A.spec))
    for n in ("yellow", "blue"):
        inc[n].setdefault("disp", [])
    W = [K.Worker(i, ROOT) for i in range(A.workers)]
    try:
        # ---- attribute: the incumbent's surface-point buffer and lobes (flat, whole frame)
        sid, st, psi = K.surface_ids(W[0], inc, f"{out}/ids.raw")
        W[0].call(spec_obj=inc, out=f"{out}/inc-flat.png", clip=[0, 0, 1448, 1086])
        Lc = K.lobes(np.asarray(Image.open(f"{out}/inc-flat.png").convert("RGB")))
        att = K.attribute(sid, st, psi, Lc, A.target)
        if "error" in att:
            json.dump(dict(target=A.target, attribution={k: v for k, v in att.items() if k != "K"}, verdict="not controllable"), open(f"{out}/fit.json", "w"), indent=1)
            print(A.target, "not controllable:", att["error"]); return
        tf = K.FEATS[K.FIDS.index(A.target)]
        nbs = []
        for g in K.FEATS:
            if g["id"] == A.target or g["colour"] != tf["colour"] or not g["id"].startswith("L"):
                continue
            a2 = K.attribute(sid, st, psi, Lc, g["id"])
            if "error" not in a2:
                nbs.append((a2["a"], a2["b"]))
        h = K.make_handle(inc, att, att["K"], nbs)
        hs = [h]
        if A.joint:
            jf = K.FEATS[K.FIDS.index(A.joint)]
            ja = K.attribute(sid, st, psi, Lc, A.joint)
            if "error" in ja:
                print(A.joint, "(joint) not controllable:", ja["error"]); return
            jn = [(a2["a"], a2["b"]) for g in K.FEATS if g["id"] not in (A.joint, A.target) and g["colour"] == jf["colour"] and g["id"].startswith("L")
                  for a2 in [K.attribute(sid, st, psi, Lc, g["id"])] if "error" not in a2]
            if jf["colour"] == tf["colour"]:
                jn.append((att["a"], att["b"])); nbs.append((ja["a"], ja["b"])); h = K.make_handle(inc, att, att["K"], nbs); hs = [h]
            hs.append(K.make_handle(inc, ja, ja["K"], jn))
        sel = A.controls.split(",") if A.controls else list(K.NAMES)
        cix = [K.NAMES.index(c) for c in sel]
        tg = [A.target] + ([A.joint] if A.joint else [])
        # ---- the crop and its features
        x0, y0, x1, y1 = window(tf, A.pad)
        if A.joint:
            jx = window(jf, A.pad); x0, y0, x1, y1 = min(x0, jx[0]), min(y0, jx[1]), max(x1, jx[2]), max(y1, jx[3])
        clip = [int(x0), int(y0), int(x1), int(y1)]
        feats = []
        for g in K.FEATS:
            bx = g["bbox"]
            ix = max(0, min(bx[2], x1) - max(bx[0], x0)) * max(0, min(bx[3], y1) - max(bx[1], y0))
            if g["id"] in tg or ix > 0.3 * (bx[2] - bx[0]) * (bx[3] - bx[1]):
                feats.append(g["id"])
        edge = None
        if A.edge:
            ex_, ey_, er_ = (float(v) for v in A.edge.split(","))
            edge = (A.target, ex_, ey_, er_)
        sc = K.Scorer(clip, feats, edge)
        def measure(spec, wi, tag):
            w = W[wi % len(W)]
            p, s, nm = f"{out}/w{w.wid}-{tag}.png", f"{out}/w{w.wid}-{tag}-shade.png", f"{out}/w{w.wid}-{tag}-normals.png"
            r = w.call(spec_obj=spec, out=p, clip=clip, box=clip, shade=s, normals=nm)
            m, ex = sc.measure(p, s, nm)
            ex["press"] = r.get("press_box", 0.0)
            return m, ex, r["fold_box"]
        m0, ex0, f0 = measure(inc, 0, "inc")
        print(f"{A.target}: {att['strand']} stations {h['a']:.0f}..{h['b']:.0f} (ramps {h['ra']:.0f}, {h['rb']:.0f}; {att['frac']:.0%} of the lobe's pixels in this run, head {att['head_frac']:.0%}); crop {clip}; guards {[f for f in feats if f != A.target]}", flush=True)
        print("  incumbent:", {k: (round(v["iou"], 3), round(v["arc"], 1)) for k, v in m0.items()}, "sil", round(ex0["sil"], 4), "fold", f0, "press", ex0["press"], "corners", ex0["corners"], flush=True)
        guards = [f for f in feats if f not in tg]
        # causes -> guards: {cause: {where}} for the features and junctions in this crop
        cz = {}
        for c in (json.load(open(A.causes)) if A.causes and os.path.exists(A.causes) else []):
            w = c["where"]
            if all(p_ in feats for p_ in w.split("|")):
                cz.setdefault(c["cause"], set()).add(w)
        mass = cz.get("mass_distribution", set()) | cz.get("flat_top", set())
        if cz:
            print("  causes on record (guards tightened):", {k: sorted(v) for k, v in cz.items()}, flush=True)
        if A.controls or A.joint or A.edge:
            print(f"  targeted: controls {sel}; joint {A.joint or '-'}; edge {A.edge or '-'} (incumbent's error there {m0[A.target].get('edge')}); junctions {list(ex0['junction'])}", flush=True)

        def J(m, ex, fold, x):
            # the target's own clay crease counts too: the judges' most repeated shared fault is a
            # pinch or dimple inside a lobe (L13 / L14, L08), which no mask measure sees
            c = sum(cost_t(m[t]) + (1.2 if t in cz.get("crease", ()) else 0.4) * max(0.0, ex["crease"].get(t, 0.0) - 1.0)
                    + (0.2 if t in cz.get("thinning", ()) else 0.0) * m[t].get("waist", 0.0) + (2.0 if t in mass else 0.0) * m[t].get("profile", 0.0) for t in tg); pen = 0.0
            if edge:
                c += abs(m[A.target]["edge"] or 0.0) / 5
            for g in guards:
                a, b = m0[g], m[g]
                pen += 5 * max(0.0, a["iou"] - b["iou"] - 0.005) + 0.04 * max(0.0, b["p95"] - a["p95"] - 1) + 0.05 * max(0.0, abs(b["arc"]) - abs(a["arc"]) - 2)
                pen += 4 * max(0.0, a["solid"] - b["solid"] - 0.01) + (0.15 if g in cz.get("thinning", ()) else 0.05) * max(0.0, b.get("waist", 0.0) - a.get("waist", 0.0) - (0 if g in cz.get("thinning", ()) else 2))
                if g in mass:
                    pen += 2.0 * max(0.0, b.get("profile", 0.0) - a.get("profile", 0.0) - 0.01)
            # folds (from round 23, lobekit.fold_length): a ridge growing inside any lobe; a feature
            # with a fold on record (r22-L13: a long diagonal fold) may not grow one at all
            for g in feats:
                fa, fb = m0[g].get("fold", 0.0), m[g].get("fold", 0.0)
                pen += (0.06 if g in cz.get("fold", ()) else 0.02) * max(0.0, fb - fa - (0 if g in cz.get("fold", ()) else 6))
            pen += 6 * max(0.0, ex0["sil"] - ex["sil"] - 0.002)
            for k, v in ex["intr"].items():
                pen += 6 * max(0.0, v - ex0["intr"].get(k, 0) - 0.003)
            pen += max(0.0, fold - f0 - 200) / 2000
            pen += max(0.0, ex["press"] - ex0["press"] - 2.0) / 4.0
            pen += (0.2 if cz.get("crossing_notch") else 0.08) * max(0.0, ex["corners"] - ex0["corners"] - (0 if cz.get("crossing_notch") else 1))
            pen += 0.5 * max(0.0, ex["bottom"] - ex0["bottom"] - 1)
            pen += max(0.0, ex["stray"] - ex0["stray"] - (0 if cz.get("stray_blob") else 20)) / (30 if cz.get("stray_blob") else 100)
            for g, cr in ex["crease"].items():
                ct = (1.1, 1.5) if g in cz.get("crease", ()) else (A.crease_tol, 0.5)
                pen += ct[1] * max(0.0, cr / max(ex0["crease"].get(g, 0.6), 0.6) - ct[0])
            # junction creases (from round 22): a pinch where two lobes meet
            for jk, cr in ex["junction"].items():
                jt = (1.0, 1.5) if jk in cz.get("junction_pinch", ()) else (1.15, 0.5)
                pen += jt[1] * max(0.0, cr / max(ex0["junction"].get(jk, 0.6), 0.6) - jt[0])
            reg = 0.01 * float(np.sum(np.square(x)))
            return c + pen + reg, c, pen, reg

        def handles(x):
            out_ = []
            for k, hk in enumerate(hs):
                p = {n: 0.0 for n in K.NAMES}
                for j, c in zip(cix, x[k * len(cix):(k + 1) * len(cix)]):
                    p[K.NAMES[j]] = float(c * K.SCALE[j])
                out_.append(dict(hk, p=p))
            return out_

        def f(x, wi):
            m, ex, fold = measure(K.apply(inc, handles(x)), wi, "c")
            j, c, pen, reg = J(m, ex, fold, x)
            return j, dict(c=c, pen=pen, reg=reg, m=m, ex=ex, fold=fold)
        nx = len(cix) * len(hs)
        lo_, hi_ = np.tile(K.LO[cix] / K.SCALE[cix], len(hs)), np.tile(K.HI[cix] / K.SCALE[cix], len(hs))
        j0 = J(m0, ex0, f0, np.zeros(nx))
        t0 = time.time(); logl = []
        def log(g, best, F, sigma):
            line = f"gen {g:2d} best {best[0]:.3f} (target {best[2][1]['c']:.3f} guards {best[2][1]['pen']:.3f} reg {best[2][1]['reg']:.3f}) sigma {sigma:.2f} t {time.time() - t0:.0f}s"
            logl.append(line)
            if g % 4 == 0 or g == A.gens - 1:
                print("  " + line, flush=True)
        x0 = None
        if A.init:
            p0 = json.load(open(A.init))["p"]
            x0 = np.tile(np.array([p0.get(K.NAMES[j], 0.0) for j in cix]) / K.SCALE[cix], len(hs))
            print(f"  repair: from {A.init} ({K.describe(handles(x0)[0])}), sigma {A.sigma}, crease tolerance {A.crease_tol}", flush=True)
        best = cma(f, nx, A.sigma, lo_, hi_, A.gens, A.workers, A.seed, log, x0)
        x = best[1]
        hs = handles(x); h = hs[0]
        spec = K.apply(inc, hs)
        mb, exb, fb = best[2][1]["m"], best[2][1]["ex"], best[2][1]["fold"]
        json.dump(h, open(f"{out}/handle.json", "w"), indent=1)
        json.dump(hs, open(f"{out}/handles.json", "w"), indent=1)
        json.dump(spec, open(f"{out}/spec.json", "w"))
        rep = dict(target=A.target, joint=A.joint, controls=sel, edge=A.edge, attribution={k: v for k, v in att.items() if k != "K"}, handle=h, handles=hs,
                   describe="; ".join(f"{hk['fid']}: {K.describe(hk)}" for hk in hs) if len(hs) > 1 else K.describe(h), clip=clip, guards=guards,
                   J0=j0[0], J=float(best[0]), before=m0, after=mb, ex_before=ex0, ex_after=exb, fold_before=f0, fold_after=fb, log=logl)
        json.dump(rep, open(f"{out}/fit.json", "w"), indent=1, default=float)
        print(f"  {A.target}: J {j0[0]:.3f} -> {best[0]:.3f}; {rep['describe']}" + (f"; edge error {m0[A.target]['edge']:+.1f} -> {mb[A.target]['edge']:+.1f} px" if edge else ""))
        for g in feats:
            a, b = m0[g], mb[g]
            print(f"    {g}: IoU {a['iou']:.3f} -> {b['iou']:.3f}, arc {a['arc']:+.1f} -> {b['arc']:+.1f}, p95 {a['p95']:.0f} -> {b['p95']:.0f}")
    finally:
        for w in W:
            w.close()


if __name__ == "__main__":
    main()
