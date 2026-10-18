"""Side-by-side sheet of diagnostic renders.
Usage: diag_sheet.py out.png "row label=prefix" ... [--modes clay,zebra,zebrav,curv] [--view arch] [--w 420]
Each row is one render prefix (as written by diag_still.mjs); columns are modes (or, with
--views a,b,c and a single --modes m, the columns are views). Optional --ref adds the
reference crop as the first column."""
import os
import sys
from PIL import Image, ImageDraw
sys.path.insert(0, __file__.rsplit("/", 1)[0])
CROPS = {"arch": (600, 380, 880, 620), "lvalley": (420, 560, 700, 800), "rvalley": (800, 540, 1080, 800),
         "larm": (380, 380, 520, 660), "rarm": (940, 420, 1080, 700), "full": (0, 0, 1448, 1086)}
args = sys.argv[1:]
out = args.pop(0)
opt = {"modes": "clay,zebra,zebrav,curv", "view": "arch", "views": None, "w": "420", "ref": None}
rows = []
while args:
    a = args.pop(0)
    if a.startswith("--"): opt[a[2:]] = args.pop(0) if a[2:] != "ref" else "1"
    else: rows.append(a.split("=", 1))
W = int(opt["w"])
modes = opt["modes"].split(",")
if opt["views"]:
    cols = [(modes[0], v) for v in opt["views"].split(",")]
else:
    cols = [(m, opt["view"]) for m in modes]
REF = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "snakes", "ref", "reference.png")
def label(t, s):
    d = ImageDraw.Draw(t); d.rectangle([0, 0, len(s) * 6 + 8, 14], fill=(255, 255, 255)); d.text((3, 1), s, fill=(0, 0, 0))
    return t
tiles = []
for lab, pre in rows:
    r = []
    if opt["ref"]:
        ref = Image.open(REF).convert("RGB").crop(CROPS[cols[0][1]])
        r.append(label(ref.resize((W, round(W * ref.height / ref.width)), Image.LANCZOS), "reference"))
    for m, v in cols:
        im = Image.open(f"{pre}{m}-{v}.png").convert("RGB")
        r.append(label(im.resize((W, round(W * im.height / im.width)), Image.LANCZOS), f"{lab} {m} {v}"))
    tiles.append(r)
H = sum(max(t.height for t in r) + 4 for r in tiles)
Wt = max(sum(t.width + 4 for t in r) for r in tiles)
sheet = Image.new("RGB", (Wt, H), (200, 200, 200))
y = 0
for r in tiles:
    x = 0
    for t in r: sheet.paste(t, (x, y)); x += t.width + 4
    y += max(t.height for t in r) + 4
sheet.save(out)
print(out, sheet.size)
