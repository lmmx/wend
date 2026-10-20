"""The owner-approved 8-parameter adjustment (2026-10-20, geo/DIAGNOSTIC.md section 3): the two
tail collars and the right arm's radius/helix pair, fitted once, replacing local handles.

Parameters (x, in order):
  bt_ext, yt_ext    tail extension, in the strand's centreline segments (~16 px each; rounded): the
                    taper finishes behind the partner's neck. The spline's interior knots are kept,
                    so the centreline upstream of the tail's last 3 segments is unchanged exactly
  bt_dh, yt_dh      the tail's last half-turn moved along the partner's neck axis (px; - = down,
                    towards the body), ramped in over its last ~150 stations: the collar wraps the
                    neck lower instead of climbing it. (A twist-phase offset about the axis was the
                    first choice; on flat renders it only swung the tip in and out of view,
                    auto/r32/phase-knob-test.png, so the height took its place)
  bt_floor, yt_floor  the tail's radius held at this share of its lobe's median until it is hidden
  bead_k            the right arm's radius bead (r - its smoothed mean) scaled by this, over blue
                    s 262-355 (L15) and yellow s 1252-tail (L16)
  dR                the strands pushed apart by this (px) over the same windows: the helix radius,
                    so the band width 2(R + r) can stay while the tubes slim

Removed handles (fixed, not parameters): blue s 1436 / 1438 rings and the s 1389 +-90 pair (the
tail pinch and oval); yellow s 1388 ring and the s 1347 +-90 pair (L16's inflation).
Windows stop short of everything frozen: the blue overlay cut starts at s 359, the yellow one
ends at s 1247, and the blue head's own stations end at s 262 (lobekit.NECK_SAFE).

Usage (from the logo root):
  collarfit.py build INC_SPEC X... OUT_SPEC     apply a parameter vector
  collarfit.py fit INC_SPEC OUT_DIR [--gens 16] [--workers 3] [--extra hybrid-r28-hybR.json]
"""
import argparse, copy, json, os, sys, time
import numpy as np
from scipy import ndimage

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import strandspline as SS

NAMES = ["bt_ext", "bt_dh", "bt_floor", "yt_ext", "yt_dh", "yt_floor", "bead_k", "dR"]
LO = np.array([0.0, -24.0, 0.0, 0.0, -24.0, 0.0, 0.0, -2.0])   # floor 0: no floor
HI = np.array([3.49, 10.0, 1.05, 3.49, 10.0, 1.05, 1.0, 8.0])
X0 = np.array([0.0, 0.0, 0.8, 0.0, 0.0, 0.8, 1.0, 0.0])           # the incumbent, less the removed handles
SCALE = np.array([1.0, 6.0, 0.08, 1.0, 6.0, 0.08, 0.25, 3.0])   # one search unit
REMOVE = {"blue": [(1436, 0), (1438, 0), (1389, 90), (1389, -90)], "yellow": [(1388, 0), (1347, 90), (1347, -90)]}
WIN = {"blue": (262, 290, 330, 355), "yellow": (1252, 1280, None, None)}
TAILW = 150.0


def smooth(e0, e1, x):
    return SS.smoothstep(e0, e1, x)


def arm_weight(name, u):
    a, b, c, d = WIN[name]
    w = smooth(a, b, u)
    return w * (1 - smooth(c, d, u)) if c is not None else w


def lsq_fit(t, u, Y, old, free):
    """control values for knots t fitting Y(u), with the controls outside `free` held at `old`"""
    B = SS.basis(u, t); n = B.shape[1]
    c = np.zeros((n,) + Y.shape[1:]); fixed = np.setdiff1d(np.arange(n), free)
    c[fixed] = old[fixed]
    rhs = Y - B[:, fixed] @ c[fixed]
    Bf = B[:, free]
    c[free] = np.linalg.lstsq(Bf.T @ Bf + 1e-9 * np.eye(len(free)), Bf.T @ rhs, rcond=None)[0]
    return c


PARTS = ("blue_tail", "yellow_tail", "arm")


def apply(spec0, x, parts=PARTS):
    """the adjustment; parts limits it to some of its three components (an ablation): blue_tail
    (the left scarf: its handles stay unless this part is on), yellow_tail (the nape), arm (L15/L16)"""
    x = np.clip(np.asarray(x, float), LO, HI)
    bt_ext, bt_dh, bt_floor, yt_ext, yt_dh, yt_floor, k, dR = x
    if "arm" not in parts: k, dR = 1.0, 0.0
    spec = copy.deepcopy(spec0)
    for name, rm in REMOVE.items():
        if (f"{name}_tail" not in parts or "keep_handles" in parts) and name == "blue": continue
        if name == "yellow" and "yellow_tail" not in parts and "arm" not in parts: continue
        spec[name]["disp"] = [h for h in spec[name].get("disp", []) if (round(h["s"]), h["psi"]) not in {(s, p) for s, p in rm}]
    L = spec0["L"]; info = {}
    for name, other, ext, dz, floor in (("blue", "yellow", bt_ext, bt_dh, bt_floor), ("yellow", "blue", yt_ext, yt_dh, yt_floor)):
        st0, so = spec0[name], spec0[other]
        s0, s1, nseg = st0["s0"], st0["s1"], st0["nseg"]; h = (s1 - s0) / nseg
        u = np.r_[np.arange(s0, s1, 0.5), s1]
        X, r = SS.evaluate(st0, u); sec = SS.evaluate_sec(st0, u)
        mate, _ = SS.evaluate(so, np.clip(L - u, so["s0"], so["s1"]))
        # the right arm: bead down by k, strands apart by dR
        w = arm_weight(name, u)
        m = ndimage.gaussian_filter1d(r, 80, mode="nearest")
        r2 = r - (1 - k) * w * (r - m)
        T = np.gradient(X, axis=0); T /= np.linalg.norm(T, axis=1)[:, None]
        nv = X - mate; nv -= (nv * T).sum(1)[:, None] * T; nv /= np.maximum(np.linalg.norm(nv, axis=1), 1e-9)[:, None]
        X2 = X + dR * w[:, None] * nv
        # the tail: about the partner's neck axis (its first stations, towards its head)
        uo = np.linspace(so["s0"], so["s0"] + 60, 25); Xo, _ = SS.evaluate(so, uo)
        A = Xo[0]; D = Xo[0] - Xo[-1]; D /= np.linalg.norm(D)
        e1 = np.cross(D, [0.0, 0.0, 1.0]); e1 /= np.linalg.norm(e1); e2 = np.cross(D, e1)
        rel = X2 - A; hh = rel @ D; o = rel - hh[:, None] * D
        rho = np.linalg.norm(o, axis=1); ph = np.unwrap(np.arctan2(o @ e2, o @ e1))
        wt = smooth(s1 - TAILW, s1 - 60, u)
        ph2 = ph; hh = hh + dz * wt
        X3 = A + hh[:, None] * D + rho[:, None] * (np.cos(ph2)[:, None] * e1 + np.sin(ph2)[:, None] * e2)
        tl = (u >= s1 - TAILW - 10) & (u <= s1 - 30); rmed = float(np.median(r[tl]))
        r3 = r2 + wt * np.maximum(0.0, floor * rmed - r2) if floor > 0 else r2
        if f"{name}_tail" not in parts:
            X3, r3, ext = X2, r2, 0
        # the extension, continuing the helix about the axis at the tail's own rates
        j = int(round(ext)); Dl = j * h
        if j:
            k20 = u >= s1 - 20
            dh = np.polyfit(u[k20], hh[k20], 1)[0]; dp = np.polyfit(u[k20], ph2[k20], 1)[0]
            ue = np.arange(s1 + 0.5, s1 + Dl + 1e-9, 0.5)
            he = hh[-1] + dh * (ue - s1); pe = ph2[-1] + dp * (ue - s1)
            Xe = A + he[:, None] * D + rho[-1] * (np.cos(pe)[:, None] * e1 + np.sin(pe)[:, None] * e2)
            u = np.r_[u, ue]; X3 = np.r_[X3, Xe]; r3 = np.r_[r3, np.full(len(ue), r3[-1])]; sec = np.r_[sec, np.repeat(sec[-1:], len(ue), 0)]
        s1n = s1 + Dl
        st = spec[name]; st["s1"] = float(s1n)
        # centreline: interior knots kept (nseg + j segments of the same length); only the controls
        # whose support meets a changed station are refitted
        t = SS.knots(s0, s1n, nseg + j); old = np.zeros((nseg + j + 3, 3)); old[:nseg + 3] = np.asarray(st0["ctrl"], float)
        moved = np.linalg.norm(X3[:len(X)] - X, axis=1) > 1e-6
        lo_s = min(u[:len(X)][moved].min() if moved.any() else s1n, s1 - 3 * h)
        free = np.array([i for i in range(nseg + j + 3) if t[i + 4] > lo_s - 1e-9])
        st["nseg"] = nseg + j; st["ctrl"] = lsq_fit(t, u, X3, old, free).tolist()
        # radius and sections: refitted on their own knots over the new range (they are smooth;
        # the upstream error is reported, info["r_err"])
        rseg = int(round(st0["rseg"] * (s1n - s0) / (s1 - s0))); tr = SS.knots(s0, s1n, rseg)
        rc = lsq_fit(tr, u, r3, np.zeros(rseg + 3), np.arange(rseg + 3))
        st["rseg"] = rseg; st["rctrl"] = rc.tolist()
        if "sec" in st0:
            sg = int(round(st0["sec"]["seg"] * (s1n - s0) / (s1 - s0))); ts = SS.knots(s0, s1n, sg)
            st["sec"] = {"seg": sg, **{kk: lsq_fit(ts, u, sec[:, i], np.zeros(sg + 3), np.arange(sg + 3)).tolist() for i, kk in enumerate(("ql", "qd", "psi"))}}
        # the fit's error where nothing was meant to change
        Xn, rn = SS.evaluate(st, u[:len(X)])
        keep = ~moved & (w < 1e-6) & (wt < 1e-6)
        info[name] = dict(ext=j, s1=s1n, x_err=float(np.abs(Xn - X)[keep].max()) if keep.any() else 0.0,
                          r_err=float(np.abs(rn - r)[keep].max()) if keep.any() else 0.0, rmed=rmed)
    spec["_collarfit"] = dict(x=x.tolist(), names=NAMES, info=info)
    return spec, info


# ---------------------------------------------------------------- the fit

CLIPS = {"left": [300, 270, 580, 600], "right": [880, 250, 1180, 780]}
TARGETS = {"left": ["L01"], "right": ["L15", "L16"]}
JUNCS = {"left": [("H1", "L01")], "right": [("H2", "L16"), ("L15", "L16")]}


def fit(A):
    import lobekit as K
    import geodiag as G
    from lobefit import cma, cost_t
    from PIL import Image
    inc = json.load(open(A.spec)); os.makedirs(A.out, exist_ok=True)
    W = [K.Worker(i, os.path.abspath(".")) for i in range(A.workers)]
    sc = {}
    for c, clip in CLIPS.items():
        x0, y0, x1, y1 = clip; feats = []
        for g in K.FEATS:
            bx = g["bbox"]; ix = max(0, min(bx[2], x1) - max(bx[0], x0)) * max(0, min(bx[3], y1) - max(bx[1], y0))
            if ix > 0.3 * (bx[2] - bx[0]) * (bx[3] - bx[1]): feats.append(g["id"])
        sc[c] = K.Scorer(clip, feats)
    # the reference's width cuts and contact-line contours, once
    frames = {}
    for f in sum(TARGETS.values(), []):
        R = G.LAB == G.FEATS.index(f) + 1; fr = G.lobe_frame(R); wr, e = G.width_profile(R, fr); frames[f] = (fr, wr, e)
    contacts = {}
    for a, b in sum(JUNCS.values(), []):
        R = G.LAB == G.FEATS.index(b) + 1; P = G.ref_contour(R)
        Ra = G.LAB == G.FEATS.index(a) + 1
        near = ndimage.distance_transform_edt(~Ra)[np.clip(np.round(P[:, 1]).astype(int), 0, 1085), np.clip(np.round(P[:, 0]).astype(int), 0, 1447)] < 4
        contacts[(a, b)] = (P, near)
    full = [0, 0, 1448, 1086]

    def measure(spec, wi, tag):
        w = W[wi % len(W)]
        p, s = os.path.abspath(f"{A.out}/w{w.wid}-{tag}.png"), os.path.abspath(f"{A.out}/w{w.wid}-{tag}-shade.png")
        r = w.call(spec_obj=spec, out=p, clip=full, box=full, shade=s, extra=A.extra)
        im = np.asarray(Image.open(p).convert("RGB")); sh = np.asarray(Image.open(s).convert("L"))
        out = {}
        for c, (x0, y0, x1, y1) in CLIPS.items():
            m, ex = sc[c].measure(im[y0:y1, x0:x1], sh[y0:y1, x0:x1])
            out[c] = (m, ex)
        L = K.lobes(im); extra = {}
        for f, (fr, wr, e) in frames.items():
            Rr = G.LAB == G.FEATS.index(f) + 1; Cm = K.match(L[G.FCOL[f]], Rr)
            if Cm is None: extra[f"w:{f}"] = 1.0; continue
            wc = G.width_on(Cm, fr, e); core = slice(6, 34); extra[f"w:{f}"] = float(np.nanmean(np.abs((wc[core] - wr[core]) / wr[core])))
        for (a, b), (P, near) in contacts.items():
            Cm = K.match(L[G.FCOL[b]], G.LAB == G.FEATS.index(b) + 1)
            if Cm is None: extra[f"c:{a}|{b}"] = 5.0; continue
            sd = G.sdf(Cm); d = -sd[np.clip(np.round(P[:, 1]).astype(int), 0, 1085), np.clip(np.round(P[:, 0]).astype(int), 0, 1447)]
            rip = G.band(d)[near]; low = ndimage.gaussian_filter1d(d, 20, mode="wrap")[near]
            extra[f"c:{a}|{b}"] = float(np.sqrt(np.mean(rip ** 2)) + 0.25 * np.mean(np.abs(low)))
        return out, extra, r.get("fold_box", 0.0)

    base = apply(inc, X0)[0]
    m0, e0, f0 = measure(inc, 0, "inc")
    mb, eb, fb = measure(base, 0, "base")
    print("incumbent:", {c: {f: round(v["iou"], 3) for f, v in m0[c][0].items()} for c in CLIPS}, e0, flush=True)
    print("handles removed only:", {c: {f: round(v["iou"], 3) for f, v in mb[c][0].items()} for c in CLIPS}, eb, flush=True)

    def J(meas, x):
        out, extra, fold = meas
        c = 0.0; pen = 0.0
        for cl in CLIPS:
            m, ex = out[cl]; mi, exi = m0[cl]
            for t in TARGETS[cl]: c += cost_t(m[t])
            for g in m:
                if g in TARGETS[cl]: continue
                a, b = mi[g], m[g]
                pen += 5 * max(0.0, a["iou"] - b["iou"] - 0.005) + 0.04 * max(0.0, b["p95"] - a["p95"] - 1) + 0.05 * max(0.0, abs(b["arc"]) - abs(a["arc"]) - 2)
            pen += 6 * max(0.0, exi["sil"] - ex["sil"] - 0.002)
            for k_, v in ex["intr"].items(): pen += 6 * max(0.0, v - exi["intr"].get(k_, 0) - 0.003)
            pen += max(0.0, ex["stray"] - exi["stray"] - 20) / 100
            for g, cr in ex["crease"].items(): pen += 0.5 * max(0.0, cr / max(exi["crease"].get(g, 0.6), 0.6) - 1.4)
            for jk, cr in ex["junction"].items(): pen += 0.5 * max(0.0, cr / max(exi["junction"].get(jk, 0.6), 0.6) - 1.15)
        c += 4 * sum(v for k_, v in extra.items() if k_.startswith("w:")) + 0.4 * sum(v for k_, v in extra.items() if k_.startswith("c:"))
        pen += max(0.0, fold - f0 - 200) / 2000
        reg = 0.01 * float(np.sum(np.square((x - X0) / SCALE)))
        return c + pen + reg, c, pen, reg

    print("J incumbent", [round(v, 4) for v in J((m0, e0, f0), X0)], "J base", [round(v, 4) for v in J((mb, eb, fb), X0)], flush=True)
    logf = open(f"{A.out}/fit.log", "a")

    def f(z, wi):
        x = X0 + z * SCALE
        spec, info = apply(inc, x)
        meas = measure(spec, wi, "c")
        j = J(meas, np.clip(x, LO, HI))
        return j[0], j, meas[1], info

    def log(g, best, F, sigma):
        x = X0 + best[1] * SCALE
        msg = f"gen {g}: best {best[0]:.4f} {dict(zip(NAMES, np.round(np.clip(x, LO, HI), 3).tolist()))} parts {np.round(best[2][1], 4).tolist()} extra {best[2][2]} sigma {sigma:.3f}"
        print(msg, flush=True); logf.write(msg + "\n"); logf.flush()

    t0 = time.time()
    lo, hi = (LO - X0) / SCALE, (HI - X0) / SCALE
    best = cma(f, len(NAMES), 0.6, lo, hi, A.gens, A.workers, seed=A.seed, log=log)
    x = np.clip(X0 + best[1] * SCALE, LO, HI)
    spec, info = apply(inc, x)
    json.dump(spec, open(f"{A.out}/spec.json", "w"))
    json.dump(dict(x=x.tolist(), names=NAMES, J=best[0], parts=best[2][1], extra=best[2][2], info=info, inc_J=J((m0, e0, f0), X0), base_J=J((mb, eb, fb), X0),
                   minutes=(time.time() - t0) / 60), open(f"{A.out}/fit.json", "w"), indent=1, default=float)
    print("done", dict(zip(NAMES, np.round(x, 3).tolist())), info, flush=True)
    for w in W: w.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("cmd"); ap.add_argument("spec"); ap.add_argument("rest", nargs="*")
    ap.add_argument("--gens", type=int, default=16); ap.add_argument("--workers", type=int, default=3); ap.add_argument("--seed", type=int, default=86)
    ap.add_argument("--extra", default="hybrid-r28-hybR.json"); ap.add_argument("--parts", default=",".join(PARTS))
    A = ap.parse_args()
    if A.cmd == "build":
        x = [float(v) for v in A.rest[:-1]]; spec, info = apply(json.load(open(A.spec)), x, tuple(A.parts.split(",")))
        json.dump(spec, open(A.rest[-1], "w")); print(json.dumps(info))
    else:
        A.out = A.rest[0]; fit(A)
