"""Before/after sheet: per view, reference | colour per tag | clay per tag | zebra per tag, at
identical framing (crops rendered with their own camera; the colour still and the reference
cropped and resized to the same size). Usage (from the logo root, logo/snake-w): vsheet.py out.png title view1,view2 tag1 tag2 ..."""
import json, sys
from PIL import Image, ImageDraw
out, title, views, tags = sys.argv[1], sys.argv[2], sys.argv[3].split(","), sys.argv[4:]
BOX = {"full": (150, 90, 1300, 1010), "rvalley": (800, 540, 1080, 800), "curl": (860, 610, 1010, 760), "lvalley": (420, 560, 700, 800)}
TW = 300
ref = Image.open("snakes/ref/reference.png").convert("RGB")
rows = []
for v in views:
    b = BOX[v]
    th = round(TW * (b[3] - b[1]) / (b[2] - b[0]))
    tiles = [("reference", ref.crop(b))]
    tiles += [(f"{t} colour", Image.open(f"jfit/r/{t}-colour.png").convert("RGB").crop(b)) for t in tags]
    for mode in ("clay", "zebra"):
        for t in tags:
            im = Image.open(f"jfit/r/{t}-{mode}-{v}.png").convert("RGB")
            if v == "full": im = im.crop(b)
            tiles.append((f"{t} {mode}", im))
    rows.append((v, [(l, im.resize((TW, th), Image.LANCZOS)) for l, im in tiles]))
ncol = len(rows[0][1])
H = 30 + sum(r[1][0][1].height + 22 for r in rows)
sheet = Image.new("RGB", (ncol * (TW + 6), H), (238, 238, 238)); d = ImageDraw.Draw(sheet)
d.text((6, 8), title, fill=(0, 0, 0))
y = 30
for v, tiles in rows:
    for i, (lab, t) in enumerate(tiles):
        sheet.paste(t, (i * (TW + 6), y + 16)); d.text((i * (TW + 6) + 4, y + 2), f"{v}: {lab}", fill=(0, 0, 0))
    y += tiles[0][1].height + 22
sheet.save(out); print(sheet.size)
