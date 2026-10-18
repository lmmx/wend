"""Reference evaluator for the spline body: each strand is an independent clamped cubic
B-spline centreline X(u) = sum_i N_i(u) P_i in 3D and a cubic B-spline radius r(u), over the
strand's own station parameter u (the scene's `s` field: spine arc length from that snake's
snout end). Knots are fixed (clamped, uniform inside [s0, s1]), so every evaluation is a
precomputed basis matrix times the control points: X = B @ ctrl.

Everything here is pure array ops with static shapes (no data-dependent Python branching in
the evaluation), so a JAX port is mechanical: np -> jnp, np.searchsorted/np.interp exist in
jax.numpy, and `safe_div` is already written with `where`.

Spec format (also read by snakes/strandspline.js):
  { "kind": "strandspline", "version": 1, "degree": 3, "L": spine length,
    "yellow": { "s0", "s1", "nseg", "ctrl": [[x,y,z]...] (nseg+3), "rseg", "rctrl": [...] (rseg+3) },
    "blue": { ... }, "tube": { overrides for params.tube }, "mate_window": px, "step": px }
"""
import numpy as np

DEG = 3


def knots(s0, s1, nseg, p=DEG):
    """Clamped knot vector, uniform inside [s0, s1]; nseg + p control points."""
    return np.r_[np.full(p, s0), np.linspace(s0, s1, nseg + 1), np.full(p, s1)]


def safe_div(a, b):
    return np.where(b > 0, a / np.where(b > 0, b, 1.0), 0.0)


def basis(u, t, deriv=0, p=DEG):
    """Basis matrix (len(u), len(t) - p - 1) of the d-th derivative, by Cox-de Boor.
    Value recursion up to degree p - deriv, then the derivative recursion up to p."""
    u = np.asarray(u, float)
    K = len(t)
    lo, hi = t[p], t[K - p - 1]
    u = np.clip(u, lo, hi)
    # the span holding u (the last non-empty span at the right end)
    span = np.clip(np.searchsorted(t, u, side="right") - 1, p, K - p - 2)
    N = (np.arange(K - 1)[None, :] == span[:, None]).astype(float)  # degree 0, (n, K-1)
    for k in range(1, p + 1):
        ti, tik = t[: K - k - 1], t[k: K - 1]          # t_i, t_{i+k}
        ti1, tik1 = t[1: K - k], t[k + 1: K]           # t_{i+1}, t_{i+k+1}
        a, b = N[:, :-1], N[:, 1:]
        if k <= p - deriv:
            N = safe_div(u[:, None] - ti, tik - ti) * a + safe_div(tik1 - u[:, None], tik1 - ti1) * b
        else:
            N = k * (safe_div(a, tik - ti) - safe_div(b, tik1 - ti1))
    return N  # (n, K - p - 1)


def span_mids(t, p=DEG):
    """Midpoints and lengths of the non-empty spans (for exact integrals of piecewise polynomials)."""
    inner = t[p: len(t) - p]
    return 0.5 * (inner[1:] + inner[:-1]), np.diff(inner)


def gauss_nodes(t, q=3, p=DEG):
    """Gauss-Legendre nodes and weights over every span (q per span)."""
    inner = t[p: len(t) - p]
    x, w = np.polynomial.legendre.leggauss(q)
    a, b = inner[:-1, None], inner[1:, None]
    return (0.5 * (b - a) * x + 0.5 * (b + a)).ravel(), (0.5 * (b - a) * w).ravel()


def penalty(t, deriv, p=DEG, q=3, weight=None):
    """Gram matrix G with c^T G c = integral of weight(u) (d^deriv/du^deriv sum c_i N_i)^2 du
    (exact for q >= p - deriv + 1 when weight is 1; `weight` is a function of u)."""
    if deriv == p:
        un, wn = span_mids(t, p)
    else:
        un, wn = gauss_nodes(t, q, p)
    if weight is not None:
        wn = wn * weight(un)
    D = basis(un, t, deriv, p)
    return (D * wn[:, None]).T @ D


def evaluate(st, u, deriv=0):
    """Centreline (n,3) and radius (n,) at stations u of one strand spec."""
    t = knots(st["s0"], st["s1"], st["nseg"])
    tr = knots(st["s0"], st["s1"], st.get("rseg", st["nseg"]))
    X = basis(u, t, deriv) @ np.asarray(st["ctrl"], float)
    r = basis(u, tr, deriv) @ np.asarray(st["rctrl"], float)
    return X, r


def arc_sample(st, step=0.5, dense_per_span=24, n_out=None):
    """Sample a strand evenly in its own arc length (~step px apart). Returns stations u, points,
    radii and cumulative arc. Static shapes: the dense grid has a fixed size; n_out may be given."""
    nd = st["nseg"] * dense_per_span + 1
    ud = np.linspace(st["s0"], st["s1"], nd)
    Xd, _ = evaluate(st, ud)
    cum = np.r_[0.0, np.cumsum(np.linalg.norm(np.diff(Xd, axis=0), axis=1))]
    if n_out is None:
        n_out = int(round(cum[-1] / step)) + 1
    a = np.linspace(0.0, cum[-1], n_out)
    u = np.interp(a, cum, ud)
    X, r = evaluate(st, u)
    return u, X, r, a


def closest_mate(P, sP, Q, sQ, window=80.0):
    """For each point of P (station sP, in shared spine stations) the closest point of polyline Q
    (stations sQ) among Q's samples within `window` station px, refined on the segment; returns
    mate points, mate stations and the distance. Dense (n x m) masked argmin: static shapes."""
    d2 = np.maximum((P * P).sum(-1)[:, None] + (Q * Q).sum(-1)[None, :] - 2 * P @ Q.T, 0.0)
    d2 = np.where(np.abs(sP[:, None] - sQ[None, :]) <= window, d2, np.inf)
    j = np.argmin(d2, axis=1)
    # refine on the two segments next to j
    best = Q[j]; bs = sQ[j]; bd = np.sqrt(d2[np.arange(len(P)), j])
    for k in (-1, 0):
        a = np.clip(j + k, 0, len(Q) - 2); b = a + 1
        e = Q[b] - Q[a]; ee = np.maximum((e * e).sum(-1), 1e-12)
        f = np.clip(((P - Q[a]) * e).sum(-1) / ee, 0, 1)
        c = Q[a] + f[:, None] * e; dc = np.linalg.norm(P - c, axis=1)
        better = dc < bd
        best = np.where(better[:, None], c, best); bs = np.where(better, sQ[a] + f * (sQ[b] - sQ[a]), bs)
        bd = np.where(better, dc, bd)
    return best, bs, bd


def smoothstep(e0, e1, x):
    tt = np.clip((x - e0) / (e1 - e0), 0, 1)
    return tt * tt * (3 - 2 * tt)


def strands(spec, step=None):
    """Both strands as the scene consumes them (the same fields centrelines() returns).
    Mates: spec["mate"] = "station" (default) pairs each sample with the partner at the same
    shared spine station (the twist partner, as centrelines() does; continuous by construction),
    "closest" with the closest partner point within mate_window station px (diagnostic: in the
    valleys it picks the neighbouring turn, which the press would then crush)."""
    step = step or spec.get("step", 0.5)
    L = spec["L"]; win = spec.get("mate_window", 80.0); mode = spec.get("mate", "station")
    out = {}
    for name in ("yellow", "blue"):
        u, X, r, a = arc_sample(spec[name], step)
        out[name] = {"u": u, "pts": X, "r": r, "arc": a}
    # shared station: yellow's s is the spine station, blue's is L - station
    sh = {"yellow": out["yellow"]["u"], "blue": L - out["blue"]["u"]}
    for name, other in (("yellow", "blue"), ("blue", "yellow")):
        A, B = out[name], out[other]
        if mode == "closest":
            m, ms, d = closest_mate(A["pts"], sh[name], B["pts"], sh[other], win)
            mateS = ms if other == "yellow" else L - ms  # in the partner's own convention
        else:
            mateS = L - A["u"]
            m, _ = evaluate(spec[other], np.clip(mateS, spec[other]["s0"], spec[other]["s1"]))
            d = np.linalg.norm(m - A["pts"], axis=1)
        tail = spec[other]["s1"]  # partner's tail end, own convention
        A.update(s=A["u"], head=np.zeros_like(A["u"]), mate=m, mateS=mateS,
                 mateW=smoothstep(0.0, 25.0, tail - mateS), mateD=d)
    return out


def curvature(st, u):
    """Curvature (1/px) and radius at stations u, from the analytic derivatives."""
    t = knots(st["s0"], st["s1"], st["nseg"]); c = np.asarray(st["ctrl"], float)
    d1, d2 = basis(u, t, 1) @ c, basis(u, t, 2) @ c
    sp = np.linalg.norm(d1, axis=1)
    return np.linalg.norm(np.cross(d1, d2), axis=1) / np.maximum(sp, 1e-9) ** 3, sp
