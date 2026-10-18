"""Which strand, at which stations, makes the right-valley dimple? For each strand: samples
whose tube reaches the dimple pixels, with r kappa, speed, depth, and the curvature direction."""
import json, sys
import numpy as np
sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.abspath(__file__)))
import strandspline as S
spec = json.load(open(sys.argv[1])); L = spec["L"]; e = np.radians(3.7746862033886837)
c, s = np.cos(e), np.sin(e)
for name in ("yellow", "blue"):
    st = spec[name]; u = np.arange(st["s0"], st["s1"], 1.0)
    X, r = S.evaluate(st, u); k, sp = S.curvature(st, u)
    t = S.knots(st["s0"], st["s1"], st["nseg"]); C = np.asarray(st["ctrl"])
    d1 = S.basis(u, t, 1) @ C; d2 = S.basis(u, t, 2) @ C
    T = d1 / np.linalg.norm(d1, axis=1, keepdims=True)
    Kv = (d2 - T * (d2 * T).sum(1, keepdims=True)) / (sp ** 2)[:, None]       # curvature vector
    x, y, z = X[:, 0], -(X[:, 1] * c - X[:, 2] * s), X[:, 1] * s + X[:, 2] * c
    rk = r * k
    m = (np.hypot(x - 942, y - 720) < r + 5)
    print(f"\n{name}: rk>1 over {np.mean(rk > 1):.0%}, rk>2 over {np.mean(rk > 2):.0%}; max rk {rk.max():.1f} at own s {u[rk.argmax()]:.0f} (shared {u[rk.argmax()] if name == 'yellow' else L - u[rk.argmax()]:.0f})")
    for i in np.nonzero(m)[0][::4]:
        kd = Kv[i] / max(np.linalg.norm(Kv[i]), 1e-12)
        kimg = (kd[0], -(kd[1] * c - kd[2] * s), kd[1] * s + kd[2] * c)
        print(f"  own {u[i]:6.0f} shared {u[i] if name=='yellow' else L-u[i]:6.0f}  img ({x[i]:5.0f},{y[i]:5.0f}) z {z[i]:5.0f}  r {r[i]:4.1f}  rk {rk[i]:5.2f}  speed {sp[i]:.2f}  bend dir img ({kimg[0]:+.2f},{kimg[1]:+.2f}, z {kimg[2]:+.2f})")
