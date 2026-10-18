"""JAX region fit of the spline body (a strandspline spec), one image window at a time.

Free: the centreline and radius control points of both strands whose basis functions reach into
the window (by projection), except within `--neck-guard` px of a head join or a tail end. Every
other control point is fixed, so the result is the same C2 spline everywhere, with the change
fading out over the free points' own support.

Objective (all evaluated on the spline itself, X = B @ ctrl, r = Br @ rctrl):
  image    cross-entropy of the occlusion-aware soft raster (jaxraster) against the reference's
           colour labels in the window (step 2 px)
  self     self-collision: pairs of samples on *non-adjacent* sections of the same strand (>= 90 px of
           station apart; calibrated on the straight parts of the rope, where no pair that far apart
           overlaps) must not overlap at all: the squared overlap r_i + r_j - d beyond `--allow-self`
           (default 0: surface clearance >= 0). The neighbouring section is the fold barriers' job.
  contact  soft contact between the two strands on different turns (>= 110 px apart): lobes may
           press into each other by `--allow` px, no more
  fair     surface bending and its variation along every surface line of the swept tube
           (jaxsurface.fairness: arc-length invariant), relative to the start
  fold     a weaker global validity barrier: any surface line running backwards (advance < `--fold-min`),
           visible or not, so a fit cannot just turn a fold away from the camera
  visfold  the fold barrier where it can be seen: on every surface line, the advance relative to the
           centreline's (1 - r kappa cos) below `--j-min`, weighted by how much that surface point
           faces the camera. The hidden inner sides of the coils may stay folded (35% of the rings
           have r kappa > 1: structural); a fold on a side that faces us is a visible dimple
  speed    hinge on the centreline's speed per station dropping below 0.6 (a near-cusp)
  radius   radius kept near the start (plumpness), and never below 0.85 of it
  trust    a trust region around the start, on the evaluated centreline (not the control points):
           screen displacement beyond `--rho-s` px and depth displacement beyond `--rho-z` px are
           penalised quadratically. The reference is nearly frontal, so depth is weakly observed:
           without this a fit can hide a large 3D loop where the image term cannot see it
  osc      depth oscillation: the second derivative of the depth displacement along the strand
  feat     per-feature fidelity (audit/registry.json, the reference's numbered lobes and heads): for
           every feature whose window lies in the image window, 1 - soft Dice of blue and of yellow
           inside that feature's window, so each lobe counts equally however small it is and no
           lobe can be traded away for pixels elsewhere; --targets F1,F2 are weighted --target-boost x
  legs     (--leg-front S1 --leg-back S2, blue shared stations) an explicit depth order for two
           sections of the blue strand that meet head-on: the one at S1 in front of the one at S2
           by --leg-margin px wherever they overlap on screen. A self-collision that is symmetric
           in depth (both at the same depth) has zero depth gradient, so a fit cannot choose which
           goes in front; this makes the choice. Crossing order is not enforced for these two
           sections (their layering is what is being decided).
  zorder   (--order "B:s0-s1>Y:s0-s1@F", repeatable) an explicit depth order between two strand
           sections, where they overlap on screen inside reference feature F's mask: the first in
           front of the second by --order-margin px. For layering the reference shows and the start
           does not (the soft raster's depth softmax saturates when the wrong strand is tens of px in
           front, so the image term alone cannot flip it). Crossing order is relaxed for those
           sections only. Strands: Y yellow, B blue; stations are shared stations.
  order    crossing order: every pair of non-adjacent sections whose discs overlap on screen at the
           start, with a clear depth order (> 15 px), keeps that order with a 10 px margin
  tik      a small pull to the start
Elliptical sections (--sec 1): each strand also carries a C2 section field (cubic B-splines,
knots every --sec-h px) of ql (lateral, screen-plane semi-axis), qd (depth semi-axis) and psi
(orientation), relative to r (jaxsurface.ellipse; geometry.js applies the same map). They are
bounded (--ql/--qd/--psi bounds) and cost:
  secdev   departure from round (so sections deform only where contact asks for it)
  secsm    the section field's second derivative along the strand (no isolated corrections)
  area     (ql qd - 1)^2: a squashed section tends to keep its area, i.e. its fullness
The raster then uses the screen half-width and front depth of each ellipse, and the contact terms
the ellipses' combined extent along each pair's separation.
The image window is the union of --box and everywhere the evaluated (movable) geometry projects,
plus its radius and the trust radius, so moved geometry cannot leave the image term's view.
L-BFGS-B (SciPy) on jit(value_and_grad), x64.

Usage: regionfit.py spec.json out.json --box x0,y0,x1,y1 [--w-img 1 ...] [--labels out.png]
"""
import argparse, copy, json, os, sys, time
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import strandspline as S
import jaxraster as jr
import jaxsurface as js
import snakefit as sf
import jax
import jax.numpy as jnp
from scipy.optimize import minimize

ELEV = np.radians(3.7746862033886837)
REF = os.path.join(HERE, "..", "snakes", "ref", "reference.png")


def parse():
    ap = argparse.ArgumentParser()
    ap.add_argument("spec"); ap.add_argument("out")
    ap.add_argument("--box", required=True)
    ap.add_argument("--margin", type=float, default=30.0)
    ap.add_argument("--free-box", default=None, help="window that picks the free control points (default: --box)")
    ap.add_argument("--fold-min", type=float, default=0.0)
    ap.add_argument("--neck-guard", type=float, default=160.0)
    ap.add_argument("--tail-guard", type=float, default=60.0)
    ap.add_argument("--step", type=float, default=2.0)
    ap.add_argument("--allow", type=float, default=12.0)
    ap.add_argument("--allow-self", type=float, default=0.0)
    ap.add_argument("--w-self", type=float, default=1.0)
    ap.add_argument("--w-img", type=float, default=1.0)
    ap.add_argument("--w-contact", type=float, default=1.0)
    ap.add_argument("--w-fair", type=float, default=0.1)
    ap.add_argument("--w-jerk", type=float, default=0.1)
    ap.add_argument("--w-fold", type=float, default=1.0)
    ap.add_argument("--w-speed", type=float, default=1.0)
    ap.add_argument("--w-visfold", type=float, default=1.0)
    ap.add_argument("--j-min", type=float, default=0.3)
    ap.add_argument("--w-rad", type=float, default=1.0)
    ap.add_argument("--w-tik", type=float, default=1e-4)
    ap.add_argument("--w-trust", type=float, default=1.0)
    ap.add_argument("--rho-s", type=float, default=12.0)
    ap.add_argument("--rho-z", type=float, default=20.0)
    ap.add_argument("--w-osc", type=float, default=1.0)
    ap.add_argument("--w-order", type=float, default=1.0)
    ap.add_argument("--w-feat", type=float, default=0.0)
    ap.add_argument("--targets", default="")
    ap.add_argument("--target-boost", type=float, default=4.0)
    ap.add_argument("--order", action="append", default=[])
    ap.add_argument("--order-margin", type=float, default=30.0)
    ap.add_argument("--w-zorder", type=float, default=2.0)
    ap.add_argument("--leg-front", type=float, default=None)
    ap.add_argument("--leg-back", type=float, default=None)
    ap.add_argument("--leg-halfwidth", type=float, default=30.0)
    ap.add_argument("--leg-margin", type=float, default=45.0)
    ap.add_argument("--w-legs", type=float, default=1.0)
    ap.add_argument("--free-radius", type=int, default=1)
    ap.add_argument("--sec", type=int, default=0)
    ap.add_argument("--sec-h", type=float, default=24.0)
    ap.add_argument("--ql", default="0.95,1.12")
    ap.add_argument("--qd", default="0.55,1.1")
    ap.add_argument("--psi-max", type=float, default=0.35)
    ap.add_argument("--w-secdev", type=float, default=1.0)
    ap.add_argument("--w-secsm", type=float, default=1.0)
    ap.add_argument("--w-area", type=float, default=1.0)
    ap.add_argument("--iters", type=int, default=150)
    ap.add_argument("--labels", default=None)
    return ap.parse_args()


def free_set(t, ulo, uhi, s0, s1, neck_guard, tail_guard, p=3):
    n = len(t) - p - 1
    i = np.arange(n)
    a, b = t[i], t[i + p + 1]
    return i[(b > ulo) & (a < uhi) & (a >= s0 + neck_guard) & (b <= s1 - tail_guard)]


def main():
    A = parse()
    spec = json.load(open(A.spec)); L = spec["L"]
    box = tuple(float(v) for v in A.box.split(","))
    x0, y0, x1, y1 = box
    fx0, fy0, fx1, fy1 = tuple(float(v) for v in A.free_box.split(",")) if A.free_box else box
    strands = {}
    for k, name in enumerate(("yellow", "blue")):
        st = spec[name]
        t = S.knots(st["s0"], st["s1"], st["nseg"]); tr = S.knots(st["s0"], st["s1"], st.get("rseg", st["nseg"]))
        u = np.arange(st["s0"], st["s1"], 1.0)
        X, r = S.evaluate(st, u)
        x, y, _ = (np.asarray(v) for v in jr.project(jnp.asarray(X), ELEV))
        m = (x + r > x0 - A.margin) & (x - r < x1 + A.margin) & (y + r > y0 - A.margin) & (y - r < y1 + A.margin)
        mf = (x > fx0) & (x < fx1) & (y > fy0) & (y < fy1)
        ulo, uhi = u[mf].min(), u[mf].max()
        fc = free_set(t, ulo, uhi, st["s0"], st["s1"], A.neck_guard, A.tail_guard)
        fr = free_set(tr, ulo, uhi, st["s0"], st["s1"], A.neck_guard, A.tail_guard) if A.free_radius else np.zeros(0, int)
        if A.sec and "sec" not in st:
            seg = max(4, int(round((st["s1"] - st["s0"]) / A.sec_h)))
            st["sec"] = {"seg": seg, "ql": [1.0] * (seg + 3), "qd": [1.0] * (seg + 3), "psi": [0.0] * (seg + 3)}
        ts = S.knots(st["s0"], st["s1"], st["sec"]["seg"]) if A.sec else None
        fsec = free_set(ts, ulo, uhi, st["s0"], st["s1"], A.neck_guard, A.tail_guard) if A.sec else np.zeros(0, int)
        lo = max(st["s0"], min(t[fc[0]], tr[fr[0]] if len(fr) else 1e9, ts[fsec[0]] if len(fsec) else 1e9) - 48)
        hi = min(st["s1"], max(t[fc[-1] + 4], tr[fr[-1] + 4] if len(fr) else -1e9, ts[fsec[-1] + 4] if len(fsec) else -1e9) + 48)
        ue = np.arange(lo, hi, 1.5)
        c0 = np.asarray(st["ctrl"], float); rc0 = np.asarray(st["rctrl"], float)
        B = S.basis(ue, t); Br = S.basis(ue, tr); B1 = S.basis(ue, t, 1)
        fixc = np.setdiff1d(np.arange(len(c0)), fc); fixr = np.setdiff1d(np.arange(len(rc0)), fr)
        strands[name] = dict(k=k, u=ue, shared=ue if name == "yellow" else L - ue, fc=fc, fr=fr,
                             Bf=jnp.asarray(B[:, fc]), Xfix=jnp.asarray(B[:, fixc] @ c0[fixc]),
                             Brf=jnp.asarray(Br[:, fr]), rfix=jnp.asarray(Br[:, fixr] @ rc0[fixr]),
                             B1f=jnp.asarray(B1[:, fc]), X1fix=jnp.asarray(B1[:, fixc] @ c0[fixc]),
                             c0=c0, rc0=rc0, r0=jnp.asarray(Br @ rc0), range=(ulo, uhi, lo, hi))
        strands[name]["all"] = (u, X, r, x, y)
        if A.sec:
            sc0 = np.column_stack([st["sec"]["ql"], st["sec"]["qd"], st["sec"]["psi"]]).astype(float)
            Bs = S.basis(ue, ts); fixs = np.setdiff1d(np.arange(len(sc0)), fsec)
            strands[name].update(fs=fsec, sc0=sc0, Bsf=jnp.asarray(Bs[:, fsec]), sfix=jnp.asarray(Bs[:, fixs] @ sc0[fixs]))
        else:
            strands[name]["fs"] = np.zeros(0, int)
        print(f"{name}: window stations {ulo:.0f}..{uhi:.0f} (own), free ctrl {fc[0]}..{fc[-1]} ({len(fc)}), "
              f"free radius ctrl {len(fr)}, evaluated {lo:.0f}..{hi:.0f} ({len(ue)} samples)")
    names = ("yellow", "blue")
    # the image window: --box, and wherever the movable geometry projects (+ radius + trust radius)
    pad = A.rho_s + 20
    for n in names:
        s_ = strands[n]; u, X, r, x, y = s_["all"]; lo, hi = s_["range"][2:]
        e = (u >= lo) & (u <= hi)
        x0 = min(x0, (x[e] - r[e]).min() - pad); x1 = max(x1, (x[e] + r[e]).max() + pad)
        y0 = min(y0, (y[e] - r[e]).min() - pad); y1 = max(y1, (y[e] + r[e]).max() + pad)
    x0, y0, x1, y1 = max(x0, 0), max(y0, 0), min(x1, 1448), min(y1, 1086)
    print(f"image window {x0:.0f},{y0:.0f},{x1:.0f},{y1:.0f}")
    for n in names:
        s_ = strands[n]; u, X, r, x, y = s_["all"]; lo, hi = s_["range"][2:]
        m = (x + r > x0 - 10) & (x - r < x1 + 10) & (y + r > y0 - 10) & (y - r < y1 + 10) & ((u < lo) | (u > hi))
        s_["fixed_balls"] = (X[m][::3], r[m][::3])
    sizes = [(len(strands[n]["fc"]) * 3, len(strands[n]["fr"]), len(strands[n]["fs"]) * 3) for n in names]
    nvar = sum(sum(z) for z in sizes)

    def unpack(v):
        out, i = {}, 0
        for n, (a, b, c) in zip(names, sizes):
            out[n] = (v[i:i + a].reshape(-1, 3), v[i + a:i + a + b], v[i + a + b:i + a + b + c].reshape(-1, 3)); i += a + b + c
        return out

    def geom(v):
        g = {}
        for n, (dc, dr, dsc) in unpack(v).items():
            s = strands[n]
            c = jnp.asarray(s["c0"][s["fc"]]) + dc
            r = s["rfix"] + (s["Brf"] @ (jnp.asarray(s["rc0"][s["fr"]]) + dr) if len(s["fr"]) else 0.0)
            sec = (s["sfix"] + (s["Bsf"] @ (jnp.asarray(s["sc0"][s["fs"]]) + dsc) if len(s["fs"]) else 0.0)) if A.sec else None
            g[n] = (s["Bf"] @ c + s["Xfix"], r, s["B1f"] @ c + s["X1fix"], sec)
        return g

    # bounds: the section controls stay in their boxes; positions and radii are free (the trust
    # region and the other terms hold them)
    lq, hq = (float(x) for x in A.ql.split(",")); ld, hd = (float(x) for x in A.qd.split(","))
    bounds = []
    for n, (a, b, c) in zip(names, sizes):
        bounds += [(None, None)] * (a + b)
        if c:
            sc = strands[n]["sc0"][strands[n]["fs"]]
            for q in sc:
                bounds += [(lq - q[0], hq - q[0]), (ld - q[1], hd - q[1]), (-A.psi_max - q[2], A.psi_max - q[2])]

    def axes(r, sec):
        """Screen half-width and front depth / half-width of each section's ellipse."""
        if sec is None:
            return r, jnp.ones_like(r)
        Aa, Bb, c, s_ = r * sec[:, 0], r * sec[:, 1], jnp.cos(sec[:, 2]), jnp.sin(sec[:, 2])
        a = jnp.sqrt(Aa ** 2 * c ** 2 + Bb ** 2 * s_ ** 2)
        b = Aa * Bb / jnp.sqrt(Aa ** 2 * s_ ** 2 + Bb ** 2 * c ** 2)
        return a, b / a

    # ---- image term: reference labels on the window grid
    grid, gshape = jr.window_grid((x0, y0, x1, y1), A.step)
    _, lab = sf.ref_labels(REF, 1.0)
    gi = np.asarray(grid).astype(int)
    ref = lab[np.clip(gi[:, 1], 0, lab.shape[0] - 1), np.clip(gi[:, 0], 0, lab.shape[1] - 1)].astype(int)
    ref_oh = jnp.asarray(np.eye(3)[ref])
    # ---- per-feature windows on the grid (the reference registry)
    regd = os.path.join(HERE, "..", "audit")
    feat_w, feat_names = [], []
    if A.w_feat and os.path.exists(f"{regd}/registry.json"):
        reg = json.load(open(f"{regd}/registry.json"))
        targets = set(t for t in A.targets.split(",") if t)
        gx, gy = np.asarray(grid)[:, 0], np.asarray(grid)[:, 1]
        for f in reg["features"]:
            bx0, by0, bx1, by1 = f["bbox"]
            inwin = (gx >= bx0 - 20) & (gx <= bx1 + 20) & (gy >= by0 - 20) & (gy <= by1 + 20)
            full = bx0 >= x0 and bx1 <= x1 and by0 >= y0 and by1 <= y1
            if inwin.sum() < 30 or not full:
                continue
            feat_w.append(inwin.astype(float) * (A.target_boost if f["id"] in targets else 1.0)); feat_names.append(f["id"])
        print(f"features in the image window: {', '.join(feat_names)}; targets {', '.join(sorted(targets)) or '-'}")
    FW = jnp.asarray(np.array(feat_w)) if feat_w else None              # (nfeat, npix)

    def featloss(prob):
        if FW is None:
            return 0.0
        tot = 0.0
        for k in (1, 2):                                                   # blue, yellow
            P, Tm = prob[:, k][None], ref_oh[:, k][None]
            inter = jnp.sum(FW * P * Tm, 1); den = jnp.sum(FW * (P + Tm), 1)
            tot = tot + (1 - 2 * inter / (den + 1e-6))
        wsum = jnp.max(FW, 1)
        return jnp.sum(wsum * tot / 2) / jnp.sum(wsum)
    fb = [strands[n]["fixed_balls"] for n in names]
    FP = jnp.asarray(np.vstack([fb[0][0], fb[1][0]]) if len(fb[0][0]) + len(fb[1][0]) else np.zeros((0, 3)))
    FR = jnp.asarray(np.r_[fb[0][1], fb[1][1]])
    FO = np.zeros((len(FR), 2)); FO[: len(fb[0][1]), 1] = 1; FO[len(fb[0][1]):, 0] = 1; FO = jnp.asarray(FO)
    OH = jnp.asarray(np.vstack([np.tile([0.0, 1.0], (len(strands["yellow"]["u"][::2]), 1)),
                                np.tile([1.0, 0.0], (len(strands["blue"]["u"][::2]), 1))]))

    def raster(g):
        P = jnp.vstack([g["yellow"][0][::2], g["blue"][0][::2], FP])
        ay, zy = axes(g["yellow"][1][::2], None if g["yellow"][3] is None else g["yellow"][3][::2])
        ab, zb = axes(g["blue"][1][::2], None if g["blue"][3] is None else g["blue"][3][::2])
        R = jnp.concatenate([ay, ab, FR]); Z = jnp.concatenate([zy, zb, jnp.ones_like(FR)])
        return jr.soft_labels(P, R, jnp.vstack([OH, FO]), grid, ELEV, tau=0.6, gamma=1.0, sharp=20.0, zscale=Z)

    VIEW = jnp.array([0.0, np.sin(ELEV), np.cos(ELEV)])     # towards the camera, world
    # ---- contact pairs (static: which pairs are on different turns)
    sh = np.r_[strands["yellow"]["shared"][::2], strands["blue"]["shared"][::2]]
    sid = np.r_[np.zeros(len(strands["yellow"]["u"][::2])), np.ones(len(strands["blue"]["u"][::2]))]
    sep = np.abs(sh[:, None] - sh[None]); same = sid[:, None] == sid[None]
    def ss(e0, e1, x):
        q = np.clip((x - e0) / (e1 - e0), 0, 1); return q * q * (3 - 2 * q)
    wself = jnp.asarray(np.triu(np.where(same, ss(80, 100, sep), 0.0), 1))
    wacross = jnp.asarray(np.triu(np.where(same, 0.0, ss(100, 120, sep)), 1))
    ncs = len(sh)

    def contact(g):
        P = jnp.vstack([g["yellow"][0][::2], g["blue"][0][::2]])
        R = jnp.concatenate([g["yellow"][1][::2], g["blue"][1][::2]])
        if A.sec:
            # ellipses: lateral (screen) semi-axis r ql, depth r qd; their combined extent along the
            # separation D (depth part Dz, screen part Ds) is sa sb |D| / sqrt(sb^2 Ds^2 + sa^2 Dz^2)
            Q = jnp.vstack([g["yellow"][3][::2], g["blue"][3][::2]])
            a, b = R * Q[:, 0], R * Q[:, 1]
            Dv = P[:, None] - P[None]
            d2 = jnp.sum(Dv ** 2, -1) + 1e-6; dz2 = (Dv @ VIEW) ** 2; ds2 = jnp.maximum(d2 - dz2, 0.0)
            sa, sb = a[:, None] + a[None], b[:, None] + b[None]
            d = jnp.sqrt(d2)
            ov = sa * sb * d / jnp.sqrt(sb ** 2 * ds2 + sa ** 2 * dz2 + 1e-6) - d
        else:
            d = jnp.sqrt(jnp.sum((P[:, None] - P[None]) ** 2, -1) + 1e-6)
            ov = R[:, None] + R[None] - d
        return (jnp.sum(wself * jax.nn.relu(ov - A.allow_self) ** 2) / ncs,
                jnp.sum(wacross * jax.nn.relu(ov - A.allow) ** 2) / ncs,
                jnp.max(jnp.where(wself > 0.5, ov, -1e9)), jnp.max(jnp.where(wacross > 0.5, ov, -1e9)))

    def visfold(P, r, sec):
        Sx, T = js.rings(P, r, 16, sec, VIEW)
        e = Sx[1:] - Sx[:-1]
        j = jnp.einsum("ijk,ik->ij", e, T[:-1]) / jnp.linalg.norm(P[1:] - P[:-1], axis=1)[:, None]
        # the surface normal from the mesh itself (elliptical sections), outwards
        around = jnp.roll(Sx, -1, axis=1) - jnp.roll(Sx, 1, axis=1)
        nrm = jnp.cross(around[:-1], e)
        out = Sx[:-1] - P[:-1, None]
        nrm = nrm * jnp.sign(jnp.sum(nrm * out, -1, keepdims=True))
        nrm = nrm / (jnp.linalg.norm(nrm, axis=-1, keepdims=True) + 1e-9)
        face = jax.nn.relu(nrm @ VIEW)
        return jnp.mean(jax.nn.softplus((A.j_min - j) * 10.0) / 10.0 * face) * 100, jnp.min(jnp.where(face > 0.3, j, 9.0))

    g0 = geom(jnp.zeros(nvar))
    def scr(P):
        x, y, z = jr.project(P, ELEV); return jnp.stack([x, y], 1), z
    P0 = {n: g0[n][0] for n in names}
    # crossing order at the start
    Pc0 = jnp.vstack([g0["yellow"][0][::2], g0["blue"][0][::2]]); Rc0 = np.r_[np.asarray(g0["yellow"][1])[::2], np.asarray(g0["blue"][1])[::2]]
    q0, z0 = (np.asarray(v) for v in scr(Pc0))
    dq = np.linalg.norm(q0[:, None] - q0[None], axis=-1); dz0 = z0[:, None] - z0[None]
    nonadj = np.where(same, sep >= 90, True)
    ordered = np.triu((dq < 0.9 * (Rc0[:, None] + Rc0[None])) & (np.abs(dz0) > 15) & nonadj, 1)
    if A.leg_front is not None:
        legA = (sid == 1) & (np.abs(sh - A.leg_front) < A.leg_halfwidth)
        legB = (sid == 1) & (np.abs(sh - A.leg_back) < A.leg_halfwidth)
        inleg = legA | legB
        ordered &= ~(inleg[:, None] | inleg[None])
        li, lj = np.nonzero(legA[:, None] & legB[None] & (dq < 1.0 * (Rc0[:, None] + Rc0[None])))
        print(f"legs: {legA.sum()} samples in front (blue @{A.leg_front:.0f}), {legB.sum()} behind (@{A.leg_back:.0f}), {len(li)} overlapping pairs")
    else:
        li = lj = np.zeros(0, int)
    # explicit, feature-scoped depth orders
    zi, zj = [], []
    if A.order:
        from PIL import Image as _I
        rlab = np.asarray(_I.open(os.path.join(HERE, "..", "audit", "registry-labels.png"))).astype(int)
        rreg = json.load(open(os.path.join(HERE, "..", "audit", "registry.json")))
        ids = [f["id"] for f in rreg["features"]]
        for spec_ in A.order:
            pair, fid = spec_.split("@")
            a_, b_ = pair.split(">")
            def sect(t):
                k, rng = t.split(":"); lo, hi = (float(v) for v in rng.split("-"))
                return (sid == (0 if k == "Y" else 1)) & (sh >= lo) & (sh <= hi)
            sa, sb = sect(a_), sect(b_)
            fm = rlab == ids.index(fid) + 1
            mid = 0.5 * (q0[:, None] + q0[None])
            mx = np.clip(mid[..., 0].astype(int), 0, rlab.shape[1] - 1); my = np.clip(mid[..., 1].astype(int), 0, rlab.shape[0] - 1)
            pm = sa[:, None] & sb[None] & (dq < 1.0 * (Rc0[:, None] + Rc0[None])) & fm[my, mx]
            pi, pj = np.nonzero(pm)
            zi.append(pi); zj.append(pj)
            ordered &= ~((sa | sb)[:, None] | (sa | sb)[None])
            print(f"order {spec_}: {sa.sum()} front samples, {sb.sum()} behind, {len(pi)} pairs inside {fid}")
        oi, oj = np.nonzero(ordered); osign = jnp.asarray(np.sign(dz0[oi, oj]))
        print(f"crossing order after relaxing: {len(oi)} ordered pairs kept")
    zi = np.concatenate(zi) if zi else np.zeros(0, int); zj = np.concatenate(zj) if zj else np.zeros(0, int)
    oi, oj = np.nonzero(ordered); osign = jnp.asarray(np.sign(dz0[oi, oj]))
    print(f"crossing order: {len(oi)} ordered pairs kept")

    def legs(g):
        if not len(li):
            return 0.0
        Pc = jnp.vstack([g["yellow"][0][::2], g["blue"][0][::2]])
        _, z = scr(Pc)
        return jnp.mean(jax.nn.relu(A.leg_margin - (z[li] - z[lj])) ** 2)

    def zorder(g):
        if not len(zi):
            return 0.0
        Pc = jnp.vstack([g["yellow"][0][::2], g["blue"][0][::2]])
        _, z = scr(Pc)
        return jnp.mean(jax.nn.relu(A.order_margin - (z[zi] - z[zj])) ** 2)

    def trust(g):
        tr = osc = 0.0
        for n in names:
            D = g[n][0] - P0[n]
            ds, dz = scr(D)
            tr += jnp.mean(jax.nn.relu(jnp.linalg.norm(ds + 1e-9, axis=1) - A.rho_s) ** 2) + jnp.mean(jax.nn.relu(jnp.abs(dz) - A.rho_z) ** 2)
            osc += jnp.mean(((dz[2:] - 2 * dz[1:-1] + dz[:-2]) / 1.5 ** 2) ** 2) * 1e4
        return tr, osc

    def order(g):
        Pc = jnp.vstack([g["yellow"][0][::2], g["blue"][0][::2]])
        _, z = scr(Pc)
        return jnp.mean(jax.nn.relu(10.0 - osign * (z[oi] - z[oj])) ** 2) if len(oi) else 0.0
    f0 = {n: js.fairness(g0[n][0], g0[n][1], nphi=16, fold_min=A.fold_min, sec=g0[n][3], view=VIEW) for n in names}

    def terms(v):
        g = geom(v)
        prob = raster(g)
        img = -jnp.mean(jnp.sum(ref_oh * jnp.log(prob + 1e-3), axis=1))
        fl = featloss(prob)
        slf, con, ovself, ovacross = contact(g)
        bend = jerk = fold = spd = rad = vf = sdev = ssm = area = 0.0
        qdmin = 9.0
        jvis = 9.0
        for n in names:
            P, r, X1, sec = g[n]
            f = js.fairness(P, r, nphi=16, fold_min=A.fold_min, sec=sec, view=VIEW)
            bend += f["bend"] / f0[n]["bend"] / 2; jerk += f["jerk"] / f0[n]["jerk"] / 2; fold += f["fold"]
            a, b = visfold(P, r, sec); vf += a; jvis = jnp.minimum(jvis, b)
            if sec is not None:
                sdev += (jnp.mean((sec[:, 0] - 1) ** 2) + jnp.mean((sec[:, 1] - 1) ** 2) + jnp.mean(sec[:, 2] ** 2)) * 100
                ssm += jnp.mean(((sec[2:] - 2 * sec[1:-1] + sec[:-2]) / 1.5 ** 2) ** 2) * 1e7
                area += jnp.mean((sec[:, 0] * sec[:, 1] - 1) ** 2) * 100
                qdmin = jnp.minimum(qdmin, jnp.min(sec[:, 1]))
            sp = jnp.linalg.norm(X1, axis=1)
            spd += jnp.mean(jax.nn.relu(0.6 - sp) ** 2) * 100
            r0 = strands[n]["r0"]
            rad += jnp.mean(((r - r0) / r0) ** 2) * 100 + jnp.mean(jax.nn.relu(0.85 - r / r0) ** 2) * 1e4
        tik = jnp.mean(v ** 2)
        trs, osc = trust(g); ordr = order(g); lg = legs(g); zo = zorder(g)
        dmax = jnp.max(jnp.concatenate([jnp.abs(scr(g[n][0] - P0[n])[1]) for n in names]))
        return dict(zorder=zo, feat=fl, legs=lg, secdev=sdev, secsm=ssm, area=area, qd_min=qdmin, trust=trs, osc=osc, order=ordr, depth_move_max=dmax, img=img, self=slf, contact=con, self_overlap_max=ovself, across_overlap_max=ovacross, bend=bend, jerk=jerk, fold=fold, visfold=vf, speed=spd, radius=rad, tik=tik, jvis=jvis)

    W = dict(zorder=A.w_zorder, feat=A.w_feat, legs=A.w_legs, secdev=A.w_secdev, secsm=A.w_secsm, area=A.w_area, trust=A.w_trust, osc=A.w_osc, order=A.w_order, img=A.w_img, self=A.w_self, contact=A.w_contact, bend=A.w_fair, jerk=A.w_jerk, fold=A.w_fold, visfold=A.w_visfold, speed=A.w_speed, radius=A.w_rad, tik=A.w_tik)

    def loss(v):
        tm = terms(v)
        return sum(W[k] * tm[k] for k in W)

    vg = jax.jit(jax.value_and_grad(loss))
    tj = jax.jit(terms)
    def show(tag, v):
        tm = {k: float(x) for k, x in tj(v).items()}
        print(f"{tag}: " + "  ".join(f"{k} {tm[k]:.4g}" + (f" (x{W[k]:g} = {W[k] * tm[k]:.4g})" if k in W else "") for k in tm))
        return tm
    v0 = np.zeros(nvar)
    t0 = time.time(); val, gr = vg(jnp.asarray(v0)); print(f"compile + first eval {time.time() - t0:.1f} s, {nvar} variables")
    t0 = time.time(); vg(jnp.asarray(v0))[0].block_until_ready(); print(f"one eval {time.time() - t0:.3f} s")
    tm0 = show("start", jnp.asarray(v0))
    hist = []
    def fun(v):
        val, gr = vg(jnp.asarray(v))
        val, gr = float(val), np.asarray(gr)
        if not np.isfinite(val) or not np.all(np.isfinite(gr)):
            return 1e30, np.zeros_like(v)
        hist.append(val)
        return val, gr
    t0 = time.time()
    res = minimize(fun, v0, jac=True, method="L-BFGS-B", bounds=bounds, options=dict(maxiter=A.iters, maxcor=50, maxfun=A.iters * 2))
    print(f"L-BFGS-B: {res.nit} iterations, {res.nfev} evaluations, {time.time() - t0:.0f} s, {res.message}")
    tm1 = show("end  ", jnp.asarray(res.x))
    # ---- write the spec
    out = copy.deepcopy(spec)
    for n, (dc, dr, dsc) in unpack(np.asarray(res.x)).items():
        s = strands[n]
        c = s["c0"].copy(); c[s["fc"]] += dc; out[n]["ctrl"] = c.tolist()
        rc = s["rc0"].copy(); rc[s["fr"]] += dr; out[n]["rctrl"] = rc.tolist()
        if A.sec:
            sc = s["sc0"].copy(); sc[s["fs"]] += dsc
            out[n]["sec"] = {"seg": spec[n]["sec"]["seg"], "ql": sc[:, 0].tolist(), "qd": sc[:, 1].tolist(), "psi": sc[:, 2].tolist()}
            print(f"{n}: sections ql {sc[:, 0].min():.3f}..{sc[:, 0].max():.3f}  qd {sc[:, 1].min():.3f}..{sc[:, 1].max():.3f}  psi {sc[:, 2].min():.3f}..{sc[:, 2].max():.3f}")
        print(f"{n}: max control-point move {np.abs(dc).max():.1f} px, radius ctrl change {dr.min() if len(dr) else 0:.1f}..{dr.max() if len(dr) else 0:.1f} px")
    out.setdefault("regionfit", []).append(dict(box=list(box), args=vars(A), start={k: tm0[k] for k in tm0}, end={k: tm1[k] for k in tm1}))
    json.dump(out, open(A.out, "w"))
    print("wrote", A.out)
    if A.labels:
        from PIL import Image
        pal = np.array([[245, 245, 245], [40, 90, 220], [245, 200, 30]], np.uint8)
        rows = []
        for v in (v0, res.x):
            pred = np.asarray(raster(geom(jnp.asarray(v)))).argmax(1).reshape(gshape)
            rr = ref.reshape(gshape)
            dis = np.where((pred != rr)[..., None], np.array([220, 40, 40], np.uint8), (pal[rr] * 0.35 + 160).astype(np.uint8))
            rows.append(np.concatenate([pal[rr], pal[pred], dis], 1))
            print("pixel agreement", float((pred == rr).mean()))
        im = np.concatenate(rows, 0)
        Image.fromarray(im).resize((im.shape[1] * 2, im.shape[0] * 2), Image.NEAREST).save(A.labels)


if __name__ == "__main__":
    main()
