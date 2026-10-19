"""The before / after sheet of one planned correction: the region of its target and joint
neighbour (the union of their windows), rows colour | clay | zebra | outlines, columns
reference | before (the incumbent) | after (the candidate). The outlines row draws, on the
reference, the target's and neighbour's reference outlines in red, the incumbent's lobes in
blue and the candidate's in green: whether the correction moved the edge the diagnosis named.
Usage (from the logo root): fix_sheet.py PLAN_ENTRY_KEY ROUND OUT.png"""
import json, os, sys
import numpy as np
from PIL import Image, ImageDraw
from skimage import measure
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from evaluate import window
import lobekit as K

key, rnd, outp = sys.argv[1:4]
S = json.load(open(f"auto/{rnd}/summary.json")); s = S["targets"][key]
st = json.load(open("auto/state.json"))
# the incumbent the round was fitted against
inc_tag = S["incumbent"]
inc_dir = next((r for r in [f"auto/{d}/renders" for d in os.listdir("auto") if d.startswith("r")] + ["auto/r10/ms"] if os.path.exists(f"{r}/{inc_tag}-colour.png")), None)
cand_dir, tag = f"auto/{rnd}/renders", s["tag"]
ids = [s["target"]] + ([s["plan"]["joint"]] if s.get("plan") and s["plan"].get("joint") else [])
bx = None
for f in ids:
    w = window(K.FEATS[K.FIDS.index(f)], 40)
    bx = w if bx is None else (min(bx[0], w[0]), min(bx[1], w[1]), max(bx[2], w[2]), max(bx[3], w[3]))
bx = tuple(int(v) for v in bx)
ref = Image.open("snakes/ref/reference.png").convert("RGB")
def full(d, t, m):
    p = f"{d}/{t}-{m}-full.png" if m != "colour" else f"{d}/{t}-colour.png"
    return Image.open(p).convert("RGB").resize((1448, 1086), Image.LANCZOS)
ims = {m: (full(inc_dir, inc_tag, m), full(cand_dir, tag, m)) for m in ("colour", "clay", "zebra")}
def lobes_of(im):
    L = K.lobes(np.asarray(im)); return {f: K.match(L[K.FEATS[K.FIDS.index(f)]["colour"]], K.LAB == K.FIDS.index(f) + 1) for f in ids}
lb, la = lobes_of(ims["colour"][0]), lobes_of(ims["colour"][1])
S2 = 2; W, H = (bx[2] - bx[0]) * S2, (bx[3] - bx[1]) * S2
def outl(img, M, colr):
    d = ImageDraw.Draw(img)
    for c in measure.find_contours(np.pad(M[bx[1]:bx[3], bx[0]:bx[2]], 1).astype(float), 0.5):
        d.line([((p[1] - 1) * S2, (p[0] - 1) * S2) for p in c], fill=colr, width=3)
rows = [("colour", [ref.crop(bx), ims["colour"][0].crop(bx), ims["colour"][1].crop(bx)]),
        ("clay", [None, ims["clay"][0].crop(bx), ims["clay"][1].crop(bx)]),
        ("zebra", [None, ims["zebra"][0].crop(bx), ims["zebra"][1].crop(bx)])]
ov = ref.crop(bx).resize((W, H), Image.LANCZOS)
for f in ids:
    outl(ov, K.LAB == K.FIDS.index(f) + 1, (230, 20, 20))
    if lb[f] is not None: outl(ov, lb[f], (30, 90, 255))
    if la[f] is not None: outl(ov, la[f], (20, 200, 40))
sheet = Image.new("RGB", (3 * (W + 10) + 90, 4 * (H + 10) + 70), (236, 236, 236)); d = ImageDraw.Draw(sheet)
d.text((8, 6), f"{tag}: {key}  |  before = {inc_tag}, after = {tag}  |  outlines: reference red, before blue, after green", fill=(0, 0, 0))
for j, c in enumerate(("reference", "before", "after")):
    d.text((90 + j * (W + 10) + 4, 26), c, fill=(40, 40, 40))
for i, (name, tiles) in enumerate(rows):
    d.text((6, 44 + i * (H + 10) + 8), name, fill=(0, 0, 0))
    for j, t in enumerate(tiles):
        if t is not None:
            sheet.paste(t.resize((W, H), Image.LANCZOS), (90 + j * (W + 10), 44 + i * (H + 10)))
d.text((6, 44 + 3 * (H + 10) + 8), "outlines", fill=(0, 0, 0))
sheet.paste(ov, (90, 44 + 3 * (H + 10)))
sheet.save(outp)
print("->", outp, bx)
