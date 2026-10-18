"""Twist-phase move: turn both strands together about the local spine, over a window of shared
stations, by w(s) * dtheta (w a smooth bump: 0 outside [s0, s1], rising to 1 over `ramp` px at
each end). The spine is the midpoint of the twist partners, C(s) = (Y(s) + B(L - s)) / 2; each
control point turns about the axis through C(s_i) along the spine's tangent at s_i, where s_i is
the control point's Greville station. Elliptical section fields are unchanged (their frame is
view-based). The result is a starting point for tools/regionfit.py, not a candidate by itself.
Usage (from the logo root): twist.py spec.json out.json s0 s1 dtheta_deg [ramp]"""
import copy, json, os, sys
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import strandspline as S


def smoothstep(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0, 1)
    return t * t * (3 - 2 * t)


def rodrigues(v, k, a):
    return v * np.cos(a) + np.cross(k, v) * np.sin(a) + k * (k @ v) * (1 - np.cos(a))


def main():
    src, out, s0, s1, deg = sys.argv[1], sys.argv[2], float(sys.argv[3]), float(sys.argv[4]), float(sys.argv[5])
    ramp = float(sys.argv[6]) if len(sys.argv) > 6 else 50.0
    spec = json.load(open(src)); L = spec["L"]
    Y, B = spec["yellow"], spec["blue"]
    def spine(s):
        y, _ = S.evaluate(Y, np.clip(np.atleast_1d(s), Y["s0"], Y["s1"]))
        b, _ = S.evaluate(B, np.clip(L - np.atleast_1d(s), B["s0"], B["s1"]))
        return 0.5 * (y + b)
    w = lambda s: smoothstep(s0, s0 + ramp, s) * (1 - smoothstep(s1 - ramp, s1, s))
    res = copy.deepcopy(spec)
    for name, st in (("yellow", Y), ("blue", B)):
        t = S.knots(st["s0"], st["s1"], st["nseg"])
        c = np.asarray(st["ctrl"], float)
        moved = 0
        for i in range(len(c)):
            g = t[i + 1:i + 4].mean()                       # Greville abscissa (own station)
            sh = g if name == "yellow" else L - g
            wi = w(sh)
            if wi <= 0:
                continue
            C = spine(sh)[0]
            T = spine(sh + 2.0)[0] - spine(sh - 2.0)[0]; T /= np.linalg.norm(T)
            c[i] = C + rodrigues(c[i] - C, T, np.radians(deg) * wi)
            moved += 1
        res[name]["ctrl"] = c.tolist()
        print(f"{name}: {moved} control points turned")
    res.setdefault("twist", []).append(dict(s0=s0, s1=s1, deg=deg, ramp=ramp))
    json.dump(res, open(out, "w"))


if __name__ == "__main__":
    main()
