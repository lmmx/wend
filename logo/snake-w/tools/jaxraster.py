"""An occlusion-aware soft rasteriser of the two strands, in JAX.

Each strand is a dense chain of balls (centre, radius). For a pixel q and ball i (projected
with the scene's camera): coverage a_i = sigmoid((r_i - |q - c_i|) / tau), and the depth of
the ball's front surface z_i = d_i + sqrt(r_i^2 - |q - c_i|^2). The pixel is covered with
probability 1 - prod_i (1 - a_i) (a soft union), and its colour is a softmax over all balls of
sharp * log a_i + z_i / gamma: the nearest covering surface wins, smoothly. Every ball competes
with every other at each pixel, so two parts of the same strand overlapping at a tight bend
occlude each other correctly (unlike a per-station model).

`sharp` matters: with log a_i alone (sharp = 1), a ball that is nearer the camera but does
not cover the pixel can still win it, so colour bleeds past the edge of a nearer disc by
about dz * tau / gamma (some 20-40 px for strands 40 px apart in depth). With `sharp`, the
bleed is about dz * tau / (sharp * gamma); the hard z-buffer is the limit of that going to 0,
not of tau and gamma alone.
"""
import jax
import jax.numpy as jnp
jax.config.update("jax_enable_x64", True)


def project(P, elev):
    """Image coordinates (x right, y down, reference pixels) and depth towards the camera."""
    c, s = jnp.cos(elev), jnp.sin(elev)
    return P[:, 0], -(P[:, 1] * c - P[:, 2] * s), P[:, 1] * s + P[:, 2] * c


def soft_labels(P, r, onehot, grid, elev, tau=0.6, gamma=1.0, sharp=20.0):
    """P (m, 3) ball centres, r (m,), onehot (m, k) colour of each ball, grid (n, 2) pixel
    centres. Returns (n, k + 1) probabilities: background, then each colour."""
    x, y, d = project(P, elev)
    d2 = (grid[:, 0, None] - x[None]) ** 2 + (grid[:, 1, None] - y[None]) ** 2
    dist = jnp.sqrt(d2 + 1e-9)
    t = (r[None] - dist) / tau
    log_a, log_1ma = jax.nn.log_sigmoid(t), jax.nn.log_sigmoid(-t)
    zf = d[None] + jnp.sqrt(jnp.maximum(r[None] ** 2 - d2, 0.0) + 1e-6)
    w = jax.nn.softmax(sharp * log_a + zf / gamma, axis=1)         # which ball is seen
    covered = 1.0 - jnp.exp(jnp.sum(log_1ma, axis=1))              # soft union
    col = w @ onehot                                               # (n, k)
    return jnp.concatenate([(1.0 - covered)[:, None], covered[:, None] * col], axis=1)


def window_grid(box, step):
    x0, y0, x1, y1 = box
    xs, ys = jnp.meshgrid(jnp.arange(x0 + step / 2, x1, step), jnp.arange(y0 + step / 2, y1, step))
    return jnp.column_stack([xs.ravel(), ys.ravel()]), xs.shape


def balls_in_window(P, r, onehot, elev, box, margin=10.0):
    import numpy as np
    x, y, _ = (np.asarray(v) for v in project(jnp.asarray(P), elev))
    x0, y0, x1, y1 = box
    keep = (x + r > x0 - margin) & (x - r < x1 + margin) & (y + r > y0 - margin) & (y - r < y1 + margin)
    return P[keep], r[keep], onehot[keep]
