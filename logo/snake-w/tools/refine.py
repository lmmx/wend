"""Powell on a few named parameters of a model; writes json and overlay. Fast iterations."""
import json, sys
import numpy as np
from scipy import optimize
sys.path.insert(0, __file__.rsplit("/", 1)[0])
import snakefit as sf

start, out, free = sys.argv[1], sys.argv[2], sys.argv[3].split(",")
maxfev = int(sys.argv[4]) if len(sys.argv) > 4 else 300
init = json.loads(sys.argv[5]) if len(sys.argv) > 5 else {}
p = json.load(open(start)); p.update(init)
small, full = sf.ref_labels("ref/reference.png", sf.SCALE)
pen = json.loads(sys.argv[6]) if len(sys.argv) > 6 else None
loss = sf.Loss(small, sf.SCALE, pen=pen)
best = [loss(p), p]; print("start", round(best[0], 3), flush=True)
def f(v):
    q = sf.unpack(v, p, free)
    if q["a"] <= 5 or q["R"] <= 5: return 1e6
    L = loss(q)
    if L < best[0]: best[0], best[1] = L, q
    return L
optimize.minimize(f, sf.pack(p, free), method="Powell", options={"maxfev": maxfev, "xtol": 0.05, "ftol": 1e-4})
print("end", round(best[0], 3))
q = best[1]
json.dump(q, open(out + ".json", "w"), indent=1)
if pen: loss.penalty(q, report=True); print("label loss", round(sf.Loss(small, sf.SCALE)(q), 3))
print(json.dumps({k: q[k] for k in free if k in q}, default=float)[:600], "elev", round(q["cam"]["elev"], 2))
sf.overlay(q, full, out + ".png")
