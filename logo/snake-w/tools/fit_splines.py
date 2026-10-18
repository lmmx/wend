"""Fit the spline body (tools/strandspline.py) to the current final's strands.

The ground truth is geometry.js: tools/dump_strands.mjs evaluates centrelines(params) in Node
and also dumps the tube centrelines the scene actually renders (sliced at each neck join,
evened to 3 px, Gaussian-smoothed by tube.smooth).

Per strand: fairness-regularised weighted least squares, linear in the control points
    min  sum_j w_j |B_j c - P_j|^2 ds  +  lam3 int |X'''|^2 ds  +  lam2 int |X''|^2 ds
and the same for the radius with mu2 int r''^2 + mu3 int r'''^2. The weights are high on the
neck windows (join_s - 40 .. join_s + 60, so strandAt(J) and the dive still match the heads) and
on the tail ends.

Usage (from snakes/):
  python ../tools/fit_splines.py [params.json] [--sweep] [--write tag:h:lam3:mu2 ...]
Writes snakes/spline-<tag>.json specs and arch/fit-metrics.json; prints the tables.
"""
import json, subprocess, sys, os
import numpy as np
from scipy.spatial import cKDTree
from scipy import ndimage
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import strandspline as S

HERE = os.path.dirname(os.path.abspath(__file__))
SNAKES = os.path.join(HERE, "..", "snakes")
ARCH = os.path.join(HERE, "..", "arch")
os.makedirs(ARCH, exist_ok=True)


def dump(params, spec=None, out=None):
    out = out or os.path.join(ARCH, "current-strands.json" if spec is None else "spline-strands.json")
    cmd = ["node", "../tools/dump_strands.mjs", params, out] + ([spec] if spec else [])
    subprocess.run(cmd, cwd=SNAKES, check=True, capture_output=True)
    return json.load(open(out))


# ---- the scene's own tube preprocessing (geometry.js evenly / gauss), mirrored

def evenly(P, r, step=3.0):
    d = np.r_[0, np.cumsum(np.linalg.norm(np.diff(P, axis=0), axis=1))]
    n = max(8, int(round(d[-1] / step)))
    t = np.linspace(0, d[-1], n + 1)
    return np.column_stack([np.interp(t, d, P[:, k]) for k in range(3)]), np.interp(t, d, r)


def gauss(P, sigma):
    if not sigma:
        return P
    h = int(np.ceil(3 * sigma)); k = np.arange(-h, h + 1); w = np.exp(-k ** 2 / (2 * sigma ** 2))
    idx = np.clip(np.arange(len(P))[:, None] + k[None, :], 0, len(P) - 1)
    return (P[idx] * w[None, :, None]).sum(1) / w.sum()


def rings(P, r, s, join_s, smooth):
    i0 = int(np.argmax(s >= join_s - 2))
    Q, rr = evenly(P[i0:], r[i0:])
    return gauss(Q, smooth), rr


# ---- fairness measures on a ring-centre polyline (3 px), the same for every model

def fairness(Q, r):
    T = np.gradient(Q, axis=0); T /= np.linalg.norm(T, axis=1, keepdims=True)
    ds = np.linalg.norm(np.gradient(Q, axis=0), axis=1)
    K = np.gradient(T, axis=0) / ds[:, None]
    k = np.linalg.norm(K, axis=1)
    dk = np.gradient(k) / ds
    d2r = np.gradient(np.gradient(r) / ds) / ds
    sl = slice(4, -4)  # away from the clamped ends
    k, dk, d2r, rk = k[sl], dk[sl], d2r[sl], (r * k)[sl]
    return dict(kmax=k.max(), k_p99=np.percentile(k, 99), dk_max=np.abs(dk).max(), dk_p99=np.percentile(np.abs(dk), 99),
                dk_energy=float((dk ** 2 * ds[sl]).sum()), rk_max=rk.max(), rk_gt05=float((rk > 0.5).mean()),
                r2_max=np.abs(d2r).max(), r2_p99=np.percentile(np.abs(d2r), 99), _k=k, _dk=dk, _r2=d2r)


def contact(Qa, ra, Qb, rb):
    """Overlap (r_a + r_b - distance to the partner's centreline) at each ring of a."""
    tree = cKDTree(Qb); d, j = tree.query(Qa)
    # refine on the neighbouring segments
    best = d.copy(); bj = j.astype(float)
    for o in (-1, 0):
        a = np.clip(j + o, 0, len(Qb) - 2); e = Qb[a + 1] - Qb[a]
        f = np.clip(((Qa - Qb[a]) * e).sum(1) / np.maximum((e * e).sum(1), 1e-12), 0, 1)
        dc = np.linalg.norm(Qa - (Qb[a] + f[:, None] * e), axis=1)
        bj = np.where(dc < best, a + f, bj); best = np.minimum(best, dc)
    rbm = np.interp(bj, np.arange(len(rb)), rb)
    return ra + rbm - best, bj


def overlap_stats(ov, mask):
    o = ov[mask]; do = np.abs(np.diff(o)) / 3.0
    return dict(mean=o.mean(), p5=np.percentile(o, 5), p95=np.percentile(o, 95), max=o.max(), min=o.min(),
                std=o.std(), dmax=do.max(), d_p99=np.percentile(do, 99))


# ---- fitting

def end_weights(s, s0, s1, join_s, w_neck, w_tail):
    neck = w_neck * (1 - S.smoothstep(join_s + 60, join_s + 100, s))
    tail = w_tail * S.smoothstep(s1 - 60, s1 - 20, s)
    return 1.0 + neck + tail


def fit_strand(st, join_s, h=20.0, lam3=1e5, lam2=0.0, mu2=1e3, mu3=0.0, rseg_h=None, w_neck=200.0, w_tail=50.0, pre=40.0,
               tight=0.0, tight_from=2.0, tight_span=20.0, iters=4, jump=0.0, jump_w=12.0):
    """One strand. `tight` > 0: curvature-limited fairing, iterated: where the fitted tube's
    r * kappa exceeds tight_from (the inside of a bend is about to fold), the fairness weight
    there is raised by `tight` x (and the data weight lowered), in a band tight_span px wide."""
    s = np.asarray(st["s"]); P = np.asarray(st["pts"]); r = np.asarray(st["r"])
    s0, s1 = join_s - pre, s[-1]
    m = (s >= s0) & (s <= s1)
    s, P, r = s[m], P[m], r[m]
    ds = np.gradient(s)
    w0 = end_weights(s, s0, s1, join_s, w_neck, w_tail) * ds
    if jump:
        # the raw strands jump where the spine's tangent kinks (piecewise-linear spine_offsets):
        # treat jump_w px around every jump (speed > jump x median) as missing data
        sp = np.r_[np.linalg.norm(np.diff(P, axis=0), axis=1) / np.diff(s), 0]
        bad = ndimage.maximum_filter1d((sp > jump * np.median(sp)).astype(float), int(2 * jump_w / np.median(ds)) + 1)
        w0 = w0 * np.where((bad > 0) & (s > join_s + 60), 0.01, 1.0)
    nseg = max(4, int(round((s1 - s0) / h)))
    rseg = max(4, int(round((s1 - s0) / (rseg_h or h))))
    t = S.knots(s0, s1, nseg); tr = S.knots(s0, s1, rseg)
    B = S.basis(s, t); Br = S.basis(s, tr)
    Ar = (Br * w0[:, None]).T @ Br + mu2 * S.penalty(tr, 2) + mu3 * S.penalty(tr, 3)
    rctrl = np.linalg.solve(Ar, (Br * w0[:, None]).T @ r)
    G3, G2 = S.penalty(t, 3), S.penalty(t, 2)
    grid = np.linspace(s0, s1, 4000); g = np.zeros_like(grid)
    for it in range(int(iters) if tight else 1):
        gf = lambda u: np.interp(u, grid, g)
        w = w0 * (1 - 0.95 * gf(s))
        A = (B * w[:, None]).T @ B + lam3 * G3 + lam2 * G2
        if tight:
            A = A + lam3 * tight * S.penalty(t, 3, weight=gf)
        ctrl = np.linalg.solve(A, (B * w[:, None]).T @ P)
        if tight:
            k, _ = S.curvature(dict(s0=s0, s1=s1, nseg=nseg, ctrl=ctrl), grid)
            rr = S.basis(grid, tr) @ rctrl
            x = np.clip((rr * k - tight_from) / 0.5, 0, 1)
            # widen to a band tight_span px each side with soft edges; never drop a flagged region
            dg = grid[1] - grid[0]
            x = ndimage.gaussian_filter1d(ndimage.maximum_filter1d(x, int(2 * tight_span / dg) + 1), tight_span / 2 / dg)
            g = np.maximum(g, x * S.smoothstep(join_s + 60, join_s + 100, grid))
    return dict(s0=float(s0), s1=float(s1), nseg=nseg, rseg=rseg, ctrl=ctrl.tolist(), rctrl=rctrl.tolist())


def make_spec(cur, params, h, lam3, mu2, lam2=0.0, mu3=0.0, tube=None, **kw):
    spec = {"kind": "strandspline", "version": 1, "degree": 3, "L": cur["L"], "step": 0.5, "mate_window": 80.0,
            "tube": tube if tube is not None else {"smooth": 0},
            "fit": dict(h=h, lam3=lam3, lam2=lam2, mu2=mu2, mu3=mu3, **kw)}
    for i, name in enumerate(("yellow", "blue")):
        spec[name] = fit_strand(cur[name], params["necks"][i]["join_s"], h=h, lam3=lam3, lam2=lam2, mu2=mu2, mu3=mu3, **kw)
    return spec


def deviation(cur, sp, params):
    """Deviation of the fitted strands from the raw JS strands (same station and closest point),
    overall and in the end windows, and from the rendered (smoothed) tube centreline."""
    out = {}
    for i, name in enumerate(("yellow", "blue")):
        st, fs = cur[name], sp[name]; js = params["necks"][i]["join_s"]
        s = np.asarray(st["s"]); P = np.asarray(st["pts"]); r = np.asarray(st["r"])
        m = (s >= fs["s0"]) & (s <= fs["s1"])
        X, rf = S.evaluate(fs, s[m])
        e_same = np.linalg.norm(X - P[m], axis=1)
        _, Xd, _, _ = S.arc_sample(fs, 0.25)
        e_cp, _ = cKDTree(Xd).query(P[m])
        er = np.abs(rf - r[m])
        neck = (s[m] >= js - 20) & (s[m] <= js + 60); tail = s[m] >= fs["s1"] - 40
        R = np.asarray(st["rendered"]["pts"]); e_rend, _ = cKDTree(Xd).query(R)
        out[name] = dict(cp_max=e_cp.max(), cp_p95=np.percentile(e_cp, 95), same_max=e_same.max(),
                         r_max=er.max(), r_p95=np.percentile(er, 95), neck_max=e_same[neck].max(), neck_r=er[neck].max(),
                         tail_max=e_same[tail].max(), rend_max=e_rend.max(), rend_p95=np.percentile(e_rend, 95))
    return out


def body_metrics(strands, params, smooth):
    """Fairness and contact on the rendered ring centres of {yellow, blue} strands."""
    Q, Rr, S_ = {}, {}, {}
    for i, name in enumerate(("yellow", "blue")):
        st = strands[name]; js = params["necks"][i]["join_s"]
        P, r, s = np.asarray(st["pts"]), np.asarray(st["r"]), np.asarray(st["s"])
        Q[name], Rr[name] = rings(P, r, s, js, smooth)
        # station of each ring, for masking: interpolate s along own arc
        i0 = int(np.argmax(s >= js - 2)); d = np.r_[0, np.cumsum(np.linalg.norm(np.diff(P[i0:], axis=0), axis=1))]
        S_[name] = np.interp(np.linspace(0, d[-1], len(Q[name])), d, s[i0:])
    res = {}
    for i, (a, b) in enumerate((("yellow", "blue"), ("blue", "yellow"))):
        f = fairness(Q[a], Rr[a])
        ov, bj = contact(Q[a], Rr[a], Q[b], Rr[b])
        # contact only where the partner is a tube (not the other snake's head/neck) and not the
        # first/last 30 px of either tube
        sb = np.interp(bj, np.arange(len(S_[b])), S_[b])
        mask = (sb > params["necks"][1 - i]["join_s"] + 30) & (S_[a] > params["necks"][i]["join_s"] + 30) & (S_[a] < S_[a][-1] - 30)
        res[a] = dict(fair=f, contact=overlap_stats(ov, mask), _ov=ov, _mask=mask, _s=S_[a])
    return res


def fmt(d, keys):
    return " ".join(f"{k}={d[k]:.4g}" for k in keys)


def main():
    args = sys.argv[1:]
    params_file = args[0] if args and args[0].endswith(".json") else "w-final.params.json"
    params = json.load(open(os.path.join(SNAKES, params_file)))
    cur = dump(params_file)
    smooth_cur = (params.get("tube") or {}).get("smooth", 0)
    report = {"current": {}}
    # the current model: the raw strands (what the head joins see) and what the scene renders
    for label, sm in (("raw (no tube smoothing)", 0), (f"rendered (tube.smooth={smooth_cur})", smooth_cur)):
        bm = body_metrics(cur, params, sm)
        report["current"][label] = bm
        print(f"\nCURRENT {label}")
        for n in ("yellow", "blue"):
            print(f"  {n:6s} fair: {fmt(bm[n]['fair'], ['kmax', 'k_p99', 'dk_max', 'dk_p99', 'dk_energy', 'rk_max', 'rk_gt05', 'r2_max', 'r2_p99'])}")
            print(f"  {n:6s} contact overlap px: {fmt(bm[n]['contact'], ['mean', 'p5', 'p95', 'min', 'max', 'std', 'dmax', 'd_p99'])}")
    configs = []
    if "--sweep" in args:
        for h in (12.0, 16.0, 20.0, 25.0):
            for lam3 in (0.0, 1e4, 1e5, 1e6, 4e6):
                configs.append((f"sweep-h{h:g}-l{lam3:g}", h, lam3, 2e3, False, {}))
    for a in args:
        if a.count(":") >= 3 and not a.startswith("--"):
            tag, h, lam3, mu2, *extra = a.split(":")
            kw = {k: float(v) for k, v in (e.split("=") for e in (extra[0].split(",") if extra else []))}
            configs.append((tag, float(h), float(lam3), float(mu2), True, kw))
    report["fits"] = {}
    print("\nFITS  (deviation px vs raw JS strands; fairness/contact on rendered ring centres, tube.smooth=0)")
    for tag, h, lam3, mu2, write, kw in configs:
        spec = make_spec(cur, params, h, lam3, mu2, **kw)
        dev = deviation(cur, spec, params)
        st = S.strands(spec)
        bm = body_metrics({n: {k: np.asarray(v) for k, v in st[n].items()} for n in st}, params, 0)
        report["fits"][tag] = dict(spec_fit=spec["fit"], nctrl=[spec["yellow"]["nseg"] + 3, spec["blue"]["nseg"] + 3], dev=dev, body=bm)
        print(f"[{tag}] h={h:g} lam3={lam3:g} mu2={mu2:g} {kw} nctrl Y/B={spec['yellow']['nseg'] + 3}/{spec['blue']['nseg'] + 3}")
        for n in ("yellow", "blue"):
            print(f"  {n:6s} dev: {fmt(dev[n], ['cp_max', 'cp_p95', 'same_max', 'rend_max', 'rend_p95', 'r_max', 'r_p95', 'neck_max', 'neck_r', 'tail_max'])}")
            print(f"  {n:6s} fair: {fmt(bm[n]['fair'], ['kmax', 'k_p99', 'dk_max', 'dk_p99', 'dk_energy', 'rk_max', 'rk_gt05', 'r2_max', 'r2_p99'])}")
            print(f"  {n:6s} contact: {fmt(bm[n]['contact'], ['mean', 'p5', 'p95', 'min', 'max', 'std', 'dmax', 'd_p99'])}")
        if write:
            json.dump(spec, open(os.path.join(SNAKES, f"spline-{tag}.json"), "w"))
    strip = lambda o: {k: strip(v) for k, v in o.items() if not k.startswith("_")} if isinstance(o, dict) else (float(o) if isinstance(o, (np.floating, float)) else o)
    json.dump(strip(report), open(os.path.join(ARCH, "fit-metrics.json"), "w"), indent=1)
    np.save(os.path.join(ARCH, "fit-profiles.npy"), report, allow_pickle=True)


if __name__ == "__main__":
    main()
