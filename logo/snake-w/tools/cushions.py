"""An implicit cushion body for one region (a bounded proof of concept, the left valley): each
visible lobe is its own volume, and the strand's continuity is a thin hidden bridge.
  lobe      an oriented superquadric: centre (image x, y and depth towards the camera), rotation
            (on screen, into depth, roll), half-lengths along its own axes that differ forward /
            back and left / right (an egg, a teardrop, a flattened base), varied smoothly across
            the lobe's middle (tanh), a depth half-length, a roundness exponent, and a bend of
            its long axis (a crescent)
  bridge    the strand's own centreline and sections over the region, thinned to `rb` x the
            radius inside it and back to the full tube at its ends, where the strand is hidden
            behind its partner (the incumbent's surface-point buffer), so it carries the snake's
            continuity under the partner without setting any visible outline
  junctions the strand's field is the plain union of locally blended pieces: each lobe with the
            bridge (smooth minimum of width k_lobe), and each pair of lobes that are neighbours
            along the snake with each other (width k_pair); lobes that are not neighbours only
            meet as a plain union; the two snakes are separate solids
  ends      outside the region the field opens and the swept tube is kept (scene.js extra.cut,
            the region's ends overlapping it by `overlap` stations, out of sight); near the ends
            the normals are the bridge's, so the two surfaces meet with the same shading
The surface is extracted by marching cubes at `vox` px, smoothed (Taubin), with normals from the
smoothed field. Output {cut, meshes, cushions} for still-spline.html / diag-clay.html ?extra=,
ffd-flat.html __run(spec, box, extra).
Usage (from the logo root): cushions.py spec.json params.json out.json [--vox 1]"""
import base64, json, os, sys
import numpy as np
from scipy import ndimage
from scipy.spatial import cKDTree
from skimage import measure
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import strandspline as S

ELEV = np.radians(3.7746862033886837)
CE, SE = np.cos(ELEV), np.sin(ELEV)
VIEW = np.array([0.0, SE, CE]); SCR_X = np.array([1.0, 0.0, 0.0]); SCR_Y = np.array([0.0, -CE, SE])


def smoothstep(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0, 1)
    return t * t * (3 - 2 * t)


def smin(a, b, k):
    k = max(k, 1e-3)
    h = np.clip(0.5 + 0.5 * (b - a) / k, 0, 1)
    return b + (a - b) * h - k * h * (1 - h)


def rot(yaw, pitch, roll):
    """the lobe's axes as columns, in world space: yaw turns the long axis on screen (degrees, from
    image x), pitch tips it into depth, roll turns the cross-section about it"""
    y, p, r = np.radians([yaw, pitch, roll])
    u = np.cos(y) * SCR_X + np.sin(y) * SCR_Y
    v = -np.sin(y) * SCR_X + np.cos(y) * SCR_Y
    u, w = np.cos(p) * u + np.sin(p) * VIEW, -np.sin(p) * u + np.cos(p) * VIEW
    v, w = np.cos(r) * v + np.sin(r) * w, -np.sin(r) * v + np.cos(r) * w
    return np.column_stack([u, v, w])


def to_world(ix, iy, depth):
    return ix * SCR_X + iy * SCR_Y + depth * VIEW


def lobe_sdf(P, L):
    """approximate signed distance (px) to the lobe L (dict): the superquadric's inside-outside value
    F - 1 over its gradient's length, so that a blend width is in px whatever the lobe's proportions"""
    q = (P - to_world(*L["c"])) @ rot(*L["rot"])
    # bend: the long axis curved into an arc on its own plane (towards +v for bend > 0, 1 / px), a
    # crescent that wraps round its neighbour
    if L.get("bend"):
        q[:, 1] = q[:, 1] - 0.5 * L["bend"] * q[:, 0] ** 2
    s = 0.25
    a = 0.5 * (L["a"][0] + L["a"][1]) + 0.5 * (L["a"][0] - L["a"][1]) * np.tanh(q[:, 0] / (s * L["a"][0] + s * L["a"][1]))
    b = 0.5 * (L["b"][0] + L["b"][1]) + 0.5 * (L["b"][0] - L["b"][1]) * np.tanh(q[:, 1] / (s * L["b"][0] + s * L["b"][1]))
    c = L["d"]; e = L["p"]
    t = [np.abs(q[:, 0] / a) + 1e-9, np.abs(q[:, 1] / b) + 1e-9, np.abs(q[:, 2] / c) + 1e-9]
    F = (t[0] ** e + t[1] ** e + t[2] ** e) ** (1.0 / e)
    g = np.sqrt(sum((ti ** (e - 1) / si) ** 2 for ti, si in zip(t, (a, b, c)))) * F ** (1 - e)
    return (F - 1.0) / np.maximum(g, 1e-6)


def lobe_box(L, margin):
    """the lobe's world-axis bounding box, `margin` px out"""
    R = rot(*L["rot"]); s = np.array([max(L["a"]), max(L["b"]) + 0.5 * abs(L.get("bend", 0.0)) * max(L["a"]) ** 2, L["d"]])
    h = np.sqrt(((R * s[None]) ** 2).sum(1)) + margin
    c = to_world(*L["c"])
    return c - h, c + h


class Region:
    """one strand's region: the voxel grid and the bridge's geometry, precomputed once so that a fit
    rebuilds only the lobes, each on the block of the grid its box covers"""

    def __init__(self, spec, name, rng, vox, lobes, pad=24.0):
        st = spec[name]; lo, hi = rng
        u = np.arange(lo - 1.0, hi + 1.0, 0.25)
        X, r = S.evaluate(st, u); q = S.evaluate_sec(st, u)
        T = np.gradient(X, axis=0); T /= np.linalg.norm(T, axis=1, keepdims=True)
        d = VIEW[None] - T * (T @ VIEW)[:, None]; d /= np.linalg.norm(d, axis=1, keepdims=True)
        l = np.cross(T, d)
        g0, g1 = X.min(0) - r.max() * 1.4 - pad, X.max(0) + r.max() * 1.4 + pad
        for L in lobes:
            c = to_world(*L["c"]); m = max(max(L["a"]), max(L["b"]), L["d"]) * 1.4 + pad
            g0, g1 = np.minimum(g0, c - m), np.maximum(g1, c + m)
        self.axes = [np.arange(g0[k], g1[k], vox) for k in range(3)]
        G = np.stack(np.meshgrid(*self.axes, indexing="ij"), -1).astype(np.float32)
        self.shape, self.g0, self.vox = G.shape[:3], g0, vox
        self.G = G
        P = G.reshape(-1, 3)
        _, jj = cKDTree(X).query(P, workers=-1)
        off = P - X[jj]
        sh = self.shape
        f4 = lambda a: a.reshape(sh).astype(np.float32)   # float32 throughout: a 1 px grid is tens of millions of points
        self.xt, self.xl, self.xd = f4((off * T[jj]).sum(1)), f4((off * l[jj]).sum(1)), f4((off * d[jj]).sum(1))
        self.r, self.qa, self.qb = f4(r[jj]), f4(q[jj, 0]), f4(q[jj, 1])
        self.u = f4(u[jj]); self.lo, self.hi = lo, hi
        del off, jj
        self.ends = (self.u < lo) | (self.u > hi)
        self._tb = (None,)

    def bridge(self, rb, ramp=(12.0, 12.0), ov=3.0):
        # the full tube up to 2 stations past the cut (the cut parts end in flat discs there,
        # inside it), thinning over `ramp` stations
        key = (rb, tuple(ramp), ov)
        if self._tb[0] == key:
            return self._tb[1:]
        a0, a1 = self.lo + ov + 2, self.hi - ov - 2
        w = smoothstep(a0, a0 + ramp[0], self.u) * (1 - smoothstep(a1 - ramp[1], a1, self.u))
        rc = self.r * (1 - w * (1 - rb))
        a_, b_ = rc * self.qa, rc * self.qb
        rho = np.sqrt((self.xl / a_) ** 2 + (self.xd / b_) ** 2 + (self.xt / np.minimum(a_, b_)) ** 2)
        tb = np.where(self.ends, np.maximum((rho - 1) * np.minimum(a_, b_), 1.0), (rho - 1) * np.minimum(a_, b_)).astype(np.float32)
        gb = np.gradient(ndimage.gaussian_filter(tb, 1.0))
        self._tb = (key, tb, w, gb)
        return tb, w, gb

    def block(self, L, margin):
        b0, b1 = lobe_box(L, margin)
        i0 = [int(np.clip(np.floor((b0[k] - self.g0[k]) / self.vox), 0, self.shape[k])) for k in range(3)]
        i1 = [int(np.clip(np.ceil((b1[k] - self.g0[k]) / self.vox) + 1, 0, self.shape[k])) for k in range(3)]
        return tuple(slice(i0[k], i1[k]) for k in range(3))

    def field(self, cfg):
        """the strand's field: the union of the blended pieces (module docstring), each lobe's
        computed on its own block of the grid"""
        tb, w, gb = self.bridge(cfg["rb"], cfg.get("ramp", (12.0, 12.0)), cfg.get("overlap", 3.0))
        f = tb.copy()
        kmax = max([L["k"] for L in cfg["lobes"]] + [p[2] for p in cfg.get("pairs", [])] + [1.0])
        ls = {}
        for L in cfg["lobes"]:
            sl = self.block(L, kmax + 6.0)
            v = lobe_sdf(self.G[sl].reshape(-1, 3), L).reshape(self.G[sl].shape[:3]).astype(np.float32)
            ls[L["id"]] = (sl, v)
            f[sl] = np.minimum(f[sl], smin(tb[sl], v, L["k"]))
        for a, b, k in cfg.get("pairs", []):
            (sa, va), (sb, vb) = ls[a], ls[b]
            # the two blocks' overlap, in each block's own indices
            o = tuple(slice(max(x.start, y.start), min(x.stop, y.stop)) for x, y in zip(sa, sb))
            if any(z.start >= z.stop for z in o):
                continue
            ia = tuple(slice(z.start - x.start, z.stop - x.start) for z, x in zip(o, sa))
            ib = tuple(slice(z.start - y.start, z.stop - y.start) for z, y in zip(o, sb))
            f[o] = np.minimum(f[o], smin(va[ia], vb[ib], k))
        f = np.where(self.ends, np.maximum(f, 1.0), f)
        return f, tb, w, gb

    def mesh(self, cfg, smooth=10):
        f, tb, w, gb = self.field(cfg)
        verts, faces, _, _ = measure.marching_cubes(f, 0.0, spacing=(self.vox,) * 3)
        if smooth:
            verts = taubin(verts, faces, smooth)
        idx = (verts / self.vox).T
        gf = np.gradient(ndimage.gaussian_filter(f, 1.0))
        nf = np.column_stack([ndimage.map_coordinates(g, idx, order=1) for g in gf])
        nb = np.column_stack([ndimage.map_coordinates(g, idx, order=1) for g in gb])
        wv = ndimage.map_coordinates(w, idx, order=1)[:, None]
        # near the region's ends, the bridge's (the tube's) own normals: the same shading as the swept tube
        n = nf * smoothstep(0.05, 0.3, wv) + nb * (1 - smoothstep(0.05, 0.3, wv))
        n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-9)
        verts = verts + self.g0
        return verts, faces, n


def taubin(v, f, n=10, lam=0.5, mu=-0.53):
    import scipy.sparse as sp
    m = len(v)
    i = np.r_[f[:, 0], f[:, 1], f[:, 2], f[:, 1], f[:, 2], f[:, 0]]
    j = np.r_[f[:, 1], f[:, 2], f[:, 0], f[:, 0], f[:, 1], f[:, 2]]
    A = sp.coo_matrix((np.ones(len(i)), (i, j)), shape=(m, m)).tocsr(); A.data[:] = 1.0
    deg = np.asarray(A.sum(1)).ravel()
    for _ in range(n):
        for wt in (lam, mu):
            v = v + wt * (A @ v / np.maximum(deg, 1)[:, None] - v)
    return v


def b64(a, dt):
    return base64.b64encode(np.ascontiguousarray(a, dt).tobytes()).decode()


def build(spec, P, vox, regions=None, smooth=10):
    """{cut, meshes} for the params P: {strand: {range, overlap, rb, lobes, pairs}}"""
    out = {"cut": {}, "meshes": {}}
    regions = {} if regions is None else regions
    for name, cfg in P.items():
        if name not in regions:
            regions[name] = Region(spec, name, cfg["range"], vox, cfg["lobes"])
        v, fc, n = regions[name].mesh(cfg, smooth)
        ov = cfg.get("overlap", 3.0)
        out["cut"][name] = [cfg["range"][0] + ov, cfg["range"][1] - ov]
        out["meshes"][name] = [{"positions64": b64(v, "<f4"), "normals64": b64(n, "<f4"), "indices64": b64(fc, "<u4")}]
    return out, regions


if __name__ == "__main__":
    spec = json.load(open(sys.argv[1])); P = json.load(open(sys.argv[2]))
    vox = float(sys.argv[sys.argv.index("--vox") + 1]) if "--vox" in sys.argv else 1.0
    res, _ = build(spec, P, vox)
    res["cushions"] = P
    json.dump(res, open(sys.argv[3], "w"))
    print({k: len(v[0]["positions64"]) * 3 // 4 // 12 for k, v in res["meshes"].items()}, "vertices")
