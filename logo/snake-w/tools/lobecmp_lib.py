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
