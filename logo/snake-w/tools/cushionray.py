"""Curved implicit cushions for one valley, and a fast renderer for fitting them: no browser in the
loop.
  lobe      a curved cushion: its axis a cubic Bezier in 3D (four control points), started from
            the strand's own centreline over the stations that draw the lobe and run on into the
            stretches its partner hides, so it weaves as the reference's strand does; its radius a
            cubic Bernstein profile along the axis (full where the reference is full, tapered or
            blunt at either end); its section an ellipse (lateral and depth scales); the ends
            close as ellipsoidal caps
  bridge    the strand's own centreline and sections over the region, thinned to `rb` x the
            radius inside it and back to the full tube at its ends (cushions.py)
  junctions each lobe with the bridge (smooth minimum of width k), each pair of lobes that are
            neighbours along the snake with each other; the two snakes are separate solids
  render    the camera is orthographic, so a pixel's surface is the first zero of the field along
            the view direction: the fields are evaluated (JAX) on a view-aligned grid over the
            crop (2 px in screen and depth), the first hit and its normal found per column, the
            field's column minimum (smooth across the outline) and the hit's depth and normal
            upsampled to 1 px, and composited against the fixed scene's colour, depth, Lambert
            shade and normals (ffd-flat.html, rendered once with the regions cut out); the
            Lambert shade of the cushions is a cubic in the view-space normal fitted to the fixed
            scene's own (rmse 1.9 grey levels)
  mesh      the same field on a world grid, marching cubes, Taubin, field normals: scene.js extra
Usage (from the logo root):
  cushionray.py init incumbent.json params.json
  cushionray.py fixed incumbent.json params.json        the fixed scene's buffers (poc/fixed)
  cushionray.py fit incumbent.json params.json OUT [--sweeps 2] [--gens 14] [--order L05,L06,L04] [--procs 4]
  cushionray.py mesh incumbent.json params.json extra.json [--vox 1.25]"""
import argparse, copy, json, os, sys, time
import numpy as np
from PIL import Image
from scipy import ndimage
from scipy.spatial import cKDTree
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.environ.setdefault("XLA_FLAGS", "--xla_cpu_multi_thread_eigen=false")   # one thread: the fit runs one renderer per core
import jax
import jax.numpy as jnp
jax.config.update("jax_enable_x64", False)
import strandspline as S
import lobekit as K
from cushions import ELEV, VIEW, SCR_X, SCR_Y, smoothstep, taubin, b64

ROOT = os.path.abspath(os.path.join(HERE, ".."))
DIST0 = 6000.0 - 1086 / 2 / np.cos(ELEV) * np.sin(ELEV)   # ffd-flat.html: a surface's distance from the camera = DIST0 - P . VIEW
COL = {"yellow": (255, 194, 46), "blue": (13, 79, 214)}
REGION = {"yellow": dict(range=[392, 608], ramp=[8, 14], lobes=["L04", "L06"], pairs=[["L04", "L06"]]),
          "blue": dict(range=[1010, 1115], ramp=[14, 14], lobes=["L05"], pairs=[])}
CLIP = [430, 540, 730, 800]
TARGETS = ["L04", "L05", "L06"]
FIXED = os.path.join(ROOT, "poc", "fixed")
M = 16   # samples along a lobe's axis, to start the Newton steps to the nearest point


# ---------------------------------------------------------------- the field
def bern(t):
    return jnp.stack([(1 - t) ** 3, 3 * (1 - t) ** 2 * t, 3 * (1 - t) * t ** 2, t ** 3], -1)


def smin(a, b, k):
    k = jnp.maximum(k, 1e-3)
    h = jnp.clip(0.5 + 0.5 * (b - a) / k, 0, 1)
    return b + (a - b) * h - k * h * (1 - h)


def dbern(t):
    return jnp.stack([-3 * (1 - t) ** 2, 3 * (1 - t) ** 2 - 6 * (1 - t) * t, 6 * (1 - t) * t - 3 * t ** 2, 3 * t ** 2], -1)


def ddbern(t):
    return jnp.stack([6 * (1 - t), -12 * (1 - t) + 6 * t, 6 * (1 - t) - 12 * t, 6 * t], -1)


def lobe_f(P, ctrl, rr, ss):
    """approximate signed distance (px) from the points P (N, 3) to the curved cushion: the
    nearest point of the cubic axis (the nearest of M samples, then Newton steps on the cubic
    itself, so the surface is as smooth as the curve), the radius and frame there"""
    ts = jnp.linspace(0.0, 1.0, M)
    Cs = bern(ts) @ ctrl
    t = ts[jnp.argmin(((P[:, None, :] - Cs[None]) ** 2).sum(-1), 1)]
    for _ in range(4):
        C, C1, C2 = bern(t) @ ctrl, dbern(t) @ ctrl, ddbern(t) @ ctrl
        o = C - P
        g = (o * C1).sum(1); h = (C1 * C1).sum(1) + (o * C2).sum(1)
        t = jnp.clip(t - g / jnp.where(h > 1e-6, h, 1e-6), 0.0, 1.0)
    C, C1 = bern(t) @ ctrl, dbern(t) @ ctrl
    r_ = bern(t) @ rr
    T = C1 / jnp.linalg.norm(C1, axis=1, keepdims=True)
    V = jnp.asarray(VIEW, jnp.float32)
    D = V[None] - T * (T @ V)[:, None]; D = D / jnp.linalg.norm(D, axis=1, keepdims=True)
    L = jnp.cross(T, D)
    o = P - C
    # past either end the offset runs along the end's tangent, so the cap is an ellipsoid
    xt, xd, xl = (o * T).sum(1), (o * D).sum(1), (o * L).sum(1)
    rho = jnp.sqrt((xl / (r_ * ss[0])) ** 2 + (xd / (r_ * ss[1])) ** 2 + (xt / r_) ** 2)
    return (rho - 1.0) * r_ * jnp.minimum(ss[0], ss[1])


def strand_field(P, tb, ends, lobes, pairs):
    """lobes: [(ctrl, rr, ss, k)], pairs: [(i, j, k)]"""
    ls = [lobe_f(P, c, r, s) for c, r, s, _ in lobes]
    f = tb
    for (c, r, s, k), l in zip(lobes, ls):
        f = jnp.minimum(f, smin(tb, l, k))
    for i, j, k in pairs:
        f = jnp.minimum(f, smin(ls[i], ls[j], k))
    return jnp.where(ends, jnp.maximum(f, 1.0), f)


def bridge_geom(spec, name, rng, P):
    """the nearest centreline station of each point, and its offsets in the strand's frame"""
    st = spec[name]; lo, hi = rng
    u = np.arange(lo - 1.0, hi + 1.0, 0.25)
    X, r = S.evaluate(st, u); q = S.evaluate_sec(st, u)
    T = np.gradient(X, axis=0); T /= np.linalg.norm(T, axis=1, keepdims=True)
    d = VIEW[None] - T * (T @ VIEW)[:, None]; d /= np.linalg.norm(d, axis=1, keepdims=True)
    l = np.cross(T, d)
    _, jj = cKDTree(X).query(P, workers=-1)
    off = P - X[jj]
    return dict(xt=(off * T[jj]).sum(1), xl=(off * l[jj]).sum(1), xd=(off * d[jj]).sum(1), r=r[jj], qa=q[jj, 0], qb=q[jj, 1], u=u[jj], lo=lo, hi=hi)


def bridge_f(g, rb, ramp, ov):
    a0, a1 = g["lo"] + ov + 2, g["hi"] - ov - 2
    w = smoothstep(a0, a0 + ramp[0], g["u"]) * (1 - smoothstep(a1 - ramp[1], a1, g["u"]))
    rc = g["r"] * (1 - w * (1 - rb)); a_, b_ = rc * g["qa"], rc * g["qb"]
    rho = np.sqrt((g["xl"] / a_) ** 2 + (g["xd"] / b_) ** 2 + (g["xt"] / np.minimum(a_, b_)) ** 2)
    ends = (g["u"] < g["lo"]) | (g["u"] > g["hi"])
    return np.where(ends, np.maximum((rho - 1) * np.minimum(a_, b_), 1.0), (rho - 1) * np.minimum(a_, b_)).astype(np.float32), ends, w


def packed(cfg):
    """a strand's params as arrays: lobes [(ctrl, rr, ss, k)], pairs [(i, j, k)]"""
    ids = [L["id"] for L in cfg["lobes"]]
    lobes = [(jnp.asarray(L["ctrl"], jnp.float32), jnp.asarray(L["r"], jnp.float32), jnp.asarray(L["s"], jnp.float32), jnp.float32(L["k"])) for L in cfg["lobes"]]
    pairs = [(ids.index(a), ids.index(b), jnp.float32(k)) for a, b, k in cfg["pairs"]]
    return lobes, pairs


# ---------------------------------------------------------------- init
def init(spec, worker, tmp):
    sid, st, _ = K.surface_ids(worker, spec, tmp)
    P = {}
    for name, R in REGION.items():
        cfg = dict(range=R["range"], overlap=3.0, rb=0.45, ramp=R["ramp"], lobes=[], pairs=[[a, b, 6.0] for a, b in R["pairs"]])
        for fid in R["lobes"]:
            M_ = (K.LAB == K.FIDS.index(fid) + 1) & (sid == (1 if name == "yellow" else 2))
            run = K.runs(st[M_])[0]   # the main run: a few junction pixels drawn by the neighbour's stations are not the lobe's
            a, b = np.percentile(run, [2, 98])
            e = 0.3 * (b - a) + 6
            a, b = max(a - e, R["range"][0] + 12), min(b + e, R["range"][1] - 12)
            u = np.linspace(a, b, 48)
            X, r = S.evaluate(spec[name], u); q = S.evaluate_sec(spec[name], u)
            cl = np.r_[0, np.cumsum(np.linalg.norm(np.diff(X, axis=0), axis=1))]; t = cl / cl[-1]
            Bm = np.asarray(bern(jnp.asarray(t)))
            ctrl = np.linalg.lstsq(Bm, X, rcond=None)[0]
            rr = np.linalg.lstsq(Bm, r, rcond=None)[0]
            cfg["lobes"].append(dict(id=fid, run=[float(a), float(b)], ctrl=ctrl.tolist(), r=rr.tolist(), s=[float(q[:, 0].mean()), float(q[:, 1].mean())], k=6.0))
        P[name] = cfg
    return P


def init_medial(spec, P0):
    """each lobe started from the reference lobe itself (P0 keeps the regions, bridges and pairs):
    its axis the longest path of the reference mask's medial axis, fitted as the cubic and run on
    past either end by 0.6 x the end's radius (a tucked end goes behind its neighbour); its radius
    the mask's inscribed radius along that axis; its depth such that its front lies on the
    incumbent's visible surface (poc/fixed/inc-depth), where the incumbent shows that lobe"""
    from skimage.morphology import skeletonize
    from scipy.sparse.csgraph import dijkstra
    from scipy.sparse import coo_matrix
    a = np.fromfile(f"{FIXED}/inc-depth.raw", np.uint8).reshape(1086, 1448, 4).astype(np.int64)
    v = a[..., 0] * 65536 + a[..., 1] * 256 + a[..., 2]
    zf = np.where(v > 0, DIST0 - (v / 256.0 + 5000.0), np.nan)
    P = copy.deepcopy(P0)
    for name, cfg in P.items():
        for L in cfg["lobes"]:
            M_ = K.LAB == K.FIDS.index(L["id"]) + 1
            dt = ndimage.distance_transform_edt(M_)
            sk = skeletonize(M_)
            ys, xs = np.nonzero(sk); n = len(xs); idx = -np.ones(M_.shape, int); idx[ys, xs] = np.arange(n)
            rows, cols, wts = [], [], []
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    if dy == dx == 0:
                        continue
                    j = idx[np.clip(ys + dy, 0, M_.shape[0] - 1), np.clip(xs + dx, 0, M_.shape[1] - 1)]
                    ok = j >= 0; rows += list(np.nonzero(ok)[0]); cols += list(j[ok]); wts += [np.hypot(dx, dy)] * int(ok.sum())
            G = coo_matrix((wts, (rows, cols)), shape=(n, n)).tocsr()
            d0 = dijkstra(G, indices=0); e1 = int(np.argmax(np.where(np.isfinite(d0), d0, -1)))
            d1, pred = dijkstra(G, indices=e1, return_predecessors=True); e2 = int(np.argmax(np.where(np.isfinite(d1), d1, -1)))
            path = [e2]
            while path[-1] != e1:
                path.append(pred[path[-1]])
            px, py = xs[path].astype(float), ys[path].astype(float); r = dt[py.astype(int), px.astype(int)]
            # the medial axis runs out into the outline's corners, where the inscribed radius falls to
            # nothing: the cushion's axis is its core, where the radius is at least 0.55 x its largest
            core = np.nonzero(r >= 0.55 * r.max())[0]; px, py, r = px[core[0]:core[-1] + 1], py[core[0]:core[-1] + 1], r[core[0]:core[-1] + 1]
            # run on past either end along its tangent, by 0.6 x the end radius
            def ext(i, j):
                tx, ty = px[i] - px[j], py[i] - py[j]; nn = np.hypot(tx, ty) + 1e-9; e = 0.6 * r[i]
                return px[i] + tx / nn * e, py[i] + ty / nn * e
            k_ = min(8, len(px) - 1)
            (ax, ay), (bx, by) = ext(0, k_), ext(-1, -1 - k_)
            px = np.r_[ax, px, bx]; py = np.r_[ay, py, by]; r = np.r_[r[0] * 0.8, r, r[-1] * 0.8]
            # depth: the incumbent's visible surface less the radius, where the incumbent shows this strand's colour there
            zz = zf[np.clip(py.astype(int), 0, 1085), np.clip(px.astype(int), 0, 1447)] - r * L["s"][1]
            good = np.isfinite(zz)
            zz = np.interp(np.arange(len(zz)), np.nonzero(good)[0], zz[good]) if good.any() else np.zeros_like(zz)
            X = px[:, None] * SCR_X + py[:, None] * SCR_Y + zz[:, None] * VIEW
            cl = np.r_[0, np.cumsum(np.linalg.norm(np.diff(X, axis=0), axis=1))]; t = cl / cl[-1]
            Bm = np.asarray(bern(jnp.asarray(t, jnp.float32)))
            L["ctrl"] = np.linalg.lstsq(Bm, X, rcond=None)[0].tolist()
            L["r"] = np.clip(np.linalg.lstsq(Bm, r, rcond=None)[0], 0.5 * r.max(), 1.2 * r.max()).tolist()
            L["k"] = 4.0; L["init"] = "medial"
            print(L["id"], "axis", len(px), "pts, r", [round(x_, 1) for x_ in L["r"]], flush=True)
    return P


# ---------------------------------------------------------------- the renderer
class Ray:
    def __init__(self, spec, P, clip=CLIP, h=3.0):
        self.clip = clip; x0, y0, x1, y1 = clip
        self.h = h
        xs = np.arange(x0, x1 + h, h); ys = np.arange(y0, y1 + h, h)
        zs = []
        for name, cfg in P.items():
            X, r = S.evaluate(spec[name], np.arange(cfg["range"][0], cfg["range"][1], 1.0))
            zs += [(X @ VIEW + 1.8 * r).max(), (X @ VIEW - 1.8 * r).min()]
        self.zs = np.arange(max(zs) + 4, min(zs) - 4, -h)            # front (towards the camera) first
        G = (xs[:, None, None, None] * SCR_X + ys[None, :, None, None] * SCR_Y + self.zs[None, None, :, None] * VIEW).astype(np.float32)
        self.shape = G.shape[:3]
        self.G = jnp.asarray(G)
        self.P = jnp.asarray(G.reshape(-1, 3))
        # each lobe is evaluated on its own block of the grid, sized from its starting axis and
        # radius with room to move and grow, placed on its current axis at each render
        self.blocks = {}
        for name, cfg in P.items():
            for L in cfg["lobes"]:
                C_ = np.asarray(bern(jnp.linspace(0, 1, M))) @ np.asarray(L["ctrl"])
                sx, sy, sz = C_ @ SCR_X, C_ @ SCR_Y, C_ @ VIEW
                m_ = 1.4 * max(L["r"]) + 20
                n_ = [int(np.ceil((v.max() - v.min() + 2 * m_) / h)) + 1 for v in (sx, sy, sz)]
                self.blocks[L["id"]] = tuple(min(a, b) for a, b in zip(n_, self.shape))
        self.xs, self.ys = xs, ys
        self.br = {}
        for name, cfg in P.items():
            g = bridge_geom(spec, name, cfg["range"], np.asarray(self.P))
            tb, ends, _ = bridge_f(g, cfg["rb"], cfg["ramp"], cfg.get("overlap", 3.0))
            self.br[name] = (jnp.asarray(tb), jnp.asarray(ends))
        # the fixed scene: the strands with the regions cut out, and the heads (ffd-flat.html)
        sl = (slice(y0, y1), slice(x0, x1))
        self.fcol = np.asarray(Image.open(f"{FIXED}/cut.png").convert("RGB"))[sl]
        self.fsh = np.asarray(Image.open(f"{FIXED}/cut-shade.png").convert("L"))[sl].astype(np.float32)
        self.fnm = np.asarray(Image.open(f"{FIXED}/cut-normals.png").convert("RGB"))[sl]
        self.fz = (DIST0 - np.load(f"{FIXED}/cut-depth.npy")[sl]).astype(np.float32)   # -inf where empty
        self.coef = np.load(f"{FIXED}/shade_coef.npy")
        self.names = list(P)
        self._col = jax.jit(self._columns, static_argnums=(4, 5))

    def _origin(self, ctrl, size):
        C_ = bern(jnp.linspace(0, 1, M)) @ ctrl
        c = jnp.stack([(C_ @ jnp.asarray(SCR_X, jnp.float32)).mean(), (C_ @ jnp.asarray(SCR_Y, jnp.float32)).mean(), (C_ @ jnp.asarray(VIEW, jnp.float32)).mean()])
        i = jnp.round((c[0] - self.xs[0]) / self.h).astype(jnp.int32); j = jnp.round((c[1] - self.ys[0]) / self.h).astype(jnp.int32)
        k = jnp.round((self.zs[0] - c[2]) / self.h).astype(jnp.int32)
        return [jnp.clip(v - s // 2, 0, n - s) for v, s, n in zip((i, j, k), size, self.shape)]

    def _columns(self, tb, ends, lobes, pk, pidx, sizes):
        tb3 = tb.reshape(self.shape); f = tb3
        o = [self._origin(c, sz) for (c, _, _, _), sz in zip(lobes, sizes)]
        blk = lambda A, oo, sz: jax.lax.dynamic_slice(A, oo + [0] * (A.ndim - 3), list(sz) + list(A.shape[3:]))
        for n_, ((c, r, s, k), sz) in enumerate(zip(lobes, sizes)):
            Pb = blk(self.G, o[n_], sz).reshape(-1, 3)
            l = lobe_f(Pb, c, r, s).reshape(sz)
            fb = jnp.minimum(blk(f, o[n_], sz), smin(blk(tb3, o[n_], sz), l, k))
            for (i, j), kk in zip(pidx, pk):
                if n_ in (i, j):
                    m_ = j if n_ == i else i
                    c2, r2, s2, _ = lobes[m_]
                    fb = jnp.minimum(fb, smin(l, lobe_f(Pb, c2, r2, s2).reshape(sz), kk))
            f = jax.lax.dynamic_update_slice(f, fb, o[n_])
        f = jnp.where(ends.reshape(self.shape), jnp.maximum(f, 1.0), f)
        # the first sample inside, from the camera (the columns are sampled every h px, densely:
        # no step relies on the field being a true distance; the cushions are > 30 px thick)
        inside = f < 0
        has = inside.any(-1)
        k = jnp.argmax(inside, -1)
        km = jnp.maximum(k - 1, 0)
        take = lambda A, idx: jnp.take_along_axis(A, idx[..., None], -1)[..., 0]
        za, zb = self.zs[0] - km * self.h, self.zs[0] - k * self.h
        fa, fb = take(f, km), take(f, k)
        # refinement on the exact field between the bracketing samples: regula falsi, the bracket kept
        I, J = jnp.meshgrid(jnp.arange(self.shape[0]), jnp.arange(self.shape[1]), indexing="ij")
        X = jnp.asarray(self.xs, jnp.float32)[I]; Y = jnp.asarray(self.ys, jnp.float32)[J]
        sx, sy, vw = (jnp.asarray(v, jnp.float32) for v in (SCR_X, SCR_Y, VIEW))
        pairs = [(i, j, kk) for (i, j), kk in zip(pidx, pk)]
        def pf(Z):
            Pt = (X[..., None] * sx + Y[..., None] * sy + Z[..., None] * vw).reshape(-1, 3)
            return self.point_field(Pt, tb3, ends, lobes, pairs).reshape(Z.shape), Pt
        for _ in range(2):
            zc = zb + (za - zb) * fb / jnp.minimum(fb - fa, -1e-6)
            fc, _ = pf(zc)
            out = fc > 0
            za, fa = jnp.where(out, zc, za), jnp.where(out, fc, fa)
            zb, fb = jnp.where(out, zb, zc), jnp.where(out, fb, fc)
        z = jnp.where(k > 0, zb + (za - zb) * fb / jnp.minimum(fb - fa, -1e-6), self.zs[0])
        # the outward normal: the exact field's gradient at the hit (autodiff), in the view's axes
        Pt = (X[..., None] * sx + Y[..., None] * sy + z[..., None] * vw).reshape(-1, 3)
        gr = jax.grad(lambda Q: self.point_field(Q, tb3, ends, lobes, pairs).sum())(Pt).reshape(self.shape[:2] + (3,))
        n = jnp.stack([gr @ sx, -(gr @ sy), gr @ vw], -1)
        g = f.min(-1)
        return g, jnp.where(has, z, -1e9), n

    def point_field(self, Pt, tb3, ends, lobes, pairs):
        """the strand's field at any points: the lobes exact, the bridge interpolated from the grid"""
        from jax.scipy.ndimage import map_coordinates as mc
        c = [((Pt @ jnp.asarray(SCR_X, jnp.float32)) - self.xs[0]) / self.h, ((Pt @ jnp.asarray(SCR_Y, jnp.float32)) - self.ys[0]) / self.h,
             (self.zs[0] - Pt @ jnp.asarray(VIEW, jnp.float32)) / self.h]
        tbp = mc(tb3, c, order=1, mode="nearest")
        ep = mc(ends.reshape(self.shape).astype(jnp.float32), c, order=0, mode="nearest") > 0.5
        return strand_field(Pt, tbp, ep, lobes, pairs)

    def up(self, A):
        """the 2 px columns at 1 px over the crop (bilinear)"""
        x0, y0, x1, y1 = self.clip
        yy, xx = np.mgrid[y0:y1, x0:x1]
        ci = np.stack([(xx - self.xs[0]) / self.h, (yy - self.ys[0]) / self.h])
        if A.ndim == 2:
            return ndimage.map_coordinates(A, ci, order=1, mode="nearest")
        return np.stack([ndimage.map_coordinates(A[..., c], ci, order=1, mode="nearest") for c in range(A.shape[-1])], -1)

    def shade(self, n):
        x, y, z = n[..., 0], n[..., 1], n[..., 2]
        F = np.stack([np.ones_like(x), x, y, z, x*x, y*y, z*z, x*y, x*z, y*z, x**3, y**3, z**3, x*x*y, x*x*z, y*y*x, y*y*z, z*z*x, z*z*y, x*y*z], -1)
        return F @ self.coef

    def render(self, P):
        """colour (RGB), Lambert shade and packed view-space normals of the crop, with the cushions"""
        col, sh, nm, zb = self.fcol.copy(), self.fsh.copy(), self.fnm.copy(), self.fz.copy()
        for name in self.names:
            tb, ends = self.br[name]
            lobes, pairs = packed(P[name])
            sizes = tuple(self.blocks[L["id"]] for L in P[name]["lobes"])
            g, z, n = (np.asarray(a) for a in self._col(tb, ends, lobes, [k for _, _, k in pairs], tuple((i, j) for i, j, _ in pairs), sizes))
            # depth: carried out past the outline so that upsampling does not pull it to the void
            zf = z.copy()
            for _ in range(3):
                zf = np.where(zf > -1e8, zf, ndimage.maximum_filter(zf, size=3))
            G, Z, N = self.up(g), self.up(zf), self.up(n)
            N = N / np.maximum(np.linalg.norm(N, axis=-1, keepdims=True), 1e-9)
            vis = (G < 0) & (Z > zb)
            col[vis] = COL[name]; zb[vis] = Z[vis]
            sh[vis] = np.clip(self.shade(N[vis]), 0, 255)
            nm[vis] = np.clip((N[vis] * 0.5 + 0.5) * 255 + 0.5, 0, 255).astype(np.uint8)
        return col, sh.astype(np.uint8), nm, zb


# ---------------------------------------------------------------- the mesh (for the real scene)
def mesh(spec, P, vox=1.25, smooth=8, pad=30.0):
    from skimage import measure
    out = {"cut": {}, "meshes": {}}
    for name, cfg in P.items():
        X, r = S.evaluate(spec[name], np.arange(cfg["range"][0], cfg["range"][1], 1.0))
        pts = [X - 1.8 * r.max(), X + 1.8 * r.max()] + [np.asarray(L["ctrl"]) for L in cfg["lobes"]]
        g0 = np.min([p.min(0) for p in pts], 0) - pad; g1 = np.max([p.max(0) for p in pts], 0) + pad
        axes = [np.arange(g0[k], g1[k], vox) for k in range(3)]
        G = np.stack(np.meshgrid(*axes, indexing="ij"), -1).astype(np.float32); sh = G.shape[:3]
        Pp = G.reshape(-1, 3)
        gm = bridge_geom(spec, name, cfg["range"], Pp)
        tb, ends, w = bridge_f(gm, cfg["rb"], cfg["ramp"], cfg.get("overlap", 3.0))
        lobes, pairs = packed(cfg)
        fn = jax.jit(lambda Q, t, e: strand_field(Q, t, e, lobes, pairs))
        f = np.concatenate([np.asarray(fn(jnp.asarray(Pp[i:i + 400000]), jnp.asarray(tb[i:i + 400000]), jnp.asarray(ends[i:i + 400000]))) for i in range(0, len(Pp), 400000)]).reshape(sh)
        tbv, wv = tb.reshape(sh), w.reshape(sh).astype(np.float32)
        v, fc, _, _ = measure.marching_cubes(f, 0.0, spacing=(vox,) * 3)
        v = taubin(v, fc, smooth)
        idx = (v / vox).T
        gf = np.gradient(ndimage.gaussian_filter(f, 1.0)); gb = np.gradient(ndimage.gaussian_filter(tbv, 1.0))
        nf = np.column_stack([ndimage.map_coordinates(q, idx, order=1) for q in gf]); nb = np.column_stack([ndimage.map_coordinates(q, idx, order=1) for q in gb])
        ww = smoothstep(0.05, 0.3, ndimage.map_coordinates(wv, idx, order=1))[:, None]
        n = nf * ww + nb * (1 - ww); n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-9)
        v = v + g0
        ov = cfg.get("overlap", 3.0)
        out["cut"][name] = [cfg["range"][0] + ov, cfg["range"][1] - ov]
        out["meshes"][name] = [{"positions64": b64(v, "<f4"), "normals64": b64(n, "<f4"), "indices64": b64(fc, "<u4")}]
        print(name, len(v), "vertices", flush=True)
    return out


# ---------------------------------------------------------------- the fit
CTRL = [("p%d%s" % (i, ax), 5.0) for i in range(4) for ax in "xyz"] + [("r%d" % i, 0.08) for i in range(4)] + [("sl", 0.06), ("sd", 0.06), ("k", 3.0)]
BOUND = 3.0


def apply(P0, x, fid, pf):
    P = copy.deepcopy(P0)
    v = {n: float(x[j]) * s for j, (n, s) in enumerate(CTRL)}
    for cfg in P.values():
        for L in cfg["lobes"]:
            if L["id"] != fid:
                continue
            c = np.asarray(L["ctrl"])
            for i in range(4):
                c[i] = c[i] + v[f"p{i}x"] * SCR_X + v[f"p{i}y"] * SCR_Y + v[f"p{i}z"] * VIEW
            L["ctrl"] = c.tolist()
            L["r"] = [ri * np.exp(v[f"r{i}"]) for i, ri in enumerate(L["r"])]
            L["s"] = [L["s"][0] * np.exp(v["sl"]), L["s"][1] * np.exp(v["sd"])]
            L["k"] = float(np.clip(L["k"] + v["k"], 1.0, 20.0))
        for pr in cfg["pairs"]:
            if (pr[0], pr[1]) in pf:
                pr[2] = float(np.clip(pr[2] + float(x[len(CTRL)]) * 3, 1.0, 20.0))
    return P


_G = {}


def _init(spec_path, P0):
    spec = json.load(open(spec_path))
    _G.update(ray=Ray(spec, P0), sc=K.Scorer(CLIP, crop_feats()))


def step(col, zb, a, b, band=4):
    """the depth step across the boundary of the lobes a and b (px; > 0: a in front of b), or None
    where they do not touch: a crevice where one cushion tucks behind the other is a step, a fused
    junction none"""
    L = K.lobes(col); x0, y0, x1, y1 = CLIP; Ms = []
    for fid in (a, b):
        i = K.FIDS.index(fid); Ms.append(K.match(L[K.FEATS[i]["colour"]], K.LAB[y0:y1, x0:x1] == i + 1))
    if Ms[0] is None or Ms[1] is None:
        return None
    A = Ms[0] & ndimage.binary_dilation(Ms[1], iterations=band); B = Ms[1] & ndimage.binary_dilation(Ms[0], iterations=band)
    if A.sum() < 20 or B.sum() < 20:
        return None
    return float(np.median(zb[A]) - np.median(zb[B]))


def _eval(P, junction=None):
    col, sh, nm, zb = _G["ray"].render(P)
    m, ex = _G["sc"].measure(col, sh, nm)
    if junction:
        ex["step"] = step(col, zb, junction[0], junction[1])
    return m, ex


def crop_feats():
    return [g["id"] for g in K.FEATS if g["id"] in TARGETS or (lambda bx: max(0, min(bx[2], CLIP[2]) - max(bx[0], CLIP[0])) * max(0, min(bx[3], CLIP[3]) - max(bx[1], CLIP[1]))
                                                                 > 0.3 * (bx[2] - bx[0]) * (bx[3] - bx[1]))(g["bbox"])]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd"); ap.add_argument("spec"); ap.add_argument("params"); ap.add_argument("out", nargs="?")
    ap.add_argument("--sweeps", type=int, default=2); ap.add_argument("--gens", type=int, default=14); ap.add_argument("--order", default="L05,L06,L04")
    ap.add_argument("--procs", type=int, default=4); ap.add_argument("--sigma", type=float, default=0.6); ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--vox", type=float, default=1.25)
    # a junction the reference shows as a groove where the fit made a smooth fillet (from the
    # visual diagnosis: L04|L06 fused into one T): A,B,G: that junction's crease (lobekit.Scorer's
    # junction measure: 5.5 for the fused T, 27-31 at the incumbent's contact grooves) at least G,
    # and that junction exempt from the guard against sharper junction creases. Cushions meet by
    # interpenetrating, so a groove is a turn of the normal, not a step in depth
    ap.add_argument("--junction")
    A = ap.parse_args()
    spec = json.load(open(A.spec))
    for n in ("yellow", "blue"):
        spec[n].setdefault("disp", [])
    if A.cmd == "init":
        w = K.Worker(0, ROOT)
        try:
            P = init(spec, w, os.path.abspath(A.params + ".ids.raw"))
        finally:
            w.close()
        json.dump(P, open(A.params, "w"), indent=1)
        return
    P0 = json.load(open(A.params))
    if A.cmd == "medial":
        json.dump(init_medial(spec, P0), open(A.out, "w"), indent=1); return
    if A.cmd == "fixed":
        os.makedirs(FIXED, exist_ok=True)
        cut = {n: [c["range"][0] + c.get("overlap", 3.0), c["range"][1] - c.get("overlap", 3.0)] for n, c in P0.items()}
        w = K.Worker(0, ROOT)
        try:
            for tag, extra in (("cut", {"cut": cut, "meshes": {}}), ("inc", None)):
                w.call(spec_obj=spec, extra=extra, out=f"{FIXED}/{tag}.png", clip=[0, 0, 1448, 1086], shade=f"{FIXED}/{tag}-shade.png", normals=f"{FIXED}/{tag}-normals.png", depth=f"{FIXED}/{tag}-depth.raw")
        finally:
            w.close()
        a = np.fromfile(f"{FIXED}/cut-depth.raw", np.uint8).reshape(1086, 1448, 4).astype(np.int64)
        v = a[..., 0] * 65536 + a[..., 1] * 256 + a[..., 2]
        np.save(f"{FIXED}/cut-depth.npy", np.where(v > 0, v / 256.0 + 5000.0, np.inf).astype(np.float32))
        # the Lambert shade as a cubic in the view-space normal, fitted to the incumbent's own
        nm = np.asarray(Image.open(f"{FIXED}/inc-normals.png").convert("RGB")).astype(float) / 255 * 2 - 1
        sh = np.asarray(Image.open(f"{FIXED}/inc-shade.png").convert("L")).astype(float)
        a = np.fromfile(f"{FIXED}/inc-depth.raw", np.uint8).reshape(1086, 1448, 4).astype(np.int64)
        body = ndimage.binary_erosion((a[..., 0] * 65536 + a[..., 1] * 256 + a[..., 2]) > 0, iterations=3)
        n = nm[body]; n /= np.linalg.norm(n, axis=1, keepdims=True); x, y, z = n.T
        F = np.stack([np.ones_like(x), x, y, z, x*x, y*y, z*z, x*y, x*z, y*z, x**3, y**3, z**3, x*x*y, x*x*z, y*y*x, y*y*z, z*z*x, z*z*y, x*y*z], 1)
        np.save(f"{FIXED}/shade_coef.npy", np.linalg.lstsq(F, sh[body], rcond=None)[0])
        return
    if A.cmd == "mesh":
        res = mesh(spec, P0, A.vox); res["cushions"] = P0
        json.dump(res, open(A.out, "w")); return
    # fit
    from concurrent.futures import ProcessPoolExecutor
    import multiprocessing as mp
    from lobefit import cma, cost_t
    out = os.path.abspath(A.out); os.makedirs(out, exist_ok=True)
    feats = crop_feats(); guards = [f for f in feats if f not in TARGETS]
    sc = K.Scorer(CLIP, feats)
    sl = (slice(CLIP[1], CLIP[3]), slice(CLIP[0], CLIP[2]))
    m0, ex0 = sc.measure(np.asarray(Image.open(f"{FIXED}/inc.png").convert("RGB"))[sl], np.asarray(Image.open(f"{FIXED}/inc-shade.png").convert("L"))[sl],
                         np.asarray(Image.open(f"{FIXED}/inc-normals.png").convert("RGB"))[sl])
    print(f"crop {CLIP}; targets {TARGETS}; guards {guards}", flush=True)
    print("  incumbent:", {k: (round(v["iou"], 3), round(v["p95"], 1), round(v["arc"], 1)) for k, v in m0.items()}, flush=True)

    def J(m, ex, x):
        c = sum(cost_t(m[t]) + 0.4 * max(0.0, ex["crease"].get(t, 0.0) - 1.0) + 0.05 * m[t].get("waist", 0.0) for t in TARGETS)
        pen = 0.0
        for g in guards:
            a, b = m0[g], m[g]
            pen += 5 * max(0.0, a["iou"] - b["iou"] - 0.005) + 0.04 * max(0.0, b["p95"] - a["p95"] - 1) + 0.05 * max(0.0, abs(b["arc"]) - abs(a["arc"]) - 2) + 4 * max(0.0, a["solid"] - b["solid"] - 0.01)
        for g in feats:
            pen += 0.02 * max(0.0, m[g].get("fold", 0.0) - m0[g].get("fold", 0.0) - 6)
        pen += 6 * max(0.0, ex0["sil"] - ex["sil"] - 0.002)
        for k, v in ex["intr"].items():
            pen += 6 * max(0.0, v - ex0["intr"].get(k, 0) - 0.003)
        pen += 0.08 * max(0.0, ex["corners"] - ex0["corners"] - 1) + 0.5 * max(0.0, ex["bottom"] - ex0["bottom"] - 1) + max(0.0, ex["stray"] - ex0["stray"] - 20) / 100
        for g, cr in ex["crease"].items():
            if g not in TARGETS:
                pen += 0.5 * max(0.0, cr / max(ex0["crease"].get(g, 0.6), 0.6) - 1.4)
        for jk, cr in ex["junction"].items():
            if jt and jk == "|".join(sorted(jt[:2])):
                continue
            pen += 0.5 * max(0.0, cr / max(ex0["junction"].get(jk, 0.6), 0.6) - 1.15)
        if jt:
            c += 0.05 * max(0.0, jt[2] - ex["junction"].get("|".join(sorted(jt[:2])), 0.0))
        reg = 0.01 * float(np.sum(np.square(x)))
        return c + pen + reg, c, pen, reg

    jt = (A.junction.split(",")[0], A.junction.split(",")[1], float(A.junction.split(",")[2])) if A.junction else None
    pool = ProcessPoolExecutor(A.procs, mp_context=mp.get_context("spawn"), initializer=_init, initargs=(os.path.abspath(A.spec), P0))
    try:
        t0 = time.time()
        P = copy.deepcopy(P0)
        m, ex = pool.submit(_eval, P).result()
        jj, c, pen, _ = J(m, ex, np.zeros(1)); info = dict(m=m, ex=ex, c=c, pen=pen)
        print(f"  start: J {jj:.3f} (target {c:.3f} guards {pen:.3f}) {time.time() - t0:.1f}s; junctions {ex['junction']}", {k: (round(v["iou"], 3), round(v["p95"], 1), round(v["arc"], 1)) for k, v in m.items()}, flush=True)
        logl = []
        for sw in range(A.sweeps):
            for fid in A.order.split(","):
                pf = {(a, b) for cfg in P.values() for a, b, _ in cfg["pairs"] if fid in (a, b)}
                n = len(CTRL) + len(pf)
                def f(x, wi, P=P, fid=fid, pf=pf):
                    m, ex = pool.submit(_eval, apply(P, x, fid, pf)).result()
                    j, c, pen, reg = J(m, ex, x)
                    return j, dict(c=c, pen=pen, reg=reg, m=m, ex=ex)
                def lg(g, best, F, sigma, fid=fid, sw=sw):
                    line = f"sweep {sw} {fid} gen {g:2d} best {best[0]:.3f} (target {best[2][1]['c']:.3f} guards {best[2][1]['pen']:.3f}) sigma {sigma:.2f} t {time.time() - t0:.0f}s"
                    logl.append(line); print("  " + line, flush=True)
                best = cma(f, n, A.sigma, -BOUND * np.ones(n), BOUND * np.ones(n), A.gens, A.procs, A.seed + 7 * sw, lg, np.zeros(n))
                if best[0] < jj:
                    P = apply(P, best[1], fid, pf); jj, info = best[0], best[2][1]
                print(f"  sweep {sw} {fid}: J {jj:.3f}; junctions {dict((k, round(v, 1)) for k, v in info['ex']['junction'].items())}", {k: (round(v["iou"], 3), round(v["p95"], 1), round(v["arc"], 1)) for k, v in info["m"].items()}, flush=True)
                json.dump(P, open(f"{out}/params.json", "w"), indent=1, default=float)
        json.dump(dict(clip=CLIP, before=m0, after=info["m"], ex_before=ex0, ex_after=info["ex"], J=float(jj), log=logl), open(f"{out}/fit.json", "w"), indent=1, default=float)
        for g in feats:
            a, b = m0[g], info["m"][g]
            print(f"    {g}: IoU {a['iou']:.3f} -> {b['iou']:.3f}, arc {a['arc']:+.1f} -> {b['arc']:+.1f}, p95 {a['p95']:.0f} -> {b['p95']:.0f}")
    finally:
        pool.shutdown(cancel_futures=True)


if __name__ == "__main__":
    main()
