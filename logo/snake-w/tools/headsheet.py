"""Review sheet for the heads: reference, render, and render with the reference outline drawn over it, at 2x."""
import json, sys
import numpy as np
from PIL import Image, ImageDraw
ref_json, out, *renders = sys.argv[1:]
R = json.load(open(ref_json))
ref = Image.open("ref/reference.png").convert("RGB")
boxes = {"yellow": (280, 270, 520, 510), "blue": (930, 260, 1170, 500)}
cols = [("reference", ref)] + [(r.rsplit("=", 1)[0], Image.open(r.rsplit("=", 1)[1]).convert("RGB")) for r in renders]
S = 2
W, H = 240 * S, 240 * S
sheet = Image.new("RGB", (W * (1 + 2 * len(renders)), (H + 30) * 2), "white")
d = ImageDraw.Draw(sheet)
for row, (name, box) in enumerate(boxes.items()):
    C = np.asarray(R[name]["contour"]); outer = np.asarray(R[name]["outer"])
    col = 0
    for k, (title, im) in enumerate(cols):
        crop = im.crop(box).resize((W, H), Image.LANCZOS)
        variants = [(title, crop)] if k == 0 else [(title, crop), (title + " + reference outline", crop.copy())]
        for t, c in variants:
            if t.endswith("outline"):
                dc = ImageDraw.Draw(c)
                pts = [((x - box[0]) * S, (y - box[1]) * S) for x, y in C]
                for i in range(len(pts)):
                    if outer[i] and outer[(i + 1) % len(pts)]:
                        dc.line([pts[i], pts[(i + 1) % len(pts)]], fill=(230, 0, 0), width=2)
            sheet.paste(c, (col * W, row * (H + 30) + 30))
            d.text((col * W + 6, row * (H + 30) + 10), f"{name}: {t}", fill=(0, 0, 0))
            col += 1
sheet.save(out)
