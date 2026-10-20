"""Corresponding edges: the reference's and a render's visible edge curves, paired by lobe identity,
and their differences in position, direction, curvature and length.

Edges (per image, from its colour labels and its registry lobe match, geodiag.match):
  contact A|B   the stretch of lobe A's boundary next to its registry neighbour B (the visible
                blue/yellow boundary between two coils, or a same-colour crease)
  outer A       the stretch of lobe A's boundary next to the background
Each edge's pixels are ordered into a curve along the longest path through them (its largest
connected piece; the share in that piece is recorded as `whole`), smoothed (sigma 2 px) and
resampled by arc length to 41 points, oriented to match the reference's (the reversal with the
smaller mean distance).

Per corresponding pair:
  pos    mean distance between corresponding points (px; arc-length correspondence)
  cham   mean symmetric chamfer distance (px; no correspondence assumed)
  dtan   mean angle between the tangents at corresponding points (deg)
  dchord signed angle between the end-to-end chords (deg; + = the render's edge turned anticlockwise
         on screen, i.e. steeper for an edge rising to the right)
  dkap   rms difference of curvature (1/px x 1000)
  dlen   relative difference of projected length
Reliability: an edge is `ok` when both curves exist, are >= 25 px long and mostly in one piece
(whole >= 0.8 in both). The noise floor of each measure is the same comparison between two
renders of one geometry (`noise` mode).

Usage (from the logo root):
  edges.py pair REF.png CAND.png OUT_PREFIX [--title T]   json + sheet + table
  edges.py noise A.png B.png OUT_PREFIX                     two renders of one geometry
"""
import argparse, json, os, sys
import numpy as np
from scipy import ndimage
from skimage import measure, morphology

HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import geodiag as G

N = 41
ARMS = {"left arm": (300, 270, 600, 720), "arch": (540, 380, 900, 780), "right arm": (880, 250, 1190, 780)}


def lobes_of(M, ref=False):
    """registry feature -> its mask in this image (the registry itself for the reference)"""
    out = {}
    for i, f in enumerate(G.FEATS):
        R = G.LAB == i + 1
        if ref: out[f] = R          # the reference's lobes are the registry's own regions
        else:
            C = G.match(M["lobes"][G.FCOL[f]], R)
            if C is not None: out[f] = C
    return out


def order(px):
    """pixels (n, 2) x, y -> an ordered curve along their longest path, and the share in it"""
    if len(px) < 5: return None, 0.0
    img = np.zeros((1086, 1448), bool); img[px[:, 1], px[:, 0]] = True
    lb = measure.label(img, connectivity=2); big = np.argmax(np.bincount(lb.ravel())[1:]) + 1
    keep = lb == big; whole = keep.sum() / img.sum()
    sk = morphology.skeletonize(ndimage.binary_dilation(keep, iterations=1))
    if sk.sum() < 5: return None, whole
    P = G.graph_path(sk)
    if len(P) < 5: return None, whole
    P = ndimage.gaussian_filter1d(P, 2, axis=0, mode="nearest")
    return P, whole


def resample(P, n=N):
    d = np.r_[0, np.cumsum(np.hypot(*np.diff(P, axis=0).T))]
    t = np.linspace(0, d[-1], n)
    return np.c_[np.interp(t, d, P[:, 0]), np.interp(t, d, P[:, 1])], d[-1]


def edges(M, L):
    """{edge id: (curve, length, whole)} for every contact and outer edge of the lobes in L"""
    out = {}; bgd = ndimage.distance_transform_edt(M["sil"])
    for f, m in L.items():
        bd = m & ~ndimage.binary_erosion(m)
        dist = {g: ndimage.distance_transform_edt(~L[g]) for g in L if g != f}
        for a, b in G.neighbours():
            if f not in (a, b): continue
            g = b if f == a else a
            if g not in L: continue
            if f != a: continue          # one curve per pair: A's side
            sel = bd & (dist[g] < 3)
            P, wh = order(np.c_[np.nonzero(sel)[::-1]])
            if P is not None: out[f"{a}|{b}"] = (P, float(np.hypot(*np.diff(P, axis=0).T).sum()), wh)
        sel = bd & (bgd < 2.5)
        P, wh = order(np.c_[np.nonzero(sel)[::-1]])
        if P is not None: out[f"outer {f}"] = (P, float(np.hypot(*np.diff(P, axis=0).T).sum()), wh)
    return out


def curvature(C):
    d1 = np.gradient(C, axis=0); d2 = np.gradient(d1, axis=0)
    return (d1[:, 0] * d2[:, 1] - d1[:, 1] * d2[:, 0]) / np.maximum(np.hypot(*d1.T) ** 3, 1e-9)


def compare(Er, Ec):
    rows = {}
    for k in sorted(set(Er) | set(Ec)):
        if k not in Er or k not in Ec:
            rows[k] = dict(ok=False, why="missing in " + ("render" if k in Er else "reference")); continue
        (Pr, lr, wr), (Pc, lc, wc) = Er[k], Ec[k]
        R, _ = resample(Pr); C, _ = resample(Pc)
        if np.linalg.norm(C[::-1] - R, axis=1).mean() < np.linalg.norm(C - R, axis=1).mean(): C = C[::-1]
        pos = float(np.linalg.norm(C - R, axis=1).mean())
        from scipy.spatial import cKDTree
        cham = float(0.5 * (cKDTree(Pr).query(Pc)[0].mean() + cKDTree(Pc).query(Pr)[0].mean()))
        Tr = np.gradient(R, axis=0); Tc = np.gradient(C, axis=0)
        cos = (Tr * Tc).sum(1) / np.maximum(np.linalg.norm(Tr, axis=1) * np.linalg.norm(Tc, axis=1), 1e-9)
        dtan = float(np.degrees(np.arccos(np.clip(cos, -1, 1))).mean())
        ar = np.degrees(np.arctan2(-(R[-1, 1] - R[0, 1]), R[-1, 0] - R[0, 0])); ac = np.degrees(np.arctan2(-(C[-1, 1] - C[0, 1]), C[-1, 0] - C[0, 0]))
        dch = float((ac - ar + 180) % 360 - 180)
        kr = ndimage.gaussian_filter1d(curvature(R), 2); kc = ndimage.gaussian_filter1d(curvature(C), 2)
        dk = float(1000 * np.sqrt(np.mean((kc - kr) ** 2)))
        ok = lr >= 25 and lc >= 25 and wr >= 0.8 and wc >= 0.8
        rows[k] = dict(ok=bool(ok), pos=pos, cham=cham, dtan=dtan, dchord=dch, dkap=dk, dlen=float(lc / lr - 1), len_ref=lr, len_cand=lc, whole=[wr, wc],
                       why="" if ok else ("short" if min(lr, lc) < 25 else "fragmented"), ref=R.tolist(), cand=C.tolist())
    return rows


def where(k):
    f = k.split()[-1].split("|")
    bx = [G.REG["features"][G.FEATS.index(x)]["bbox"] for x in f]
    cx = np.mean([(b[0] + b[2]) / 2 for b in bx])
    return "left arm" if cx < 560 else "right arm" if cx > 880 else "arch"


def sheet(rows, Mr, Mc, out_png, title, noise=None):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    cmap = plt.get_cmap("tab20")
    keys = [k for k in rows if "ref" in rows[k]]
    fig = plt.figure(figsize=(26, 19), dpi=80)
    gs = fig.add_gridspec(2, 4, height_ratios=[1.0, 0.9])
    for j, arm in enumerate(("left arm", "right arm")):
        x0, y0, x1, y1 = ARMS[arm]
        for i, (M, nm, key) in enumerate(((Mr, "reference", "ref"), (Mc, "render", "cand"))):
            ax = fig.add_subplot(gs[0, 2 * j + i]); g = M["im"].mean(2, keepdims=True); base = (255 - (255 - g) * 0.45).repeat(3, 2).astype(np.uint8)
            ax.imshow(base[y0:y1, x0:x1], extent=(x0, x1, y1, y0)); ax.set_title(f"{arm}: {nm}", fontsize=12); ax.axis("off")
            for n, k in enumerate(keys):
                if where(k) != arm: continue
                C = np.array(rows[k][key]); c = cmap(n % 20)
                ax.plot(*C.T, "-", color=c, lw=2.6 if rows[k]["ok"] else 1.2, ls="-" if rows[k]["ok"] else ":")
                ax.text(*C[len(C) // 2], str(n + 1), color="k", fontsize=9, weight="bold", bbox=dict(fc=c, ec="none", alpha=0.85, pad=0.5))
                if key == "cand":
                    R = np.array(rows[k]["ref"])
                    for q in range(0, N, 8): ax.plot([R[q, 0], C[q, 0]], [R[q, 1], C[q, 1]], "-", color="#d62728", lw=0.7)
                    ax.plot(*R.T, "-", color="k", lw=0.6, alpha=0.6)
            ax.set_xlim(x0, x1); ax.set_ylim(y1, y0)
    ax = fig.add_subplot(gs[1, :]); ax.axis("off")
    hdr = f"{'#':>3} {'edge':<12} {'arm':<9} {'ok':<4} {'pos px':>7} {'cham px':>8} {'dtan °':>7} {'dchord °':>9} {'dkap':>6} {'dlen %':>7} {'len ref':>8}" + ("   noise: pos / dtan / dchord / dlen" if noise else "")
    lines = [hdr]
    for n, k in enumerate(keys):
        r = rows[k]; nz = noise.get(k) if noise else None
        ns = f"   {nz['pos']:.1f} / {nz['dtan']:.1f} / {nz['dchord']:+.1f} / {100 * nz['dlen']:+.0f}" if nz and "pos" in nz else ""
        lines.append(f"{n + 1:>3} {k:<12} {where(k):<9} {'yes' if r['ok'] else r['why'][:4]:<4} {r['pos']:7.1f} {r['cham']:8.1f} {r['dtan']:7.1f} {r['dchord']:+9.1f} {r['dkap']:6.1f} {100 * r['dlen']:+7.0f} {r['len_ref']:8.0f}{ns}")
    half = (len(lines) + 1) // 2
    ax.text(0.0, 1.0, "\n".join(lines[:half]), family="monospace", fontsize=9.5, va="top")
    ax.text(0.5, 1.0, "\n".join([hdr] + lines[half:]), family="monospace", fontsize=9.5, va="top")
    fig.suptitle(title, fontsize=15, weight="bold")
    fig.tight_layout(); fig.savefig(out_png); plt.close(fig)


def run(a, b, ref_is_registry=True):
    Ma, Mb = G.masks(a), G.masks(b)
    La = lobes_of(Ma, ref=ref_is_registry); Lb = lobes_of(Mb)
    return Ma, Mb, compare(edges(Ma, La), edges(Mb, Lb))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("cmd"); ap.add_argument("a"); ap.add_argument("b"); ap.add_argument("out")
    ap.add_argument("--title", default=""); ap.add_argument("--noise")
    A = ap.parse_args()
    if A.cmd == "noise":
        _, _, rows = run(A.a, A.b, ref_is_registry=False)
    else:
        Ma, Mb, rows = run(A.a, A.b)
        noise = json.load(open(A.noise)) if A.noise else None
        sheet(rows, Ma, Mb, A.out + ".png", A.title or f"corresponding edges: {A.b} against {A.a}", noise)
    json.dump(rows, open(A.out + ".json", "w"), indent=1)
    keep = {k: v for k, v in rows.items() if "pos" in v}
    print(f"{len(keep)} paired edges, {sum(v['ok'] for v in keep.values())} reliable, {len(rows) - len(keep)} unpaired")
    for k, v in sorted(keep.items(), key=lambda kv: -abs(kv[1]['dchord'])):
        print(f"  {k:<12} {where(k):<9} ok {v['ok']!s:<5} pos {v['pos']:5.1f} cham {v['cham']:5.1f} dtan {v['dtan']:5.1f} dchord {v['dchord']:+6.1f} dkap {v['dkap']:5.1f} dlen {100*v['dlen']:+5.0f}%  len {v['len_ref']:.0f}")
