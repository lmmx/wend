"""Independent evaluator: a real Three.js render against the reference, feature by feature, using
the reference's registry (tools/anatomy.py). It never uses the JAX surrogate.

Per feature F (a reference lobe or head of colour c, mask R):
  match       the candidate's lobe region of colour c that overlaps R most. Candidate lobes are
              split from each colour's mask by a watershed on its smoothed distance transform
              (markers: h-maxima, h = 5 px), a rule that reproduces the reference registry itself
              (all 18 features at IoU >= 0.97), so touching lobes of one colour stay separate
  iou         IoU of R and the match
  dx, dy      centroid offset of the match from R (px, +x right, +y down)
  area        area ratio match / R
  ext         extremal offsets of the match's bounding box against R's: left, right, top, bottom
              (px; + means the candidate's edge lies further right / further down)
  sdist       symmetric boundary distance between R and the match: mean and 95th percentile (px)
  side        signed boundary error per side of R (E, W, N, S by the boundary's outward normal):
              mean of the match's signed distance at R's boundary points; + = the candidate falls
              short of R there, - = it overshoots (px)
  cover       fractions of R that the candidate shows as colour c, the other colour, background
  merged      other reference features of colour c that the match also covers (> 15% of them):
              the candidate shows two reference lobes as one
  tilt        orientation of the match's principal axis minus R's (degrees, + = turned
              anticlockwise on screen), from image moments
  elong       elongation (major / minor axis) of the match and of R: a rope-like lobe is longer
              and thinner than a cushion-like one
  seg         validity of the candidate-side split, which the reference self-test cannot vouch
              for on a different image: "merged" (the match also covers > 15% of another
              reference lobe of the same colour), "split" (R falls across two or more candidate
              regions, each > 20% of R), "unstable" (the match's IoU with R moves by > 0.1 when the
              split's h is 3 or 8 instead of 5). A flagged feature's metric severity is uncertain:
              it may be a segmentation artefact rather than a geometry error
  crease      surface: 99th percentile of |Laplacian| of the clay render inside the match, away
              from its outline (higher = creases, pinches, dimples), when a clay render is given
  fold_vis    visible folded surface area (px^2) inside F's window, from mesh_check --dump
Global: silhouette IoU and boundary distance (mean, p95, max), blue and yellow IoU, and for each
negative space the fraction the candidate intrudes on.
A metric severity 0-5 per feature combines these with fixed thresholds (documented in severity()).

Usage (from the logo root): evaluate.py colour.png [--clay clay.png] [--folds dump.json] [--out m.json]"""
import argparse, json, os
import numpy as np
from PIL import Image
from scipy import ndimage
from skimage import measure, morphology, segmentation, filters

HERE = os.path.dirname(os.path.abspath(__file__))
import sys
sys.path.insert(0, HERE)
from anatomy import colour_masks


def load_registry(d="audit"):
    reg = json.load(open(f"{d}/registry.json"))
    lab = np.asarray(Image.open(f"{d}/registry-labels.png")).astype(int)
    neg = np.asarray(Image.open(f"{d}/registry-negatives.png")).astype(int)
    return reg, lab, neg


def window(f, pad=30, size=(1448, 1086)):
    x0, y0, x1, y1 = f["bbox"]
    return max(0, x0 - pad), max(0, y0 - pad), min(size[0], x1 + pad), min(size[1], y1 + pad)


def sdf(mask):
    """Signed distance: + outside the mask, - inside (px)."""
    return ndimage.distance_transform_edt(~mask) - ndimage.distance_transform_edt(mask)


def boundary(mask):
    return segmentation.find_boundaries(mask, mode="inner")


def split_lobes(m, h=5.0):
    """Split a colour mask into lobes: watershed on the smoothed distance transform, markers at
    its h-maxima. On the reference this reproduces the registry (min IoU 0.97)."""
    e = filters.gaussian(ndimage.distance_transform_edt(m), 2)
    mk = measure.label(morphology.h_maxima(e, h))
    return segmentation.watershed(-e, mk, mask=m)


def severity(m):
    """0 (matches) .. 5 (wrong): the worst of
       IoU      >= .85 0, .75 1, .65 2, .5 3, .35 4, else 5
       p95 dist <= 6 0, 10 1, 16 2, 24 3, 35 4, else 5
       centroid <= 4 0, 8 1, 14 2, 20 3, 30 4, else 5
       merged: at least 4; missing: 5"""
    if m.get("missing"):
        return 5
    s_iou = next(i for i, t in enumerate([.85, .75, .65, .5, .35, -1]) if m["iou"] >= t)
    s_d = next(i for i, t in enumerate([6, 10, 16, 24, 35, 1e9]) if m["sdist"]["p95"] <= t)
    c = float(np.hypot(m["dx"], m["dy"]))
    s_c = next(i for i, t in enumerate([4, 8, 14, 20, 30, 1e9]) if c <= t)
    s = max(s_iou, s_d, s_c)
    if m["merged"]:
        s = max(s, 4)
    return int(s)


def evaluate(colour_path, clay_path=None, folds_path=None, reg_dir="audit"):
    reg, lab, neglab = load_registry(reg_dir)
    im = np.asarray(Image.open(colour_path).convert("RGB"))
    assert im.shape[:2] == lab.shape, (im.shape, lab.shape)
    blue, yellow = colour_masks(im)
    cand = {"blue": ndimage.binary_fill_holes(morphology.remove_small_objects(blue, max_size=150)),
            "yellow": ndimage.binary_fill_holes(morphology.remove_small_objects(yellow, max_size=150))}
    comps = {c: split_lobes(m) for c, m in cand.items()}
    alt = {h: {c: split_lobes(m, h) for c, m in cand.items()} for h in (3.0, 8.0)}
    refcol = {}
    rb, ry = colour_masks(np.asarray(Image.open(os.path.join(HERE, "..", reg["reference"])).convert("RGB")))
    feats = reg["features"]
    for i, f in enumerate(feats):
        refcol.setdefault(f["colour"], np.zeros_like(lab, bool))
        refcol[f["colour"]] |= lab == i + 1
    clay = None
    if clay_path:
        g = np.asarray(Image.open(clay_path).convert("L")).astype(float)
        if g.shape != lab.shape:
            g = np.asarray(Image.fromarray(g.astype(np.uint8)).resize(lab.shape[::-1], Image.LANCZOS)).astype(float)
        clay = np.abs(filters.laplace(filters.gaussian(g, 1.0)))
    folds = json.load(open(folds_path)) if folds_path else None
    out = {"features": {}, "global": {}}
    for i, f in enumerate(feats):
        R = lab == i + 1
        c, other = f["colour"], ("yellow" if f["colour"] == "blue" else "blue")
        L = comps[c]
        ids, cnt = np.unique(L[R], return_counts=True)
        cnt = cnt[ids > 0]; ids = ids[ids > 0]
        m = {"id": f["id"], "colour": c}
        m["cover"] = {"same": float(cand[c][R].mean()), "other": float((cand[other] & ~cand[c])[R].mean()),
                      "background": float((~cand[c] & ~cand[other])[R].mean())}
        if not len(ids):
            m.update(missing=True, severity=5); out["features"][f["id"]] = m; continue
        K = L == ids[np.argmax(cnt)]
        inter = (K & R).sum(); union = (K | R).sum()
        m["iou"] = float(inter / union)
        ry_, rx_ = np.nonzero(R); ky, kx = np.nonzero(K)
        m["dx"], m["dy"] = float(kx.mean() - rx_.mean()), float(ky.mean() - ry_.mean())
        m["area"] = float(K.sum() / R.sum())
        m["ext"] = {"left": int(kx.min() - rx_.min()), "right": int(kx.max() - rx_.max()),
                    "top": int(ky.min() - ry_.min()), "bottom": int(ky.max() - ry_.max())}
        bR, bK = boundary(R), boundary(K)
        dK = ndimage.distance_transform_edt(~bK); dR = ndimage.distance_transform_edt(~bR)
        d = np.r_[dK[bR], dR[bK]]
        m["sdist"] = {"mean": float(d.mean()), "p95": float(np.percentile(d, 95))}
        # signed error per side of R: R's outward normal from its own sdf gradient
        phiK = sdf(K); phiR = filters.gaussian(sdf(R), 2)
        gy, gx = np.gradient(phiR)
        by, bx = np.nonzero(bR)
        nx, ny = gx[by, bx], gy[by, bx]
        ang = np.degrees(np.arctan2(-ny, nx)) % 360          # 0 = east, 90 = north (image up)
        side = {}
        for nm, a0 in (("E", 0), ("N", 90), ("W", 180), ("S", 270)):
            sel = np.abs(((ang - a0 + 180) % 360) - 180) < 45
            # R's own inner boundary sits at -1 in an sdf: report relative to that
            side[nm] = float(phiK[by[sel], bx[sel]].mean() + 1) if sel.any() else None
        m["side"] = side
        pR, pK = measure.regionprops(R.astype(int))[0], measure.regionprops(K.astype(int))[0]
        dth = np.degrees(pK.orientation - pR.orientation)
        m["tilt"] = float((dth + 90) % 180 - 90)
        m["elong"] = {"cand": float(pK.major_axis_length / max(pK.minor_axis_length, 1)), "ref": float(pR.major_axis_length / max(pR.minor_axis_length, 1))}
        merged = []
        for j, g in enumerate(feats):
            if j == i or g["colour"] != c:
                continue
            Rj = lab == j + 1
            if (K & Rj).sum() > 0.15 * Rj.sum():
                merged.append(g["id"])
        m["merged"] = merged
        seg = []
        if merged:
            seg.append("merged")
        if (cnt > 0.2 * R.sum()).sum() >= 2:
            seg.append("split")
        for h, cc in alt.items():
            Lh = cc[c]; idh, cth = np.unique(Lh[R], return_counts=True); cth = cth[idh > 0]; idh = idh[idh > 0]
            if len(idh):
                Kh = Lh == idh[np.argmax(cth)]
                if abs((Kh & R).sum() / (Kh | R).sum() - m["iou"]) > 0.1:
                    seg.append("unstable"); break
        m["seg"] = seg
        if clay is not None:
            inner = morphology.erosion(K, morphology.disk(6))
            m["crease"] = float(np.percentile(clay[inner], 99)) if inner.any() else None
        if folds is not None:
            x0, y0, x1, y1 = window(f, 0)
            pts = [p for p in folds["visible_fold"] if x0 <= p[0] <= x1 and y0 <= p[1] <= y1 and lab[int(p[1]), int(p[0])] == i + 1]
            m["fold_vis"] = float(sum(p[2] for p in pts))
        m["severity"] = severity(m)
        out["features"][f["id"]] = m
    # silhouettes: the colour regions with the thin dark creases between lobes closed, for both
    def silhouette(m):
        return ndimage.binary_fill_holes(morphology.closing(m, morphology.disk(4)))
    S_ref = silhouette(lab > 0)
    S = silhouette(cand["blue"] | cand["yellow"])
    g = out["global"]
    g["silhouette_iou"] = float((S & S_ref).sum() / (S | S_ref).sum())
    bR, bS = boundary(S_ref), boundary(S)
    d = np.r_[ndimage.distance_transform_edt(~bS)[bR], ndimage.distance_transform_edt(~bR)[bS]]
    g["silhouette_dist"] = {"mean": float(d.mean()), "p95": float(np.percentile(d, 95)), "max": float(d.max())}
    for c in ("blue", "yellow"):
        g[f"{c}_iou"] = float((cand[c] & refcol[c]).sum() / (cand[c] | refcol[c]).sum())
    g["negatives"] = {}
    for n in reg["negatives"]:
        k = int(n["id"][1:])
        N = neglab == k
        g["negatives"][n["id"]] = {"intrusion": float(S[N].mean())}
    return out


def table(m):
    rows = ["| ID | sev | IoU | dx, dy | area | p95 dist | sides E/N/W/S (+ short, - over) | merged | seg flags | crease | fold px² | tilt ° | elong cand / ref |",
            "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for fid, x in m["features"].items():
        if x.get("missing"):
            rows.append(f"| {fid} | 5 | missing | | | | | | | |"); continue
        sd = " / ".join("-" if x["side"][k] is None else f"{x['side'][k]:+.0f}" for k in "ENWS")
        rows.append(f"| {fid} | {x['severity']} | {x['iou']:.2f} | {x['dx']:+.0f}, {x['dy']:+.0f} | {x['area']:.2f} | {x['sdist']['p95']:.0f} | {sd} | "
                    f"{','.join(x['merged'])} | {','.join(x.get('seg', []))} | {'' if x.get('crease') is None else f'{x['crease']:.1f}'} | {'' if x.get('fold_vis') is None else f'{x['fold_vis']:.0f}'} | {x.get('tilt', 0):+.0f} | {x['elong']['cand']:.2f} / {x['elong']['ref']:.2f} |")
    g = m["global"]
    rows.append("")
    rows.append(f"Global: silhouette IoU {g['silhouette_iou']:.3f}, boundary distance mean {g['silhouette_dist']['mean']:.1f} / p95 {g['silhouette_dist']['p95']:.1f} / max {g['silhouette_dist']['max']:.0f} px; "
                f"blue IoU {g['blue_iou']:.3f}, yellow IoU {g['yellow_iou']:.3f}; negative-space intrusion " +
                ", ".join(f"{k} {v['intrusion']:.1%}" for k, v in g["negatives"].items()))
    return "\n".join(rows)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("colour"); ap.add_argument("--clay"); ap.add_argument("--folds"); ap.add_argument("--out")
    A = ap.parse_args()
    m = evaluate(A.colour, A.clay, A.folds)
    if A.out:
        json.dump(m, open(A.out, "w"), indent=1)
    print(table(m))
