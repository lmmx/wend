"""geodiag: the advisory geometry diagnosis of a candidate, every region at once.

It measures broadly and gates nothing. Acceptance stays where it was:
  hard     the existing structural checks: autoround.gates (a feature's severity up by 2, an IoU
           down by more than 0.08, the silhouette down by more than 0.01, the target not improved)
           and the mesh check's folds and self-penetration;
  soft     the numbered-feature ledger (IoU, contour p95, worst arc) and the blind judge;
  advisory everything here. A finding says what looks wrong, where, how sure it is and what
           probably causes it. It ranks the next experiment; it never rejects a candidate. New or
           tighter gates are proposed to the owner separately, with evidence (GEODIAG.md).

Regions (all of them, every run): the W's macro regions (spine, helix envelope, twist phase),
every registry feature L01-L16 / H1 / H2 (outline, visible width profile, placement, and on the
strands' 3D tube: radius bead, sections, pinches, interpenetration, handle load, tail taper),
every junction between neighbouring features (the contact line), and both strand tails.

Each finding: {region, check, value, ref, inc, sev 0-3, conf high|med|low, causes [...],
status new|regressed|unchanged|improved, where [x, y]}. Severity comes from the calibration
(tools/geodiag_calib.json: per check, thresholds from the accepted incumbent and the recorded
rejections, `geodiag.py calibrate`). Low confidence never raises severity above 1.

Usage (from the logo root, the snakes venv's python):
  geodiag.py run TAG COLOUR.png SPEC.json OUTDIR [--extra snakes/X.json] [--clay C.png]
             [--zebra Z.png] [--metrics M.json] [--inc INC_geodiag.json] [--params P.json]
  geodiag.py calibrate          rebuild tools/geodiag_calib.json from the library (GEODIAG.md)
  geodiag.py regress [--quick]  run the regression library: does each recorded defect get flagged?
Outputs in OUTDIR: geodiag-TAG.json, geodiag-TAG.png (the worst regions, annotated)."""
import argparse, base64, hashlib, json, os, subprocess, sys
import numpy as np
from PIL import Image
from scipy import ndimage
from scipy.spatial import cKDTree
from skimage import morphology, measure, filters

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from anatomy import colour_masks
from evaluate import load_registry, split_lobes, sdf

E = np.radians(3.7746862033886837); CE, SE = np.cos(E), np.sin(E)
REF = "snakes/ref/reference.png"
CALIB = os.path.join(HERE, "geodiag_calib.json")
CACHE = "auto/geodiag/cache"
REG, LAB, _ = load_registry()
FEATS = [f["id"] for f in REG["features"]]; FCOL = {f["id"]: f["colour"] for f in REG["features"]}
# the strand tails and the feature each ends in (a tail's taper should finish out of sight)
TAILS = {"yellow": "L16", "blue": "L01"}
# the heads whose neck a tail wraps: the collar junctions
COLLARS = {"H1|L01": "blue tail round the yellow neck", "H2|L16": "yellow tail round the blue neck"}
# geometric causes a finding can name (GEODIAG.md: how each is inferred)
CAUSES = ("spine", "helix_radius", "twist_phase", "tube_radius", "section_shape", "contact_deformation", "handles", "tail", "overlay")


# ---------------------------------------------------------------- image measures

def to_img(P):
    P = np.atleast_2d(P)
    return np.c_[P[:, 0], P[:, 1] * -CE + P[:, 2] * SE]


def masks(path):
    im = np.asarray(Image.open(path).convert("RGB"))
    b, y = colour_masks(im)
    b = morphology.remove_small_objects(b, max_size=150); y = morphology.remove_small_objects(y, max_size=150)
    sil = ndimage.binary_fill_holes(ndimage.binary_closing(b | y, morphology.disk(2)))
    sil = morphology.remove_small_objects(sil, max_size=2000)
    lab = np.zeros(sil.shape, np.int8); lab[sil] = 3; lab[y] = 2; lab[b] = 1
    lobes = {c: split_lobes(ndimage.binary_fill_holes(morphology.remove_small_objects(m, max_size=150))) for c, m in (("blue", b), ("yellow", y))}
    return dict(im=im, sil=sil, lab=lab, lobes=lobes)


def match(L, R):
    ids, cnt = np.unique(L[R], return_counts=True); cnt = cnt[ids > 0]; ids = ids[ids > 0]
    return (L == ids[np.argmax(cnt)]) if len(ids) else None


def graph_path(sk, a=None, b=None):
    """a skeleton's shortest path between the pixels nearest a and b, or (a, b None) its longest"""
    from scipy import sparse
    from scipy.sparse import csgraph
    ys, xs = np.nonzero(sk); idx = -np.ones(sk.shape, int); idx[ys, xs] = np.arange(len(xs))
    rows, cols, w = [], [], []
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dx == dy == 0: continue
            y2, x2 = ys + dy, xs + dx; ok = (y2 >= 0) & (y2 < sk.shape[0]) & (x2 >= 0) & (x2 < sk.shape[1])
            j = np.full(len(xs), -1); j[ok] = idx[y2[ok], x2[ok]]; ok = j >= 0
            rows += list(np.nonzero(ok)[0]); cols += list(j[ok]); w += [np.hypot(dx, dy)] * ok.sum()
    G = sparse.csr_matrix((w, (rows, cols)), shape=(len(xs), len(xs)))
    if a is None:
        d0 = csgraph.dijkstra(G, indices=0); d0[~np.isfinite(d0)] = -1; i0 = int(np.argmax(d0))
        d1 = csgraph.dijkstra(G, indices=i0); d1[~np.isfinite(d1)] = -1; i1 = int(np.argmax(d1))
    else:
        near = lambda p: int(np.argmin((xs - p[0]) ** 2 + (ys - p[1]) ** 2)); i0, i1 = near(a), near(b)
    _, pred = csgraph.dijkstra(G, indices=i0, return_predecessors=True)
    path = [i1]
    while path[-1] != i0 and path[-1] >= 0: path.append(pred[path[-1]])
    return np.c_[xs[path[::-1]], ys[path[::-1]]].astype(float)


def resample(P, step):
    d = np.r_[0, np.cumsum(np.hypot(*np.diff(P, axis=0).T))]
    t = np.arange(0, d[-1], step)
    return np.c_[np.interp(t, d, P[:, 0]), np.interp(t, d, P[:, 1])]


def spine(sil, a=(372, 340), b=(1095, 322)):
    """the W-spine: the skeleton path between the heads of the silhouette blurred past its lobe notches"""
    P = graph_path(morphology.skeletonize(filters.gaussian(sil.astype(float), 24) > 0.5), a, b)
    return resample(ndimage.gaussian_filter1d(P, 6, axis=0, mode="nearest"), 2.0)


def normals(P):
    T = np.gradient(P, axis=0); T /= np.linalg.norm(T, axis=1)[:, None]
    return np.c_[-T[:, 1], T[:, 0]]


def chords(mask, P, N, reach=140):
    t = np.arange(0, reach, 0.5); out = np.zeros((len(P), 2))
    for k, sgn in enumerate((1, -1)):
        X = P[:, None, :] + sgn * t[None, :, None] * N[:, None, :]
        xi = np.clip(np.round(X[..., 0]).astype(int), 0, mask.shape[1] - 1); yi = np.clip(np.round(X[..., 1]).astype(int), 0, mask.shape[0] - 1)
        inside = mask[yi, xi]; fo = np.argmax(~inside, axis=1); fo[inside.all(1)] = len(t) - 1
        out[:, k] = t[fo]
    return out


def turning(P):
    y = ndimage.gaussian_filter1d(P[:, 1], 10); h = len(y) // 2
    v1 = int(np.argmax(y[:h])); v2 = h + int(np.argmax(y[h:])); top = v1 + int(np.argmin(y[v1:v2]))
    return {"head_L": 0, "valley_L": v1, "arch": top, "valley_R": v2, "head_R": len(y) - 1}


def phase_switches(lab, P):
    xi = np.clip(np.round(P[:, 0]).astype(int), 0, lab.shape[1] - 1); yi = np.clip(np.round(P[:, 1]).astype(int), 0, lab.shape[0] - 1)
    c = lab[yi, xi].astype(float); c[(c == 0) | (c == 3)] = np.nan
    k = ~np.isnan(c); c = np.interp(np.arange(len(c)), np.nonzero(k)[0], c[k]).round()
    c = ndimage.median_filter(c, 5)
    return c, [(int(i), int(c[i]), int(c[i + 1])) for i in np.nonzero(np.diff(c))[0]]


def ref_contour(R):
    cs = measure.find_contours(np.pad(R, 1).astype(float), 0.5)
    C = max(cs, key=len)[:, ::-1] - 1
    return resample(np.r_[C, C[:1]], 1.0)


def band(d, lo=2.0, hi=20.0):
    """band-pass along a closed contour: the bumps between lo and hi px, without pixel noise or the
    lobe's overall offset"""
    return ndimage.gaussian_filter1d(d, lo, mode="wrap") - ndimage.gaussian_filter1d(d, hi, mode="wrap")


def lobe_frame(m):
    yy, xx = np.nonzero(m); c = np.array([xx.mean(), yy.mean()]); w, v = np.linalg.eigh(np.cov(np.c_[xx, yy].T))
    a = v[:, 1] if v[0, 1] >= 0 else -v[:, 1]
    return c, a, np.array([-a[1], a[0]])


def width_profile(m, frame, n=40):
    c, a, b = frame; yy, xx = np.nonzero(m); P = np.c_[xx, yy] - c; u, v = P @ a, P @ b
    ur = np.percentile(u, [1, 99]); e = np.linspace(ur[0], ur[1], n + 1); k = np.clip(np.digitize(u, e) - 1, 0, n - 1)
    return np.array([np.ptp(v[k == i]) + 1 if (k == i).sum() > 3 else np.nan for i in range(n)]), e


def width_on(m, frame, edges):
    c, a, b = frame; yy, xx = np.nonzero(m); P = np.c_[xx, yy] - c; u, v = P @ a, P @ b
    n = len(edges) - 1; k = np.digitize(u, edges) - 1
    return np.array([np.ptp(v[k == i]) + 1 if (k == i).sum() > 3 else np.nan for i in range(n)])


def neighbours():
    """adjacent registry features: (A, B) pairs whose reference regions touch"""
    out = []
    for i, a in enumerate(FEATS):
        Ra = ndimage.binary_dilation(LAB == i + 1, iterations=3)
        for j in range(i + 1, len(FEATS)):
            if (Ra & (LAB == j + 1)).sum() > 30: out.append((a, FEATS[j]))
    return out


def image_measures(M, Mr):
    """everything measured on the candidate's colour render against the reference's"""
    out = {"features": {}, "junctions": {}, "macro": {}}
    Sr = spine(Mr["sil"]); Sc = spine(M["sil"]); N = normals(Sr)
    cr, cc = chords(Mr["sil"], Sr, N), chords(M["sil"], Sr, N)
    _, j = cKDTree(Sc).query(Sr); off = ((Sc[j] - Sr) * N).sum(1)
    _, tr = phase_switches(Mr["lab"], Sr); _, tc = phase_switches(M["lab"], Sr)
    tp = turning(Sr); tpc = turning(Sc)
    idx = sorted(tp.values()); names = ["L head/neck", "left arm", "left valley", "arch", "right valley", "right arm", "R neck/head"]
    # macro regions between the turning points (the arms split at their midpoints into neck and arm)
    bounds = [0, idx[1] // 3, idx[1], (idx[1] + idx[2]) // 2, (idx[2] + idx[3]) // 2, idx[3], idx[3] + (idx[4] - idx[3]) * 2 // 3, idx[4] + 1]
    for k, nm in enumerate(names):
        sl = slice(bounds[k], bounds[k + 1])
        sh = [(kk - i) * 2.0 for i, a, b in tr if bounds[k] <= i < bounds[k + 1] for kk, a2, b2 in tc if (a2, b2) == (a, b) and abs(kk - i) < 30]
        wr, wc = cr[sl].sum(1), cc[sl].sum(1)
        out["macro"][nm] = dict(spine_p90=float(np.percentile(np.abs(off[sl]), 90)), width_dev=float(abs(wc.mean() / wr.mean() - 1)),
                                width_signed=float(wc.mean() / wr.mean() - 1), phase_max=float(max([abs(s) for s in sh], default=0.0)),
                                where=Sr[(bounds[k] + bounds[k + 1]) // 2].tolist())
    out["macro_turning"] = {k: dict(ref=Sr[tp[k]].tolist(), cand=Sc[tpc[k]].tolist(), d=float(np.hypot(*(Sc[tpc[k]] - Sr[tp[k]])))) for k in tp}
    out["arrays"] = dict(Sr=Sr, Sc=Sc)
    lobe_c = {}
    for i, f in enumerate(FEATS):
        R = LAB == i + 1; C = match(M["lobes"][FCOL[f]], R)
        if C is None:
            out["features"][f] = dict(missing=True); continue
        lobe_c[f] = C
        # outline: the candidate's signed offset along the reference contour (+ = the candidate
        # reaches past it), its band-passed bumps, and its smooth part
        P = ref_contour(R); sd = sdf(C)
        xi = np.clip(np.round(P[:, 0]).astype(int), 0, 1447); yi = np.clip(np.round(P[:, 1]).astype(int), 0, 1085)
        d = -sd[yi, xi]; rip = band(d); low = ndimage.gaussian_filter1d(d, 20, mode="wrap")
        k = int(np.argmax(np.abs(rip)))
        fr = lobe_frame(R); wr, e = width_profile(R, fr); wc = width_on(C, fr, e); core = slice(6, 34)
        rel = (wc[core] - wr[core]) / wr[core]
        yy, xx = np.nonzero(R); cy, cx = np.nonzero(C)
        ext = dict(top=int(cy.min() - yy.min()), bottom=int(cy.max() - yy.max()), left=int(cx.min() - xx.min()), right=int(cx.max() - xx.max()))
        a1 = np.degrees(np.arctan2(fr[1][1], fr[1][0])); a2 = lobe_frame(C)[1]; a2 = np.degrees(np.arctan2(a2[1], a2[0]))
        out["features"][f] = dict(
            area=int(R.sum()), iou=float((R & C).sum() / (R | C).sum()), centroid=float(np.hypot(cx.mean() - xx.mean(), cy.mean() - yy.mean())),
            tilt=float(abs((a2 - a1 + 90) % 180 - 90)), ext=ext, ext_max=float(max(abs(v) for v in ext.values())),
            outline_ripple=float(np.sqrt(np.mean(rip ** 2))), ripple_max=float(np.abs(rip).max()), ripple_at=P[k].tolist(),
            outline_offset=float(np.percentile(np.abs(low), 95)), offset_at=P[int(np.argmax(np.abs(low)))].tolist(),
            width_dev=float(np.nanmean(np.abs(rel))), width_bulge=float(max(0.0, np.nanmax(rel))), width_thin=float(max(0.0, -np.nanmin(rel))),
            width_at=(fr[0] + fr[1] * ((e[6:34][int(np.nanargmax(np.abs(rel)))] + e[7:35][int(np.nanargmax(np.abs(rel)))]) / 2)).tolist(),
            profile=dict(ref=np.nan_to_num(wr).tolist(), cand=np.nan_to_num(wc).tolist()))
        out["features"][f]["_contour"] = (P, d)
    # junctions: the contact line, the stretch of A's reference contour next to B
    for a, b in neighbours():
        if a not in out["features"] or "_contour" not in out["features"][a]: continue
        P, d = out["features"][a]["_contour"]
        Rb = LAB == FEATS.index(b) + 1
        near = ndimage.distance_transform_edt(~Rb)[np.clip(np.round(P[:, 1]).astype(int), 0, 1085), np.clip(np.round(P[:, 0]).astype(int), 0, 1447)] < 4
        if near.sum() < 15: continue
        rip = band(d)[near]; low = ndimage.gaussian_filter1d(d, 20, mode="wrap")[near]
        k = int(np.argmax(np.abs(rip)))
        out["junctions"][f"{a}|{b}"] = dict(length=int(near.sum()), contact_ripple=float(np.sqrt(np.mean(rip ** 2))), ripple_max=float(np.abs(rip).max()),
                                            contact_offset=float(np.mean(np.abs(low))), where=P[near][k].tolist())
    for f in out["features"].values(): f.pop("_contour", None)
    return out, lobe_c


# ---------------------------------------------------------------- 3D measures

def sha(*paths):
    h = hashlib.sha1()
    for p in paths:
        if p and os.path.exists(p): h.update(open(p, "rb").read())
    return h.hexdigest()[:16]


def strand_inputs(spec, params="w-final.params.json"):
    """the strands (dump_strands.mjs) and the tube rings (ffd_worker __rings) of a spec, cached by content"""
    os.makedirs(CACHE, exist_ok=True); key = sha(spec, f"snakes/{params}")
    sp, rp = os.path.abspath(f"{CACHE}/{key}-strands.json"), os.path.abspath(f"{CACHE}/{key}-rings.json")
    rel = os.path.relpath(os.path.abspath(spec), "snakes")
    if not os.path.exists(sp):
        subprocess.run(["node", "../tools/dump_strands.mjs", params, sp, rel], cwd="snakes", check=True, capture_output=True)
    if not os.path.exists(rp):
        req = json.dumps({"id": 1, "spec": rel, "rings": rp}) + "\n"
        subprocess.run(["node", "../tools/ffd_worker.mjs"], cwd="snakes", input=req, text=True, check=True, capture_output=True, env=dict(os.environ, FFD_PARAMS=params))
    return json.load(open(sp)), json.load(open(rp))


def ring_metrics(R):
    C = R.mean(1); d = np.linalg.norm(R - C[:, None], axis=2); F = np.abs(np.fft.rfft(d, axis=1)) / d.shape[1] * 2; m = d.mean(1)
    return dict(C=C, rho=m, ell=(d.max(1) - d.min(1)) / m, a3=np.sqrt((F[:, 3:9] ** 2).sum(1)) / m)


def proj_width(R):
    C = to_img(R.mean(1)); T = np.gradient(C, axis=0); T /= np.linalg.norm(T, axis=1)[:, None]; N = np.c_[-T[:, 1], T[:, 0]]
    u = ((np.stack([to_img(r) for r in R]) - C[:, None]) * N[:, None]).sum(2)
    return u.max(1) - u.min(1)


def strand_measures(spec_path, extra_path, lobe_c, M, params="w-final.params.json"):
    G, rings = strand_inputs(spec_path, params)
    spec = json.load(open(spec_path)); extra = json.load(open(extra_path)) if extra_path else None
    out = {"lobes": {}, "tails": {}, "stations": {}}
    for name, other in (("yellow", "blue"), ("blue", "yellow")):
        g = G[name]; rg = rings[name]; m, rad = rg["m"], rg["radial"]
        R = np.frombuffer(base64.b64decode(rg["rings"]), np.float32).reshape(m, rad, 3).astype(float)
        s = np.array(rg["s"]); rm = ring_metrics(R); pw = proj_width(R); ov = np.zeros(m, bool)
        rho, ell, a3 = rm["rho"].copy(), rm["ell"].copy(), rm["a3"].copy()
        # where the overlay replaces the tube, its own rings are the surface
        for mesh in (extra or {}).get("meshes", {}).get(name, []):
            X = np.frombuffer(base64.b64decode(mesh["positions64"]), np.float32).reshape(-1, rad, 3).astype(float)
            om = ring_metrics(X); jj = cKDTree(rm["C"]).query(om["C"])[1]
            rho[jj], ell[jj], a3[jj], pw[jj], ov[jj] = om["rho"], om["ell"], om["a3"], proj_width(X), True
        gs = np.array(g["s"]); r_nom = np.interp(s, gs, np.array(g["r"]))
        P = np.array(g["pts"]); Q = np.array(g["mate"]); W = np.array(g["mateW"])
        r_mate = np.interp(np.array(g["mateS"]), np.array(G[other]["s"]), np.array(G[other]["r"]))
        dist = np.linalg.norm(P - Q, axis=1); pen = np.where(W > 0.5, (np.array(g["r"]) + r_mate - dist) / np.array(g["r"]), np.nan)
        Rr = np.where(W > 0.5, dist / 2 / np.array(g["r"]), np.nan)
        # bend: curvature x radius of the ring-centre line (stations ~1.6 apart, smoothed over ~5)
        Cs = ndimage.gaussian_filter1d(rm["C"], 3, axis=0, mode="nearest"); Tc = np.gradient(Cs, s, axis=0); Tc /= np.linalg.norm(Tc, axis=1)[:, None]
        Kst = np.linalg.norm(np.gradient(Tc, s, axis=0), axis=1) * r_nom
        Ci = to_img(rm["C"]); xi = np.clip(np.round(Ci[:, 0]).astype(int), 0, 1447); yi = np.clip(np.round(Ci[:, 1]).astype(int), 0, 1085)
        own = M["lab"][yi, xi] == (2 if name == "yellow" else 1)
        base = ndimage.gaussian_filter1d(rho, 25, mode="nearest"); dip = (base - rho) / base
        out["stations"][name] = dict(s=s.tolist(), r=r_nom.tolist(), rho=rho.tolist(), pw=pw.tolist(), ell=ell.tolist(), ov=ov.tolist())
        hs = spec[name].get("disp", [])
        for f, C in lobe_c.items():
            if FCOL[f] != name or f.startswith("H"): continue
            vis = C[yi, xi] & own
            if vis.sum() < 6: continue
            ii = np.nonzero(vis)[0]; a, b = s[ii].min(), s[ii].max(); run = (s >= a) & (s <= b); grun = (gs >= a) & (gs <= b)
            hh = [h for h in hs if a - h["sig_s"] <= h["s"] <= b + h["sig_s"]]
            out["lobes"][f] = dict(
                s=[float(a), float(b)], n=int(run.sum()), overlay=float(ov[run].mean()),
                bead=float(r_nom[run].max() / r_nom[run].min() - 1), seen_bead=float(pw[run].max() / pw[run].min() - 1),
                rho_bead=float(rho[run].max() / rho[run].min() - 1),
                ell_p90=float(np.percentile(ell[run], 90)), lumps_p90=float(np.percentile(a3[run], 90)), pinch=float(max(0.0, dip[run].max())),
                pinch_at=Ci[run][int(np.argmax(dip[run]))].tolist(),
                interpen=float(np.nanmean(pen[grun])) if np.isfinite(pen[grun]).any() else 0.0, R_over_r=float(np.nanmean(Rr[grun])) if np.isfinite(Rr[grun]).any() else 1.0,
                bend=float(np.percentile(Kst[run], 98)),
                handles=len(hh), handle_load=float(sum(abs(h["a"]) for h in hh)), handle_max=float(max([abs(h["a"]) for h in hh], default=0.0)),
                handle_s=[round(h["s"]) for h in hh if abs(h["a"]) >= 0.05],
                where=Ci[run][len(Ci[run]) // 2].tolist())
        # the tail: does its taper show? the share of the last visible stretch thinner than 85% of
        # the tail lobe's median, and whether the tip's own station is visible
        f = TAILS[name]; L = out["lobes"].get(f)
        if L:
            run = (s >= L["s"][0]) & (s <= L["s"][1]); med = np.median(r_nom[run]); tail = s >= s.max() - 120
            vis = np.zeros(m, bool); vis[run] = (lobe_c[f][yi, xi] & own)[run]
            out["tails"][name] = dict(lobe=f, s1=float(s.max()), run_end=L["s"][1], gap=float(s.max() - L["s"][1]),
                                      taper_visible=float(((r_nom < 0.85 * med) & vis & tail).sum() / max(1, (vis & tail).sum())),
                                      tip_visible=bool(own[-3:].any() and vis[-12:].any()), where=Ci[-1].tolist())
    return out


# ---------------------------------------------------------------- findings

# which value of a region is a check's badness, the region kind it applies to, and its geometric
# meaning (GEODIAG.md has the definitions)
CHECKS = {
    "outline_ripple": ("features", "bumps along the outline (band-passed offset, rms px)"),
    "outline_offset": ("features", "the outline displaced (smooth offset, p95 px)"),
    "width_dev": ("features", "visible width profile vs the reference (mean |rel|)"),
    "width_bulge": ("features", "the widest local swelling vs the reference (rel)"),
    "width_thin": ("features", "the deepest local thinning vs the reference (rel)"),
    "ext_max": ("features", "an extremum (top/bottom/left/right) displaced (px)"),
    "centroid": ("features", "the lobe's centre displaced (px)"),
    "seen_bead": ("lobes", "the tube's seen width varying along the visible run (max/min - 1)"),
    "ell_p90": ("lobes", "sections not round (ellipticity p90)"),
    "lumps_p90": ("lobes", "lumpy sections (harmonics 3-8, p90)"),
    "pinch": ("lobes", "a local pinch of the ring radius (depth vs the local mean)"),
    "interpen": ("lobes", "the strands interpenetrating (share of r) before the press"),
    "bend": ("lobes", "a tight bend of the centreline (curvature x r, p98)"),
    "contact_ripple": ("junctions", "bumps along the contact line (rms px)"),
    "contact_offset": ("junctions", "the contact line displaced (mean px)"),
    "spine_p90": ("macro", "the W-spine displaced (p90 px)"),
    "width_dev_macro": ("macro", "the helix envelope's width vs the reference (rel)"),
    "phase_max": ("macro", "a front-strand switch displaced along the W (px)"),
    "taper_visible": ("tails", "the tail's taper inside the visible run (share)"),
}
DEFAULT_T = {  # used until calibrate has run: (sev1, sev2, sev3)
    "outline_ripple": (1.0, 1.6, 2.5), "outline_offset": (6, 10, 16), "width_dev": (0.06, 0.09, 0.13), "width_bulge": (0.10, 0.15, 0.22),
    "width_thin": (0.10, 0.15, 0.22), "ext_max": (8, 13, 20), "centroid": (3, 5, 8), "seen_bead": (0.45, 0.6, 0.8), "ell_p90": (0.25, 0.32, 0.4),
    "lumps_p90": (0.06, 0.09, 0.12), "pinch": (0.08, 0.12, 0.18), "interpen": (0.2, 0.26, 0.32), "bend": (0.6, 0.8, 1.0),
    "contact_ripple": (1.2, 1.9, 2.8), "contact_offset": (4, 7, 11), "spine_p90": (4, 7, 11), "width_dev_macro": (0.04, 0.07, 0.1),
    "phase_max": (8, 12, 18), "taper_visible": (0.25, 0.45, 0.65)}


def thresholds():
    t = dict(DEFAULT_T)
    if os.path.exists(CALIB):
        for k, v in json.load(open(CALIB)).get("thresholds", {}).items(): t[k] = tuple(v)
    return t


def delta_thresholds():
    """per check, the change against the incumbent beyond which a region counts as regressed or
    improved: the 97.5th percentile of the changes between judged candidates and their incumbents
    where no defect was recorded (geodiag_lib.calibrate)"""
    return json.load(open(CALIB)).get("delta", {}) if os.path.exists(CALIB) else {}


def sev_of(v, t):
    return int(sum(v > x for x in t))


def causes_for(region, check, F, L, macro_here):
    """the likely geometric causes of a finding, most likely first, from the region's other measures"""
    c = []
    if check in ("outline_offset", "centroid", "ext_max") and F and F.get("width_dev", 0) < 0.06:
        c.append("spine" if (macro_here or {}).get("spine_p90", 0) >= 4 else "twist_phase")
    if L:
        if L["seen_bead"] >= 0.45 or (F and F.get("width_bulge", 0) >= 0.1 and L["bead"] >= 0.35): c.append("tube_radius")
        if L["handle_max"] >= 0.08 and check in ("width_bulge", "width_dev", "seen_bead", "pinch", "outline_ripple", "contact_ripple", "width_thin"): c.append("handles")
        if L["interpen"] >= 0.2 or L["R_over_r"] < 0.88: c += ["contact_deformation", "helix_radius"]
        if L["ell_p90"] >= 0.25 and check in ("ell_p90", "width_dev", "width_bulge"): c.append("section_shape")
        if L["overlay"] > 0.3: c.append("overlay")
    if check in ("width_dev_macro",): c.append("helix_radius")
    if check in ("phase_max",): c.append("twist_phase")
    if check in ("spine_p90",): c.append("spine")
    if check == "taper_visible" or (region in TAILS.values() and check in ("ext_max", "width_thin", "outline_offset")): c.append("tail")
    seen = []
    for x in c:
        if x not in seen: seen.append(x)
    return seen or ["unknown"]


def findings(D, T):
    out = []
    feats, lobes, juncs, macro, tails = D["image"]["features"], D["strands"].get("lobes", {}), D["image"]["junctions"], D["image"]["macro"], D["strands"].get("tails", {})
    near_macro = lambda xy: min(macro.values(), key=lambda m: np.hypot(m["where"][0] - xy[0], m["where"][1] - xy[1])) if xy else None
    for f, F in feats.items():
        if F.get("missing"):
            out.append(dict(region=f, check="missing", value=1, sev=3, conf="high", causes=["unknown"], where=None)); continue
        L = lobes.get(f)
        conf = "high" if F["area"] > 2500 else "med"
        if D.get("metrics", {}).get(f, {}).get("seg"): conf = "low"
        for k in ("outline_ripple", "outline_offset", "width_dev", "width_bulge", "width_thin", "ext_max", "centroid"):
            v = F[k]; sv = sev_of(v, T[k])
            if sv:
                at = F.get({"outline_ripple": "ripple_at", "outline_offset": "offset_at"}.get(k, "width_at"))
                out.append(dict(region=f, check=k, value=round(v, 4), sev=min(sv, 1) if conf == "low" else sv, conf=conf, causes=causes_for(f, k, F, L, near_macro(at)), where=at))
        if L:
            lc = "high" if L["n"] >= 25 else "med"
            for k in ("seen_bead", "ell_p90", "lumps_p90", "pinch", "interpen", "bend"):
                v = L[k]; sv = sev_of(v, T[k])
                if sv:
                    out.append(dict(region=f, check=k, value=round(v, 4), sev=min(sv, 1) if lc == "low" else sv, conf=lc, causes=causes_for(f, k, F, L, None),
                                    where=L["pinch_at"] if k == "pinch" else L["where"]))
    for j, J in juncs.items():
        conf = "high" if J["length"] >= 40 else "med" if J["length"] >= 20 else "low"
        for k in ("contact_ripple", "contact_offset"):
            v = J[k]; sv = sev_of(v, T[k])
            if sv:
                a, b = j.split("|")
                cs = []
                for f in (a, b):
                    L = lobes.get(f)
                    if L: cs += [c for c in causes_for(f, k, feats.get(f), L, None) if c not in cs]
                if j in COLLARS or j[::-1] in COLLARS or any(t in (a, b) for t in TAILS.values()) and ("H1" in (a, b) or "H2" in (a, b)): cs = ["tail"] + [c for c in cs if c != "tail"]
                out.append(dict(region=j, check=k, value=round(v, 3), sev=min(sv, 1) if conf == "low" else sv, conf=conf, causes=cs or ["unknown"], where=J["where"]))
    for nm, Mm in macro.items():
        for k, kk in (("spine_p90", "spine_p90"), ("width_dev", "width_dev_macro"), ("phase_max", "phase_max")):
            sv = sev_of(Mm[k], T[kk])
            if sv: out.append(dict(region=nm, check=kk, value=round(Mm[k], 4), sev=sv, conf="med", causes=causes_for(nm, kk, None, None, Mm), where=Mm["where"]))
    for name, Tl in tails.items():
        sv = sev_of(Tl["taper_visible"], T["taper_visible"])
        if sv or Tl["tip_visible"]:
            out.append(dict(region=f"tail:{name}", check="taper_visible", value=round(Tl["taper_visible"], 3), sev=max(sv, 1 if Tl["tip_visible"] else 0), conf="med",
                            causes=["tail"] + (["handles"] if lobes.get(Tl["lobe"], {}).get("handle_max", 0) >= 0.08 else []), where=Tl["where"], tip_visible=Tl["tip_visible"]))
    return out


def compare(fs, inc, vals):
    """status of each finding against the incumbent's geodiag run: regressed / improved when the
    value moved by more than the calibrated change for its check (delta_thresholds), else
    unchanged; new when the incumbent's region was below sev 1. The incumbent's findings that
    improved past their change threshold and are now below sev 1 are listed as resolved."""
    if not inc:
        for f in fs: f["status"] = "no incumbent"
        return fs, []
    dt = delta_thresholds(); iv = inc.get("values", {})
    by = {(f["region"], f["check"]): f for f in inc["findings"]}
    for f in fs:
        key = f"{f['region']}|{f['check']}"; o = iv.get(key); f["inc"] = o
        d = dt.get(f["check"])
        if o is None: f["status"] = "unchanged"; continue
        if d is not None and f["value"] - o > d: f["status"] = "new" if (f["region"], f["check"]) not in by else "regressed"
        elif d is not None and o - f["value"] > d: f["status"] = "improved"
        else: f["status"] = "unchanged"
    mine = {(f["region"], f["check"]) for f in fs}
    gone = [dict(o, status="resolved", sev=0, now=vals.get(f"{k[0]}|{k[1]}")) for k, o in by.items() if k not in mine]
    return fs, gone


SUGGEST = {
    "tail": "tail collar: extend s1 behind the partner's neck, phase-shift the last half-turn, hold r until hidden; drop tail pinch handles",
    "tube_radius": "smooth r(s) through the lobe (bead amplitude down), with the helix radius raised to keep the band width",
    "handles": "remove or shrink the inflating / pinching disp handles at the stations named",
    "helix_radius": "raise (or lower) the helix radius over the arm, keeping the band width 2(R + r)",
    "contact_deformation": "separate the strands (helix radius) before reaching for the press or a cushion overlay",
    "section_shape": "relax sec ql/qd towards 1 over the lobe",
    "twist_phase": "a twist-phase offset over the region (tools/twist.py)",
    "spine": "move the region's spine (regionfit translate) - the W itself",
    "overlay": "the hybrid overlay's cushions there (refit cushions, not the tube)",
    "unknown": "inspect the crops; no cause rule fired",
}


def rank_findings(fs):
    w = {"high": 1.0, "med": 0.75, "low": 0.4}
    return sorted([f for f in fs if f["sev"] > 0], key=lambda f: -(f["sev"] * w[f["conf"]] + (0.5 if f.get("status") in ("new", "regressed") else 0)))


def next_experiments(ranked, k=3):
    """group the top findings by region and dominant cause: what to try next, bounded to k"""
    seen, out = set(), []
    for f in ranked:
        key = (f["region"].split("|")[0], f["causes"][0])
        if key in seen: continue
        seen.add(key)
        same = [g for g in ranked if g["region"] == f["region"] or (g["causes"][0] == f["causes"][0] and g["region"].split("|")[0] in f["region"])]
        out.append(dict(region=f["region"], cause=f["causes"][0], evidence=[f"{g['region']} {g['check']}={g['value']} (sev {g['sev']}, {g['conf']})" for g in same[:4]],
                        try_=SUGGEST.get(f["causes"][0], "")))
        if len(out) >= k: break
    return out


# ---------------------------------------------------------------- sheet

def sheet(D, M, Mr, out_png, clay=None, zebra=None, k=6):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Circle
    ranked = D["ranked"]
    fig = plt.figure(figsize=(22, 15), dpi=80)
    gs = fig.add_gridspec(3, 6, height_ratios=[2.2, 1, 1])
    ax = fig.add_subplot(gs[0, :4])
    g = Mr["im"].mean(2, keepdims=True); base = (255 - (255 - g) * 0.3).repeat(3, 2).astype(np.uint8)
    ro, co = Mr["sil"] & ~M["sil"], M["sil"] & ~Mr["sil"]
    base[ro] = (base[ro] * 0.3 + np.array([230, 40, 160]) * 0.7).astype(np.uint8); base[co] = (base[co] * 0.3 + np.array([0, 190, 220]) * 0.7).astype(np.uint8)
    ax.imshow(base); ax.set_xlim(280, 1190); ax.set_ylim(800, 250); ax.axis("off")
    ax.plot(*D["_arr"]["Sr"].T, "k-", lw=1.2); ax.plot(*D["_arr"]["Sc"].T, "--", color="#ff7f0e", lw=1.0)
    col = {1: "#f0a020", 2: "#e05010", 3: "#b00000"}
    top = ranked[:12]
    for i, f in enumerate(top):
        if not f.get("where"): continue
        ax.add_patch(Circle(f["where"], 14 + 6 * f["sev"], fill=False, ec=col[f["sev"]], lw=2.2, ls="-" if f["conf"] != "low" else ":"))
        ax.text(f["where"][0] + 18, f["where"][1] - 10, str(i + 1), color=col[f["sev"]], fontsize=13, weight="bold")
    ax.set_title(f"geodiag {D['tag']} - advisory: the worst findings (magenta: reference only, cyan: candidate only)", fontsize=13)
    ax = fig.add_subplot(gs[0, 4:]); ax.axis("off")
    lines = [f"{i + 1:2d}. sev {f['sev']} {f['conf'][:1]}  {f['region']}: {f['check']} = {f['value']}" + (f"  [{f.get('status')}]" if f.get("status") not in (None, "no incumbent") else "")
             + f"\n      cause: {', '.join(f['causes'][:3])}" for i, f in enumerate(top)]
    lines += ["", "next experiments:"] + [f"- {e['region']} ({e['cause']}): {e['try_']}" for e in D["next"]]
    ax.text(0, 1, "\n".join(lines), va="top", fontsize=9.2, family="monospace", wrap=True)
    crops = [f for f in ranked if f.get("where")][:k]
    imgs = [("reference", Mr["im"]), ("candidate", M["im"])] + ([("clay", np.asarray(Image.open(clay).convert("RGB")))] if clay else []) + ([("zebra", np.asarray(Image.open(zebra).convert("RGB")))] if zebra else [])
    for i, f in enumerate(crops[:6]):
        r, c = 1 + i // 3, (i % 3) * 2
        sub = gs[r, c:c + 2].subgridspec(1, len(imgs[:3]))
        x, y = f["where"]
        for j, (nm, im) in enumerate(imgs[:3]):
            a = fig.add_subplot(sub[0, j]); a.imshow(im); a.set_xlim(x - 70, x + 70); a.set_ylim(y + 70, y - 70); a.set_xticks([]); a.set_yticks([])
            if j == 0: a.set_title(f"{ranked.index(f) + 1}. {f['region']} {f['check']}", fontsize=9, loc="left")
            if j == 1: a.set_title(nm, fontsize=8)
    fig.tight_layout(); fig.savefig(out_png); plt.close(fig)


# ---------------------------------------------------------------- entry points

_REF = {}


def ref_masks():
    if "M" not in _REF: _REF["M"] = masks(REF)
    return _REF["M"]


def run(tag, colour, spec, outdir, extra=None, clay=None, zebra=None, metrics=None, inc=None, params="w-final.params.json", draw=True):
    os.makedirs(outdir, exist_ok=True)
    Mr = ref_masks(); M = masks(colour)
    img, lobe_c = image_measures(M, Mr)
    arr = img.pop("arrays")
    st = strand_measures(spec, extra, lobe_c, M, params) if spec else {}
    D = dict(tag=tag, colour=colour, spec=spec, extra=extra, image=img, strands=st,
             metrics={f: {k: v for k, v in m.items() if k in ("seg", "crease", "fold_vis", "iou")} for f, m in (json.load(open(metrics))["features"].items() if metrics else [])})
    fs = findings(D, thresholds())
    incD = json.load(open(inc)) if inc and os.path.exists(inc) else None
    import geodiag_lib as GL
    vals = {f"{k[0]}|{k[1]}": float(v) for k, v in GL.values(D).items()}
    fs, gone = compare(fs, incD, vals)
    D["values"] = vals
    D["findings"] = fs; D["resolved"] = gone; D["ranked"] = rank_findings(fs); D["next"] = next_experiments(D["ranked"])
    D["summary"] = dict(n=len(D["ranked"]), sev3=sum(f["sev"] == 3 for f in fs), sev2=sum(f["sev"] == 2 for f in fs),
                        new=[f"{f['region']}:{f['check']}" for f in fs if f.get("status") == "new"],
                        regressed=[f"{f['region']}:{f['check']}" for f in fs if f.get("status") == "regressed"],
                        resolved=[f"{f['region']}:{f['check']}" for f in gone if f["sev"] == 0])
    D["_arr"] = arr
    if draw: sheet(D, M, Mr, f"{outdir}/geodiag-{tag}.png", clay, zebra)
    D.pop("_arr")
    json.dump(D, open(f"{outdir}/geodiag-{tag}.json", "w"), indent=1, default=float)
    return D


def report(D, n=10):
    lines = [f"geodiag {D['tag']}: {D['summary']['n']} advisory findings (sev3 {D['summary']['sev3']}, sev2 {D['summary']['sev2']}); "
             f"new sev>=2: {', '.join(D['summary']['new']) or '-'}; regressed: {', '.join(D['summary']['regressed']) or '-'}; resolved: {', '.join(D['summary']['resolved']) or '-'}"]
    for f in D["ranked"][:n]:
        lines.append(f"  sev {f['sev']} ({f['conf']}) {f['region']:<12} {f['check']:<15} {f['value']:<8} causes {','.join(f['causes'][:3])}  {f.get('status', '')}")
    lines.append("  next: " + " | ".join(f"{e['region']} -> {e['cause']}" for e in D["next"]))
    return "\n".join(lines)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("cmd")
    ap.add_argument("rest", nargs="*")
    for o in ("--extra", "--clay", "--zebra", "--metrics", "--inc", "--params"): ap.add_argument(o)
    ap.add_argument("--quick", action="store_true")
    A = ap.parse_args()
    if A.cmd == "run":
        tag, colour, spec, outdir = A.rest
        D = run(tag, colour, None if spec == "-" else spec, outdir, A.extra, A.clay, A.zebra, A.metrics, A.inc, A.params or "w-final.params.json")
        print(report(D))
    else:
        import geodiag_lib as GL
        getattr(GL, A.cmd)(A)
