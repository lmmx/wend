"""Lobe-primitive body for one region (a bounded prototype): inside a range of shared stations,
each strand is a signed distance field, a core tube (the spec's own centreline, radius and
elliptical sections, thinned to `core` x radius away from the range's ends) smoothly blended
(polynomial smooth-min, width `k` px: narrow, so the crevices between lobes survive) with one
ellipsoid per visible reference lobe of that strand. At the range's ends the field is exactly the
spec's tube, and the swept tube is cut out over the same stations (scene.js `extra.cut`), so the
two meshes meet ring to ring. Meshed by marching cubes (scikit-image) at `vox` px.
The ellipsoids start from the reference lobe masks (audit/registry): centroid, principal axes
and orientation, scaled by `grow` (the visible mask is partly occluded), depth axis = `depth` x
the minor axis, centred at the depth of the strand's centreline nearest the centroid. These are
starting estimates, to be fitted.
Writes {cut, meshes, beads} for `still-spline.html` / `diag-clay.html` `?extra=`.
Usage (from the logo root): beads.py spec.json out.json [params.json]"""
import json, os, sys
import numpy as np
from scipy.spatial import cKDTree
from skimage import measure
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import strandspline as S
from evaluate import load_registry

ELEV = np.radians(3.7746862033886837)
CE, SE = np.cos(ELEV), np.sin(ELEV)
VIEW = np.array([0.0, SE, CE])
DEF = dict(range={"yellow": [390.0, 600.0], "blue": [430.0, 560.0]}, ramp=30.0, core=0.85, k=8.0, vox=1.5,
           grow=1.10, depth=0.95, smooth=12, lobes={"blue": ["L05"], "yellow": ["L04", "L06"]})
# the ranges' ends are where each strand is hidden behind its partner (tools/who.py), so the
# junction with the swept tube is out of sight


def smoothstep(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0, 1)
    return t * t * (3 - 2 * t)


def smin(a, b, k):
    h = np.clip(0.5 + 0.5 * (b - a) / k, 0, 1)
    return b + (a - b) * h - k * h * (1 - h)


def to_world(ix, iy, depth):
    """Image point (ix, iy) at a depth towards the camera -> world point."""
    return np.array([ix, -iy * CE + depth * SE, iy * SE + depth * CE])


SCR_X = np.array([1.0, 0.0, 0.0]); SCR_Y = np.array([0.0, -CE, SE])     # image x, image y (down)


def ellipsoid_sdf(p, c, R, ax):
    """Approximate signed distance to an ellipsoid: centre c, rotation R (columns = axes), semi-axes ax."""
    q = (p - c) @ R / ax
    k0 = np.linalg.norm(q, axis=-1); k1 = np.linalg.norm(q / ax, axis=-1)
    return k0 * (k0 - 1.0) / np.maximum(k1, 1e-9)


def taubin(v, f, n=12, lam=0.5, mu=-0.53):
    """Volume-preserving mesh smoothing (removes the marching-cubes terracing)."""
    import scipy.sparse as sp
    m = len(v)
    i = np.r_[f[:, 0], f[:, 1], f[:, 2], f[:, 1], f[:, 2], f[:, 0]]
    j = np.r_[f[:, 1], f[:, 2], f[:, 0], f[:, 0], f[:, 1], f[:, 2]]
    A = sp.coo_matrix((np.ones(len(i)), (i, j)), shape=(m, m)).tocsr()
    A.data[:] = 1.0
    deg = np.asarray(A.sum(1)).ravel()
    # vertices on the open boundary stay put
    for _ in range(n):
        for w in (lam, mu):
            v = v + w * (A @ v / np.maximum(deg, 1)[:, None] - v)
    return v


def vertex_normals(v, f):
    fn = np.cross(v[f[:, 1]] - v[f[:, 0]], v[f[:, 2]] - v[f[:, 0]])
    n = np.zeros_like(v)
    for k in range(3):
        np.add.at(n, f[:, k], fn)
    return n / np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12)


def build(spec, P):
    reg, lab, _ = load_registry()
    ids = [f["id"] for f in reg["features"]]
    L = spec["L"]
    out = {"cut": {}, "meshes": {}, "beads": {}}
    for name in ("yellow", "blue"):
        st = spec[name]
        own = lambda sh: sh if name == "yellow" else L - sh
        s0_, s1_ = P["range"][name]
        lo, hi = sorted((own(s0_), own(s1_)))
        out["cut"][name] = [lo + P.get("overlap", 3.0), hi - P.get("overlap", 3.0)]
        u = np.arange(lo - 1.0, hi + 1.0, 0.25)
        X, r = S.evaluate(st, u); q = S.evaluate_sec(st, u)
        sh = u if name == "yellow" else L - u
        T = np.gradient(X, axis=0); T /= np.linalg.norm(T, axis=1, keepdims=True)
        d = VIEW[None] - T * (T @ VIEW)[:, None]; d /= np.linalg.norm(d, axis=1, keepdims=True)
        l = np.cross(T, d)
        w = smoothstep(s0_, s0_ + P["ramp"], sh) * (1 - smoothstep(s1_ - P["ramp"], s1_, sh))
        rc = r * (1 - w * (1 - P["core"]))
        # beads from the reference masks
        beads = []
        for fid in P["lobes"][name]:
            f = reg["features"][ids.index(fid)]
            m = lab == ids.index(fid) + 1
            pr = measure.regionprops(m.astype(int))[0]
            cy, cx = pr.centroid
            th = pr.orientation                       # angle of the major axis to the row axis
            maj = np.sin(th) * SCR_X + np.cos(th) * SCR_Y
            mnr = np.cos(th) * SCR_X - np.sin(th) * SCR_Y
            lp = P.get("per_lobe", {}).get(fid, {})
            A = pr.major_axis_length / 2 * lp.get("grow_major", P["grow"])
            B = pr.minor_axis_length / 2 * lp.get("grow_minor", P["grow"])
            cx, cy = cx + lp.get("dx", 0.0), cy + lp.get("dy", 0.0)
            # depth: the strand's centreline sample nearest the centroid on screen
            ix, iy = X[:, 0], -(X[:, 1] * CE - X[:, 2] * SE)
            j = np.argmin((ix - cx) ** 2 + (iy - cy) ** 2)
            zd = X[j] @ VIEW
            c = to_world(cx, cy, zd)
            Rm = np.column_stack([maj, mnr, VIEW])
            beads.append(dict(id=fid, c=c.tolist(), R=Rm.tolist(), ax=[A, B, B * P["depth"]], station=float(sh[j]), w=float(w[j])))
        out["beads"][name] = beads
        # the voxel grid over this strand's section
        pad = r.max() * 1.3 + 4 * P["vox"]
        g0 = X.min(0) - pad; g1 = X.max(0) + pad
        for b in beads:
            g0 = np.minimum(g0, np.array(b["c"]) - max(b["ax"]) - 10); g1 = np.maximum(g1, np.array(b["c"]) + max(b["ax"]) + 10)
        axes = [np.arange(g0[k], g1[k], P["vox"]) for k in range(3)]
        G = np.stack(np.meshgrid(*axes, indexing="ij"), -1)
        pts = G.reshape(-1, 3)
        dist, jj = cKDTree(X).query(pts)
        off = pts - X[jj]
        xt, xl, xd = (off * T[jj]).sum(1), (off * l[jj]).sum(1), (off * d[jj]).sum(1)
        a_, b_ = rc[jj] * q[jj, 0], rc[jj] * q[jj, 1]
        rho = np.sqrt((xl / a_) ** 2 + (xd / b_) ** 2 + (xt / np.minimum(a_, b_)) ** 2)
        sdf = (rho - 1) * np.minimum(a_, b_)
        for b in beads:
            e = ellipsoid_sdf(pts, np.array(b["c"]), np.array(b["R"]), np.array(b["ax"]))
            e = e + (1 - w[jj]) * 200.0          # beads fade out towards the range's ends
            sdf = smin(sdf, e, P["k"])
        # outside the station range: open (the tube segments take over)
        ends = (u[jj] < lo) | (u[jj] > hi)
        sdf = np.where(ends, np.maximum(sdf, 1.0), sdf)
        vol = sdf.reshape(G.shape[:3]).astype(np.float32)
        verts, faces, normals, _ = measure.marching_cubes(vol, 0.0, spacing=(P["vox"],) * 3)
        verts += g0
        if P.get("smooth"):
            verts = taubin(verts, faces, P["smooth"])
        # normals from the field's own gradient at the (smoothed) vertices: a mirror shows facets otherwise
        from scipy.ndimage import map_coordinates, gaussian_filter
        vs = gaussian_filter(vol, 1.0)
        gx, gy, gz = np.gradient(vs)
        idx = ((verts - g0) / P["vox"]).T
        gn = np.column_stack([map_coordinates(g_, idx, order=1) for g_ in (gx, gy, gz)])
        normals = gn / np.maximum(np.linalg.norm(gn, axis=1, keepdims=True), 1e-9)
        fn = vertex_normals(verts, faces)
        bad = (normals * fn).sum(1) < 0.3            # fall back where the field is ambiguous (the open ends)
        normals[bad] = fn[bad]
        out["meshes"][name] = [{"positions": np.round(verts, 2).ravel().tolist(), "normals": np.round(normals, 4).ravel().tolist(), "indices": faces.ravel().tolist()}]
        print(f"{name}: stations {lo:.0f}..{hi:.0f} (own), grid {G.shape[:3]}, {len(verts)} vertices, beads " + ", ".join(f"{b['id']} ax {b['ax'][0]:.0f}/{b['ax'][1]:.0f}/{b['ax'][2]:.0f}" for b in beads))
    return out


if __name__ == "__main__":
    spec = json.load(open(sys.argv[1]))
    P = dict(DEF)
    if len(sys.argv) > 3:
        P.update(json.load(open(sys.argv[3])))
    res = build(spec, P)
    res["params"] = {k: v for k, v in P.items()}
    json.dump(res, open(sys.argv[2], "w"))
