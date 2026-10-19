"""A round's visual report (LOOP.md, "Visual reporting"), from renders the round already made:
  full.png        reference | previous accepted best | new accepted best (colour, then clay)
  KEY.png         per attempted correction, the region of its target and joint neighbour:
                  columns reference | before | candidate; rows colour, clay, zebra, delta (green:
                  the colour now agrees with the reference where it did not; red: now disagrees
                  where it agreed; grey: still wrong), contours (reference red, before blue,
                  candidate green), with the numbered features labelled
  cumulative.png  (--cumulative) reference | the loop's start (lvt60) | the diagnosis-driven
                  start (r18-L12) | the latest accepted best, full frame in colour and clay
  report.md       the per-feature numbers of each candidate's target, neighbour and guards
Usage (from the logo root): round_report.py ROUND [--cumulative]"""
import json, os, sys
import numpy as np
from PIL import Image, ImageDraw
from skimage import measure
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from evaluate import window
from anatomy import colour_masks
import lobekit as K

rnd = sys.argv[1]; R = f"auto/{rnd}"; out = f"{R}/report"; os.makedirs(out, exist_ok=True)
S = json.load(open(f"{R}/summary.json")); st = json.load(open("auto/state.json"))
done = next((r for r in st["rounds"] if r["round"] == rnd), {})
ref = Image.open("snakes/ref/reference.png").convert("RGB")


def find(tag):
    for d in [f"auto/{x}/renders" for x in sorted(os.listdir("auto")) if x.startswith("r")] + ["auto/r10/ms", "ffd/before"]:
        if os.path.exists(f"{d}/{tag}-colour.png"):
            return d
    raise FileNotFoundError(tag)


def img(tag, m):
    d = find(tag); p = f"{d}/{tag}-colour.png" if m == "colour" else f"{d}/{tag}-{m}-full.png"
    return Image.open(p).convert("RGB").resize((1448, 1086), Image.LANCZOS)


def cls(im):
    b, y = colour_masks(np.asarray(im)); c = np.zeros(b.shape, np.int8); c[b] = 1; c[y] = 2; return c


def grid(rows, cols, title, path, scale):
    W = max(t.width for _, ts in rows for t in ts if t is not None); H = max(t.height for _, ts in rows for t in ts if t is not None)
    sh = Image.new("RGB", (90 + len(cols) * (W + 10), 50 + len(rows) * (H + 10)), (236, 236, 236)); d = ImageDraw.Draw(sh)
    d.text((8, 6), title, fill=(0, 0, 0))
    for j, c in enumerate(cols):
        d.text((90 + j * (W + 10) + 4, 26), c, fill=(40, 40, 40))
    for i, (name, ts) in enumerate(rows):
        d.text((6, 44 + i * (H + 10) + 8), name, fill=(0, 0, 0))
        for j, t in enumerate(ts):
            if t is not None:
                sh.paste(t, (90 + j * (W + 10), 44 + i * (H + 10)))
    sh.save(path)


B = (150, 90, 1300, 1010)
prev, new = S["incumbent"], st["incumbent"]["tag"] if done.get("accepted") else S["incumbent"]
fr = lambda im: im.crop(B).resize((805, 644), Image.LANCZOS)
grid([("colour", [fr(ref), fr(img(prev, "colour")), fr(img(new, "colour"))]), ("clay", [None, fr(img(prev, "clay")), fr(img(new, "clay"))])],
     ["reference", f"previous accepted best ({prev})", f"new accepted best ({new})" + ("" if done.get("accepted") else ": unchanged, nothing accepted")],
     f"round {rnd}: whole frame", f"{out}/full.png", 1)
cref = cls(ref)
lines = [f"# Round {rnd}: report", "", f"Previous accepted best {prev}; new accepted best {new}.", ""]
for key, s in S["targets"].items():
    if "tag" not in s:
        continue
    ids = [s["target"]] + ([s["plan"]["joint"]] if s.get("plan") and s["plan"].get("joint") else [])
    bx = None
    for f in ids:
        w = window(K.FEATS[K.FIDS.index(f)], 45)
        bx = w if bx is None else (min(bx[0], w[0]), min(bx[1], w[1]), max(bx[2], w[2]), max(bx[3], w[3]))
    bx = tuple(int(v) for v in bx)
    sc = min(2.0, 620 / max(bx[2] - bx[0], bx[3] - bx[1]))
    sz = (int((bx[2] - bx[0]) * sc), int((bx[3] - bx[1]) * sc))
    cut = lambda im: im.crop(bx).resize(sz, Image.LANCZOS)
    bcol, ccol = img(prev, "colour"), Image.open(f"{R}/renders/{s['tag']}-colour.png").convert("RGB")
    cc = lambda m: Image.open(f"{R}/renders/{s['tag']}-{m}-full.png").convert("RGB").resize((1448, 1086), Image.LANCZOS)
    # delta: which pixels moved towards the reference's colour and which away
    cb, ca = cls(bcol), cls(ccol)
    def delta(c_before, c_after):
        D = np.full(cref.shape + (3,), 255, np.uint8)
        D[(c_after != cref)] = (175, 175, 175)
        D[(c_after == cref) & (c_before != cref)] = (20, 190, 40)
        D[(c_after != cref) & (c_before == cref)] = (225, 30, 30)
        return Image.fromarray(D)
    dl = [None, delta(cb, cb), delta(cb, ca)]
    # contours of the target and neighbour: reference red, before blue, candidate green
    Lb, La = K.lobes(np.asarray(bcol)), K.lobes(np.asarray(ccol))
    def contours(base):
        im = cut(base); d = ImageDraw.Draw(im)
        for f in ids:
            i = K.FIDS.index(f); Rm = K.LAB == i + 1; c = K.FEATS[i]["colour"]
            for M, colr in ((Rm, (230, 20, 20)), (K.match(Lb[c], Rm), (30, 90, 255)), (K.match(La[c], Rm), (20, 200, 40))):
                if M is None:
                    continue
                for cn in measure.find_contours(np.pad(M[bx[1]:bx[3], bx[0]:bx[2]], 1).astype(float), 0.5):
                    d.line([((p[1] - 1) * sc, (p[0] - 1) * sc) for p in cn], fill=colr, width=3)
        return im
    def label(im):
        d = ImageDraw.Draw(im)
        for f in K.FEATS:
            cx, cy = f["centroid"]
            if bx[0] < cx < bx[2] and bx[1] < cy < bx[3]:
                x, y = (cx - bx[0]) * sc, (cy - bx[1]) * sc
                d.rectangle((x - 2, y - 2, x + 30, y + 12), fill=(255, 255, 255)); d.text((x, y), f["id"], fill=(0, 0, 0))
        return im
    rows = [("colour", [label(cut(ref)), cut(bcol), cut(ccol)]), ("clay", [None, cut(img(prev, "clay")), cut(cc("clay"))]),
            ("zebra", [None, cut(img(prev, "zebra")), cut(cc("zebra"))]),
            ("delta", [None, None, label(cut(dl[2]))]), ("contours", [contours(ref), None, None])]
    jv = open(f"{R}/judge-{s['tag']}.md").readline().strip() if os.path.exists(f"{R}/judge-{s['tag']}.md") else "verdict: (gates) " + ("REJECT" if s.get("gate_fails") else "pending")
    grid(rows, ["reference", f"before ({prev})", f"candidate ({s['tag']})"],
         f"{s['tag']}: {key}  |  {jv}  |  delta: green = now agrees with the reference, red = now disagrees, grey = still wrong  |  contours: reference red, before blue, candidate green",
         f"{out}/{key}.png", sc)
    mb = json.load(open(find(prev).replace("/renders", "") + f"/metrics-{prev}.json")) if os.path.exists(find(prev).replace("/renders", "") + f"/metrics-{prev}.json") else None
    mc = json.load(open(f"{R}/metrics-{s['tag']}.json"))
    lines += [f"## {key}: {jv}", "", f"Diagnosis: {(s.get('plan') or {}).get('diagnosis', '-')}", "", f"Handle: {s['describe']}", "",
              "| feature | IoU | p95 contour px | crease | severity (metric) |", "|---|---|---|---|---|"]
    for f in ids + [g for g in K.FIDS if g not in ids and mb and abs(mc["features"][g]["iou"] - mb["features"][g]["iou"]) >= 0.01]:
        a, b = (mb["features"][f] if mb else {}), mc["features"][f]
        lines.append(f"| {f} | {a.get('iou', 0):.3f} -> {b['iou']:.3f} | {a.get('sdist', {}).get('p95', 0):.1f} -> {b['sdist']['p95']:.1f} | {a.get('crease') or 0:.2f} -> {b.get('crease') or 0:.2f} | {a.get('severity', '-')} -> {b['severity']} |")
    lines.append("")
open(f"{out}/report.md", "w").write("\n".join(lines) + "\n")
if "--cumulative" in sys.argv:
    tags = ["lvt60", "r18-L12", st["incumbent"]["tag"]]
    grid([("colour", [fr(ref)] + [fr(img(t, "colour")) for t in tags]), ("clay", [None] + [fr(img(t, "clay")) for t in tags])],
         ["reference", "loop start (lvt60)", "diagnosis-driven start (r18-L12)", f"latest accepted best ({tags[2]})"],
         f"cumulative after {rnd}", f"{out}/cumulative.png", 1)
print("report ->", out, sorted(os.listdir(out)))
