"""Round sheet for the people following the work (not for the blind judge: it carries metrics and
names): what a candidate changed against the current best, on real renders.
  top     reference | best | candidate | delta. In the delta, green marks pixels whose colour
          (blue / yellow / background) the candidate now gets right against the reference and the
          best got wrong, red the reverse; the rest is the candidate, faded
  rows    every feature whose metric severity or IoU changed (|dIoU| >= 0.02), with
          "IoU before -> after, severity before -> after" in the label: reference | best | candidate
          | delta | best clay | candidate clay | best zebra | candidate zebra
Usage (from the logo root): delta_sheet.py BEST_RENDERS BEST_TAG CAND_RENDERS CAND_TAG OUT.png [title]"""
import json, os, sys
import numpy as np
from PIL import Image, ImageDraw
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from evaluate import window, load_registry, evaluate
from anatomy import colour_masks

rb, tb, rc, tc, out = sys.argv[1:6]
title = sys.argv[6] if len(sys.argv) > 6 else f"{tc} against {tb}"
reg, lab, _ = load_registry()
ref = Image.open("snakes/ref/reference.png").convert("RGB")
B = Image.open(f"{rb}/{tb}-colour.png").convert("RGB"); C = Image.open(f"{rc}/{tc}-colour.png").convert("RGB")


def labels(im):
    b, y = colour_masks(np.asarray(im))
    return np.where(b, 1, np.where(y, 2, 0))


rl = np.where(lab > 0, np.array([0] + [1 if f["colour"] == "blue" else 2 for f in reg["features"]])[lab], 0)
lb, lc = labels(B), labels(C)
gain = (lc == rl) & (lb != rl); loss = (lc != rl) & (lb == rl)
d = (np.asarray(C).astype(float) * 0.45 + 140).clip(0, 255)
d[gain] = (40, 200, 60); d[loss] = (230, 40, 40)
D = Image.fromarray(d.astype(np.uint8))
mb = json.load(open(f"{rb}/../metrics-{tb}.json")) if os.path.exists(f"{rb}/../metrics-{tb}.json") else evaluate(f"{rb}/{tb}-colour.png")
mc = json.load(open(f"{rc}/../metrics-{tc}.json")) if os.path.exists(f"{rc}/../metrics-{tc}.json") else evaluate(f"{rc}/{tc}-colour.png")


def fit(im, h):
    return im.resize((round(im.width * h / im.height), h), Image.LANCZOS)


rows = []
F = (150, 90, 1300, 1010)
top = [fit(x.crop(F), 300) for x in (ref, B, C, D)]
for f in reg["features"]:
    a, b = mb["features"][f["id"]], mc["features"][f["id"]]
    if abs(b.get("iou", 0) - a.get("iou", 0)) < 0.02 and a["severity"] == b["severity"]:
        continue
    bx = window(f, 30)
    t = [fit(x.crop(bx), 200) for x in (ref, B, C, D)]
    for m in ("clay", "zebra"):
        for r_, t_ in ((rb, tb), (rc, tc)):
            p = f"{r_}/{t_}-{m}-{f['id']}.png"
            t.append(fit(Image.open(p).convert("RGB"), 200) if os.path.exists(p) else Image.new("RGB", (150, 200), (200, 200, 200)))
    lbl = f"{f['id']}: IoU {a.get('iou', 0):.2f} -> {b.get('iou', 0):.2f}, severity {a['severity']} -> {b['severity']}" + (f"  (candidate split flags: {','.join(b['seg'])})" if b.get("seg") else "")
    rows.append((lbl, t))
cols = ["reference", tb, tc, "delta: green fixed, red broken"]
W = max(sum(t.width for t in top) + 3 * 8, max([sum(t.width for t in r[1]) + 7 * 6 for r in rows] or [0])) + 20
H = 40 + top[0].height + 30 + sum(r[1][0].height + 34 for r in rows) + 30
g = mb["global"], mc["global"]
sheet = Image.new("RGB", (W, H), (240, 240, 240)); dr = ImageDraw.Draw(sheet)
dr.text((10, 8), title, fill=(0, 0, 0))
dr.text((10, 22), f"silhouette IoU {g[0]['silhouette_iou']:.3f} -> {g[1]['silhouette_iou']:.3f}, blue IoU {g[0]['blue_iou']:.3f} -> {g[1]['blue_iou']:.3f}, yellow IoU {g[0]['yellow_iou']:.3f} -> {g[1]['yellow_iou']:.3f}; delta pixels: {gain.sum()} fixed, {loss.sum()} broken", fill=(0, 0, 0))
x = 10
for k, t in enumerate(top):
    sheet.paste(t, (x, 40)); dr.text((x + 4, 40 + t.height + 4), cols[k], fill=(60, 60, 60)); x += t.width + 8
y = 40 + top[0].height + 30
for lbl, t in rows:
    dr.text((10, y), lbl, fill=(0, 0, 0))
    x = 10
    for k, im in enumerate(t):
        sheet.paste(im, (x, y + 14)); x += im.width + 6
    y += t[0].height + 34
dr.text((10, H - 22), "row columns: reference | best | candidate | delta | best clay | candidate clay | best zebra | candidate zebra", fill=(60, 60, 60))
sheet.save(out)
print(out, sheet.size, "fixed", int(gain.sum()), "broken", int(loss.sum()))
