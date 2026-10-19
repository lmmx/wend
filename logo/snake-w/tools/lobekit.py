"""The lobe kit: what turns the audit's per-feature measurements into geometry moves.
  arcs()       the signed contour error of a candidate lobe along the reference feature's outline
               (+ the candidate overshoots, - it falls short), and its worst stretch: the local
               error that an IoU averages away
  arcs2()      arcs() both ways, adding the error along the candidate's own outline, which sees a
               thin tip that pokes past the reference's edge (from round 12)
  waist()      how much more the candidate's width profile along the lobe dips than the
               reference's: a lobe pinched in one place (from round 13)
  Worker       a persistent flat renderer (tools/ffd_worker.mjs: snakes/ffd-flat.html, the real
               geometry and the baked heads in flat colours, ~0.5 s a render)
  surface_ids  which strand, own station and section angle every pixel shows (ffd-flat.html __ids)
  attribute()  for a registry feature, the run of stations of its strand that draws the
               candidate's matching lobe, from the surface-point buffer
  lobe handles a small set of controls on that run of the continuous strand, each weighted by a
               smooth bump over the run (1 inside, smoothstep ramps outside): translate in the
               screen plane (tx, ty, px) and in depth (tz, px towards the camera), rotate about
               the view axis (rot, degrees, about the run's middle), stretch along the lobe's axis
               (fraction), fatten (radius, fraction), widen (the section's screen-plane semi-axis,
               fraction), bulge either side (geometry.js displacement at psi +-90 degrees), round
               either end (displacement round the whole section at the run's ends), and from round
               15 move either end on screen on its own (ea_x, ea_y, eb_x, eb_y, px: a bump centred
               on the end, 12 stations into the run and out to the end of its ramp, or out to the
               strand's tail at an open end; a lobe mostly ends where its strand passes under the
               partner, and the whole-run moves cannot lower one end without the other). The centreline, radius and section moves act on
               spline control points, so the strand stays one C2 surface; nothing is cut or added.
  Scorer       per-feature measurements of a flat render on a crop (the evaluate.py lobe split and
               match), with arcs, silhouette, negative-space intrusion and the clay crease
Used by tools/discrepancy.py (detect), tools/lobefit.py (attribute + optimise)."""
import copy, json, os, subprocess, sys, threading
import numpy as np
from PIL import Image
from scipy import ndimage
from skimage import filters, measure, morphology
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import strandspline as S
from anatomy import colour_masks
from evaluate import split_lobes, boundary, load_registry, sdf

ELEV = np.radians(3.7746862033886837)
CE, SE = np.cos(ELEV), np.sin(ELEV)
VIEW = np.array([0.0, SE, CE])
SCR_X = np.array([1.0, 0.0, 0.0]); SCR_Y = np.array([0.0, -CE, SE])     # image x, image y (down)
# the baked heads are keyed on each strand's own points up to its neck join + 60 (geometry.js
# headKey): a handle's support must stay above these own stations
NECK_SAFE = {"yellow": 165.0 + 64, "blue": 198.0 + 64}
REG, LAB, NEGLAB = load_registry()
FEATS = REG["features"]; FIDS = [f["id"] for f in FEATS]
NAMES = ["tx", "ty", "tz", "rot", "stretch", "fat", "width", "bulge_p", "bulge_n", "tip_a", "tip_b", "ea_x", "ea_y", "eb_x", "eb_y"]
SCALE = np.array([10, 10, 10, 8, 0.1, 0.08, 0.08, 0.1, 0.1, 0.1, 0.1, 8, 8, 8, 8])     # one search unit
LO = np.array([-25, -25, -25, -20, -0.25, -0.1, -0.1, -0.2, -0.2, -0.15, -0.15, -20, -20, -20, -20])
HI = np.array([25, 25, 25, 20, 0.25, 0.15, 0.15, 0.2, 0.2, 0.15, 0.15, 20, 20, 20, 20])


def to_screen(P):
    P = np.atleast_2d(P)
    return np.c_[P[:, 0], -(P[:, 1] * CE - P[:, 2] * SE)]


def lobes(im):
    """the evaluate.py candidate lobe split of a colour image (blue, yellow label images)"""
    blue, yellow = colour_masks(im)
    out = {}
    for c, m in (("blue", blue), ("yellow", yellow)):
        out[c] = split_lobes(ndimage.binary_fill_holes(morphology.remove_small_objects(m, max_size=150)))
    return out


def match(L, R):
    """the candidate lobe overlapping reference mask R most (evaluate.py), or None"""
    ids, cnt = np.unique(L[R], return_counts=True)
    cnt = cnt[ids > 0]; ids = ids[ids > 0]
    return (L == ids[np.argmax(cnt)]) if len(ids) else None


COMPASS = ["E", "NE", "N", "NW", "W", "SW", "S", "SE"]


def arcs(R, K, length=40):
    """signed error of K's outline along R's outline: at each point of R's (longest) contour,
    + the distance K extends beyond it, - the distance K falls short. Returns the per-point
    errors, the mean |error|, and the worst stretch: the moving average over `length` px with
    the largest magnitude, where it is (x, y), and which way R's outline faces there."""
    cs = measure.find_contours(np.pad(R, 1).astype(float), 0.5)
    if not cs:
        return None
    c = max(cs, key=len) - 1
    # resample to ~1 px spacing
    seg = np.r_[0, np.cumsum(np.hypot(*np.diff(c, axis=0).T))]
    n = max(int(seg[-1]), 8)
    t = np.linspace(0, seg[-1], n, endpoint=False)
    c = np.c_[np.interp(t, seg, c[:, 0]), np.interp(t, seg, c[:, 1])]
    iy = np.clip(np.round(c[:, 0]).astype(int), 0, R.shape[0] - 1); ix = np.clip(np.round(c[:, 1]).astype(int), 0, R.shape[1] - 1)
    if K is None:
        v = np.full(n, -30.0)
    else:
        din = ndimage.distance_transform_edt(K); dout = ndimage.distance_transform_edt(~K)
        v = np.where(K[iy, ix], din[iy, ix], -dout[iy, ix])
    w = min(length, n)
    avg = np.convolve(np.r_[v[-w:], v, v[:w]], np.ones(w) / w, "same")[w:-w]
    k = int(np.argmax(np.abs(avg)))
    phi = filters.gaussian(sdf(R), 2); gy, gx = np.gradient(phi)
    ang = np.degrees(np.arctan2(-gy[iy[k], ix[k]], gx[iy[k], ix[k]])) % 360
    return dict(v=v, mean_abs=float(np.abs(v).mean()), worst=float(avg[k]), at=(float(c[k, 1]), float(c[k, 0])),
                faces=COMPASS[int(((ang + 22.5) % 360) // 45)], faces_deg=float(ang))


def arcs2(R, K, length=40):
    """arcs() both ways. Along R's outline it finds where K falls short or overshoots R's edge;
    but where K pokes out past R as a thin tip, the nearest edge of K from R's outline is K's own
    side, a few px away, so R's side reads the tip as small (the blue collar L01 of r7-merged:
    its top end rides 18 px above the reference's, which R's side measured as nothing; the error
    along K's outline is +15 px there). The worst stretch, where it is and its facing are those of
    the larger side (+ K overshoots, - it falls short); worst_r and worst_k are each side's."""
    A = arcs(R, K, length)
    if K is None or A is None:
        return A
    B = arcs(K, R, length)
    A = dict(A, worst_r=A["worst"], worst_k=-B["worst"])
    if abs(B["worst"]) > abs(A["worst"]):
        A.update(worst=-B["worst"], at=B["at"], faces=B["faces"], faces_deg=B["faces_deg"])
    return A


def widths(R, K, nb=10):
    """the width profiles of R and K across R's principal axis: their extents (px) in nb slices
    along that axis, between R's 4th and 96th percentiles"""
    ys, xs = np.nonzero(R); c = np.c_[xs, ys].astype(float); mu = c.mean(0)
    _, V = np.linalg.eigh(np.cov((c - mu).T)); u, n = V[:, 1], V[:, 0]
    def tv(M):
        y, x = np.nonzero(M); q = np.c_[x, y] - mu
        return q @ u, q @ n
    tR, vR = tv(R); tK, vK = tv(K)
    e = np.linspace(*np.percentile(tR, [4, 96]), nb + 1)
    w = lambda t, v, a, b: float(np.ptp(v[(t >= a) & (t < b)])) if ((t >= a) & (t < b)).any() else 0.0
    return np.array([w(tR, vR, a, b) for a, b in zip(e, e[1:])]), np.array([w(tK, vK, a, b) for a, b in zip(e, e[1:])])


def waist(R, K, nb=10):
    """how much more K's width profile dips than R's (px): the largest, over the interior slices,
    of (the mean of the two neighbouring widths - the width), K's less R's. The blind judges reject
    a lobe that is pinched in one place even when its outline error falls (r12-L01: the collar's
    top overshoot went 15 -> 11 px by thinning its upper half, a dip of 8.5 px here; the
    incumbent's 0.5)"""
    wR, wK = widths(R, K, nb)
    dip = lambda w: 0.5 * (w[:-2] + w[2:]) - w[1:-1]
    return float(max(0.0, np.max(dip(wK) - dip(wR))))


class Worker:
    """ffd_worker.mjs in a subprocess; it renders with the params and head bake that FFD_PARAMS and
    FFD_HEADS name in the environment (default the final pair), as a head variant's fit sets"""

    def __init__(self, wid, root):
        self.wid = wid; self.root = root
        self.p = subprocess.Popen(["node", "../tools/ffd_worker.mjs"], cwd=os.path.join(root, "snakes"), stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE, text=True, bufsize=1)
        self.lock = threading.Lock()

    def call(self, **req):
        with self.lock:
            self.p.stdin.write(json.dumps({"id": f"w{self.wid}", **req}) + "\n"); self.p.stdin.flush()
            r = json.loads(self.p.stdout.readline())
        if "error" in r:
            raise RuntimeError(r["error"])
        return r

    def close(self):
        try:
            self.p.stdin.close(); self.p.wait(timeout=10)
        except Exception:
            self.p.kill()


def surface_ids(worker, spec, tmp):
    """(sid, s, psi) arrays of the whole frame: sid 0 background, 1 / 2 yellow / blue strand, 3 / 4
    yellow / blue head; s the strand's own station; psi in degrees"""
    path = os.path.abspath(tmp)
    r = worker.call(spec_obj=spec, ids=path, clip=[0, 0, 1448, 1086])
    a = np.fromfile(path, np.uint8).reshape(r["h"], r["w"], 4)
    return a[..., 0], (a[..., 1].astype(float) * 256 + a[..., 2]) / 40.0, a[..., 3] / 255.0 * 360.0 - 180.0


def runs(s, gap=12.0):
    """contiguous runs of a set of stations (sorted, split at gaps > `gap`), largest first"""
    s = np.sort(s)
    cut = np.nonzero(np.diff(s) > gap)[0]
    parts = np.split(s, cut + 1)
    return sorted(parts, key=len, reverse=True)


def attribute(sid, st, psi, Lc, fid):
    """the station run of the feature's strand that draws the candidate's lobe matching
    registry feature `fid`: {strand, a, b, sc, n, head_frac, psi_med} (own stations), or the
    reason it has none"""
    i = FIDS.index(fid); f = FEATS[i]
    R = LAB == i + 1
    K = match(Lc[f["colour"]], R)
    if K is None:
        return dict(fid=fid, error="no candidate lobe")
    k = 1 if f["colour"] == "yellow" else 2
    own = K & (sid == k); head = K & (sid == k + 2)
    hf = float(head.sum() / max(K.sum(), 1))
    if own.sum() < 50:
        return dict(fid=fid, error=f"lobe drawn by the head ({hf:.0%})", head_frac=hf)
    rs = runs(st[own])
    run = rs[0]
    a, b = np.percentile(run, [3, 97])
    return dict(fid=fid, strand=f["colour"], a=float(a), b=float(b), sc=float(np.median(run)), n=int(len(run)),
                frac=float(len(run) / own.sum()), head_frac=hf, psi_med=float(np.median(psi[own])),
                K=K)


def greville(t, n):
    return np.array([t[i + 1:i + 4].mean() for i in range(n)])


def smoothstep(e0, e1, x):
    t = np.clip((x - e0) / max(e1 - e0, 1e-9), 0, 1)
    return t * t * (3 - 2 * t)


def bump(s, h):
    return smoothstep(h["a"] - h["ra"], h["a"], s) * (1 - smoothstep(h["b"], h["b"] + h["rb"], s))


def endbump(s, h, e, w=12.0):
    """the weight of an end move (version 3 handles): 1 at end `e` ("a" or "b") of the run, falling
    to 0 within `w` stations inside the run (the lobe's body stays put) and by the end of that
    side's ramp outside it. At an open end (`open_b`: no lobe of the strand beyond, the strand's
    tail tucking behind the other head) the weight stays 1 out to the tail, so the move carries the
    whole tail: the blue collar L01's top tip is the blue tail beside the yellow head, which a move
    of the tail alone lowers (flat probe: cost 2.51 -> 2.24) where a move reaching into the run's
    middle dropped the collar's shoulder with it (2.51 -> 2.61)"""
    a, b = h["a"], h["b"]
    if e == "a":
        return smoothstep(a - h["ra"], a, s) * (1 - smoothstep(a, a + w, s))
    if h.get("open_b"):
        return smoothstep(b - w, b + w, s)
    return smoothstep(b - w, b, s) * (1 - smoothstep(b, b + h["rb"], s))


def rodrigues(V, k, ang):
    return V * np.cos(ang) + np.cross(k, V) * np.sin(ang) + np.outer(V @ k, k) * (1 - np.cos(ang))


def make_handle(spec, att, K, neighbours, ramp=28.0):
    """a handle on the run `att` of a strand: support ramps that stop short of the neighbouring
    runs of the same strand (`neighbours`: [(a, b)]) and of the neck; anchor at the run's middle
    on the centreline; axis the candidate lobe's principal axis on screen"""
    a, b = att["a"], att["b"]
    lo_n = [nb for (na, nb) in neighbours if nb <= a + 4]
    hi_n = [na for (na, nb) in neighbours if na >= b - 4]
    ra = ramp if not lo_n else float(np.clip(a - max(lo_n) - 2, 6, ramp))
    rb = ramp if not hi_n else float(np.clip(min(hi_n) - b - 2, 6, ramp))
    a = max(a, NECK_SAFE[att["strand"]] + ra)
    st = spec[att["strand"]]
    X, _ = S.evaluate(st, np.array([att["sc"]]))
    pr = measure.regionprops(K.astype(int))[0]
    th = pr.orientation
    axis = np.sin(th) * SCR_X + np.cos(th) * SCR_Y
    return dict(v=3, fid=att["fid"], strand=att["strand"], a=float(a), b=float(b), ra=ra, rb=rb, open_b=not hi_n, sc=att["sc"],
                anchor=X[0].tolist(), axis=axis.tolist(), p={n: 0.0 for n in NAMES})


def apply(spec, handles):
    """the spec with every handle's moves applied (supports on one strand may not overlap)"""
    sp = copy.deepcopy(spec)
    for h in handles:
        st = sp[h["strand"]]; p = h["p"]
        c = np.array(h["anchor"]); u = np.array(h["axis"])
        P = np.array(st["ctrl"], float)
        W = bump(greville(S.knots(st["s0"], st["s1"], st["nseg"]), len(P)), h)
        q = P - c
        q = q + p["stretch"] * np.outer(q @ u, u)
        q = rodrigues(q, VIEW, np.radians(p["rot"]))
        Pn = c + q + p["tx"] * SCR_X + p["ty"] * SCR_Y + p["tz"] * VIEW
        Q = P + W[:, None] * (Pn - P)
        G = greville(S.knots(st["s0"], st["s1"], st["nseg"]), len(P))
        for e in ("a", "b"):
            ex_, ey_ = p.get(f"e{e}_x", 0.0), p.get(f"e{e}_y", 0.0)
            if ex_ or ey_:
                Q = Q + endbump(G, h, e)[:, None] * (ex_ * SCR_X + ey_ * SCR_Y)
        st["ctrl"] = Q.tolist()
        rc = np.array(st["rctrl"], float)
        Wr = bump(greville(S.knots(st["s0"], st["s1"], st["rseg"]), len(rc)), h)
        st["rctrl"] = (rc * (1 + Wr * p["fat"])).tolist()
        if p["width"]:
            if "sec" not in st:
                seg = st["nseg"]; st["sec"] = dict(seg=seg, ql=[1.0] * (seg + 3), qd=[1.0] * (seg + 3), psi=[0.0] * (seg + 3))
            ql = np.array(st["sec"]["ql"], float)
            Ws = bump(greville(S.knots(st["s0"], st["s1"], st["sec"]["seg"]), len(ql)), h)
            st["sec"]["ql"] = np.clip(ql * (1 + Ws * p["width"]), 0.5, 1.7).tolist()
        mid, half = 0.5 * (h["a"] + h["b"]), 0.5 * (h["b"] - h["a"])
        # end rounding: version 1 handles (round 1) used a support of +-max(0.4 half, 10) stations, a
        # narrow radial dent that the zebra shows as a notch (r1-L04); version 2 spreads it over at
        # least the radius (+-max(half, 24) stations)
        tw = max(0.4 * half, 10.0) if h.get("v", 1) == 1 else max(half, 24.0)
        d = [(mid, 90.0, half + 0.5 * (h["ra"] + h["rb"]), 70.0, p["bulge_p"]), (mid, -90.0, half + 0.5 * (h["ra"] + h["rb"]), 70.0, p["bulge_n"]),
             (h["a"], 0.0, tw, 180.0, p["tip_a"]), (h["b"], 0.0, tw, 180.0, p["tip_b"])]
        for s_, psi_, ss, sp_, amp in d:
            if amp:
                st.setdefault("disp", []).append(dict(s=float(s_), psi=psi_, sig_s=float(ss), sig_psi=sp_, a=float(amp)))
    return sp


def describe(h):
    """the handle's settings in words (non-zero only), with the screen direction of the bulges"""
    p = h["p"]; out = []
    if abs(p["tx"]) + abs(p["ty"]) > 0.5: out.append(f"move {p['tx']:+.0f},{p['ty']:+.0f} px")
    if abs(p["tz"]) > 0.5: out.append(f"depth {p['tz']:+.0f} px")
    for e in ("a", "b"):
        if abs(p.get(f"e{e}_x", 0.0)) + abs(p.get(f"e{e}_y", 0.0)) > 0.5: out.append(f"end {e} {p[f'e{e}_x']:+.0f},{p[f'e{e}_y']:+.0f} px")
    if abs(p["rot"]) > 0.5: out.append(f"turn {p['rot']:+.0f} deg")
    for k, lbl in (("stretch", "length"), ("fat", "radius"), ("width", "width"), ("bulge_p", "bulge +"), ("bulge_n", "bulge -"), ("tip_a", "end a"), ("tip_b", "end b")):
        if abs(p[k]) > 0.01: out.append(f"{lbl} {p[k]:+.0%}")
    return ", ".join(out) or "none"


def corners(b, y, thr=55.0, k=5):
    """sharp corners on the colour boundaries of a flat crop (blue and yellow masks): points of the
    outlines that turn by more than `thr` degrees over +-k px, away from the crop's edge. A kinked
    crossing, a notch where one strand cuts another, or a pointed tip adds corners (the blind judges
    rejected r3-L06 and r3-L13 for such defects: 23 -> 30 and 38 -> 41 corners)"""
    H, W = b.shape; n = 0
    for m in (b, y):
        for c in measure.find_contours(np.pad(m, 1).astype(float), 0.5):
            c = c - 1
            if len(c) < 30:
                continue
            seg = np.r_[0, np.cumsum(np.hypot(*np.diff(c, axis=0).T))]
            t = np.arange(0, seg[-1], 1.0); c = np.c_[np.interp(t, seg, c[:, 0]), np.interp(t, seg, c[:, 1])]
            v1 = c[k:-k] - c[:-2 * k]; v2 = c[2 * k:] - c[k:-k]
            ang = np.degrees(np.abs(np.arctan2(v1[:, 0] * v2[:, 1] - v1[:, 1] * v2[:, 0], (v1 * v2).sum(1))))
            pts = c[k:-k]
            inner = (pts[:, 0] > 3) & (pts[:, 0] < H - 4) & (pts[:, 1] > 3) & (pts[:, 1] < W - 4)
            n += int((ang[inner] > thr).sum())
    return n


class Scorer:
    """per-feature measurements of a flat render on a crop: the evaluate.py lobe split and match,
    IoU, boundary distances, centroid, arcs (both ways, arcs2), waist; silhouette IoU, negative-space
    intrusion, clay crease"""

    def __init__(self, clip, feats):
        self.clip = clip; x0, y0, x1, y1 = clip
        self.lab = LAB[y0:y1, x0:x1]
        self.feats = feats
        self.ref = {}
        for fid in feats:
            i = FIDS.index(fid); R = self.lab == i + 1
            self.ref[fid] = (R, boundary(R), ndimage.distance_transform_edt(~boundary(R)), FEATS[i]["colour"])
        neg = NEGLAB[y0:y1, x0:x1]
        self.neg = {n["id"]: neg == int(n["id"][1:]) for n in REG["negatives"] if (neg == int(n["id"][1:])).sum() > 500}
        self.sil = ndimage.binary_fill_holes(morphology.closing(self.lab > 0, morphology.disk(4)))
        # the reference lobes' shape: elongation, orientation (degrees), solidity (area / convex hull
        # area: the reference's cushions are near-convex, 0.94-0.96; a band, wedge or notch is less)
        self.props = {}
        for fid in feats:
            p = measure.regionprops(self.ref[fid][0].astype(int))[0]
            self.props[fid] = (float(p.axis_major_length / max(p.axis_minor_length, 1)), float(np.degrees(p.orientation)), float(p.solidity))

    def measure(self, png, shade=None):
        im = np.asarray(Image.open(png).convert("RGB"))
        L = lobes(im)
        res = {}
        for fid in self.feats:
            R, bR, dR, c = self.ref[fid]
            K = match(L[c], R)
            if K is None:
                res[fid] = dict(iou=0.0, p95=99.0, mean=99.0, dx=50.0, dy=50.0, arc=-30.0, arc_mean=30.0, elong=1.0, elong_ref=1.0, tilt=45.0, solid=0.5, solid_ref=0.95, waist=30.0); continue
            bK = boundary(K); dK = ndimage.distance_transform_edt(~bK)
            d = np.r_[dK[bR], dR[bK]]
            ry, rx = np.nonzero(R); ky, kx = np.nonzero(K)
            A = arcs2(R, K)
            pr, pk = self.props[fid], measure.regionprops(K.astype(int))[0]
            res[fid] = dict(iou=float((K & R).sum() / (K | R).sum()), p95=float(np.percentile(d, 95)), mean=float(d.mean()),
                            dx=float(kx.mean() - rx.mean()), dy=float(ky.mean() - ry.mean()), arc=A["worst"], arc_mean=A["mean_abs"],
                            elong=float(pk.axis_major_length / max(pk.axis_minor_length, 1)), elong_ref=pr[0],
                            tilt=float((np.degrees(pk.orientation) - pr[1] + 90) % 180 - 90), solid=float(pk.solidity), solid_ref=pr[2],
                            waist=waist(R, K))
            if shade is not None:
                res[fid]["_K"] = K
        blue, yellow = colour_masks(im)
        sil = ndimage.binary_fill_holes(morphology.closing(blue | yellow, morphology.disk(4)))
        ex = {"sil": float((sil & self.sil).sum() / (sil | self.sil).sum()), "intr": {k: float(sil[m].mean()) for k, m in self.neg.items()}, "crease": {},
              "corners": corners(blue, yellow),
              # the lowest body pixel row in the crop: the floor shadow is painted from the model's lowest feet (scene.js
              # shadowCard), so a lobe lowered past the feet leaves a pale gap (r3-L13, r5-L13)
              "bottom": int(np.nonzero((blue | yellow).any(1))[0].max()) if (blue | yellow).any() else 0}
        if shade is not None:
            g = np.asarray(Image.open(shade).convert("L")).astype(float)
            lap = np.abs(filters.laplace(filters.gaussian(g, 1.0)))
            for fid, r in res.items():
                K = r.pop("_K", None)
                if K is None:
                    continue
                inner = morphology.erosion(K, morphology.disk(6))
                ex["crease"][fid] = float(np.percentile(lap[inner], 99)) if inner.any() else 0.0
        return res, ex
