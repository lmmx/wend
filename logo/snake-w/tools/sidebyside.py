"""One side-by-side sheet for choosing between representations (for the people following the work,
not for the blind judge: it carries names): columns are the reference and each candidate, rows are
colour, clay and zebra over one region at identical framing (the union of the given features'
boxes), then the whole frame in colour. The reference has no clay or zebra: its rows show the
reference in greyscale (form from shading alone) and in colour again.
Usage (from the logo root): sidebyside.py OUT.png F1,F2,... DIR:TAG:LABEL [DIR:TAG:LABEL ...] [--scale S] [--title T]"""
import os, sys
import numpy as np
from PIL import Image, ImageDraw, ImageOps
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from evaluate import load_registry

argv = sys.argv[1:]
def opt(name, default):
    if name in argv:
        i = argv.index(name); v = argv[i + 1]; del argv[i:i + 2]; return v
    return default
scale = float(opt("--scale", "1.5")); title = opt("--title", "")
out, feats, cands = argv[0], argv[1].split(","), [a.split(":", 2) for a in argv[2:]]
reg, lab, _ = load_registry()
bb = np.array([f["bbox"] for f in reg["features"] if f["id"] in feats])
pad = 30
box = tuple(int(v) for v in (max(bb[:, 0].min() - pad, 0), max(bb[:, 1].min() - pad, 0), min(bb[:, 2].max() + pad, 1448), min(bb[:, 3].max() + pad, 1086)))
ref = Image.open("snakes/ref/reference.png").convert("RGB")


def crop(im):
    c = im.crop(box)
    return c.resize((round(c.width * scale), round(c.height * scale)), Image.LANCZOS)


def thumb(im, w):
    return im.resize((w, round(im.height * w / im.width)), Image.LANCZOS)


cols = [("reference", [crop(ref), crop(ImageOps.grayscale(ref).convert("RGB")), crop(ref)], ref)]
for d, tag, label in cands:
    ims = [Image.open(f"{d}/{tag}-{m}.png").convert("RGB") for m in ("colour", "clay-full", "zebra-full")]
    cols.append((label, [crop(x) for x in ims], ims[0]))
cw, ch = cols[0][1][0].size
tw = cw
th = thumb(ref, tw).height
gap, lh = 8, 18
rows = ["colour", "clay (reference: greyscale)", "zebra (reference: colour)", "whole frame"]
W = 90 + len(cols) * (cw + gap)
H = 40 + lh + 3 * (ch + gap) + th + gap + 20
sheet = Image.new("RGB", (W, H), (240, 240, 240)); dr = ImageDraw.Draw(sheet)
dr.text((10, 8), title or f"{', '.join(feats)}: box {box}, x{scale}", fill=(0, 0, 0))
for k, (label, ims, full) in enumerate(cols):
    x = 90 + k * (cw + gap)
    dr.text((x + 4, 40), label, fill=(0, 0, 0))
    y = 40 + lh
    for im in ims:
        sheet.paste(im, (x, y)); y += ch + gap
    sheet.paste(thumb(full, tw), (x, y))
y = 40 + lh
for r, name in enumerate(rows):
    dr.text((6, y + 4), name.split(" (")[0], fill=(60, 60, 60)); y += ch + gap
sheet.save(out)
print(out, sheet.size, box)
