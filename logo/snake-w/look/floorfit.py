"""fit the floor's shadow card (lookfit.FLOOR_SPACE) on a look, against the reference's floor
usage: LOOK_SCALE=0.5 look/floorfit.py LOOK.json OUT_DIR [gens]"""

import json
import os
import sys

import numpy as np
from PIL import Image


sys.path.insert(0, "tools")
import lookfit as L
from lobefit import cma


look0, out = json.load(open(sys.argv[1])), os.path.abspath(sys.argv[2])
gens = int(sys.argv[3]) if len(sys.argv) > 3 else 25
os.makedirs(out, exist_ok=True)
base = json.load(open("snakes/w-final.look.json"))
sc0 = {**base["shadowCard"], **look0.get("shadowCard", {})}


def get(sc, p):
    k = p.split(".")[1:]
    if k[0] == "colour":
        return sc["colour"]["rgb".index(k[1])]
    if k[0] == "bounce":
        return (sc.get("bounce") or {}).get(
            k[1], {"k": 0.0, "fall": 40, "blur": 12}[k[1]]
        )
    return sc[k[0]]


u0 = np.array([(get(sc0, p) - lo) / (hi - lo) for p, lo, hi in L.FLOOR_SPACE]).clip(
    0, 1
)


def card(u):
    sc = json.loads(json.dumps(sc0))
    sc["colour"] = list(sc["colour"])
    sc["bounce"] = dict(sc.get("bounce") or {})
    for (p, lo, hi), x in zip(L.FLOOR_SPACE, u):
        v = lo + float(np.clip(x, 0, 1)) * (hi - lo)
        k = p.split(".")[1:]
        if k[0] == "colour":
            sc["colour"]["rgb".index(k[1])] = v
        elif k[0] == "bounce":
            sc["bounce"][k[1]] = v
        else:
            sc[k[0]] = v
    return sc


ws = [L.Worker() for _ in range(3)]
best = [np.inf]


def f(u, wk):
    lk = dict(look0, shadowCard=card(u))
    raw = f"{out}/w{wk}.png"
    ws[wk].render(lk, raw)
    im = L.blur(
        np.asarray(Image.open(raw).convert("RGB")), lk.get("softness", 0) * L.SCALE
    )
    t, p = L.floor_score(im)
    if t < best[0]:
        best[0] = t
        json.dump(dict(loss=t, look=lk), open(f"{out}/best.json", "w"), indent=1)
    return (t, p)


try:
    print("start", f(u0, 0)[0], flush=True)
    cma(
        f,
        len(u0),
        0.2,
        np.zeros(len(u0)),
        np.ones(len(u0)),
        gens,
        3,
        seed=8,
        log=lambda g, b, F, s: print(
            f"gen {g} best {b[0] if isinstance(b, tuple) else b:.3f} sigma {s:.3f}",
            flush=True,
        ),
        m0=u0,
    )
finally:
    [w.close() for w in ws]
print("best", best[0])
