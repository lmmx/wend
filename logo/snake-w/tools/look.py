"""Reference | render | render with the reference outline (red) over it, cropped around a head, 2x."""
import sys
import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage
from skimage import measure
sys.path.insert(0, __file__.rsplit("/", 1)[0])
import snakefit as sf

render, out = sys.argv[1], sys.argv[2]
boxes = {"blue": (930, 230, 1200, 520), "yellow": (250, 230, 520, 520)}
which = sys.argv[3:] or ["blue", "yellow"]
ref = Image.open("ref/reference.png").convert("RGB"); ren = Image.open(render).convert("RGB")
_, lr = sf.ref_labels("ref/reference.png", 1.0)
seeds = {"yellow": ((405, 305), 2), "blue": ((1060, 300), 1)}
rows = []
for nm in which:
    (sx, sy), lab = seeds[nm]
    cc, _ = ndimage.label(lr == lab); comp = ndimage.binary_fill_holes(cc == cc[sy, sx])
    x0, y0, x1, y1 = boxes[nm]; S = 2
    tiles = [ref.crop(boxes[nm]), ren.crop(boxes[nm]), ren.crop(boxes[nm])]
    tiles = [t.resize(((x1 - x0) * S, (y1 - y0) * S), Image.LANCZOS) for t in tiles]
    d = ImageDraw.Draw(tiles[2])
    for c in measure.find_contours(comp[y0:y1, x0:x1].astype(float), 0.5):
        d.line([(q[1] * S, q[0] * S) for q in c], fill=(255, 0, 0), width=2)
    row = Image.new("RGB", (sum(t.width for t in tiles), tiles[0].height), "white")
    x = 0
    for t in tiles: row.paste(t, (x, 0)); x += t.width
    rows.append(row)
sheet = Image.new("RGB", (rows[0].width, sum(r.height for r in rows)), "white")
y = 0
for r in rows: sheet.paste(r, (0, y)); y += r.height
sheet.save(out)
