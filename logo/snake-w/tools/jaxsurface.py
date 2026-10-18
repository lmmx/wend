"""The swept strand surface and its fairness, in JAX (x64), differentiable end to end.

A strand is a centreline P(s) and a radius r(s), both linear in their spline control values
(P = B @ ctrl, r = Br @ rc, with fixed basis matrices). The surface is built the way the
scene builds it: rotation-minimising frames along P (double reflection, Wang et al. 2008, as a
lax.scan) and rings S[i, j] = P[i] + r[i] (cos phi_j N[i] + sin phi_j Bn[i]).

Fairness is measured on that evaluated surface, not on the centreline, and does not depend
on how the samples are spaced (they need not be uniform in arc length, and won't be while
control points move). On each longitudinal surface line X_i, with edges e_i = X_{i+1} - X_i,
lengths l_i and unit tangents t_i, the discrete curvature vector at a vertex is
k_i = (t_i - t_{i-1}) / ((l_{i-1} + l_i) / 2), and
  bend    sum |k_i|^2 * ds_i over all lines, per unit length (bending energy)
  jerk    sum |(k_{i+1} - k_i) / ds|^2 * ds (how fast the bending changes: kinks, abrupt bulges)
  fold    a barrier on each surface line's advance relative to the centreline's, a ratio of
          lengths (~ 1 - r kappa cos(phi - phi_kappa)): below `fold_min` the tube is about to
          pass through itself on the inside of a bend
  spread  the variance of the centreline's own sample spacing, relative to its mean (keeps a
          moving spline's samples from bunching; a regulariser on the parameterisation)

Sections may be elliptical (`sec` = (n, 3): ql, qd, psi per sample, with `view` the unit vector
towards the camera): the section's depth axis d is the view direction made perpendicular to the
tangent, its lateral axis l = T x d lies in the screen plane, and the circle of radius r becomes
the ellipse with semi-axes r ql and r qd about (l, d) turned by psi. So ql alone sets the visible
width of the tube and qd its thickness towards the camera. Where the tangent nearly points at the
camera (|d| small) the section blends back to a circle. The scene's tube (geometry.js
strandSurface, `sec`) applies the same map to the same rings.
"""
import jax
import jax.numpy as jnp
jax.config.update("jax_enable_x64", True)


def rmf(P):
    """Tangents and rotation-minimising normals/binormals along a polyline (n, 3)."""
    T = jnp.gradient(P, axis=0); T = T / jnp.linalg.norm(T, axis=1, keepdims=True)
    t0 = T[0]
    ref = jnp.where(jnp.abs(t0[1]) < 0.9, jnp.array([0.0, 1.0, 0.0]), jnp.array([1.0, 0.0, 0.0]))
    r0 = ref - t0 * (ref @ t0); r0 = r0 / jnp.linalg.norm(r0)
    def step(r, k):
        v1 = P[k + 1] - P[k]; c1 = v1 @ v1
        rL = r - (2 / c1) * (v1 @ r) * v1
        tL = T[k] - (2 / c1) * (v1 @ T[k]) * v1
        v2 = T[k + 1] - tL; c2 = v2 @ v2
        rn = rL - (2 / jnp.maximum(c2, 1e-18)) * (v2 @ rL) * v2
        rn = rn / jnp.linalg.norm(rn)
        return rn, rn
    _, rs = jax.lax.scan(step, r0, jnp.arange(P.shape[0] - 1))
    N = jnp.vstack([r0[None], rs]); Bn = jnp.cross(T, N)
    return T, N, Bn


def smoothstep(e0, e1, x):
    t = jnp.clip((x - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3 - 2 * t)


def ellipse(T, dirs, sec, view):
    """Map unit circle directions dirs (n, k, 3), perpendicular to T (n, 3), to the elliptical section."""
    d = view[None] - T * (T @ view)[:, None]
    dn = jnp.linalg.norm(d, axis=1)
    lev = smoothstep(0.2, 0.45, dn)
    d = d / jnp.maximum(dn, 1e-9)[:, None]
    l = jnp.cross(T, d)
    ql, qd, psi = 1 + lev * (sec[:, 0] - 1), 1 + lev * (sec[:, 1] - 1), lev * sec[:, 2]
    c, s = jnp.cos(psi)[:, None], jnp.sin(psi)[:, None]
    a1, a2 = c * l + s * d, -s * l + c * d
    c1, c2 = jnp.einsum("nkj,nj->nk", dirs, a1), jnp.einsum("nkj,nj->nk", dirs, a2)
    return (c1 * ql[:, None])[..., None] * a1[:, None] + (c2 * qd[:, None])[..., None] * a2[:, None]


def rings(P, r, nphi=24, sec=None, view=None):
    T, N, Bn = rmf(P)
    phi = jnp.linspace(0, 2 * jnp.pi, nphi, endpoint=False)
    dirs = jnp.cos(phi)[None, :, None] * N[:, None] + jnp.sin(phi)[None, :, None] * Bn[:, None]
    if sec is not None:
        dirs = ellipse(T, dirs, sec, view)
    return P[:, None] + r[:, None, None] * dirs, T


def fairness(P, r, nphi=24, fold_min=0.25, sec=None, view=None):
    """Fairness terms of the swept surface for centreline samples P (n, 3) and radii r (n,)."""
    S, T = rings(P, r, nphi, sec, view)                                       # (n, nphi, 3)
    e = S[1:] - S[:-1]
    l = jnp.linalg.norm(e, axis=-1)
    t = e / l[..., None]
    ds = 0.5 * (l[1:] + l[:-1])                                    # per interior vertex
    k = (t[1:] - t[:-1]) / ds[..., None]
    total = jnp.sum(l, axis=0)                                     # length of each surface line
    bend = jnp.mean(jnp.sum(jnp.sum(k ** 2, -1) * ds, axis=0) / total)
    dsk = 0.5 * (ds[1:] + ds[:-1])
    jerk = jnp.mean(jnp.sum(jnp.sum(((k[1:] - k[:-1]) / dsk[..., None]) ** 2, -1) * dsk, axis=0) / total)
    adv = jnp.einsum("ijk,ik->ij", e, T[:-1])
    cl = jnp.linalg.norm(P[1:] - P[:-1], axis=1)
    j = adv / cl[:, None]
    fold = jnp.mean(jax.nn.softplus((fold_min - j) * 20.0) / 20.0) * 100
    spread = jnp.var(cl) / jnp.mean(cl) ** 2
    return dict(bend=bend, jerk=jerk, fold=fold, spread=spread, jmin=jnp.min(j))


if __name__ == "__main__":
    import numpy as np
    from scipy.interpolate import BSpline
    rng = np.random.default_rng(0)
    K = 24
    kn = np.r_[[0] * 3, np.linspace(0, 1, K - 2), [1] * 3]
    ctrl = np.column_stack([np.linspace(0, 600, K), 80 * np.sin(np.linspace(0, 6, K)), 30 * np.cos(np.linspace(0, 9, K))]) + rng.normal(size=(K, 3))
    rc = 40 + 3 * rng.normal(size=K)
    def at(tt):
        B = jnp.asarray(BSpline.design_matrix(tt, kn, 3).toarray())
        return B
    # 1. gradients against central differences
    B = at(np.linspace(0, 1, 600))
    def loss(c, q):
        f = fairness(B @ c, B @ q)
        return f["bend"] * 1e3 + f["jerk"] * 1e5 + f["fold"] + f["spread"]
    c0, q0 = jnp.asarray(ctrl), jnp.asarray(rc)
    g_c, g_r = jax.grad(loss, argnums=(0, 1))(c0, q0)
    v = rng.normal(size=ctrl.shape); w = rng.normal(size=rc.shape); eps = 1e-4
    fd = (loss(c0 + eps * v, q0 + eps * w) - loss(c0 - eps * v, q0 - eps * w)) / (2 * eps)
    ad = jnp.sum(g_c * v) + jnp.sum(g_r * w)
    print(f"gradient: autodiff {float(ad):.8e}  finite difference {float(fd):.8e}  rel err {abs(float(ad - fd)) / abs(float(fd)):.1e}")
    # 2. the same surface sampled uniformly and very non-uniformly in the spline parameter
    u = np.linspace(0, 1, 600)
    warped = u + 0.08 * np.sin(2 * np.pi * u) / (2 * np.pi) * 6 * (u * (1 - u))   # monotone, uneven spacing
    warped = (warped - warped[0]) / (warped[-1] - warped[0])
    for name, tt in (("uniform", u), ("warped", warped)):
        Bt = at(tt); f = fairness(Bt @ c0, Bt @ q0)
        print(f"{name:8s} spacing cv {float(jnp.sqrt(f['spread'])):.3f}  bend {float(f['bend']):.6e}  jerk {float(f['jerk']):.6e}  jmin {float(f['jmin']):.3f}")
