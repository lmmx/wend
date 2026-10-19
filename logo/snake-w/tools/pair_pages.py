"""Pages for a paired blind judge: the reference and two anonymised candidates, X and Y, side
by side at identical framing, for the whole frame and every registry feature.
  row per feature: reference | X colour | Y colour | X clay | Y clay | X zebra | Y zebra
The order X / Y is given by the caller (randomised and recorded outside the pages).
With --focus F1,F2: page4-focus.png, those features at a larger scale (each tile 520 px tall), the
same seven columns: small corrections (10-15 px) are hard to see at the standard tile size.
Usage (from the logo root): pair_pages.py RENDERS_X TAG_X RENDERS_Y TAG_Y OUT_DIR [--focus F1,F2]"""
import os, sys
from PIL import Image, ImageDraw
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from evaluate import window, load_registry

argv = sys.argv[1:]
focus = []
if "--focus" in argv:
    i = argv.index("--focus"); focus = argv[i + 1].split(","); del argv[i:i + 2]
rx, tx, ry, ty, out = argv[:5]
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
if focus:
    import numpy as np
    from skimage import morphology
    rows = []
    for f in [g for g in feats if g["id"] in focus]:
        bx = window(f, 30)
        t = [fit(ref.crop(bx), 520, 640)] + [fit(col[k].crop(bx), 520, 640) for k in "XY"]
        t += [fit(Image.open(f"{src[k][0]}/{src[k][1]}-{m}-{f['id']}.png").convert("RGB"), 520, 640) for m in ("clay", "zebra") for k in "XY"]
        rows.append((f["id"], t))
    # a junction "A|B": the window round where the two features meet in the reference, cut from
    # the whole-frame clay and zebra (a pinch between two lobes is at neither lobe's centre)
    ids = [g["id"] for g in feats]
    for j in [x for x in focus if "|" in x]:
        a, b = j.split("|")
        J = morphology.dilation(lab == ids.index(a) + 1, morphology.disk(4)) & morphology.dilation(lab == ids.index(b) + 1, morphology.disk(4))
        if J.sum() < 5:
            continue
        ys, xs = np.nonzero(J)
        bx = (max(0, xs.min() - 45), max(0, ys.min() - 45), min(1448, xs.max() + 45), min(1086, ys.max() + 45))
        t = [fit(ref.crop(bx), 520, 640)] + [fit(col[k].crop(bx), 520, 640) for k in "XY"]
        t += [fit(whole(m, k).crop(bx), 520, 640) for m in ("clay", "zebra") for k in "XY"]
        rows.append((j, t))
    page(rows, "enlarged: " + ", ".join(focus), f"{out}/page4-focus.png")
print("pair pages in", out)
