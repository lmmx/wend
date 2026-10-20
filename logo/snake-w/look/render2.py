"""render looks at 2x supersampling, then the look's softness, and sample their tones
usage: look/render2.py OUT_DIR name=look.json ..."""

import colorsys
import json
import os
import sys


sys.path.insert(0, "tools")
import lobekit as K
import lookfit as L
import numpy as np
from PIL import Image
from scipy import ndimage


out = sys.argv[1]
os.makedirs(out, exist_ok=True)
w = L.Worker(ss="2")


def tones(im):
    Lb = K.lobes(im)
    lum = (im.astype(float) * [0.2126, 0.7152, 0.0722]).sum(-1)
    res = []
    for col in ("yellow", "blue"):
        inner = ndimage.binary_erosion(np.asarray(Lb[col], bool), iterations=4)
        li = lum[inner]
        row = []
        for lo, hi in ((0, 10), (45, 55), (88, 92), (99, 99.7)):
            a, b = np.percentile(li, [lo, hi])
            m = inner & (lum >= a) & (lum <= b)
            c = im[m].reshape(-1, 3).mean(0)
            h, s, v = colorsys.rgb_to_hsv(*(c / 255))
            row.append(
                f"#{int(c[0]):02x}{int(c[1]):02x}{int(c[2]):02x} h{h * 360:.0f} s{s:.2f} v{v:.2f}"
            )
        res.append(f"{col[0]}: " + " | ".join(row))
    return "  ".join(res)


try:
    for it in sys.argv[2:]:
        n, p = it.split("=")
        lk = json.load(open(p))
        w.render(lk, os.path.abspath(f"{out}/{n}-ss2.png"))
        im = np.asarray(
            Image.open(f"{out}/{n}-ss2.png")
            .convert("RGB")
            .resize((1448, 1086), Image.LANCZOS)
        )
        im = L.blur(im, lk.get("softness", 0))
        Image.fromarray(im).save(f"{out}/{n}.png")
        print(n, tones(im), flush=True)
finally:
    w.close()
print("ref", tones(np.asarray(Image.open("snakes/ref/reference.png").convert("RGB"))))
