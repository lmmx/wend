"""The residual blue-on-blue collision: for the worst non-adjacent blue pairs, their screen and
depth separation, depth radii, and what lies directly behind / in front of each leg on screen."""
import json, sys
import numpy as np
sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.abspath(__file__)))
import strandspline as S
spec = json.load(open(sys.argv[1])); L = spec["L"]; e = np.radians(3.7746862033886837)
V = np.array([0, np.sin(e), np.cos(e)])
def sec_at(st, u):
    if "sec" not in st: return np.ones((len(u), 2))
    t = S.knots(st["s0"], st["s1"], st["sec"]["seg"]); B = S.basis(u, t)
    return np.column_stack([B @ np.asarray(st["sec"]["ql"]), B @ np.asarray(st["sec"]["qd"])])
D = {}
for n in ("yellow", "blue"):
    st = spec[n]; u = np.arange(st["s0"], st["s1"], 2.0); X, r = S.evaluate(st, u); q = sec_at(st, u)
    D[n] = dict(u=u, sh=u if n == "yellow" else L - u, X=X, r=r, a=r * q[:, 0], b=r * q[:, 1],
                x=X[:, 0], y=-(X[:, 1] * np.cos(e) - X[:, 2] * np.sin(e)), z=X @ V)
B = D["blue"]
m = (B["sh"] > 1000) & (B["sh"] < 1220)
idx = np.nonzero(m)[0]
best = []
for i in idx:
    for j in idx:
        if B["sh"][j] - B["sh"][i] < 90: continue
        dv = B["X"][i] - B["X"][j]; dz = dv @ V; ds = np.sqrt(max(dv @ dv - dz * dz, 0))
        sa, sb = B["a"][i] + B["a"][j], B["b"][i] + B["b"][j]; d = np.linalg.norm(dv)
        ov = sa * sb * d / np.sqrt(sb ** 2 * ds ** 2 + sa ** 2 * dz ** 2 + 1e-9) - d
        best.append((ov, i, j, ds, dz))
best.sort(reverse=True)
Y = D["yellow"]
for ov, i, j, ds, dz in best[:1] + [b for b in best if abs(B["sh"][b[1]] - B["sh"][best[0][1]]) > 15][:2]:
    need = (B["b"][i] + B["b"][j]) * np.sqrt(max(1 - (ds / (B["a"][i] + B["a"][j])) ** 2, 0))
    print(f"blue@{B['sh'][i]:.0f} vs blue@{B['sh'][j]:.0f}: overlap {ov:.1f} px; screen sep {ds:.1f}, depth sep {dz:+.1f}; "
          f"lateral radii {B['a'][i]:.0f}+{B['a'][j]:.0f}, depth radii {B['b'][i]:.0f}+{B['b'][j]:.0f}; depth sep needed {need:.0f} px")
    for k in (i, j):
        # yellow sections overlapping this blue section on screen: depth order and gap
        dq = np.hypot(Y["x"] - B["x"][k], Y["y"] - B["y"][k]); o = dq < 0.8 * (Y["a"] + B["a"][k])
        if o.any():
            zs = Y["z"][o] - B["z"][k]
            print(f"   blue@{B['sh'][k]:.0f} img ({B['x'][k]:.0f},{B['y'][k]:.0f}) z {B['z'][k]:.0f}: yellow on screen at stations {Y['sh'][o].min():.0f}..{Y['sh'][o].max():.0f}, "
                  f"depth rel. to blue {zs.min():+.0f}..{zs.max():+.0f} (behind < 0)")
