"""The reference's anatomy: every visible lobe and both heads as a stable, numbered region,
defined on the reference image only (never on a reconstruction), plus the global features.

Regions come from the reference's own colours: saturated blue and yellow pixels (the dark
creases between lobes and the eyes are excluded), split into connected components. Two yellow
components each hold two touching lobes (one in each valley); they are split along their
crease by a seeded watershed on the smoothed luminance (seeds at the two lobes' bright centres).
IDs run along the W from the yellow head to the blue head: H1, L01 .. L16, H2. Negative spaces
(N1..) are the background components enclosed by the W's convex hull.

Writes audit/registry.json (per feature: id, kind, colour, bbox, centroid, area, neighbours),
audit/registry-labels.png (label image, value = index + 1) and audit/reference-annotated.png.
Usage (from the logo root): anatomy.py"""
import json, os
import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage
from skimage import measure, morphology, segmentation, filters

HERE = os.path.dirname(os.path.abspath(__file__))
REF = os.path.join(HERE, "..", "snakes", "ref", "reference.png")
OUT = "audit"


def colour_masks(im):
    im = im.astype(float)
    r, g, b = im[..., 0], im[..., 1], im[..., 2]
    mx = im.max(-1); mn = im.min(-1); sat = (mx - mn) / np.maximum(mx, 1)
    blue = (b > r + 40) & (b > g + 20) & (sat > 0.35)
    yellow = (r > b + 60) & (g > b + 40) & (sat > 0.35)
    return blue, yellow


# the lobes along the W (image x, y of a point inside each), in order from the yellow head.
# Taken from the reference's components (see the docstring); the two merged yellow components
# are split at the seeds marked "split".
ORDER = [
    ("H1", "yellow", (377, 354), "yellow head and neck"),
    ("L01", "blue", (431, 448), "left arm, first blue lobe under the yellow head"),
    ("L02", "yellow", (451, 539), "left arm, yellow lobe"),
    ("L03", "blue", (482, 620), "left arm, lower blue lobe"),
    ("L04", "yellow", (520, 700), "left valley, yellow lobe at the bottom left (split)"),
    ("L05", "blue", (591, 718), "left valley, blue lobe at the bottom"),
    ("L06", "yellow", (632, 640), "left valley, yellow lobe rising to the right (split)"),
    ("L07", "blue", (636, 571), "arch left leg, blue lobe"),
    ("L08", "yellow", (657, 501), "arch left, yellow lobe"),
    ("L09", "blue", (724, 462), "arch top, blue lobe"),
    ("L10", "yellow", (794, 524), "arch right, yellow lobe"),
    ("L11", "blue", (832, 617), "arch right leg, blue lobe descending"),
    ("L12", "yellow", (872, 690), "right valley, yellow lobe at the bottom left (split)"),
    ("L13", "blue", (945, 711), "right valley, blue lobe at the bottom"),
    ("L14", "yellow", (985, 625), "right valley, yellow lobe rising to the right (split)"),
    ("L15", "blue", (1009, 558), "right arm, blue lobe"),
    ("L16", "yellow", (1033, 476), "right arm, yellow lobe"),
    ("H2", "blue", (1078, 354), "blue head and neck"),
]


def build():
    im = np.asarray(Image.open(REF).convert("RGB"))
    blue, yellow = colour_masks(im)
    lum = filters.gaussian(im.astype(float).mean(-1), 3)
    labels = np.zeros(im.shape[:2], int)
    feats = []
    comp = {}
    for name, m in (("blue", blue), ("yellow", yellow)):
        m = morphology.remove_small_objects(m, max_size=400)
        m = ndimage.binary_fill_holes(m)            # eyes and highlights belong to the region
        comp[name] = measure.label(m, connectivity=1)
    # which component holds each seed; components with two seeds are split by watershed
    seeds = {}
    for i, (fid, col, (x, y), _) in enumerate(ORDER):
        c = comp[col][y, x]
        assert c > 0, (fid, "seed outside its colour")
        seeds.setdefault((col, c), []).append(i)
    for (col, c), idx in seeds.items():
        region = comp[col] == c
        if len(idx) == 1:
            labels[region] = idx[0] + 1
            continue
        mk = np.zeros_like(labels)
        for i in idx:
            x, y = ORDER[i][2]
            mk[y - 3:y + 4, x - 3:x + 4] = i + 1
        ws = segmentation.watershed(-lum, mk, mask=region)
        labels[region] = ws[region]
    # global: silhouette and negative spaces inside the convex hull
    sil = labels > 0
    sil_closed = morphology.binary_closing(sil, morphology.disk(4))
    hull = morphology.convex_hull_image(sil_closed)
    neg = measure.label(hull & ~sil_closed, connectivity=1)
    # the big background region over the W holds both V counters and the space above the arch:
    # split it at the arch's left and right shoulders (the tops of L08 and L10's outer edges)
    big = max(measure.regionprops(neg), key=lambda p: p.area).label
    xs = [ORDER[i][2][0] for i in range(len(ORDER))]
    arch = (labels == [f for f, *_ in ORDER].index("L08") + 1) | (labels == [f for f, *_ in ORDER].index("L09") + 1) | (labels == [f for f, *_ in ORDER].index("L10") + 1)
    ax0, ax1 = np.nonzero(arch.any(0))[0][[0, -1]]
    top = np.nonzero(arch.any(1))[0][0]
    yy, xx = np.mgrid[: labels.shape[0], : labels.shape[1]]
    nb = neg == big
    nxt = neg.max() + 1
    neg[nb & (xx < ax0)] = nxt; neg[nb & (xx > ax1)] = nxt + 1
    neg[nb & (xx >= ax0) & (xx <= ax1) & (yy < top + 40)] = nxt + 2
    neg[nb & (xx >= ax0) & (xx <= ax1) & (yy >= top + 40)] = 0
    negs = sorted([p for p in measure.regionprops(neg) if p.area > 2000], key=lambda p: (p.centroid[1]))
    for i, (fid, col, (x, y), desc) in enumerate(ORDER):
        m = labels == i + 1
        p = measure.regionprops(m.astype(int))[0]
        y0, x0, y1, x1 = p.bbox
        feats.append(dict(id=fid, kind="head" if fid.startswith("H") else "lobe", colour=col, desc=desc,
                          bbox=[int(x0), int(y0), int(x1), int(y1)], centroid=[round(p.centroid[1], 1), round(p.centroid[0], 1)],
                          area=int(p.area), seed=[x, y]))
    # neighbours: regions whose dilated masks touch
    for i, f in enumerate(feats):
        d = morphology.binary_dilation(labels == i + 1, morphology.disk(4))
        f["neighbours"] = [feats[j]["id"] for j in np.unique(labels[d]) - 1 if j >= 0 and j != i]
    nfe = []
    for k, p in enumerate(negs):
        y0, x0, y1, x1 = p.bbox
        nfe.append(dict(id=f"N{k + 1}", kind="negative", bbox=[int(x0), int(y0), int(x1), int(y1)],
                        centroid=[round(p.centroid[1], 1), round(p.centroid[0], 1)], area=int(p.area)))
    neglab = np.zeros_like(labels)
    for k, p in enumerate(negs):
        neglab[neg == p.label] = k + 1
    reg = dict(reference="snakes/ref/reference.png", size=[im.shape[1], im.shape[0]], features=feats, negatives=nfe,
               silhouette_area=int(sil.sum()), note="IDs are defined on the reference and never change")
    os.makedirs(OUT, exist_ok=True)
    json.dump(reg, open(f"{OUT}/registry.json", "w"), indent=1)
    Image.fromarray(labels.astype(np.uint8)).save(f"{OUT}/registry-labels.png")
    Image.fromarray(neglab.astype(np.uint8)).save(f"{OUT}/registry-negatives.png")
    # annotated reference: each feature tinted its own colour (adjacent IDs far apart in hue),
    # thick boundaries, IDs; negative spaces hatched green
    import colorsys
    ann = im.astype(float).copy()
    n = len(feats)
    for i in range(n):
        h = (i * 7 % n) / n
        c = np.array(colorsys.hsv_to_rgb(h, 0.9, 1.0)) * 255
        m = labels == i + 1
        ann[m] = 0.45 * ann[m] + 0.55 * c
    bnd = morphology.dilation(segmentation.find_boundaries(labels, mode="inner"), morphology.disk(1))
    ann[bnd] = (0, 0, 0)
    for k in range(1, neglab.max() + 1):
        m = neglab == k
        ann[m & ((np.add.outer(np.arange(m.shape[0]), np.arange(m.shape[1])) // 6) % 2 == 0)] = (150, 220, 150)
    ann = ann.clip(0, 255).astype(np.uint8)
    A = Image.fromarray(ann); d = ImageDraw.Draw(A)
    for f in feats:
        x, y = f["centroid"]
        d.rectangle([x - 16, y - 9, x + 16, y + 9], fill=(255, 255, 255)); d.text((x - 13, y - 6), f["id"], fill=(0, 0, 0))
    for f in nfe:
        x, y = f["centroid"]
        d.text((x - 6, y - 6), f["id"], fill=(0, 120, 0))
    A.crop((260, 240, 1200, 820)).resize((1410, 870), Image.LANCZOS).save(f"{OUT}/reference-annotated.png")
    for f in feats:
        print(f"{f['id']:4s} {f['colour']:6s} area {f['area']:6d} centroid {f['centroid']} bbox {f['bbox']} neighbours {','.join(f['neighbours'])}")
    for f in nfe:
        print(f"{f['id']:4s} negative space area {f['area']} centroid {f['centroid']} bbox {f['bbox']}")


if __name__ == "__main__":
    build()
