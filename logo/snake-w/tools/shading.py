"""Shading as shape evidence: is the heads' 3D form right, independently of the material?

For each head and model: take the model's surface normals (MeshNormalMaterial render, hero
camera), and fit the smooth lighting (second-order spherical harmonics, 9 terms) that best
explains the reference's luminance over the head, leaving out its specular highlights. With
the lighting fitted for each model, what remains is down to the normals: a model whose 3D
form is right explains the reference's shading well and leaves an unstructured residual.

Also: isophotes (lines of equal smoothed luminance) of the reference against those the fitted
lighting predicts, and the highlights of the reference against those of the colour render.
"""
import json, sys
import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage
from skimage import measure
sys.path.insert(0, __file__.rsplit("/", 1)[0])
import snakefit as sf

out_png = sys.argv[1]
models = [a.split("=") for a in sys.argv[2:]]  # label=normals.png=colour.png
srgb_to_lin = lambda c: np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
ref = np.asarray(Image.open("ref/reference.png").convert("RGB")).astype(float) / 255
_, lab = sf.ref_labels("ref/reference.png", 1.0)
HEADS = {"yellow": dict(label=2, seed=(405, 305), box=(280, 270, 520, 510), eye=(369, 336)),
         "blue": dict(label=1, seed=(1060, 300), box=(930, 260, 1170, 500), eye=(1103, 324))}


def lum(rgb): return srgb_to_lin(rgb) @ [0.2126, 0.7152, 0.0722]


def head_mask(labels, h):
    cc, _ = ndimage.label(labels == h["label"])
    return ndimage.binary_fill_holes(cc == cc[h["seed"][1], h["seed"][0]])


def sh9(N):
    x, y, z = N[:, 0], N[:, 1], N[:, 2]
    return np.column_stack([np.ones_like(x), x, y, z, x * y, y * z, x * z, x * x - y * y, 3 * z * z - 1])


Lref = lum(ref)
Lref_s = ndimage.gaussian_filter(Lref, 1.5)
results = {}
panels = {}


def robust_fit(Nm, Lm):
    keep = Lm < np.percentile(Lm, 96)
    for _ in range(3):
        c = np.linalg.lstsq(sh9(Nm[keep]), Lm[keep], rcond=None)[0]
        res = Lm - sh9(Nm) @ c
        sd = res[keep].std(); keep = keep & (np.abs(res) < 2.5 * sd)
    return c, keep

# lighting, fixed: calibrated once per colour on the rope body (geometry both models share,
# and well fitted), with the first model's normals; then applied unchanged to both heads
FIXED = {}
nimg0 = np.asarray(Image.open(models[0][1]).convert("RGB")).astype(float) / 255
N0 = 2 * nimg0 - 1; n0 = np.linalg.norm(N0, axis=2)
_, lab0 = sf.ref_labels(models[0][2], 1.0)
for name, h in HEADS.items():
    heads_px = np.zeros(lab.shape, bool)
    for hh in HEADS.values(): heads_px |= head_mask(lab, hh)
    body = (lab == h["label"]) & (lab0 == h["label"]) & ~ndimage.binary_dilation(heads_px, iterations=12) & (n0 > 0.8)
    body = ndimage.binary_erosion(body, iterations=3)
    c, keep = robust_fit(N0[body] / n0[body][:, None], Lref_s[body])
    pred = sh9(N0[body] / n0[body][:, None]) @ c
    FIXED[name] = c
    print(f"{name}: lighting calibrated on {int(body.sum())} body pixels, body R2 {1 - np.var((Lref_s[body] - pred)[keep]) / np.var(Lref_s[body][keep]):.3f}")
for name, h in HEADS.items():
    mref = head_mask(lab, h)
    eye = np.zeros_like(mref); eye[h["eye"][1] - 22:h["eye"][1] + 22, h["eye"][0] - 22:h["eye"][0] + 22] = True
    for label_, npng, cpng in models:
        nimg = np.asarray(Image.open(npng).convert("RGB")).astype(float) / 255
        N = 2 * nimg - 1   # MeshNormalMaterial writes (n + 1) / 2 without colour encoding: checked, |n| = 1.000
        nrm = np.linalg.norm(N, axis=2)
        _, lab_r = sf.ref_labels(cpng, 1.0)
        mrend = head_mask(lab_r, h)
        mask = ndimage.binary_erosion(mref & mrend & (nrm > 0.8), iterations=3) & ~eye
        Nm = N[mask] / nrm[mask][:, None]
        Lm = Lref_s[mask]
        spec = Lm >= np.percentile(Lm, 96)           # the reference's highlights, left out of the scores
        # fixed lighting (primary): the body-calibrated lighting, unchanged
        pred = sh9(Nm) @ FIXED[name]
        ok = ~spec
        r2 = 1 - np.mean((Lm - pred)[ok] ** 2) / np.var(Lm[ok])
        rel = np.sqrt(np.mean((Lm - pred)[ok] ** 2)) / (np.percentile(Lm, 95) - np.percentile(Lm, 5))
        # fitted lighting (upper bound only): the best this model's normals could do with any smooth lighting
        cf, keep = robust_fit(Nm, Lm)
        pf = sh9(Nm) @ cf
        r2f = 1 - np.var((Lm - pf)[keep]) / np.var(Lm[keep])
        results.setdefault(name, {})[label_] = dict(fixed_lighting_r2=round(float(r2), 3), fixed_lighting_resid_rel=round(float(rel), 3),
                                                     fitted_lighting_r2_upper_bound=round(float(r2f), 3), pixels=int(mask.sum()))
        P = np.full(Lref.shape, np.nan); P[mask] = pred
        Rres = np.full(Lref.shape, np.nan); Rres[mask] = Lm - pred
        panels[(name, label_)] = (mask, P, Rres)
        # the colour render's highlights
        Lc = ndimage.gaussian_filter(lum(np.asarray(Image.open(cpng).convert("RGB")).astype(float) / 255), 1.5)
        panels[(name, label_, "hl")] = Lc
print(json.dumps(results, indent=1))

# drawing
S = 2
def to_img(a, lo, hi, cmap):
    a = np.clip((a - lo) / (hi - lo), 0, 1)
    if cmap == "grey":
        rgb = np.stack([a, a, a], -1)
    else:  # diverging: blue negative, white zero, red positive
        t = 2 * a - 1
        rgb = np.stack([1 - np.clip(-t, 0, 1) * 0 - np.clip(t, 0, 1) * 0, 1 - np.abs(t), 1 - np.clip(t, 0, 1) * 0 - np.clip(-t, 0, 1) * 0], -1)
        rgb[..., 0] = np.where(t < 0, 1 + t, 1.0); rgb[..., 2] = np.where(t > 0, 1 - t, 1.0); rgb[..., 1] = 1 - np.abs(t)
    return (rgb * 255).astype(np.uint8)

rows = []
for name, h in HEADS.items():
    x0, y0, x1, y1 = h["box"]
    mref = head_mask(lab, h)
    tiles = []
    L = Lref_s[y0:y1, x0:x1]
    lo_, hi_ = np.nanpercentile(Lref_s[mref], 2), np.nanpercentile(Lref_s[mref], 99)
    base = to_img(np.where(mref[y0:y1, x0:x1], L, hi_), lo_, hi_, "grey")
    tiles.append(("reference luminance", base, None))
    for label_, _, cpng in models:
        mask, P, Rres = panels[(name, label_)]
        pt = to_img(np.where(mask[y0:y1, x0:x1], P[y0:y1, x0:x1], hi_), lo_, hi_, "grey")
        rt = to_img(np.where(mask[y0:y1, x0:x1], Rres[y0:y1, x0:x1], 0), -0.25 * (hi_ - lo_), 0.25 * (hi_ - lo_), "div")
        tiles.append((f"{label_}: shading its normals predict (fixed light)", pt, (mask, P)))
        tiles.append((f"{label_}: reference minus prediction", rt, None))
    imgs = []
    for title, arr, iso in tiles:
        im = Image.fromarray(arr).resize(((x1 - x0) * S, (y1 - y0) * S), Image.NEAREST)
        d = ImageDraw.Draw(im)
        # isophotes: reference in red on every tile; prediction in blue on prediction tiles
        levels = np.linspace(lo_, hi_, 9)[1:-1]
        for lev in levels:
            for cnt in measure.find_contours(np.where(mref[y0:y1, x0:x1], L, np.nan), lev):
                d.line([(c[1] * S, c[0] * S) for c in cnt], fill=(220, 30, 30), width=1)
            if iso is not None:
                mask, P = iso
                for cnt in measure.find_contours(np.where(mask[y0:y1, x0:x1], P[y0:y1, x0:x1], np.nan), lev):
                    d.line([(c[1] * S, c[0] * S) for c in cnt], fill=(30, 90, 230), width=1)
        d.rectangle([0, 0, im.width, 18], fill=(255, 255, 255)); d.text((4, 3), f"{name}: {title}", fill=(0, 0, 0))
        imgs.append(im)
    # highlights: reference (red) and each colour render (cyan), on the reference crop
    refc = Image.open("ref/reference.png").convert("RGB").crop(h["box"]).resize(((x1 - x0) * S, (y1 - y0) * S), Image.LANCZOS)
    for label_, _, cpng in models:
        im = refc.copy(); d = ImageDraw.Draw(im)
        Lc = panels[(name, label_, "hl")]
        mask = panels[(name, label_)][0]
        for Lx, col in ((Lref_s, (230, 0, 0)), (Lc, (0, 200, 230))):
            thr = np.percentile(Lx[mask], 93)
            for cnt in measure.find_contours(np.where(mask, Lx, 0)[y0:y1, x0:x1], thr):
                d.line([(c[1] * S, c[0] * S) for c in cnt], fill=col, width=2)
        d.rectangle([0, 0, im.width, 18], fill=(255, 255, 255)); d.text((4, 3), f"{name}: brightest 7% - red reference, cyan {label_} render", fill=(0, 0, 0))
        imgs.append(im)
    rows.append(imgs)
W = max(sum(i.width for i in r) for r in rows); H = sum(r[0].height for r in rows)
sheet = Image.new("RGB", (W, H), "white"); y = 0
for r in rows:
    x = 0
    for im in r: sheet.paste(im, (x, y)); x += im.width
    y += r[0].height
sheet.save(out_png)
