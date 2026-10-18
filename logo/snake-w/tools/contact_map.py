"""Where does the spline body pass through itself? For every pair of centreline samples
(both strands, station step 2 px) the overlap r_i + r_j - |X_i - X_j|, as a function of how far
apart the pair is along the rope: same strand -> own arc distance; across strands -> shared
station distance. Prints the overlap profile by separation (to pick the 'different turn'
threshold) and the worst different-turn contacts with their image positions.
Usage: contact_map.py spec.json [box x0,y0,x1,y1]"""
import json, sys, os
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import strandspline as S

spec = json.load(open(sys.argv[1])); L = spec["L"]
elev = np.radians(3.7746862033886837)
pts, rad, sid, sta, arc = [], [], [], [], []
for k, name in enumerate(("yellow", "blue")):
    st = spec[name]
    u = np.arange(st["s0"], st["s1"], 2.0)
    X, r = S.evaluate(st, u)
    a = np.r_[0, np.cumsum(np.linalg.norm(np.diff(X, axis=0), axis=1))]
    pts.append(X); rad.append(r); sid.append(np.full(len(u), k)); sta.append(u if k == 0 else L - u); arc.append(a)
P, R, I, Sh, A = map(np.concatenate, (pts, rad, sid, sta, arc))
D = np.linalg.norm(P[:, None] - P[None], axis=-1)
ov = R[:, None] + R[None] - D
same = I[:, None] == I[None]
sep = np.where(same, np.abs(A[:, None] - A[None]), np.abs(Sh[:, None] - Sh[None]))
print("max overlap by separation (px along the rope); same strand | across strands")
for lo in range(0, 400, 20):
    m = (sep >= lo) & (sep < lo + 20)
    a = ov[m & same]; b = ov[m & ~same]
    print(f"  {lo:3d}-{lo+20:3d}: same p50 {np.median(a):7.1f} max {a.max():7.1f}   across p50 {np.median(b):7.1f} max {b.max():7.1f}")
x = P[:, 0]; yimg = -(P[:, 1] * np.cos(elev) - P[:, 2] * np.sin(elev)); z = P[:, 1] * np.sin(elev) + P[:, 2] * np.cos(elev)
np.savez(os.path.join(os.path.dirname(sys.argv[1]) or ".", "contact_map.npz"), P=P, R=R, I=I, Sh=Sh, A=A, x=x, y=yimg, z=z)
for thr_same, thr_across in ((150, 60), (200, 90)):
    bad = np.where(same, sep > thr_same, sep > thr_across) & (ov > 0)
    i, j = np.nonzero(np.triu(bad))
    print(f"\ndifferent-turn overlaps (same strand arc > {thr_same}, across station > {thr_across}): {len(i)} pairs")
    order = np.argsort(-ov[i, j])
    seen = []
    for o in order:
        a, b = i[o], j[o]
        if any(abs(x[a] - p) + abs(yimg[a] - q) < 30 for p, q in seen): continue
        seen.append((x[a], yimg[a]))
        print(f"  ov {ov[a,b]:5.1f}  {'YB'[I[a]]}@{Sh[a]:6.0f} img({x[a]:5.0f},{yimg[a]:5.0f}) z{z[a]:5.0f}  <->  {'YB'[I[b]]}@{Sh[b]:6.0f} img({x[b]:5.0f},{yimg[b]:5.0f}) z{z[b]:5.0f}  d {D[a,b]:5.1f} r {R[a]:4.1f}+{R[b]:4.1f}")
        if len(seen) >= 14: break
