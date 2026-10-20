"""The swept-profile head and the constructed neck, in Python (the same mathematics as geometry.js).

Head, in its own frame: t in [0, 1] along the axis from the rear of the head (t = 0) to the
snout tip (t = 1), v perpendicular to it in the picture plane (up), z towards the camera.
  upper outline  u(t) =  U(t) * sqrt(t (1 - t))
  lower outline  l(t) = -Lo(t) * sqrt(t (1 - t))
  depth          rz(t) = D(t) * sqrt(t (1 - t))
U, Lo, D are Catmull-Rom curves through control values at evenly spaced t. The square
root closes both ends with rounded caps; U and Lo at t = 1 set how blunt the snout is above
and below. Each cross-section is two half-superellipses glued at the cheek line
m(t) = l + beta (u - l): the upper half has height u - m, the lower m - l, both depth rz.

Neck: a quintic Hermite curve from Q (inside the head) to J (on the body strand, hidden
behind the other snake's wrap), matching J's position, tangent and curvature, with a
radius that eases from r_top to the strand's radius.
"""
import numpy as np


def catmull(ctrl, t):
    """Uniform Catmull-Rom through ctrl at t_k = k / (K - 1), ends extended linearly."""
    c = np.asarray(ctrl, float); K = len(c)
    P = np.r_[2 * c[0] - c[1], c, 2 * c[-1] - c[-2]]
    x = np.clip(np.asarray(t, float), 0, 1) * (K - 1)
    i = np.minimum(np.floor(x).astype(int), K - 2); u = x - i
    p0, p1, p2, p3 = P[i], P[i + 1], P[i + 2], P[i + 3]
    return 0.5 * ((2 * p1) + (-p0 + p2) * u + (2 * p0 - 5 * p1 + 4 * p2 - p3) * u**2 + (-p0 + 3 * p1 - 3 * p2 + p3) * u**3)


def catmull_basis(K, t):
    """The matrix B with catmull(c, t) == B @ c (Catmull-Rom is linear in its control values)."""
    return np.column_stack([catmull(np.eye(K)[k], t) for k in range(K)])


def head_frame(h, elev):
    """World-space frame of a head: rear point, unit axis, unit up, length (world y = -image y / cos e)."""
    w = lambda p: np.array([p[0], -p[1] / np.cos(elev), 0.0])
    R0, Tp = w(h["rear"]), w(h["tip"])
    d = Tp - R0; Lh = np.linalg.norm(d); d = d / Lh
    n = np.array([-d[1], d[0], 0.0])
    if n[1] < 0: n = -n
    return R0, d, n, Lh


def head_profiles(h, t):
    s = np.sqrt(np.clip(t * (1 - t), 0, None))
    u = catmull(h["U"], t) * s; l = -catmull(h["Lo"], t) * s; rz = catmull(h["D"], t) * s
    return u, l, rz


def head_distance(h, elev, P):
    """Distance estimate to the head surface (negative inside), for points P (m, 3)."""
    R0, d, n, Lh = head_frame(h, elev)
    rel = P - R0
    t = (rel @ d) / Lh; v = rel @ n; z = P[:, 2]
    u, l, rz = head_profiles(h, t)
    m = l + h["beta"] * (u - l)
    hu, hl = np.maximum(u - m, 1e-6), np.maximum(m - l, 1e-6)
    hv = np.where(v >= m, hu, hl)
    q = h["q"]
    rho = ((np.abs(v - m) / hv) ** q + (np.abs(z) / np.maximum(rz, 1e-6)) ** q) ** (1 / q)
    # one scale above and below the cheek line, so the field is smooth across it ("split" is
    # the earlier, kinked version)
    scale = np.minimum(hv, rz) if h.get("field_scale") == "split" else np.minimum(rz, 0.5 * (u - l))
    dist = (rho - 1) * scale
    tipw, rearw = R0 + d * Lh, R0
    dist = np.where(t >= 1, np.linalg.norm(P - tipw, axis=1), dist)
    dist = np.where(t <= 0, np.linalg.norm(P - rearw, axis=1), dist)
    return dist


def quintic(P0, V0, A0, A1, V1, P1, tau):
    t = np.asarray(tau, float)[:, None]
    h0 = 1 - 10 * t**3 + 15 * t**4 - 6 * t**5
    h1 = t - 6 * t**3 + 8 * t**4 - 3 * t**5
    h2 = 0.5 * t**2 - 1.5 * t**3 + 1.5 * t**4 - 0.5 * t**5
    h3 = 0.5 * t**3 - t**4 + 0.5 * t**5
    h4 = -4 * t**3 + 7 * t**4 - 3 * t**5
    h5 = 10 * t**3 - 15 * t**4 + 6 * t**5
    return h0 * P0 + h1 * V0 + h2 * A0 + h3 * A1 + h4 * V1 + h5 * P1


def strand_at(pts, d, at):
    """Position, unit tangent (towards larger d) and curvature vector of a strand at arc d = at."""
    order = np.argsort(d); D = d[order]; P = pts[order]
    sl = np.r_[0, np.cumsum(np.linalg.norm(np.diff(P, axis=0), axis=1))]
    s0 = np.interp(at, D, sl)
    S = s0 + np.array([-12.0, -6.0, 0.0, 6.0, 12.0])
    Q = np.column_stack([np.interp(S, sl, P[:, k]) for k in range(3)])
    T = (Q[3] - Q[1]) / 12.0; T1 = (Q[4] - Q[2]) / 12.0; T0 = (Q[2] - Q[0]) / 12.0
    tn = T / np.linalg.norm(T)
    K = (T1 / np.linalg.norm(T1) - T0 / np.linalg.norm(T0)) / 12.0
    return Q[2], tn, K


def neck_curve(nk, h, elev, J, TJ, KJ, rJ, n=80):
    """Centreline samples (n, 3) and radii (n,) of a neck."""
    R0, d, nu, Lh = head_frame(h, elev)
    Q = R0 + d * nk["tQ"] * Lh + nu * nk["vQ"]
    ang = np.radians(nk["angQ"])  # direction out of the head, in the head's (axis, up) plane
    dQ = np.cos(ang) * d + np.sin(ang) * nu
    tau = np.linspace(0, 1, n)
    C = quintic(Q, nk["alpha"] * dQ, np.zeros(3), nk["beta"] ** 2 * KJ, nk["beta"] * TJ, J, tau)
    e = np.clip((tau - nk["tau_a"]) / (1 - nk["tau_a"]), 0, 1); e = e * e * (3 - 2 * e)
    r = nk["r_top"] + (rJ - nk["r_top"]) * e - nk.get("waist", 0.0) * np.sin(np.pi * tau) ** 2
    # waist_back (geometry.js neckCurve): the share of the waist taken off the back of the neck
    wb = nk.get("waist_back", 0.0)
    if wb and nk.get("waist"):
        T = np.gradient(C, axis=0)
        nb = np.c_[-T[:, 1], T[:, 0], np.zeros(len(T))]; nb /= np.linalg.norm(nb, axis=1)[:, None]
        nb *= np.where(nb @ d > 0, -1.0, 1.0)[:, None]
        f0, f1 = nk.get("waist_back_fade", (0.35, 0.6))
        f = np.clip((tau - f0) / (f1 - f0), 0, 1); f = f * f * (3 - 2 * f)
        h2 = 0.5 * wb * nk["waist"] * np.sin(np.pi * tau) ** 2 * (1 - f)
        C = C + h2[:, None] * nb; r = r + h2
    return C, r


def head_distance_meridian(h, elev, P, coarse=64, refine=10):
    """Distance to the swept head surface, measured in each point's meridian plane: for each
    station t' along the axis, the distance from the point to the section boundary along the
    ray from that section's centre, combined with the axial offset; the minimum over t'. Exact
    for circular sections; for the superelliptic ones, the ray stands in for the normal, which
    is close near the surface. Unlike the base estimate it stays a distance (gradient ~1) at the
    poles and the rear cap. Sign from the base field (the zero set is the same)."""
    R0, d, n, Lh = head_frame(h, elev)
    rel = P - R0
    t0 = (rel @ d) / Lh; v = rel @ n; z = P[:, 2]
    q = h["q"]
    def dist_at(tp):
        u, l, rz = head_profiles(h, tp)
        m = l + h["beta"] * (u - l); hu, hl = np.maximum(u - m, 1e-9), np.maximum(m - l, 1e-9)
        dv = v - m; rho = np.hypot(dv, z)
        c = np.abs(dv) / np.maximum(rho, 1e-12); sn = np.abs(z) / np.maximum(rho, 1e-12)
        hv = np.where(dv >= 0, hu, hl)
        Rr = 1 / np.maximum(((c / hv) ** q + (sn / np.maximum(rz, 1e-9)) ** q) ** (1 / q), 1e-12)
        return np.hypot((tp - t0) * Lh, np.maximum(rho - Rr, 0.0)), rho - Rr
    # coarse search over stations clustered towards both ends, then golden-section refinement
    sg = np.linspace(0, 1, coarse); grid = (1 - np.cos(np.pi * sg)) / 2
    best = np.full(len(P), np.inf); bi = np.zeros(len(P), int)
    for i, tp in enumerate(grid):
        dd, _ = dist_at(np.full(len(P), tp))
        better = dd < best; best[better] = dd[better]; bi[better] = i
    lo = grid[np.maximum(bi - 1, 0)]; hi = grid[np.minimum(bi + 1, coarse - 1)]
    gr = (np.sqrt(5) - 1) / 2
    a, b = lo.copy(), hi.copy()
    c1 = b - gr * (b - a); c2 = a + gr * (b - a)
    f1, _ = dist_at(c1); f2, _ = dist_at(c2)
    for _ in range(refine):
        left = f1 < f2
        b = np.where(left, c2, b); a = np.where(left, a, c1)
        c2n = np.where(left, c1, a + gr * (b - a)); c1n = np.where(left, b - gr * (b - a), c2)
        c1, c2 = c1n, c2n
        f1, _ = dist_at(c1); f2, _ = dist_at(c2)
    tb = (a + b) / 2
    dout, _ = dist_at(tb)
    # inside: the depth below the nearest section boundary (the outside formula is 0 there)
    base = head_distance(h, elev, P)
    inside = base < 0
    if inside.any():
        # for inside points, the distance to the boundary is the smaller of the radial gap at
        # their own station and the distance to the boundary at nearby stations
        din = np.full(len(P), np.inf)
        for tp in np.linspace(0, 1, 161)[1:-1]:
            _, gap = dist_at(np.full(len(P), tp))
            u, l, rz = head_profiles(h, np.full(len(P), tp))
            # distance from an inside point to section tp's boundary curve, in the meridian plane
            din = np.minimum(din, np.hypot((tp - t0) * Lh, np.minimum(-gap, 1e9)) if False else np.where(gap < 0, np.hypot((tp - t0) * Lh, gap), np.hypot((tp - t0) * Lh, gap)))
        dout = np.where(inside, -din, dout)
    return dout


def head_distance_sections(h, elev, P, band=None, coarse=9, refine=8):
    """Distance to the swept head as the union of its planar sections: for each point, the
    minimum over stations t' of sqrt(axial offset^2 + in-plane distance to section t'^2). That
    is exact for any section shape; the one approximation is the in-plane distance, taken along
    the ray from the section's centre and corrected to first order by the boundary normal there
    (exact on the boundary, second-order error off it). The search is bracketed around the
    point's own station (wider beyond the ends). Points with |base| > band keep the base value.
    Sign from the base field, so the zero set is unchanged."""
    R0, d, n, Lh = head_frame(h, elev)
    base = head_distance(h, elev, P)
    out = base.copy()
    sel = np.ones(len(P), bool) if band is None else np.abs(base) < band
    if not sel.any(): return out
    Q = P[sel]; inside = base[sel] < 0
    rel = Q - R0
    t0 = (rel @ d) / Lh; v = rel @ n; z = Q[:, 2]
    q = h["q"]
    w = ((band if band is not None else 40.0) + 8.0) / Lh
    def sec(tp):
        u, l, rz = head_profiles(h, tp)
        m = l + h["beta"] * (u - l); hu, hl = np.maximum(u - m, 1e-9), np.maximum(m - l, 1e-9); rz = np.maximum(rz, 1e-9)
        dv = v - m; rho = np.maximum(np.hypot(dv, z), 1e-12)
        c, s_ = dv / rho, z / rho
        hv = np.where(dv >= 0, hu, hl)
        Rr = 1 / ((np.abs(c) / hv) ** q + (np.abs(s_) / rz) ** q) ** (1 / q)
        a_, b_ = Rr * c, Rr * s_
        gn = np.column_stack([np.sign(a_) * np.abs(a_ / hv) ** (q - 1) / hv, np.sign(b_) * np.abs(b_ / rz) ** (q - 1) / rz])
        gn /= np.maximum(np.linalg.norm(gn, axis=1, keepdims=True), 1e-12)
        cosa = np.clip(np.abs(c * gn[:, 0] + s_ * gn[:, 1]), 0.05, 1)
        gap = (rho - Rr) * cosa
        ax = (tp - t0) * Lh
        return np.where(inside, np.hypot(ax, gap), np.hypot(ax, np.maximum(gap, 0)))
    lo = np.clip(t0 - w, 0, 1); hi = np.clip(t0 + w, 0, 1)
    lo = np.where(t0 > 1, 1 - w, lo); hi = np.where(t0 < 0, w, hi)
    lo, hi = np.minimum(lo, hi - 1e-6), np.maximum(hi, lo + 1e-6)
    best = np.full(len(Q), np.inf); bt = np.zeros(len(Q))
    for k in range(coarse):
        tp = lo + (hi - lo) * k / (coarse - 1)
        dd = sec(tp); better = dd < best; best[better] = dd[better]; bt[better] = tp[better]
    step = (hi - lo) / (coarse - 1)
    a, b = np.clip(bt - step, 0, 1), np.clip(bt + step, 0, 1)
    gr = (np.sqrt(5) - 1) / 2
    c1 = b - gr * (b - a); c2 = a + gr * (b - a); f1 = sec(c1); f2 = sec(c2)
    for _ in range(refine):
        left = f1 < f2
        b = np.where(left, c2, b); a = np.where(left, a, c1)
        nc1 = np.where(left, b - gr * (b - a), c2); nc2 = np.where(left, c1, a + gr * (b - a))
        f1n = np.where(left, sec(nc1), f2); f2n = np.where(left, f1, sec(nc2))
        c1, c2, f1, f2 = nc1, nc2, f1n, f2n
    dist = np.minimum(np.minimum(f1, f2), best)
    out[sel] = np.where(inside, -dist, dist)
    return out
