# Measure the reference: colour masks, silhouette, medial axis, colours.
import numpy as np
from PIL import Image
from skimage import morphology, measure
import sys
src = sys.argv[1]; out = sys.argv[2]
im = np.asarray(Image.open(src).convert("RGB")).astype(float)
r, g, b = im[..., 0], im[..., 1], im[..., 2]
mx = im.max(-1); mn = im.min(-1); sat = (mx - mn) / np.maximum(mx, 1)
blue = (b > r + 40) & (b > g + 20) & (sat > 0.35)
yellow = (r > b + 60) & (g > b + 40) & (sat > 0.35)
dark = (mx < 70)  # eyes
obj = blue | yellow | dark
obj = morphology.remove_small_objects(obj, 500)
obj = morphology.remove_small_holes(obj, 2000)
lab = measure.label(obj)
props = sorted(measure.regionprops(lab), key=lambda p: -p.area)
print("components", [(p.area, p.bbox) for p in props[:5]])
ys, xs = np.nonzero(obj)
print("object bbox x", xs.min(), xs.max(), "y", ys.min(), ys.max())
# colours: median of each mask's mid-luminance pixels (body colour, not highlight or shadow)
for name, m in [("blue", blue), ("yellow", yellow)]:
    px = im[m]
    lum = px @ [0.2126, 0.7152, 0.0722]
    q = np.percentile(lum, [10, 50, 90])
    mid = px[(lum > q[0]) & (lum < q[2])]
    print(name, "median", np.median(mid, 0).round(), "p10", np.median(px[np.abs(lum-q[0])<3],0).round(), "p90", np.median(px[np.abs(lum-q[2])<3],0).round(), "n", m.sum())
# background
bgm = ~morphology.binary_dilation(obj, morphology.disk(20))
print("bg corners", im[:40, :40].reshape(-1,3).mean(0).round(1), im[-40:, :40].reshape(-1,3).mean(0).round(1), "bg under", im[790:830, 500:950].reshape(-1,3).mean(0).round(1))
# eyes
el = measure.label(dark & obj)
for p in measure.regionprops(el):
    if p.area > 30: print("eye", p.area, [round(c) for c in p.centroid[::-1]], p.bbox)
# vertical profile of shadow under valleys
col = im[:, 540]; print("col540 lum below object", [round(float(v)) for v in (col[740:860:8] @ [0.2126,0.7152,0.0722])])
col = im[:, 720]; print("col720 lum below", [round(float(v)) for v in (col[540:860:16] @ [0.2126,0.7152,0.0722])])
vis = np.zeros(im.shape, np.uint8) + 255
vis[blue] = [40, 80, 220]; vis[yellow] = [250, 200, 40]; vis[dark] = [0, 0, 0]
skel = morphology.skeletonize(morphology.binary_opening(obj, morphology.disk(25)))
vis[morphology.binary_dilation(skel, morphology.disk(2))] = [255, 0, 0]
Image.fromarray(vis).save(out)
np.save(out.replace(".png", "-obj.npy"), obj)
