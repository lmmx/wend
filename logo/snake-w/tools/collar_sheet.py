"""Close-ups of the three owner-named defects (the left scarf, the right nape, the RHS tubes) and
the full frame, real renders. One row per defect: reference | incumbent colour | candidate colour |
incumbent clay | candidate clay | incumbent zebra | candidate zebra (several candidates: their
colour, clay and zebra columns follow in turn).
Usage (from the logo root): collar_sheet.py OUT.png TITLE INC_DIR/INC_TAG CAND_DIR/CAND_TAG [...]"""
import sys
import numpy as np
from PIL import Image
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

REGIONS = [("1  left scarf (L01)", (330, 290, 540, 560)), ("2  right nape (H2 | L16)", (960, 270, 1175, 500)), ("3  RHS tubes (L14-L16)", (895, 380, 1115, 740))]
out, title, *runs = sys.argv[1:]
ref = np.asarray(Image.open("snakes/ref/reference.png").convert("RGB"))
img = {}
load = lambda p: img.setdefault(p, np.asarray(Image.open(p).convert("RGB")))
names = [r.split("/")[-1] for r in runs]
cols = [("reference", None, "colour")] + [(f"{n} {m.split('-')[0]}", r, m) for m in ("colour", "clay-full", "zebra-full") for n, r in zip(names, runs)]
fig = plt.figure(figsize=(2.6 * len(cols), 3.2 + 3.4 * 3), dpi=90)
gs = fig.add_gridspec(4, len(cols), height_ratios=[1.0, 1.25, 1.25, 1.25])
for j, (nm, r) in enumerate([("reference", None)] + list(zip(names, runs))):
    span = slice(0, 1) if r is None else slice(1 + (j - 1) * (len(cols) - 1) // len(runs), 1 + j * (len(cols) - 1) // len(runs))
    ax = fig.add_subplot(gs[0, span]); ax.imshow(ref if r is None else load(f"{r}-colour.png")); ax.set_xlim(280, 1190); ax.set_ylim(800, 250); ax.axis("off")
    ax.set_title(nm, fontsize=11)
    for lab, (x0, y0, x1, y1) in REGIONS:
        ax.add_patch(plt.Rectangle((x0, y0), x1 - x0, y1 - y0, fill=False, ec="#d62728", lw=1, ls="--"))
for i, (lab, (x0, y0, x1, y1)) in enumerate(REGIONS):
    for j, (nm, r, mode) in enumerate(cols):
        ax = fig.add_subplot(gs[1 + i, j]); ax.imshow(ref if r is None else load(f"{r}-{mode}.png"))
        ax.set_xlim(x0, x1); ax.set_ylim(y1, y0); ax.set_xticks([]); ax.set_yticks([])
        if i == 0: ax.set_title(nm, fontsize=9)
        if j == 0: ax.set_ylabel(lab, fontsize=10, color="#d62728")
fig.suptitle(title, fontsize=13, weight="bold")
fig.tight_layout(); fig.savefig(out); plt.close(fig)
print("wrote", out)
