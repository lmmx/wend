"""Geometry-only measurements of the frozen final W (r28-hybR geometry, look6 render) against the
reference: the W-spine (medial path of the silhouette), the band's width and centre along it, the
front-strand colour phase along it, the turning points, per-lobe placement vs volume, and the
strands' 3D sections (tube rings, and the hybrid overlay's rings where it replaces the tube).

Writes geo/diag.json (+ geo/diag.npz with the arrays the sheets draw). No geometry is changed.
Usage (from the workspace root): python geo/measure.py
"""

import base64
import json
import sys

import numpy as np
from PIL import Image
from scipy import ndimage, sparse
from scipy.sparse import csgraph
from skimage import filters, morphology


sys.path.insert(0, "tools")
from anatomy import colour_masks
from evaluate import load_registry, split_lobes


E = np.radians(3.7746862033886837)
CE, SE = np.cos(E), np.sin(E)
SRC = {"ref": "snakes/ref/reference.png", "cand": "look/look6.png"}


def to_img(P):
    P = np.atleast_2d(P)
    return np.c_[P[:, 0], P[:, 1] * -CE + P[:, 2] * SE]


def masks(path):
    im = np.asarray(Image.open(path).convert("RGB"))
    b, y = colour_masks(im)
    b = morphology.remove_small_objects(b, max_size=150)
    y = morphology.remove_small_objects(y, max_size=150)
    sil = ndimage.binary_fill_holes(
        morphology.binary_closing(b | y, morphology.disk(2))
    )
    sil = morphology.remove_small_objects(sil, max_size=2000)
    lab = np.zeros(sil.shape, np.int8)
    lab[sil] = 3
    lab[y] = 2
    lab[b] = 1  # 1 blue 2 yellow 3 other (eyes, AA edge)
    return im, sil, lab


def spine(sil, a=(372, 340), b=(1095, 322), smooth=24):
    """the W-spine: the shortest skeleton path between the two head points, of the silhouette
    blurred enough to fill the lobe notches; smoothed and resampled every 2 px"""
    m = filters.gaussian(sil.astype(float), smooth) > 0.5
    sk = morphology.skeletonize(m)
    ys, xs = np.nonzero(sk)
    idx = -np.ones(sk.shape, int)
    idx[ys, xs] = np.arange(len(xs))
    rows, cols, w = [], [], []
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dx == dy == 0:
                continue
            y2, x2 = ys + dy, xs + dx
            ok = (y2 >= 0) & (y2 < sk.shape[0]) & (x2 >= 0) & (x2 < sk.shape[1])
            j = np.full(len(xs), -1)
            j[ok] = idx[y2[ok], x2[ok]]
            ok = j >= 0
            rows += list(np.nonzero(ok)[0])
            cols += list(j[ok])
            w += [np.hypot(dx, dy)] * ok.sum()
    G = sparse.csr_matrix((w, (rows, cols)), shape=(len(xs), len(xs)))
    near = lambda p: int(np.argmin((xs - p[0]) ** 2 + (ys - p[1]) ** 2))
    i0, i1 = near(a), near(b)
    _, pred = csgraph.dijkstra(G, indices=i0, return_predecessors=True)
    path = [i1]
    while path[-1] != i0:
        path.append(pred[path[-1]])
    P = np.c_[xs[path[::-1]], ys[path[::-1]]].astype(float)
    P = ndimage.gaussian_filter1d(P, 6, axis=0, mode="nearest")
    return resample(P, 2.0)


def resample(P, step):
    d = np.r_[0, np.cumsum(np.hypot(*np.diff(P, axis=0).T))]
    t = np.arange(0, d[-1], step)
    return np.c_[np.interp(t, d, P[:, 0]), np.interp(t, d, P[:, 1])]


def frame(P):
    T = np.gradient(P, axis=0)
    T /= np.linalg.norm(T, axis=1)[:, None]
    N = np.c_[
        -T[:, 1], T[:, 0]
    ]  # left of travel (left head -> right head): image "up" on a rising stretch
    return T, N


def chords(mask, P, N, reach=140):
    """along each spine normal: the extent of the mask on either side (first exit), px"""
    t = np.arange(0, reach, 0.5)
    out = np.zeros((len(P), 2))
    for k, sgn in enumerate((1, -1)):
        X = P[:, None, :] + sgn * t[None, :, None] * N[:, None, :]
        xi = np.clip(np.round(X[..., 0]).astype(int), 0, mask.shape[1] - 1)
        yi = np.clip(np.round(X[..., 1]).astype(int), 0, mask.shape[0] - 1)
        inside = mask[yi, xi]
        first_out = np.argmax(~inside, axis=1)
        first_out[inside.all(1)] = len(t) - 1
        out[:, k] = t[first_out]
    return out  # [+N extent, -N extent]


def runs(c):
    """[(start, end, value)] of a label sequence"""
    cut = np.r_[0, np.nonzero(np.diff(c))[0] + 1, len(c)]
    return [(int(a), int(b), int(c[a])) for a, b in zip(cut[:-1], cut[1:])]


def turning(P, arc):
    """the head ends, the two valley bottoms (largest y) and the arch top (smallest y between)"""
    y = ndimage.gaussian_filter1d(P[:, 1], 10)
    n = len(y)
    h = n // 2
    v1 = int(np.argmax(y[:h]))
    v2 = h + int(np.argmax(y[h:]))
    top = v1 + int(np.argmin(y[v1:v2]))
    return {"head_L": 0, "valley_L": v1, "arch": top, "valley_R": v2, "head_R": n - 1}


def ring_metrics(R):
    """R: (m, radial, 3). Per ring: mean radius, ellipticity (max-min)/mean, harmonic amplitudes
    a2 (oval) and a3+ (lumps) of the radial distance, each / mean"""
    C = R.mean(1)
    d = np.linalg.norm(R - C[:, None], axis=2)
    F = np.abs(np.fft.rfft(d, axis=1)) / d.shape[1] * 2
    mean = d.mean(1)
    return {
        "C": C,
        "rho": mean,
        "ell": (d.max(1) - d.min(1)) / mean,
        "a2": F[:, 2] / mean,
        "a3": np.sqrt((F[:, 3:9] ** 2).sum(1)) / mean,
    }


def proj_width(R):
    """per ring: its projected extent across the projected centreline (what the camera sees)"""
    C = to_img(R.mean(1))
    T = np.gradient(C, axis=0)
    T /= np.linalg.norm(T, axis=1)[:, None]
    N = np.c_[-T[:, 1], T[:, 0]]
    Q = np.stack([to_img(r) for r in R])
    u = ((Q - C[:, None]) * N[:, None]).sum(2)
    return u.max(1) - u.min(1)


def main():
    reg, LAB, _ = load_registry()
    feats = {f["id"]: f for f in reg["features"]}
    M = {k: masks(p) for k, p in SRC.items()}
    sil_r, sil_c = M["ref"][1], M["cand"][1]
    out = {"silhouette_iou": float((sil_r & sil_c).sum() / (sil_r | sil_c).sum())}
    # --- W-spine, band width/centre, phase
    Sr = spine(sil_r)
    Sc = spine(sil_c)
    T, N = frame(Sr)
    arc = np.arange(len(Sr)) * 2.0
    cr, cc = chords(sil_r, Sr, N), chords(sil_c, Sr, N)
    width_r, width_c = cr.sum(1), cc.sum(1)
    mid_r, mid_c = (
        (cr[:, 0] - cr[:, 1]) / 2,
        (cc[:, 0] - cc[:, 1]) / 2,
    )  # chord centre along +N
    # the candidate spine's offset along the reference normal (nearest point)
    from scipy.spatial import cKDTree

    kd = cKDTree(Sc)
    _, j = kd.query(Sr)
    sp_off = ((Sc[j] - Sr) * N).sum(1)
    lab_r, lab_c = M["ref"][2], M["cand"][2]
    xi = np.clip(np.round(Sr[:, 0]).astype(int), 0, 1447)
    yi = np.clip(np.round(Sr[:, 1]).astype(int), 0, 1085)
    ph_r, ph_c = lab_r[yi, xi], lab_c[yi, xi]

    # colour transitions along the spine (front strand switches), and their shift
    def trans(c):
        c = c.copy()
        c[(c == 0) | (c == 3)] = 0
        k = np.nonzero(c)[0]
        cf = c.copy()
        cf[:] = np.interp(np.arange(len(c)), k, c[k]).round()  # fill gaps
        cf = ndimage.median_filter(cf, 5)
        t = np.nonzero(np.diff(cf))[0]
        return cf, [(int(i), int(cf[i]), int(cf[i + 1])) for i in t]

    phr, tr = trans(ph_r)
    phc, tc = trans(ph_c)
    shifts = []
    for i, a, b in tr:
        best = None
        for k, a2, b2 in tc:
            if (
                (a2, b2) == (a, b)
                and abs(k - i) < 30
                and (best is None or abs(k - i) < abs(best - i))
            ):
                best = k
        shifts.append(
            {
                "i": i,
                "arc": i * 2.0,
                "kind": f"{'BY'[a - 1]}->{'BY'[b - 1]}",
                "shift_px": None if best is None else (best - i) * 2.0,
            }
        )
    # local half-period from the reference's own transitions
    ti = np.array([s["i"] for s in shifts])
    for k, s in enumerate(shifts):
        nb = np.diff(ti)[max(0, k - 1) : k + 1] * 2.0
        s["half_period_px"] = float(nb.mean()) if len(nb) else None
        s["phase_deg"] = (
            None
            if s["shift_px"] is None or not s["half_period_px"]
            else 180.0 * s["shift_px"] / s["half_period_px"]
        )
    tp_r, tp_c = turning(Sr, arc), turning(Sc, arc)
    tps = {
        k: {
            "ref": Sr[tp_r[k]].tolist(),
            "cand": Sc[tp_c[k]].tolist(),
            "d": (Sc[tp_c[k]] - Sr[tp_r[k]]).tolist(),
        }
        for k in tp_r
    }
    out.update(
        {
            "spine_len": {"ref": float(arc[-1]), "cand": float(len(Sc) * 2.0)},
            "turning": tps,
            "phase": shifts,
        }
    )

    # --- per-lobe placement vs volume
    def lobe_masks_cand():
        im = M["cand"][0]
        b, y = colour_masks(im)
        L = {}
        for c, m in (("blue", b), ("yellow", y)):
            L[c] = split_lobes(
                ndimage.binary_fill_holes(
                    morphology.remove_small_objects(m, max_size=150)
                )
            )
        return L

    Lc = lobe_masks_cand()
    lobes = {}
    lobe_c = {}
    for fid, f in feats.items():
        R = LAB == (list(feats).index(fid) + 1)
        if R.sum() == 0:
            continue
        ids, cnt = np.unique(Lc[f["colour"]][R], return_counts=True)
        cnt = cnt[ids > 0]
        ids = ids[ids > 0]
        if not len(ids):
            continue
        C = Lc[f["colour"]] == ids[np.argmax(cnt)]
        lobe_c[fid] = C

        def stats(m):
            dt = ndimage.distance_transform_edt(m)
            sk = morphology.skeletonize(m)
            yy, xx = np.nonzero(m)
            cov = np.cov(np.c_[xx, yy].T)
            w, v = np.linalg.eigh(cov)
            ang = np.degrees(np.arctan2(v[1, 1], v[0, 1])) % 180
            return {
                "area": int(m.sum()),
                "cx": float(xx.mean()),
                "cy": float(yy.mean()),
                "thick": float(2 * dt.max()),
                "thick_med": float(2 * np.median(dt[sk])) if sk.any() else 0.0,
                "len": float(4 * np.sqrt(w[1])),
                "ang": float(ang),
                "top": int(yy.min()),
                "bottom": int(yy.max()),
                "left": int(xx.min()),
                "right": int(xx.max()),
            }

        a, b = stats(R), stats(C)
        # visible-axis offset: mean distance from the candidate lobe's skeleton to the reference lobe's skeleton
        skr = np.c_[np.nonzero(morphology.skeletonize(R))[::-1]]
        skc = np.c_[np.nonzero(morphology.skeletonize(C))[::-1]]
        d1 = cKDTree(skr).query(skc)[0] if len(skr) and len(skc) else np.array([0.0])
        dang = (b["ang"] - a["ang"] + 90) % 180 - 90
        lobes[fid] = {
            "colour": f["colour"],
            "ref": a,
            "cand": b,
            "iou": float((R & C).sum() / (R | C).sum()),
            "dx": b["cx"] - a["cx"],
            "dy": b["cy"] - a["cy"],
            "dang": dang,
            "axis_mean": float(d1.mean()),
            "axis_p90": float(np.percentile(d1, 90)),
            "thick_ratio": b["thick"] / a["thick"],
            "thick_med_ratio": b["thick_med"] / max(a["thick_med"], 1e-6),
            "len_ratio": b["len"] / a["len"],
            "area_ratio": b["area"] / a["area"],
        }
    out["lobes"] = lobes
    # --- strands: projected centrelines, the model spine, sections
    G = json.load(open("geo/strands.json"))
    spec = json.load(open("snakes/w-final.spec.json"))
    extra = json.load(open("snakes/w-final.extra.json"))
    rings = json.load(open("poc/right/inc-rings.json"))
    arrays = {
        "Sr": Sr,
        "Sc": Sc,
        "N": N,
        "cr": cr,
        "cc": cc,
        "width_r": width_r,
        "width_c": width_c,
        "mid_r": mid_r,
        "mid_c": mid_c,
        "sp_off": sp_off,
        "ph_r": phr,
        "ph_c": phc,
        "model_spine": to_img(np.array(G["spine"])),
    }
    strands = {}
    for name in ("yellow", "blue"):
        g = G[name]
        P = np.array(g["pts"])
        Q = np.array(g["mate"])
        W = np.array(g["mateW"])
        arrays[f"{name}_pts"] = to_img(np.array(g["rendered"]["pts"]))
        arrays[f"{name}_eff"] = to_img((P + Q)[W > 0.5] / 2)
        arrays[f"{name}_helixR"] = np.c_[
            np.array(g["s"])[W > 0.5], np.linalg.norm(P - Q, axis=1)[W > 0.5] / 2
        ]
        rg = rings[name]
        m, rad = rg["m"], rg["radial"]
        R = (
            np.frombuffer(base64.b64decode(rg["rings"]), np.float32)
            .reshape(m, rad, 3)
            .astype(float)
        )
        s = np.array(rg["s"])
        rm = ring_metrics(R)
        pw = proj_width(R)
        cut = extra["cut"][name]
        cen = np.array(rg["centres"])
        ov = []
        for mesh in extra["meshes"][name]:
            X = (
                np.frombuffer(base64.b64decode(mesh["positions64"]), np.float32)
                .reshape(-1, rad, 3)
                .astype(float)
            )
            om = ring_metrics(X)
            opw = proj_width(X)
            jj = cKDTree(rm["C"]).query(om["C"])[1]
            disp = np.linalg.norm(X - R[jj], axis=2)
            ov.append(
                {
                    "s": s[jj],
                    "rho": om["rho"],
                    "ell": om["ell"],
                    "a2": om["a2"],
                    "a3": om["a3"],
                    "pw": opw,
                    "disp_mean": disp.mean(1),
                    "disp_max": disp.max(1),
                    "C": to_img(om["C"]),
                }
            )
        # station -> lobe (projected centre inside the candidate's lobe of this colour)
        Ci = to_img(rm["C"])
        xi = np.clip(np.round(Ci[:, 0]).astype(int), 0, 1447)
        yi = np.clip(np.round(Ci[:, 1]).astype(int), 0, 1085)
        lobe_of = np.full(m, "", object)
        for fid, C in lobe_c.items():
            if feats[fid]["colour"] == name:
                lobe_of[C[yi, xi]] = fid
        lruns = []
        for a, b, _ in runs(np.unique(lobe_of, return_inverse=True)[1]):
            if lobe_of[a] and b - a > 4:
                lruns.append((lobe_of[a], float(s[a]), float(s[b - 1])))
        strands[name] = {
            "lobe_runs": lruns,
            "cut": cut,
            "disp": spec[name]["disp"],
            "s0": spec[name]["s0"],
            "s1": spec[name]["s1"],
            "sec": spec[name]["sec"],
        }
        arrays[f"{name}_s"] = s
        arrays[f"{name}_r"] = (
            np.array(g["rendered"]["r"])[:m]
            if len(g["rendered"]["r"]) >= m
            else np.interp(s, np.array(g["s"]), np.array(g["r"]))
        )
        for k in ("rho", "ell", "a2", "a3"):
            arrays[f"{name}_{k}"] = rm[k]
        arrays[f"{name}_pw"] = pw
        arrays[f"{name}_C"] = Ci
        for i, o in enumerate(ov):
            for k, v in o.items():
                arrays[f"{name}_ov{i}_{k}"] = v
        strands[name]["n_ov"] = len(ov)
    out["strands"] = strands
    json.dump(out, open("geo/diag.json", "w"), indent=1, default=float)
    np.savez_compressed("geo/diag.npz", **arrays)
    np.save(
        "geo/lobes_cand.npy",
        np.stack([lobe_c.get(f, np.zeros_like(sil_r)) for f in feats]),
    )
    print(
        json.dumps(
            {k: out[k] for k in ("silhouette_iou", "spine_len", "turning")}, indent=1
        )
    )
    for s in shifts:
        print(s)
    for fid, l in lobes.items():
        print(
            f"{fid} {l['colour'][0]} iou {l['iou']:.3f} d=({l['dx']:+5.1f},{l['dy']:+5.1f}) dang {l['dang']:+5.1f} axis {l['axis_mean']:4.1f}/{l['axis_p90']:4.1f} "
            f"thick {l['ref']['thick']:.0f}->{l['cand']['thick']:.0f} ({l['thick_ratio']:.2f}) med {l['thick_med_ratio']:.2f} len {l['len_ratio']:.2f} area {l['area_ratio']:.2f} "
            f"top {l['cand']['top'] - l['ref']['top']:+d} bot {l['cand']['bottom'] - l['ref']['bottom']:+d}"
        )
    for n, st in strands.items():
        print(n, st["lobe_runs"])


if __name__ == "__main__":
    main()
