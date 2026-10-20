"""matched crops of the reference and renders: colour row and luminance row per crop
usage: look/crops.py OUT.png render.png [render2.png ...]"""
import sys
import numpy as np
from PIL import Image, ImageDraw
import os
COLOUR_ONLY = os.environ.get("COLOUR_ONLY") == "1"
out, rens = sys.argv[1], sys.argv[2:]
ref = Image.open("snakes/ref/reference.png").convert("RGB")
ims = [ref] + [Image.open(r).convert("RGB").resize(ref.size, Image.LANCZOS) for r in rens]
crops = {"left arm": (300, 280, 560, 560), "left valley": (440, 520, 720, 800), "arch": (560, 380, 860, 640), "right valley": (800, 520, 1080, 800), "blue head": (980, 230, 1200, 450)}
if os.environ.get("CROPS"): crops = {k: v for k, v in crops.items() if k in os.environ["CROPS"].split(",")}
Z = 2; tiles = []
for name, b in crops.items():
    row = []
    for im in ims:
        c = im.crop(b); w, h = c.size
        c2 = c.resize((w * Z, h * Z), Image.LANCZOS)
        g = c2.convert("L").convert("RGB")
        row.append((c2, g))
    tiles.append((name, row))
w, h = tiles[0][1][0][0].size
n = len(ims); W = n * (w + 8) + 8
H = sum(2 * (t[1][0][0].size[1] + 8) + 22 for t in tiles)
S = Image.new("RGB", (max(W, 2 * W) + 2000, H), (230, 230, 230)); d = ImageDraw.Draw(S)
y = 4
for name, row in tiles:
    hh = row[0][0].size[1]; ww = row[0][0].size[0]
    d.text((8, y), name + ": reference | " + " | ".join(rens), fill=(0, 0, 0)); y += 16
    for i, (c, g) in enumerate(row):
        S.paste(c, (8 + i * (ww + 8), y))
        if not COLOUR_ONLY: S.paste(g, (8 + (n + i) * (ww + 8), y))
    y += hh + 12
S = S.crop((0, 0, 8 + (1 if COLOUR_ONLY else 2) * n * (ww + 8), y)); S.save(out); print(S.size)
