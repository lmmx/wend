"""Pages for a paired blind judge: the reference and two anonymised candidates, X and Y, side
by side at identical framing, for the whole frame and every registry feature.
  row per feature: reference | X colour | Y colour | X clay | Y clay | X zebra | Y zebra
The order X / Y is given by the caller (randomised and recorded outside the pages).
Usage (from the logo root): pair_pages.py RENDERS_X TAG_X RENDERS_Y TAG_Y OUT_DIR"""
import os, sys
from PIL import Image, ImageDraw
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from evaluate import window, load_registry

rx, tx, ry, ty, out = sys.argv[1:6]
os.makedirs(out, exist_ok=True)
reg, lab, _ = load_registry()
ref = Image.open("snakes/ref/reference.png").convert("RGB")
col = {"X": Image.open(f"{rx}/{tx}-colour.png").convert("RGB"), "Y": Image.open(f"{ry}/{ty}-colour.png").convert("RGB")}
src = {"X": (rx, tx), "Y": (ry, ty)}
COLS = ["reference", "X colour", "Y colour", "X clay", "Y clay", "X zebra", "Y zebra"]
TH = 220


def fit(im, h=TH, wmax=280):
    w = round(im.width * h / im.height)
    if w > wmax:
        h = round(h * wmax / w); w = wmax
    return im.resize((w, h), Image.LANCZOS)


def page(rows, title, path):
    widths = [max(r[1][k].width for r in rows) for k in range(len(COLS))]
    H = 40 + sum(max(t.height for t in r[1]) + 22 for r in rows) + 16
    W = sum(widths) + 6 * len(COLS) + 50
    pg = Image.new("RGB", (W, H), (236, 236, 236)); d = ImageDraw.Draw(pg)
    d.text((8, 8), title, fill=(0, 0, 0))
    x = 50
    for k, c in enumerate(COLS):
        d.text((x + 2, 24), c, fill=(60, 60, 60)); x += widths[k] + 6
    y = 40
    for fid, tiles in rows:
        d.text((6, y + 8), fid, fill=(0, 0, 0))
        x = 50
        for k, t in enumerate(tiles):
            pg.paste(t, (x, y)); x += widths[k] + 6
        y += max(t.height for t in tiles) + 22
    pg.save(path)


def whole(m, k):
    im = Image.open(f"{src[k][0]}/{src[k][1]}-{m}-full.png").convert("RGB")
    return im.resize((1448, 1086), Image.LANCZOS) if im.width != 1448 else im


B = (150, 90, 1300, 1010)
tiles = [fit(ref.crop(B), 260, 330)] + [fit(col[k].crop(B), 260, 330) for k in "XY"]
tiles += [fit(whole(m, k).crop(B), 260, 330) for m in ("clay", "zebra") for k in "XY"]
page([("whole", tiles)], "whole frame", f"{out}/page0-whole.png")
feats = reg["features"]
for p in range(0, len(feats), 6):
    rows = []
    for f in feats[p:p + 6]:
        bx = window(f, 30)
        t = [fit(ref.crop(bx))] + [fit(col[k].crop(bx)) for k in "XY"]
        t += [fit(Image.open(f"{src[k][0]}/{src[k][1]}-{m}-{f['id']}.png").convert("RGB")) for m in ("clay", "zebra") for k in "XY"]
        rows.append((f["id"], t))
    last = feats[min(p + 5, len(feats) - 1)]["id"]
    page(rows, f"features {feats[p]['id']} .. {last}", f"{out}/page{p // 6 + 1}-{feats[p]['id']}-{last}.png")
print("pair pages in", out)
