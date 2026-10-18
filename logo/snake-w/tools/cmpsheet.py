"""Body comparison sheet: per view (full frame and the five crops), the reference, both bodies
in colour, then both in clay and in zebra (identical lighting). Usage (from snakes/):
cmpsheet.py out.png base_colour.png new_colour.png ../cmp/base- ../cmp/new- [title]"""
import sys
from PIL import Image, ImageDraw
out, bc, nc, bp, npre = sys.argv[1:6]
title = sys.argv[6] if len(sys.argv) > 6 else "baseline vs new body"
VIEWS = {"full": (0, 0, 1448, 1086), "arch": (600, 380, 880, 620), "lvalley": (420, 560, 700, 800),
         "rvalley": (800, 540, 1080, 800), "larm": (380, 380, 520, 660), "rarm": (940, 420, 1080, 700)}
FULLCROP = (150, 90, 1300, 1010)       # the composition, as the other sheets frame it
TW = 250
ref = Image.open("ref/reference.png").convert("RGB")
cols = [("reference", None), ("baseline colour", None), ("new colour", None), ("baseline clay", "clay"), ("new clay", "clay"), ("baseline zebra", "zebra"), ("new zebra", "zebra")]
rows = []
for view, box in VIEWS.items():
    b = FULLCROP if view == "full" else box
    tiles = [ref.crop(b), Image.open(bc).convert("RGB").crop(b), Image.open(nc).convert("RGB").crop(b)]
    for pre in (bp, npre, bp, npre):
        pass
    for mode in ("clay", "zebra"):
        for pre in (bp, npre):
            im = Image.open(f"{pre}{mode}-{view}.png").convert("RGB")
            if view == "full":   # the full-frame shot is 1448 x 1086: crop it the same way
                im = im.crop(FULLCROP)
            tiles.append(im)
    th = round(TW * (b[3] - b[1]) / (b[2] - b[0]))
    rows.append((view, [t.resize((TW, th), Image.LANCZOS) for t in tiles]))
H = 30 + sum(r[1][0].height + 22 for r in rows)
sheet = Image.new("RGB", (7 * (TW + 6), H), (238, 238, 238)); d = ImageDraw.Draw(sheet)
d.text((6, 8), title, fill=(0, 0, 0))
y = 30
for view, tiles in rows:
    for i, (t, (lab, _)) in enumerate(zip(tiles, cols)):
        sheet.paste(t, (i * (TW + 6), y + 16)); d.text((i * (TW + 6) + 4, y + 2), f"{view}: {lab}", fill=(0, 0, 0))
    y += tiles[0].height + 22
sheet.save(out)
print(sheet.size)
