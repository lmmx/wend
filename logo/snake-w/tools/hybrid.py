"""The hybrid: the incumbent's own swept tube, moved locally towards the fitted cushions,
S = S_incumbent + alpha w delta.
  delta   for each body-ring vertex of the region, the cushions' signed distance there
          (cushionray.lobe_f and the lobes' pair blends, no bridge), along the vertex normal,
          clipped to +-30 px
  w       where the surface shows (the vertex faces the camera and lies on the incumbent's
          depth buffer, poc/fixed/inc-depth) times cushionray.hybrid_weight (the lobes' reference
          masks grown 20 px, zero over the L04|L05 and L05|L06 junctions, `jw` over L04|L06,
          blurred), blurred again over the tube's own (station, angle) grid
  ends    tapered to zero over 15 stations at the region's ends, so the moved rings meet the
          unmoved tube exactly
The tube's continuity, its press and its section are kept: only the vertices move. Output: scene.js
extra {cut, meshes} for the region (ffd-flat.html, still-spline.html, diag-clay.html).
Usage (from the logo root): hybrid.py incumbent.json cushions.json rings.json OUT.json --alpha A [--jw J]"""
import argparse, base64, json, os, sys
import numpy as np
from scipy import ndimage
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import jax.numpy as jnp
import cushionray as CR
from cushions import VIEW, SCR_X, SCR_Y, smoothstep, b64
import lobekit as K


def deform(spec, P, rings, alpha, jw=0.0, clipd=30.0, taper=15.0):
    a = np.fromfile(f"{CR.FIXED}/inc-depth.raw", np.uint8).reshape(1086, 1448, 4).astype(np.int64)
    v = a[..., 0] * 65536 + a[..., 1] * 256 + a[..., 2]
    zbuf = np.where(v > 0, CR.DIST0 - (v / 256.0 + 5000.0), -1e9)
    out = {"cut": {}, "meshes": {}}; info = {}
    for name, cfg in P.items():
        rg = rings[name]; m, rad = rg["m"], rg["radial"]
        R = np.frombuffer(base64.b64decode(rg["rings"]), np.float32).reshape(m, rad, 3).astype(float)
        s = np.asarray(rg["s"]); C = np.asarray(rg["centres"], float)
        lo, hi = cfg["range"]; ov = cfg.get("overlap", 3.0)
        sel = np.nonzero((s >= lo) & (s <= hi))[0]; R, s, C = R[sel], s[sel], C[sel]
        def normals(X):
            du = np.gradient(X, axis=0); dv = (np.roll(X, -1, 1) - np.roll(X, 1, 1)) / 2
            n = np.cross(du, dv); n /= np.linalg.norm(n, axis=-1, keepdims=True) + 1e-12
            return n * np.sign(((X - C[:, None]) * n).sum(-1, keepdims=True))
        n = normals(R)
        x, y = R[..., 0], -(R[..., 1] * np.cos(CR.ELEV) - R[..., 2] * np.sin(CR.ELEV))
        xi, yi = np.clip(np.round(x).astype(int), 0, 1447), np.clip(np.round(y).astype(int), 0, 1085)
        vis = ((R @ VIEW) >= zbuf[yi, xi] - 2.5) & ((n @ VIEW) > 0)
        W = CR.hybrid_weight(name, jw)
        w = vis * ndimage.map_coordinates(W, [y.ravel(), x.ravel()], order=1).reshape(x.shape)
        w = ndimage.gaussian_filter(w.astype(float), (3.0, 2.0), mode=("nearest", "wrap"))
        lobes, pairs = CR.packed(cfg)
        Pt = jnp.asarray(R.reshape(-1, 3), jnp.float32)
        fc = np.asarray(CR.strand_field(Pt, jnp.full(len(Pt), 1e3, jnp.float32), jnp.zeros(len(Pt), bool), lobes, pairs)).reshape(x.shape)
        d = -alpha * w * np.clip(fc, -clipd, clipd)
        d = ndimage.gaussian_filter(d, (2.5, 2.0), mode=("nearest", "wrap"))
        d *= (smoothstep(lo, lo + taper, s) * (1 - smoothstep(hi - taper, hi, s)))[:, None]
        X = R + d[..., None] * n
        nn = normals(X)
        k = len(sel); idx = np.arange(k * rad).reshape(k, rad)
        a_, b_, c_, e_ = idx[:-1], np.roll(idx, -1, 1)[:-1], idx[1:], np.roll(idx, -1, 1)[1:]
        tri = np.concatenate([np.stack([a_, b_, c_], -1).reshape(-1, 3), np.stack([b_, e_, c_], -1).reshape(-1, 3)])   # facing out (the tube's own winding)
        out["cut"][name] = [lo + ov, hi - ov]
        out["meshes"][name] = [{"positions64": b64(X.reshape(-1, 3), "<f4"), "normals64": b64(nn.reshape(-1, 3), "<f4"), "indices64": b64(tri, "<u4")}]
        info[name] = dict(rings=k, moved_max=float(np.abs(d).max()), moved_p95=float(np.percentile(np.abs(d[w > 0.05]), 95)) if (w > 0.05).any() else 0.0)
    return out, info


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("spec"); ap.add_argument("cushions"); ap.add_argument("rings"); ap.add_argument("out")
    ap.add_argument("--alpha", type=float, default=1.0); ap.add_argument("--jw", type=float, default=0.0)
    A = ap.parse_args()
    ex, info = deform(json.load(open(A.spec)), json.load(open(A.cushions)), json.load(open(A.rings)), A.alpha, A.jw)
    ex["hybrid"] = dict(alpha=A.alpha, jw=A.jw, cushions=A.cushions)
    json.dump(ex, open(A.out, "w")); print(info)
