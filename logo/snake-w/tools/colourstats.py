"""Per-colour luminance percentiles and median colours of an image's blue and yellow parts."""
import sys
import numpy as np
from PIL import Image
for path in sys.argv[1:]:
    im = np.asarray(Image.open(path).convert("RGB")).astype(float)
    r, g, b = im[..., 0], im[..., 1], im[..., 2]
    mx = im.max(-1); mn = im.min(-1); sat = (mx - mn) / np.maximum(mx, 1)
    masks = {"blue": (b > r + 40) & (b > g + 20) & (sat > 0.35), "yellow": (r > b + 60) & (g > b + 40) & (sat > 0.35)}
    out = []
    for name, m in masks.items():
        px = im[m]; lum = px @ [0.2126, 0.7152, 0.0722]
        qs = np.percentile(lum, [5, 25, 50, 75, 95])
        bands = [np.median(px[np.abs(lum - q) < 4], 0).round().astype(int).tolist() for q in qs]
        out.append(f"{name}: lum p5..p95 {qs.round().astype(int).tolist()}  rgb at p5/p50/p95 {bands[0]} {bands[2]} {bands[4]}")
    hi = (mn > 235) & (sat < 0.12)
    print(path.rsplit("/", 1)[-1], "|", " | ".join(out))
