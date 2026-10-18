"""Read the reference directly: spine from the silhouette's medial axis, lobes from colour components."""
import json, sys
import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage
from skimage import morphology, graph
sys.path.insert(0, __file__.rsplit("/", 1)[0])
import snakefit as sf

ref_path, out_dir = sys.argv[1:3]
_, lab = sf.ref_labels(ref_path, 1.0)
obj = lab > 0
im = np.asarray(Image.open(ref_path).convert("RGB")).astype(float)
r, g, b = im[..., 0], im[..., 1], im[..., 2]
sat = (im.max(-1) - im.min(-1)) / np.maximum(im.max(-1), 1)
lum = im @ [0.2126, 0.7152, 0.0722]
raw = np.zeros(lab.shape, np.int8)
raw[(b > r + 40) & (b > g + 20) & (sat > 0.35) & (lum > 45)] = 1
raw[(r > b + 60) & (g > b + 40) & (sat > 0.35) & (lum > 120)] = 2
# lobes: connected components of each colour, after a small erosion so touching lobes split
lobes = []
for c, name in [(1, "blue"), (2, "yellow")]:
    # the raw colour (not the crease-filled labels), so the dark creases separate lobes
    m = ndimage.binary_erosion(ndimage.binary_fill_holes((raw == c)) & (lab == c), iterations=4)
    cc, k = ndimage.label(m)
    parts = []
    for i in range(1, k + 1):
        ys, xs = np.nonzero(cc == i)
        if len(xs) < 150: continue
        # two lobes joined across a faint crease: split along the longer axis (2-means), but
        # not the heads, which are big on their own
        head = ys.mean() < 400 and (xs.mean() < 420 or xs.mean() > 1040)
        if len(xs) > 13500 and not head:
            X = np.column_stack([xs, ys]).astype(float); cen = X[[np.argmin(xs), np.argmax(xs)]]
            for _ in range(20):
                lab2 = np.argmin(((X[:, None] - cen[None]) ** 2).sum(-1), 1)
                cen = np.array([X[lab2 == j].mean(0) for j in (0, 1)])
            parts += [(xs[lab2 == j], ys[lab2 == j]) for j in (0, 1)]
        else:
            parts.append((xs, ys))
    for xs, ys in parts:
        cov = np.cov(np.vstack([xs, ys])); w, v = np.linalg.eigh(cov)
        ax = v[:, 1]
        lobes.append(dict(colour=name, area=int(len(xs)), cx=float(xs.mean()), cy=float(ys.mean()),
                          angle=float(np.degrees(np.arctan2(ax[1], ax[0]))) % 180, elong=float(np.sqrt(w[1] / w[0]))))
# spine: medial axis of the silhouette, the path between the two snout ends
sm = ndimage.gaussian_filter(obj.astype(float), 6) > 0.5
skel = morphology.skeletonize(sm)
pts = np.argwhere(skel)
def nearest(x, y): return int(np.argmin((pts[:, 1] - x) ** 2 + (pts[:, 0] - y) ** 2))
cost = np.where(skel, 1.0, 1e6)
a, b = nearest(300, 335), nearest(1165, 318)
path, _ = graph.route_through_array(cost, tuple(pts[a]), tuple(pts[b]), fully_connected=True, geometric=True)
P = np.array(path, float)[:, ::-1]  # (x, y) image coords
P = ndimage.gaussian_filter1d(P, 8, axis=0, mode="nearest")
d = np.r_[0, np.cumsum(np.linalg.norm(np.diff(P, axis=0), axis=1))]
for L in lobes:
    j = int(np.argmin((P[:, 0] - L["cx"]) ** 2 + (P[:, 1] - L["cy"]) ** 2)); L["s"] = float(d[j])
    t = P[min(j + 5, len(P) - 1)] - P[max(j - 5, 0)]
    L["spine_angle"] = float(np.degrees(np.arctan2(t[1], t[0]))) % 180
lobes.sort(key=lambda L: L["s"])
json.dump({"spine": P.tolist(), "length": float(d[-1]), "lobes": lobes}, open(f"{out_dir}/reading.json", "w"), indent=1)
for L in lobes:
    rel = (L["angle"] - L["spine_angle"] + 90) % 180 - 90
    print(f'{L["colour"]:6s} s={L["s"]:7.1f} c=({L["cx"]:.0f},{L["cy"]:.0f}) area={L["area"]:6d} lobe-vs-spine {rel:+5.0f} deg, elong {L["elong"]:.1f}')
vis = Image.open(ref_path).convert("RGB"); dr = ImageDraw.Draw(vis)
dr.line([tuple(p) for p in P], fill=(220, 0, 0), width=3)
for L in lobes:
    dr.ellipse([L["cx"] - 6, L["cy"] - 6, L["cx"] + 6, L["cy"] + 6], fill=(0, 0, 0))
vis.save(f"{out_dir}/reading.png")
print("spine length", round(d[-1]))
