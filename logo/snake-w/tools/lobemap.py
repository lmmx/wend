"""The lobe-to-surface map of a spec: for every registry lobe, the run of its strand's own
stations that draws the candidate's matching lobe (from the surface-point buffer of a flat render
of the real geometry, lobekit.attribute), as JSON and as a picture. Picture:
  - left, the reference with the registry outlines;
  - right, the candidate surface coloured by station, with each lobe's run marked in its colour
    and labelled "ID strand a-b".
Usage (from the logo root): lobemap.py spec.json OUT.json OUT.png"""
import colorsys, json, os, sys
import numpy as np
from PIL import Image, ImageDraw
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import lobekit as K
from evaluate import boundary

ROOT = os.path.abspath(os.path.join(HERE, ".."))
spec = json.load(open(sys.argv[1]))
tmp = os.path.abspath(os.path.splitext(sys.argv[2])[0])
w = K.Worker(0, ROOT)
try:
    sid, st, psi = K.surface_ids(w, spec, tmp + "-ids.raw")
    w.call(spec_obj=spec, out=tmp + "-flat.png", clip=[0, 0, 1448, 1086])
finally:
    w.close()
Lc = K.lobes(np.asarray(Image.open(tmp + "-flat.png").convert("RGB")))
out = {}
for f in K.FEATS:
    if not f["id"].startswith("L"):
        continue
    a = K.attribute(sid, st, psi, Lc, f["id"])
    out[f["id"]] = {k: v for k, v in a.items() if k != "K"}
json.dump(out, open(sys.argv[2], "w"), indent=1)
# picture
rgb = np.zeros(sid.shape + (3,))
for k in (1, 2):
    m = sid == k
    hue = (st[m] % 80) / 80
    rgb[m] = np.array([colorsys.hsv_to_rgb(h, 0.25, 0.75 if k == 1 else 0.55) for h in hue])
rgb[sid >= 3] = 0.85
pal = [colorsys.hsv_to_rgb(i / 16, 0.9, 1.0) for i in range(16)]
for i, f in enumerate([g for g in K.FEATS if g["id"].startswith("L")]):
    a = out[f["id"]]
    if "error" in a:
        continue
    k = 1 if a["strand"] == "yellow" else 2
    m = (sid == k) & (st >= a["a"]) & (st <= a["b"])
    rgb[m] = 0.45 * rgb[m] + 0.55 * np.array(pal[i])
ref = Image.open(os.path.join(ROOT, "snakes/ref/reference.png")).convert("RGB")
R = np.asarray(ref).copy()
for i, f in enumerate(K.FEATS):
    R[boundary(K.LAB == i + 1)] = (0, 0, 0)
A = Image.fromarray(R); B = Image.fromarray((rgb * 255).astype(np.uint8))
dA, dB = ImageDraw.Draw(A), ImageDraw.Draw(B)
for i, f in enumerate([g for g in K.FEATS if g["id"].startswith("L")]):
    ys, xs = np.nonzero(K.LAB == K.FIDS.index(f["id"]) + 1)
    dA.text((xs.mean() - 10, ys.mean() - 5), f["id"], fill=(0, 0, 0))
    a = out[f["id"]]
    if "error" in a:
        dB.text((xs.mean() - 20, ys.mean() - 5), f"{f['id']} ?", fill=(0, 0, 0)); continue
    k = 1 if a["strand"] == "yellow" else 2
    m = (sid == k) & (st >= a["a"]) & (st <= a["b"])
    yy, xx = np.nonzero(m)
    dB.text((xx.mean() - 30, yy.mean() - 5), f"{f['id']} {a['strand'][0]} {a['a']:.0f}-{a['b']:.0f}", fill=(0, 0, 0))
crop = (150, 230, 1300, 900)
sheet = Image.new("RGB", ((crop[2] - crop[0]) * 2 + 10, crop[3] - crop[1] + 30), (255, 255, 255))
sheet.paste(A.crop(crop), (0, 30)); sheet.paste(B.crop(crop), (crop[2] - crop[0] + 10, 30))
ImageDraw.Draw(sheet).text((8, 8), "reference lobes (registry) | the candidate surface: each lobe's station run (y yellow / b blue strand, own stations), from the surface-point buffer", fill=(0, 0, 0))
sheet.save(sys.argv[3])
for fid, a in out.items():
    print(fid, a.get("strand"), round(a.get("a", 0)), round(a.get("b", 0)), a.get("error", ""), f"frac {a.get('frac', 0):.2f}")
