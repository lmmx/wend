"""Pages for the blind visual critic: one candidate against the reference, at identical framing.
  page 0   whole frame: reference | candidate colour | candidate clay | candidate zebra |
           candidate colour with the reference silhouette outlined (cyan)
  page 1.. six registry features per page, one row each: reference crop | candidate colour |
           candidate clay | candidate zebra | candidate colour with the reference feature
           outlined (cyan). Every crop is the feature's fixed registry window.
The pages carry only the feature IDs and column names: no metrics, no history, no candidate name.
Usage (from the logo root): critic_pages.py RENDERS_DIR TAG OUT_DIR"""
import json, os, sys
import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage
from skimage import segmentation, morphology
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from evaluate import window, load_registry

rd, tag, out = sys.argv[1], sys.argv[2], sys.argv[3]
os.makedirs(out, exist_ok=True)
reg, lab, neg = load_registry()
ref = Image.open("snakes/ref/reference.png").convert("RGB")
col = Image.open(f"{rd}/{tag}-colour.png").convert("RGB")
TH = 250
COLS = ["reference", "candidate colour", "candidate clay", "candidate zebra", "candidate + reference outline (cyan)"]


def fit(im, h=TH, wmax=330):
    w = round(im.width * h / im.height)
    if w > wmax:
        h = round(h * wmax / w); w = wmax
    return im.resize((w, h), Image.LANCZOS)


def outlined(im_crop, mask_crop):
    a = np.asarray(im_crop).copy()
    b = morphology.dilation(segmentation.find_boundaries(mask_crop, mode="inner"), morphology.disk(1))
    a[b] = (0, 230, 255)
    return Image.fromarray(a)


def page(rows, title, path):
    widths = [max(r[1][k].width for r in rows) for k in range(5)]
    H = 34 + sum(max(t.height for t in r[1]) + 24 for r in rows) + 20
    W = sum(widths) + 6 * 6 + 60
    pg = Image.new("RGB", (W, H), (236, 236, 236)); d = ImageDraw.Draw(pg)
    d.text((8, 8), title, fill=(0, 0, 0))
    x = 60
    for k, c in enumerate(COLS):
        d.text((x + 2, 22), c, fill=(60, 60, 60)); x += widths[k] + 6
    y = 40
    for fid, tiles in rows:
        d.text((8, y + 8), fid, fill=(0, 0, 0))
        x = 60
        for k, t in enumerate(tiles):
            pg.paste(t, (x, y)); x += widths[k] + 6
        y += max(t.height for t in tiles) + 24
    pg.save(path)


# page 0: the whole frame
B = (150, 90, 1300, 1010)
sil = ndimage.binary_fill_holes(morphology.closing(lab > 0, morphology.disk(4)))
g0 = [fit(ref.crop(B), 300, 380), fit(col.crop(B), 300, 380)]
for m in ("clay", "zebra"):
    im = Image.open(f"{rd}/{tag}-{m}-full.png").convert("RGB")
    if im.width != 1448:
        im = im.resize((1448, 1086), Image.LANCZOS)
    g0.append(fit(im.crop(B), 300, 380))
g0.append(fit(outlined(col.crop(B), sil[B[1]:B[3], B[0]:B[2]]), 300, 380))
page([("whole", g0)], "whole frame", f"{out}/page0-whole.png")
feats = reg["features"]
for p in range(0, len(feats), 6):
    rows = []
    for i in range(p, min(p + 6, len(feats))):
        f = feats[i]
        x0, y0, x1, y1 = window(f, 30)
        tiles = [fit(ref.crop((x0, y0, x1, y1))), fit(col.crop((x0, y0, x1, y1)))]
        for m in ("clay", "zebra"):
            tiles.append(fit(Image.open(f"{rd}/{tag}-{m}-{f['id']}.png").convert("RGB")))
        tiles.append(fit(outlined(col.crop((x0, y0, x1, y1)), lab[y0:y1, x0:x1] == i + 1)))
        rows.append((f["id"], tiles))
    page(rows, f"features {feats[p]['id']} .. {feats[min(p + 5, len(feats) - 1)]['id']}", f"{out}/page{p // 6 + 1}-{feats[p]['id']}-{feats[min(p + 5, len(feats) - 1)]['id']}.png")
print("pages in", out)
