"""Every visible lobe of the reference against the reconstruction: extracted the same way
from both images (each colour's raw mask, eroded so the creases split it, big joined pairs
split in two), matched by colour and position, and compared: centre, orientation, length,
width, area. Writes a full-image overlay: the reference's lobe outlines (thin, white-edged)
on the render, an arrow from each reference centre to its match, worst lobes numbered."""
import json, sys
import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage
from scipy.optimize import linear_sum_assignment
from skimage import measure
sys.path.insert(0, __file__.rsplit("/", 1)[0])
import snakefit as sf

render, out_png = sys.argv[1], sys.argv[2]

def lobes_of(path):
    _, lab = sf.ref_labels(path, 1.0)
    im = np.asarray(Image.open(path).convert("RGB")).astype(float)
    r, g, b = im[..., 0], im[..., 1], im[..., 2]
    sat = (im.max(-1) - im.min(-1)) / np.maximum(im.max(-1), 1)
    lum = im @ [0.2126, 0.7152, 0.0722]
    raw = np.zeros(lab.shape, np.int8)
    raw[(b > r + 40) & (b > g + 20) & (sat > 0.35) & (lum > 45)] = 1
    raw[(r > b + 60) & (g > b + 40) & (sat > 0.35) & (lum > 120)] = 2
    out = []
    for c, name in [(1, "blue"), (2, "yellow")]:
        m = ndimage.binary_erosion(ndimage.binary_fill_holes(raw == c) & (lab == c), iterations=4)
        cc, k = ndimage.label(m)
        for i in range(1, k + 1):
            mask = cc == i
            ys, xs = np.nonzero(mask)
            if len(xs) < 150: continue
            head = ys.mean() < 400 and (xs.mean() < 420 or xs.mean() > 1040)
            parts = [mask]
            if len(xs) > 13500 and not head:
                X = np.column_stack([xs, ys]).astype(float); cen = X[[np.argmin(xs), np.argmax(xs)]]
                for _ in range(20):
                    l2 = np.argmin(((X[:, None] - cen[None]) ** 2).sum(-1), 1)
                    cen = np.array([X[l2 == j].mean(0) for j in (0, 1)])
                parts = []
                for j in (0, 1):
                    mm = np.zeros_like(mask); mm[ys[l2 == j], xs[l2 == j]] = True; parts.append(mm)
            for mm in parts:
                ys, xs = np.nonzero(mm)
                cov = np.cov(np.vstack([xs, ys])); w, v = np.linalg.eigh(cov)
                ax = v[:, 1]
                # length and width: the extent along each principal axis (5th-95th percentile)
                X = np.column_stack([xs, ys]) - [xs.mean(), ys.mean()]
                pa, pb = X @ v[:, 1], X @ v[:, 0]
                out.append(dict(colour=name, head=bool(head), area=int(len(xs)), cx=float(xs.mean()), cy=float(ys.mean()),
                                angle=float(np.degrees(np.arctan2(ax[1], ax[0]))) % 180,
                                length=float(np.percentile(pa, 97) - np.percentile(pa, 3)), width=float(np.percentile(pb, 97) - np.percentile(pb, 3)),
                                mask=mm))
    return out

R, M = lobes_of("ref/reference.png"), lobes_of(render)
rows = []
for colour in ("blue", "yellow"):
    a = [l for l in R if l["colour"] == colour]; b = [l for l in M if l["colour"] == colour]
    C = np.array([[np.hypot(x["cx"] - y["cx"], x["cy"] - y["cy"]) for y in b] for x in a])
    ia, ib = linear_sum_assignment(C)
    for i, j in zip(ia, ib):
        if C[i, j] > 90: continue
        x, y = a[i], b[j]
        dang = (y["angle"] - x["angle"] + 90) % 180 - 90
        # the reference outline's overlap with the model's lobe
        inter = (x["mask"] & y["mask"]).sum(); iou = inter / (x["mask"] | y["mask"]).sum()
        rows.append(dict(colour=colour, head=x["head"], ref=x, mod=y, d=float(C[i, j]), dang=float(dang),
                         dlen=y["length"] / x["length"], dwid=y["width"] / x["width"], darea=y["area"] / x["area"], iou=float(iou)))
    for i in set(range(len(a))) - set(ia[C[ia, ib] <= 90]):
        rows.append(dict(colour=colour, head=a[i]["head"], ref=a[i], mod=None, d=np.inf, dang=0, dlen=0, dwid=0, darea=0, iou=0.0))
# misalignment score: centre offset, orientation, shape, overlap (heads left out of the ranking)
for r_ in rows:
    r_["score"] = (r_["d"] / 10 + abs(r_["dang"]) / 5 + abs(np.log(r_["dlen"] or 1e-3)) * 10 + abs(np.log(r_["dwid"] or 1e-3)) * 10 + (1 - r_["iou"]) * 10) if r_["mod"] else 99
body = sorted([r_ for r_ in rows if not r_["head"]], key=lambda r_: -r_["score"])
for k, r_ in enumerate(body): r_["rank"] = k + 1
print(f"{'#':>2} {'colour':6} {'ref centre':>12} {'offset px':>9} {'angle deg':>9} {'len x':>6} {'wid x':>6} {'area x':>6} {'IoU':>5}")
for r_ in body:
    x = r_["ref"]
    if r_["mod"] is None: print(f"{r_['rank']:2d} {r_['colour']:6} ({x['cx']:.0f},{x['cy']:.0f})   UNMATCHED"); continue
    print(f"{r_['rank']:2d} {r_['colour']:6} ({x['cx']:4.0f},{x['cy']:4.0f})  {r_['d']:9.1f} {r_['dang']:+9.0f} {r_['dlen']:6.2f} {r_['dwid']:6.2f} {r_['darea']:6.2f} {r_['iou']:5.2f}")
unmatched_model = [l for l in M if not any(r_["mod"] is l for r_ in rows) and not l["head"]]
print("model lobes with no reference counterpart:", [(round(l["cx"]), round(l["cy"]), l["colour"]) for l in unmatched_model])
ious = [r_["iou"] for r_ in body]
print(f"body lobes: {len(body)}; mean IoU {np.mean(ious):.2f}; mean centre offset {np.mean([r_['d'] for r_ in body if r_['mod']]):.1f} px; mean |angle| {np.mean([abs(r_['dang']) for r_ in body if r_['mod']]):.0f} deg")
# overlay
ren = Image.open(render).convert("RGB")
base = Image.blend(ren, Image.new("RGB", ren.size, "white"), 0.35)
d = ImageDraw.Draw(base)
for r_ in rows:
    x = r_["ref"]
    for c in measure.find_contours(x["mask"].astype(float), 0.5):
        pts = [(q[1], q[0]) for q in c[::2]]
        d.line(pts, fill=(255, 255, 255), width=4); d.line(pts, fill=(200, 0, 0) if x["colour"] == "yellow" else (0, 0, 0), width=2)
    if r_["mod"] is not None:
        y = r_["mod"]
        d.line([(x["cx"], x["cy"]), (y["cx"], y["cy"])], fill=(255, 0, 255), width=3)
        d.ellipse([y["cx"] - 4, y["cy"] - 4, y["cx"] + 4, y["cy"] + 4], fill=(255, 0, 255))
    d.ellipse([x["cx"] - 5, x["cy"] - 5, x["cx"] + 5, x["cy"] + 5], outline=(0, 0, 0), width=2)
    if not r_["head"] and r_["rank"] <= 6:
        t = f"{r_['rank']}"
        d.rectangle([x["cx"] + 8, x["cy"] - 22, x["cx"] + 30, x["cy"] - 4], fill=(255, 255, 0)); d.text((x["cx"] + 12, x["cy"] - 20), t, fill=(0, 0, 0))
d.rectangle([0, 0, 760, 44], fill=(255, 255, 255))
d.text((8, 6), "reference lobe outlines (black: blue lobes, red: yellow lobes) over the render; magenta: reference centre -> model centre", fill=(0, 0, 0))
d.text((8, 24), "yellow tags: the six most misaligned body lobes, worst first", fill=(0, 0, 0))
base.crop((150, 60, 1300, 1010)).save(out_png)
json.dump([{k: v for k, v in dict(colour=r_["colour"], head=r_["head"], rank=r_.get("rank"), ref=[round(r_["ref"]["cx"]), round(r_["ref"]["cy"])],
                                   offset=r_["d"], dang=r_["dang"], dlen=r_["dlen"], dwid=r_["dwid"], iou=r_["iou"]).items()} for r_ in rows],
          open(out_png.replace(".png", ".json"), "w"), indent=1, default=float)
