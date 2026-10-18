"""Whole-body check: per tag (rows), colour and clay in the hero view, then colour and clay in
the 3/4 view (yaw 35). The reference heads the first column. Usage (from the logo root, logo/snake-w):
fullsheet.py out.png title tag1 tag2 ..."""
import sys
from PIL import Image, ImageDraw
out, title, tags = sys.argv[1], sys.argv[2], sys.argv[3:]
B = (150, 90, 1300, 1010); BS = (150, 60, 1300, 1050)
TW = 330
def tile(path, box):
    im = Image.open(path).convert("RGB")
    if im.width != 1448: im = im.resize((1448, 1086), Image.LANCZOS)   # crop-scale renders
    im = im.crop(box)
    return im.resize((TW, round(TW * (box[3] - box[1]) / (box[2] - box[0]))), Image.LANCZOS)
rows = [("reference", [tile("snakes/ref/reference.png", B)])]
for t in tags:
    rows.append((t, [tile(f"jfit/r/{t}-colour.png", B), tile(f"jfit/r/{t}-clay-full.png", B),
                     tile(f"jfit/r/{t}-colour-side.png", BS), tile(f"jfit/r/{t}-clay-side.png", BS)]))
heads = ["colour (hero view)", "clay (hero view)", "colour (3/4 view, yaw 35)", "clay (3/4 view)"]
H = 30 + sum(max(t.height for t in r[1]) + 22 for r in rows)
sheet = Image.new("RGB", (4 * (TW + 6), H), (238, 238, 238)); d = ImageDraw.Draw(sheet)
d.text((6, 8), title, fill=(0, 0, 0))
y = 30
for name, tiles in rows:
    for i, t in enumerate(tiles):
        sheet.paste(t, (i * (TW + 6), y + 16)); d.text((i * (TW + 6) + 4, y + 2), f"{name}: {heads[i] if name != 'reference' else 'reference'}", fill=(0, 0, 0))
    y += max(t.height for t in tiles) + 22
sheet.save(out); print(sheet.size)
