"""Art-direction sheet: reference and variants side by side, full composition on top, then
the same five crops of each (left head, right head, left valley, right valley, central arch).
Usage: artsheet.py out.png label=render.png ..."""
import sys
from PIL import Image, ImageDraw
out = sys.argv[1]
cols = [("reference", "ref/reference.png")] + [a.split("=", 1) for a in sys.argv[2:]]
FULL = (150, 90, 1300, 1010)
CROPS = [("left head", (250, 240, 500, 500)), ("right head", (940, 240, 1200, 500)),
         ("left valley", (420, 560, 700, 800)), ("right valley", (800, 540, 1080, 800)),
         ("central arch", (600, 380, 880, 620))]
CW = 330
def tile(im, box, w, title=None):
    t = im.crop(box); t = t.resize((w, round(w * t.height / t.width)), Image.LANCZOS)
    if title:
        d = ImageDraw.Draw(t); d.rectangle([0, 0, len(title) * 6 + 10, 15], fill=(255, 255, 255)); d.text((4, 2), title, fill=(0, 0, 0))
    return t
ims = [Image.open(p).convert("RGB") for _, p in cols]
rows = [[tile(im, FULL, CW, lab) for (lab, _), im in zip(cols, ims)]]
for name, box in CROPS:
    rows.append([tile(im, box, CW, name if i == 0 else None) for i, im in enumerate(ims)])
H = sum(r[0].height + 4 for r in rows)
sheet = Image.new("RGB", (len(cols) * (CW + 4), H), (235, 235, 235))
y = 0
for r in rows:
    for i, t in enumerate(r): sheet.paste(t, (i * (CW + 4), y))
    y += r[0].height + 4
sheet.save(out)
