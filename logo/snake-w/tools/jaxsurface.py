"""The swept strand surface and its fairness, in JAX (x64), differentiable end to end.

A strand is a centreline P(s) and a radius r(s), both linear in their spline control values
(P = B @ ctrl, r = Br @ rc, with fixed basis matrices). The surface is built the way the
scene builds it: rotation-minimising frames along P (double reflection, Wang et al. 2008, as a
lax.scan) and rings S[i, j] = P[i] + r[i] (cos phi_j N[i] + sin phi_j Bn[i]).

Fairness is measured on that evaluated surface, not on the centreline:
  bend    mean |d2 S / ds2|^2 over all longitudinal surface lines (bending energy)
  jerk    mean |d3 S / ds3|^2 (how fast that bending changes: kinks, abrupt bulges)
  fold    a barrier on the ring-to-ring advance of each surface line relative to the
          centreline's, ~ 1 - r kappa cos(phi - phi_kappa): below `fold_min` the tube is about
          to pass through itself on the inside of a bend
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


def rings(P, r, nphi=24):
    T, N, Bn = rmf(P)
    phi = jnp.linspace(0, 2 * jnp.pi, nphi, endpoint=False)
    dirs = jnp.cos(phi)[None, :, None] * N[:, None] + jnp.sin(phi)[None, :, None] * Bn[:, None]
    return P[:, None] + r[:, None, None] * dirs, T


def fairness(P, r, h, nphi=24, fold_min=0.25):
    """Fairness terms of the swept surface for centreline samples P (n, 3) spaced ~h apart."""
    S, T = rings(P, r, nphi)
    d1 = (S[1:] - S[:-1]) / h
    d2 = (S[2:] - 2 * S[1:-1] + S[:-2]) / h ** 2
    d3 = (S[3:] - 3 * S[2:-1] + 3 * S[1:-2] - S[:-3]) / h ** 3
    adv = jnp.einsum("ijk,ik->ij", d1, T[:-1])                   # surface line advance / centreline advance (~1 - r kappa cos)
    cl = jnp.linalg.norm((P[1:] - P[:-1]) / h, axis=1)
    j = adv / cl[:, None]
    fold = jnp.mean(jax.nn.softplus((fold_min - j) * 20.0) / 20.0) * 100
    return dict(bend=jnp.mean(jnp.sum(d2 ** 2, -1)), jerk=jnp.mean(jnp.sum(d3 ** 2, -1)), fold=fold, jmin=jnp.min(j))


if __name__ == "__main__":
    # gradient check: JAX against central finite differences of the same function, x64
    import numpy as np
    from scipy.interpolate import BSpline
    rng = np.random.default_rng(0)
    n, K = 400, 24
    t = np.linspace(0, 1, n)
    kn = np.r_[[0] * 3, np.linspace(0, 1, K - 2), [1] * 3]
    B = BSpline.design_matrix(t, kn, 3).toarray()
    ctrl = np.column_stack([np.linspace(0, 600, K), 80 * np.sin(np.linspace(0, 6, K)), 30 * np.cos(np.linspace(0, 9, K))]) + rng.normal(size=(K, 3))
    rc = 40 + 3 * rng.normal(size=K)
    B, ctrl, rc = jnp.asarray(B), jnp.asarray(ctrl), jnp.asarray(rc)
    def loss(c, q):
        P = B @ c; rr = B @ q
        f = fairness(P, rr, 1.5)
        return f["bend"] + 0.1 * f["jerk"] + f["fold"]
    g_c, g_r = jax.grad(loss, argnums=(0, 1))(ctrl, rc)
    v = rng.normal(size=ctrl.shape); w = rng.normal(size=rc.shape)
    eps = 1e-4
    fd = (loss(ctrl + eps * v, rc + eps * w) - loss(ctrl - eps * v, rc - eps * w)) / (2 * eps)
    ad = jnp.sum(g_c * v) + jnp.sum(g_r * w)
    print(f"directional derivative: autodiff {float(ad):.8e}  finite difference {float(fd):.8e}  rel err {abs(float(ad - fd)) / abs(float(fd)):.2e}")
    f = fairness(B @ ctrl, B @ rc, 1.5); print({k: float(v_) for k, v_ in f.items()})
