"""Fit the look (studio, materials, key light, tone mapping, colours) to the reference, on the
final geometry: snakes/look-lab.html through tools/look_worker.mjs (the meshes built once, a look
re-rendered in a few seconds).
The loss, over each strand's interior where the reference and the render agree on its colour
(both colour masks eroded 3 px), per strand (yellow, blue):
  match   CIELAB dE76 per pixel, at 1/4 resolution (where the light and shade fall on the form;
          coarse, so a highlight a few px off is not punished twice)
  dist    20 quantiles of L*, C* and hue: the tones present (a highlight of the right strength
          and area, the depth of the shade)
  grad    20 quantiles of |grad L*| (px): crisp highlights and contacts rather than smeared ones
and the floor band (y 790-1000, the background in both): dE per pixel at 1/4 resolution.
softness (look key, px): the Gaussian blur the page puts on the canvas (CSS), applied here.
Usage (from the logo root):
  lookfit.py variants OUT_DIR name=patch.json|'{...}' ...     render, score, crop sheet
  lookfit.py fit OUT_DIR --space space.json [--gens 30 --pop 16 --procs 3]"""
import argparse, json, os, subprocess, sys, threading
import numpy as np
from PIL import Image
from scipy import ndimage
from skimage import color as skc
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import lobekit as K
ROOT = os.path.abspath(os.path.join(HERE, ".."))
# LOOK_SCALE (env): the fit renders and scores at this fraction of the frame (0.5: 4x fewer pixels);
# only the W's box is scored (BOX, frame px)
SCALE = float(os.environ.get("LOOK_SCALE", "1"))
BOX = (240, 200, 1220, 1000)
def prep(im):
    """a frame (any size) -> the scored box at SCALE"""
    W, H = round(1448 * SCALE), round(1086 * SCALE)
    if im.shape[1] != W:
        im = np.asarray(Image.fromarray(im).resize((W, H), Image.LANCZOS))
    b = [round(v * SCALE) for v in BOX]
    return im[b[1]:b[3], b[0]:b[2]]
REF_FULL = np.asarray(Image.open(os.path.join(ROOT, "snakes/ref/reference.png")).convert("RGB"))
REF = prep(REF_FULL)
REF_LAB = skc.rgb2lab(REF / 255.0)
REF_L = K.lobes(REF)
FLOOR = (slice(round((790 - BOX[1]) * SCALE), round((1000 - BOX[1]) * SCALE)), slice(round((250 - BOX[0]) * SCALE), round((1200 - BOX[0]) * SCALE)))
ER = max(1, round(3 * SCALE)); PL = max(1, round(4 * SCALE))


class Worker:
    def __init__(self, base="w-final.look.json", ss=None):
        ss = ss or str(SCALE)
        env = dict(os.environ, LOOK_BASE=base, LOOK_SS=ss)
        self.p = subprocess.Popen(["node", "../tools/look_worker.mjs"], cwd=os.path.join(ROOT, "snakes"), stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, env=env)
        assert json.loads(self.p.stdout.readline()).get("ready")
        self.lock = threading.Lock(); self.n = 0

    def render(self, look, out):
        with self.lock:
            self.n += 1
            self.p.stdin.write(json.dumps({"id": self.n, "look": look, "out": out}) + "\n"); self.p.stdin.flush()
            r = json.loads(self.p.stdout.readline())
        if "error" in r:
            raise RuntimeError(r["error"])
        return r

    def close(self):
        self.p.stdin.close(); self.p.wait(timeout=30)


def blur(im, s):
    if not s:
        return im
    a = im.astype(float)
    return np.clip(np.stack([ndimage.gaussian_filter(a[..., c], s) for c in range(3)], -1), 0, 255).round().astype(np.uint8)


def pool4(x):
    """the mean over cells of 4 frame px (PL px at SCALE)"""
    k = PL; h, w = (x.shape[0] // k) * k, (x.shape[1] // k) * k
    return x[:h, :w].reshape(h // k, k, w // k, k, *x.shape[2:]).mean((1, 3))


Q = np.r_[np.linspace(0.02, 0.98, 20), 0.99, 0.995, 0.999]
QH = np.array([0.5, 0.8, 0.9, 0.95, 0.98, 0.99, 0.995, 0.999])
TRIM = 0.85   # the match term's mean over its best 85% of cells: a highlight a few px off is not punished twice


def tophat(lab, m):
    """each pixel's L* above the strand's own mean L* around it (8 frame px; the background does not
    bleed in): highlights' strength and area, wherever they fall"""
    w = m.astype(float); s8 = 8 * SCALE
    bl = ndimage.gaussian_filter(lab[..., 0] * w, s8) / np.maximum(ndimage.gaussian_filter(w, s8), 1e-3)
    return (lab[..., 0] - bl)[m]


def score(im):
    """the loss of a render (H x W x 3 uint8, the frame) against the reference, and its parts"""
    im = prep(im); lab = skc.rgb2lab(im / 255.0); L = K.lobes(im); parts = {}
    for col in ("yellow", "blue"):
        m = ndimage.binary_erosion(REF_L[col], iterations=ER) & ndimage.binary_erosion(L[col], iterations=ER)
        # match: per pixel at 1/4 resolution, over 4x4 cells wholly inside the matched interior
        cell = pool4(m.astype(float)) > 0.999
        d = np.sort(np.linalg.norm(pool4(lab) - pool4(REF_LAB), axis=-1)[cell])[: int(TRIM * cell.sum())]
        a, b = lab[m], REF_LAB[m]
        qd = lambda f: np.abs(np.quantile(f(a), Q) - np.quantile(f(b), Q)).mean()
        ch = lambda x: np.hypot(x[:, 1], x[:, 2]); hu = lambda x: np.degrees(np.arctan2(x[:, 2], x[:, 1]))
        mr = ndimage.binary_erosion(L[col], iterations=ER); mf = ndimage.binary_erosion(REF_L[col], iterations=ER)
        hl = float(np.abs(np.quantile(tophat(lab, mr), QH) - np.quantile(tophat(REF_LAB, mf), QH)).mean())
        g = lambda X: np.hypot(ndimage.sobel(X[..., 0], 0), ndimage.sobel(X[..., 0], 1)) / 8.0 * SCALE   # per frame px
        mg = ndimage.binary_erosion(m, iterations=max(1, round(2 * SCALE)))
        parts[col] = dict(match=float(d.mean()), dist=float(qd(lambda x: x[:, 0]) + qd(ch) + 1.5 * qd(hu)), hl=2.0 * hl,
                          grad=float(np.abs(np.quantile(g(lab)[mg], Q) - np.quantile(g(REF_LAB)[mg], Q)).mean() * 4))
    bg = ~(L["yellow"] | L["blue"]) & ~(REF_L["yellow"] | REF_L["blue"])
    fm = np.zeros(bg.shape, bool); fm[FLOOR] = True; fm &= ndimage.binary_erosion(bg, iterations=max(1, round(6 * SCALE)))
    cell = pool4(fm.astype(float)) > 0.999
    parts["floor"] = float(np.linalg.norm(pool4(lab) - pool4(REF_LAB), axis=-1)[cell].mean())
    total = sum(p["match"] + p["dist"] + p["grad"] + p["hl"] for c, p in parts.items() if c != "floor") + 0.5 * parts["floor"]
    return float(total), parts


# the floor alone (lookfit.py fit --floor): the shadow card's parameters against the reference's
# floor, per pixel (CIELAB dE at 1/2 resolution) over the background in both, y 690-960
FLOOR_SPACE = [
    ("shadowCard.band", 0.05, 0.7), ("shadowCard.bandOffset", -20, 10), ("shadowCard.fadeUp", 3, 40), ("shadowCard.fadeDown", 3, 40),
    ("shadowCard.fade", 80, 500), ("shadowCard.contact", 0.0, 0.9), ("shadowCard.contactFall", 2, 20), ("shadowCard.contactRange", 2, 40),
    ("shadowCard.colour.r", 0.3, 0.8), ("shadowCard.colour.g", 0.2, 0.7), ("shadowCard.colour.b", 0.2, 0.8),
    ("shadowCard.bounce.k", 0.0, 0.5), ("shadowCard.bounce.fall", 5, 120), ("shadowCard.bounce.blur", 4, 60),
]
FLOOR_ROWS = (690, 960)


def floor_score(im):
    W, H = round(1448 * SCALE), round(1086 * SCALE)
    if im.shape[1] != W:
        im = np.asarray(Image.fromarray(im).resize((W, H), Image.LANCZOS))
    ref = np.asarray(Image.fromarray(REF_FULL).resize((W, H), Image.LANCZOS))
    r0, r1 = (round(v * SCALE) for v in FLOOR_ROWS); a, b = im[r0:r1], ref[r0:r1]
    La, Lb = K.lobes(a), K.lobes(b)
    bg = ndimage.binary_erosion(~(La["yellow"] | La["blue"] | Lb["yellow"] | Lb["blue"]), iterations=max(1, round(4 * SCALE)))
    d = np.linalg.norm(skc.rgb2lab(a / 255.0) - skc.rgb2lab(b / 255.0), axis=-1)
    # the shading's own scale is a few L*: weight the dark band's error, where the reference is not white
    return float(d[bg].mean() * 10), {"floor": float(d[bg].mean())}


def load_patch(s):
    return json.loads(s) if s.strip().startswith("{") else json.load(open(s))


def variants(out, items):
    os.makedirs(out, exist_ok=True)
    w = Worker(); res = {}
    try:
        for it in items:
            name, patch = it.split("=", 1); patch = load_patch(patch)
            raw = f"{out}/{name}-raw.png"; w.render(patch, raw)
            base = json.load(open(os.path.join(ROOT, "snakes/w-final.look.json")))
            soft = patch.get("softness", base.get("softness", 0))
            im = blur(np.asarray(Image.open(raw).convert("RGB")), soft * SCALE); Image.fromarray(im).save(f"{out}/{name}.png")
            t, p = score(im); res[name] = dict(total=t, parts=p)
            print(f"{name}: {t:.2f}", json.dumps({k: (round(v, 2) if isinstance(v, float) else {kk: round(vv, 2) for kk, vv in v.items()}) for k, v in p.items()}), flush=True)
    finally:
        w.close()
    json.dump(res, open(f"{out}/scores.json", "w"), indent=1)


if __name__ == "__main__" and sys.argv[1] == "variants":
    ap = argparse.ArgumentParser(); ap.add_argument("cmd"); ap.add_argument("out"); ap.add_argument("items", nargs="*")
    A = ap.parse_args()
    if A.cmd == "variants":
        variants(os.path.abspath(A.out), A.items)


# the fitted look: (key path, lo, hi); a colour is three entries (hue deg, saturation, value)
SPACE = [
    ("yellow", "hsv", [(30, 60), (0.55, 1.0), (0.7, 1.0)]),
    ("blue", "hsv", [(205, 235), (0.75, 1.0), (0.6, 1.0)]),
    ("exposure", 0.5, 1.6), ("envLevel", 0.8, 4.0),
    ("env.key", 2, 30), ("env.keySize", 0.8, 4.0), ("env.keyAz", -80, 10), ("env.keyEl", 10, 70),
    ("env.over", 0, 10), ("env.front", 0, 5), ("env.fill", 0, 4), ("env.floor", 0, 3), ("env.room", 0.0, 0.4), ("env.blur", 0.0, 0.12), ("env.walls", 0, 2.5),
    ("keyLight.colour.g", 0.85, 1.05), ("keyLight.colour.b", 0.75, 1.1),
    ("material.roughness", 0.18, 0.45), ("material.clearcoat", 0.4, 1.0), ("material.clearcoatRoughness", 0.03, 0.16), ("material.specularIntensity", 0.3, 1.0), ("material.aoPower", 0.5, 3.0),
    ("materials.yellow.shade.k", 0, 1), ("materials.yellow.shade.tint.g", 0.6, 1.0), ("materials.yellow.shade.tint.b", 0.3, 1.0),
    ("materials.blue.shade.k", 0, 1), ("materials.blue.shade.tint.r", 0.4, 1.0), ("materials.blue.shade.tint.g", 0.4, 1.0),
    ("materials.yellow.envMapIntensity", 0.4, 1.6), ("materials.blue.envMapIntensity", 0.4, 1.6),
    ("keyLight.intensity", 0, 4), ("keyLight.az", -80, 10), ("keyLight.el", 15, 75), ("keyLight.size", 2, 24),
]


def hsv_hex(h, s, v):
    import colorsys
    r, g, b = colorsys.hsv_to_rgb((h % 360) / 360, s, v)
    return "#%02x%02x%02x" % tuple(int(round(255 * c)) for c in (r, g, b))


def hex_hsv(x):
    import colorsys
    r, g, b = (int(x[i:i + 2], 16) / 255 for i in (1, 3, 5)); h, s, v = colorsys.rgb_to_hsv(r, g, b)
    return [h * 360, s, v]


def dims():
    out = []
    for e in SPACE:
        if e[1] == "hsv":
            out += [(f"{e[0]}.{c}",) + tuple(r) for c, r in zip("hsv", e[2])]
        else:
            out.append(e)
    return out


def setp(d, path, v):
    ks = path.split("."); [d := d.setdefault(k, {}) for k in ks[:-1]]; d[ks[-1]] = v


def getp(d, path, default=None):
    for k in path.split("."):
        if not isinstance(d, dict) or k not in d:
            return default
        d = d[k]
    return d


def dirv(az, el):
    """towards a light at azimuth az (deg, 0 = the camera, negative = left) and elevation el"""
    a, e = np.radians(az), np.radians(el)
    return [float(np.sin(a) * np.cos(e)), float(np.sin(e)), float(np.cos(a) * np.cos(e))]


def to_look(u, fixed):
    """unit vector -> a look patch (on top of `fixed`)"""
    look = json.loads(json.dumps(fixed)); vals = {}
    for (path, lo, hi), x in zip(dims(), u):
        vals[path] = lo + float(np.clip(x, 0, 1)) * (hi - lo)
    for col in ("yellow", "blue"):
        look[col] = hsv_hex(vals.pop(f"{col}.h"), vals.pop(f"{col}.s"), vals.pop(f"{col}.v"))
    kd = 8.4   # the base look's key distance (its apparent size)
    az, el = vals.pop("env.keyAz"), vals.pop("env.keyEl"); look.setdefault("env", {})["keyPos"] = [kd * c for c in dirv(az, el)]
    az, el = vals.pop("keyLight.az"), vals.pop("keyLight.el"); look.setdefault("keyLight", {})["dir"] = dirv(az, el)
    if "keyLight.colour.g" in vals:
        look.setdefault("keyLight", {})["colour"] = [1.0, vals.pop("keyLight.colour.g"), vals.pop("keyLight.colour.b")]
    for col, keys in (("yellow", "rgb"), ("blue", "rgb")):
        t = [vals.pop(f"materials.{col}.shade.tint.{c}", 1.0) for c in keys]
        if f"materials.{col}.shade.k" in vals:
            setp(look, f"materials.{col}.shade.tint", t); setp(look, f"materials.{col}.shade.ref", 1.0)
    for p, v in vals.items():
        setp(look, p, v)
    return look


def from_look(look):
    """a full look -> the unit vector (the inverse of to_look, for the start)"""
    u = []
    kp = np.asarray(getp(look, "env.keyPos", [-3.5, 4, 6.5]), float); kp /= np.linalg.norm(kp)
    kd = np.asarray(getp(look, "keyLight.dir", [-0.5, 0.6, 0.6]), float); kd /= np.linalg.norm(kd)
    ang = lambda d: (float(np.degrees(np.arctan2(d[0], d[2]))), float(np.degrees(np.arcsin(d[1]))))
    hv = {c: hex_hsv(look[c]) for c in ("yellow", "blue")}
    special = {"env.keyAz": ang(kp)[0], "env.keyEl": ang(kp)[1], "keyLight.az": ang(kd)[0], "keyLight.el": ang(kd)[1]}
    for path, lo, hi in dims():
        if path[:-2] in hv:
            v = hv[path[:-2]]["hsv".index(path[-1])]
        elif path in special:
            v = special[path]
        elif path.startswith("keyLight.colour."):
            v = (getp(look, "keyLight.colour", [1, 1, 1]) or [1, 1, 1])["rgb".index(path[-1])]
        elif ".shade.tint." in path:
            t = getp(look, path.rsplit(".", 1)[0], [1, 1, 1]); v = t["rgb".index(path[-1])]
        elif path.endswith(".shade.k"):
            v = getp(look, path, 0.0)
        else:
            v = getp(look, path, {"material.aoPower": 1.0, "keyLight.intensity": 0.0, "keyLight.size": 8.0, "materials.blue.envMapIntensity": 1.0, "materials.yellow.envMapIntensity": 1.0, "env.walls": 0.0}.get(path, lo))
        u.append((float(v) - lo) / (hi - lo))
    return np.clip(np.asarray(u), 0, 1)


def fit(out, fixed, start, gens, procs, sigma, seed, free=None, ranges=None):
    sys.path.insert(0, HERE)
    from lobefit import cma
    os.makedirs(out, exist_ok=True)
    base = json.load(open(os.path.join(ROOT, "snakes/w-final.look.json")))
    full0 = json.loads(json.dumps(base)); [setp(full0, k, v) for k, v in flatten(start).items()]
    if ranges:
        # narrower ranges for some dimensions: { path: [lo, hi] }
        for i, e in enumerate(SPACE):
            if e[1] == "hsv":
                SPACE[i] = (e[0], "hsv", [tuple(ranges.get(f"{e[0]}.{c}", r)) for c, r in zip("hsv", e[2])])
            elif e[0] in ranges:
                SPACE[i] = (e[0], *ranges[e[0]])
    U0 = from_look(full0)
    # --free: only the dimensions whose path starts with one of these; the rest held at the start
    idx = [i for i, (p, *_) in enumerate(dims()) if not free or any(p.startswith(f) for f in free)]
    u0 = U0[idx]; n = len(u0)
    def full(u):
        U = U0.copy(); U[idx] = u; return U
    print("free", [dims()[i][0] for i in idx], flush=True)
    ws = [Worker() for _ in range(procs)]; log = open(f"{out}/fit.log", "a"); best = [np.inf, None]
    def f(u, wk):
        look = to_look(full(u), fixed); raw = f"{out}/w{wk}.png"
        ws[wk].render(look, raw)
        im = blur(np.asarray(Image.open(raw).convert("RGB")), look.get("softness", 0) * SCALE)
        t, p = score(im)
        if t < best[0]:
            best[0], best[1] = t, look; Image.fromarray(im).save(f"{out}/best.png"); json.dump(dict(loss=t, parts=p, look=look), open(f"{out}/best.json", "w"), indent=1)
        return (t, p)
    try:
        t0, p0 = f(u0, 0); print(f"start {t0:.2f}", flush=True); log.write(f"start {t0:.3f} {json.dumps(p0)}\n"); log.flush()
        def lg(g, b, F, s):
            b = b[0] if isinstance(b, tuple) else b
            print(f"gen {g:3d} best {b:.2f} gen-min {min(F):.2f} median {np.median(F):.2f} sigma {s:.3f}", flush=True)
            log.write(f"gen {g} best {b:.3f} min {min(F):.3f} sigma {s:.4f}\n"); log.flush()
        cma(f, n, sigma, np.zeros(n), np.ones(n), gens, procs, seed=seed, log=lg, m0=u0)
    finally:
        [w.close() for w in ws]
    print("best", best[0])


def flatten(d, pre=""):
    out = {}
    for k, v in d.items():
        if isinstance(v, dict):
            out.update(flatten(v, pre + k + "."))
        else:
            out[pre + k] = v
    return out


if __name__ == "__main__" and sys.argv[1] == "fit":
    ap = argparse.ArgumentParser(); ap.add_argument("cmd"); ap.add_argument("out")
    ap.add_argument("--fixed", default="{}"); ap.add_argument("--start", default="{}")
    ap.add_argument("--gens", type=int, default=30); ap.add_argument("--procs", type=int, default=2)
    ap.add_argument("--sigma", type=float, default=0.15); ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--free", default=""); ap.add_argument("--ranges", default="{}")
    A = ap.parse_args()
    fit(os.path.abspath(A.out), load_patch(A.fixed), load_patch(A.start), A.gens, A.procs, A.sigma, A.seed,
        free=[f for f in A.free.split(",") if f] or None, ranges=load_patch(A.ranges))
