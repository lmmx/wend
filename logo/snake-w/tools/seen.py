"""Is a change visible at viewing scale? Both images at quarter scale (362 x 272, how the logo is
seen whole), blurred by sigma 1 px so that a shift of a few full-size px washes out as it does
to the eye, then the CIEDE2000 colour difference per pixel, over the pixels where either shows
the sculpture.
  mean      mean dE00 over those pixels
  vis       the fraction of them with dE00 > 5 (a difference anyone sees side by side)
  verdict   UNCHANGED when vis < 5% and mean < 1.5: nobody would tell the two apart whole (the
            owner's eye, 2026-10-19: rounds 11-19's incumbents, mean 0.98 and 4.4% apart, read
            as no change at all)
A side diagnostic of rendered appearance only. It is not a geometry metric and not a gate:
blurred, downsampled colour differences cannot say whether a lobe has the right shape, and a
whole-frame number does not move for a real correction to one lobe. The numbered-lobe
evaluator decides what is wrong with the geometry and the blind judge whether it improved.
Usage (from the logo root): seen.py A.png B.png [--map out.png]"""
import os, sys
import numpy as np
from PIL import Image
from scipy import ndimage
from skimage import color
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from anatomy import colour_masks


def small(path):
    im = Image.open(path).convert("RGB")
    a = np.asarray(im.resize((im.width // 4, im.height // 4), Image.LANCZOS)).astype(float) / 255
    a = np.stack([ndimage.gaussian_filter(a[..., k], 1.0) for k in range(3)], -1)
    b, y = colour_masks(np.asarray(im))
    m = np.asarray(Image.fromarray(((b | y) * 255).astype(np.uint8)).resize((im.width // 4, im.height // 4))) > 64
    return color.rgb2lab(a), m


def seen(pa, pb):
    A, ma = small(pa); B, mb = small(pb)
    d = color.deltaE_ciede2000(A, B)
    M = ndimage.binary_dilation(ma | mb, iterations=2)
    mean, vis = float(d[M].mean()), float((d[M] > 5).mean())
    return dict(mean=mean, vis=vis, verdict="UNCHANGED" if vis < 0.05 and mean < 1.5 else "CHANGED", d=d, M=M)


if __name__ == "__main__":
    a, b = sys.argv[1], sys.argv[2]
    r = seen(a, b)
    print(f"{os.path.basename(a)} vs {os.path.basename(b)}: mean dE00 {r['mean']:.2f}, visible (dE>5) {r['vis']:.1%} -> {r['verdict']}")
    if "--map" in sys.argv:
        d = np.clip(r["d"] / 20, 0, 1)
        Image.fromarray((np.stack([d, d * 0.3, 1 - d], -1) * 255 * r["M"][..., None]).astype(np.uint8)).resize((d.shape[1] * 2, d.shape[0] * 2), Image.NEAREST).save(sys.argv[sys.argv.index("--map") + 1])
