"""Pages for the visual diagnosis that starts every round: the reference beside the incumbent,
for a critic to say what looks wrong and what correction would fix it (LOOK, DESCRIBE).
  columns  reference | current colour | current clay | current zebra | overlay (the current colour,
           with the reference feature's outline in red and the current lobe's in green)
  page0    the whole frame
  page1-3  the registry features H1, L01-L16, H2 (six a page)
  page4-7  the junctions between neighbouring features (the registry's neighbour pairs), a window
           round where the two meet in the reference: a pinch or a step between two lobes lies
           outside both lobes' own windows' centres
  page8    the negative spaces N1-N6
Usage (from the logo root): diag_pages.py RENDERS TAG OUT_DIR"""
import os, sys
import numpy as np
from PIL import Image, ImageDraw
from skimage import measure, morphology
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from evaluate import window, load_registry
import lobekit as K

rd, tag, out = sys.argv[1:4]
os.makedirs(out, exist_ok=True)
reg, lab, neglab = load_registry()
ref = Image.open("snakes/ref/reference.png").convert("RGB")
col = Image.open(f"{rd}/{tag}-colour.png").convert("RGB")
full = {m: Image.open(f"{rd}/{tag}-{m}-full.png").convert("RGB").resize((1448, 1086), Image.LANCZOS) for m in ("clay", "zebra")}
L = K.lobes(np.asarray(col))
COLS = ["reference", "current colour", "current clay", "current zebra", "overlay: reference red, current green"]
TH = 300


def fit(im, h=TH, wmax=380):
    w = round(im.width * h / im.height)
    if w > wmax:
        h = round(h * wmax / w); w = wmax
    return im.resize((w, h), Image.LANCZOS)


def overlay(bx, masks):
    im = col.crop(bx).copy(); d = ImageDraw.Draw(im)
    x0, y0 = bx[0], bx[1]
    for M, c in masks:
        for cn in measure.find_contours(np.pad(M[bx[1]:bx[3], bx[0]:bx[2]], 1).astype(float), 0.5):
            d.line([(p[1] - 1, p[0] - 1) for p in cn], fill=c, width=2)
    return im


def tiles(bx, masks, own=None):
    t = [ref.crop(bx), col.crop(bx)]
    if own:
        t += [Image.open(f"{rd}/{tag}-{m}-{own}.png").convert("RGB") for m in ("clay", "zebra")]
    else:
        t += [full[m].crop(bx) for m in ("clay", "zebra")]
    t.append(overlay(bx, masks))
    return [fit(x) for x in t]


def page(rows, title, path):
    widths = [max(r[1][k].width for r in rows) for k in range(len(COLS))]
    H = 40 + sum(max(t.height for t in r[1]) + 22 for r in rows) + 16
    W = sum(widths) + 6 * len(COLS) + 70
    pg = Image.new("RGB", (W, H), (236, 236, 236)); d = ImageDraw.Draw(pg)
    d.text((8, 8), title, fill=(0, 0, 0))
    x = 70
    for k, c in enumerate(COLS):
        d.text((x + 2, 24), c, fill=(60, 60, 60)); x += widths[k] + 6
    y = 40
    for name, ts in rows:
        d.text((6, y + 8), name, fill=(0, 0, 0))
        x = 70
        for k, t in enumerate(ts):
            pg.paste(t, (x, y)); x += widths[k] + 6
        y += max(t.height for t in ts) + 22
    pg.save(path)


def cand(fid):
    i = K.FIDS.index(fid); f = K.FEATS[i]
    return K.match(L[f["colour"]], lab == i + 1)


B = (150, 90, 1300, 1010)
page([("whole", [fit(x, 420, 560) for x in (ref.crop(B), col.crop(B), full["clay"].crop(B), full["zebra"].crop(B), col.crop(B))])],
     f"whole frame: reference and the incumbent {tag}", f"{out}/page0-whole.png")
feats = reg["features"]
for p in range(0, len(feats), 6):
    rows = []
    for f in feats[p:p + 6]:
        i = K.FIDS.index(f["id"]); C = cand(f["id"])
        rows.append((f["id"], tiles(window(f, 30), [(lab == i + 1, (230, 20, 20))] + ([(C, (20, 200, 20))] if C is not None else []), own=f["id"])))
    page(rows, f"features {feats[p]['id']} .. {feats[min(p + 5, len(feats) - 1)]['id']}", f"{out}/page{p // 6 + 1}-features.png")
pairs = []
for f in feats:
    for n in f.get("neighbours", []):
        if (n, f["id"]) not in pairs:
            pairs.append((f["id"], n))
jrows = []
for a, b in pairs:
    ia, ib = K.FIDS.index(a), K.FIDS.index(b)
    Ra, Rb = lab == ia + 1, lab == ib + 1
    J = morphology.dilation(Ra, morphology.disk(4)) & morphology.dilation(Rb, morphology.disk(4))
    if J.sum() < 5:
        continue
    ys, xs = np.nonzero(J)
    bx = (max(0, xs.min() - 45), max(0, ys.min() - 45), min(1448, xs.max() + 45), min(1086, ys.max() + 45))
    ms = [(Ra, (230, 20, 20)), (Rb, (230, 120, 20))]
    for fid, c in ((a, (20, 200, 20)), (b, (20, 160, 200))):
        C = cand(fid)
        if C is not None:
            ms.append((C, c))
    jrows.append((f"{a}|{b}", tiles(bx, ms)))
for k in range(0, len(jrows), 6):
    page(jrows[k:k + 6], "junctions (red / orange: the reference's two features; green / cyan: the current lobes)", f"{out}/page{4 + k // 6}-junctions.png")
nrows = []
for n in reg["negatives"]:
    k = int(n["id"][1:]); M = neglab == k
    if M.sum() < 50:
        continue
    ys, xs = np.nonzero(M)
    bx = (max(0, xs.min() - 30), max(0, ys.min() - 30), min(1448, xs.max() + 30), min(1086, ys.max() + 30))
    nrows.append((n["id"], tiles(bx, [(M, (230, 20, 20))])))
page(nrows, "negative spaces (red: the reference's gap)", f"{out}/page{4 + (len(jrows) + 5) // 6}-negatives.png")
print("pages ->", out, len(jrows), "junctions")
