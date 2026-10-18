"""Compare a still with the reference: side by side, a 50% blend, and label agreement."""
import sys
import numpy as np
from PIL import Image, ImageDraw
sys.path.insert(0, __file__.rsplit("/", 1)[0])
import snakefit as sf

ref_p, still_p, out_p = sys.argv[1:4]
ref = Image.open(ref_p).convert("RGB"); st = Image.open(still_p).convert("RGB").resize(ref.size)
_, lr = sf.ref_labels(ref_p, 1.0)
_, ls = sf.ref_labels(still_p, 1.0)
agree = ((lr == ls) & (lr > 0)).sum() / max(((lr > 0) | (ls > 0)).sum(), 1)
sil = ((lr > 0) & (ls > 0)).sum() / max(((lr > 0) | (ls > 0)).sum(), 1)
blend = Image.blend(ref, st, 0.5)
diff = np.full((*lr.shape, 3), 255, np.uint8)
diff[(lr != ls) & (lr > 0)] = [230, 60, 60]
diff[(lr != ls) & (lr == 0)] = [60, 160, 230]
diff[(lr == ls) & (lr > 0)] = [205, 205, 205]
W, H = ref.size
sheet = Image.new("RGB", (W * 2, H * 2), "white")
sheet.paste(ref, (0, 0)); sheet.paste(st, (W, 0)); sheet.paste(blend, (0, H)); sheet.paste(Image.fromarray(diff), (W, H))
d = ImageDraw.Draw(sheet)
for (x, y), t in zip([(10, 10), (W + 10, 10), (10, H + 10), (W + 10, H + 10)],
                     ["reference", "three.js", "50% blend", f"labels: silhouette IoU {sil:.3f}, colour agreement {agree:.3f}"]):
    d.text((x, y), t, fill=(0, 0, 0))
sheet = sheet.resize((W, H), Image.LANCZOS)
sheet.save(out_p)
print(f"silhouette IoU {sil:.3f}  colour agreement {agree:.3f}")
