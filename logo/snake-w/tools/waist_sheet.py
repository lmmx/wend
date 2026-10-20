"""The blue neck's waist, isolated: the incumbent (waist 12.9 px) against 6 and 0, both strands and
the blue alone, clay / zebra / curvature; and the neck's edges x(y) against the reference's.
Diagnostic renders only (snakes/diag-waist*.params.json); the committed model is unchanged.
Usage (from the logo root): waist_sheet.py OUT.png"""
import sys
import numpy as np
from PIL import Image
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
sys.path.insert(0, "tools")
from anatomy import colour_masks
D = "auto/r33/nape"; box = (960, 270, 1175, 500); x0, y0, x1, y1 = box; S = 3
rows = [("waist 12.9 px (the incumbent)", ""), ("waist 6 px", "waist6-"), ("waist 0", "waist0-")]
cols = [("both", "clay"), ("both", "zebra"), ("onlyblue", "clay"), ("onlyblue", "zebra"), ("onlyblue", "curv")]
fig = plt.figure(figsize=(3.1 * 7, 3.3 * 3 + 0.6), dpi=90)
gs = fig.add_gridspec(3, 7, width_ratios=[1, 1, 1, 1, 1, 1, 1.3])
ref = np.asarray(Image.open("snakes/ref/reference.png").convert("RGB"))
b, y = colour_masks(ref); refsil = b | y
def edges(sil, ys, x_off=0, sc=1):
    L, R = [], []
    for yy in ys:
        row = np.nonzero(sil[int((yy - y0) * sc) if sc != 1 else yy])[0] if sc != 1 else np.nonzero(sil[yy, 960:1130])[0] + 960
        if sc != 1: row = row / sc + x0
        L.append(row.min() if len(row) else np.nan); R.append(row.max() if len(row) else np.nan)
    return np.array(L), np.array(R)
ys = np.arange(330, 470)
eL, eR = edges(refsil, ys)
for i, (lab, pre) in enumerate(rows):
    for j, (who, mode) in enumerate(cols):
        ax = fig.add_subplot(gs[i, j]); ax.imshow(np.asarray(Image.open(f"{D}/{pre}{who}-{mode}-nape.png").convert("RGB"))); ax.set_xticks([]); ax.set_yticks([])
        if i == 0: ax.set_title(f"{'both strands' if who == 'both' else 'blue alone'}: {mode}", fontsize=10)
        if j == 0: ax.set_ylabel(lab, fontsize=10, weight="bold")
    ax = fig.add_subplot(gs[i, 6])
    im = np.asarray(Image.open(f"{D}/{pre}onlyblue-clay-nape.png").convert("L")).astype(float)
    sil = im < 225
    cL = []; cR = []
    for yy in ys:
        r = np.nonzero(sil[int((yy - y0) * S), : int((1130 - x0) * S)])[0]
        cL.append(r.min() / S + x0 if len(r) else np.nan); cR.append(r.max() / S + x0 if len(r) else np.nan)
    ax.plot(eL, ys, "k-", lw=1.4, label="reference outline (yellow covers the neck below ~y 405)")
    ax.plot(cL, ys, "-", color="#1f3fbf", lw=1.4, label="blue alone: back of the neck")
    ax.plot(cR, ys, "--", color="#1f3fbf", lw=1.2, label="blue alone: throat")
    ax.plot(eR, ys, "k--", lw=1.0)
    ax.invert_yaxis(); ax.set_xlim(960, 1130); ax.set_aspect("equal"); ax.tick_params(labelsize=7)
    if i == 0: ax.legend(fontsize=7, loc="lower left")
fig.suptitle("Right nape: the blue neck's waist (necks[1].waist) makes the hourglass the yellow coil traces (diagnostic renders; the model is unchanged)", fontsize=12, weight="bold")
fig.tight_layout(); fig.savefig(sys.argv[1]); plt.close(fig); print("wrote", sys.argv[1])
