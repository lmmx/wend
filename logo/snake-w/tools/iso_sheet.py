"""Close-ups for a head candidate: the reference and production crop, then incumbent vs candidate
for the assembly (both strands: colour, clay, zebra, curvature) and the isolated strand (clay,
zebra, curvature) from auto/rN/iso/{inc,cand}-{both,only*}-MODE-VIEW.png.
Usage (from the logo root): iso_sheet.py ISO_DIR VIEW ONLY INC_COLOUR CAND_COLOUR OUT.png TITLE"""
import sys
import numpy as np
from PIL import Image
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
D, view, only, ic, cc, out, title = sys.argv[1:8]
box = {"nape": (960, 270, 1175, 500), "scarf": (330, 290, 540, 560)}[view]
crop = lambda p: Image.open(p).convert("RGB").crop(box)
rows = [("incumbent", "inc", ic), ("candidate", "cand", cc)]
fig, axs = plt.subplots(2, 8, figsize=(3.0 * 8, 3.4 * 2 + 0.6), dpi=90)
for i, (lab, who, col) in enumerate(rows):
    tiles = [("reference", crop("snakes/ref/reference.png")), ("real render (loop look)", crop(col))]
    tiles += [(f"assembly {m}", Image.open(f"{D}/{who}-both-{m}-{view}.png")) for m in ("clay", "zebra", "curv")]
    tiles += [(f"{only.replace('only', '')} alone {m}", Image.open(f"{D}/{who}-{only}-{m}-{view}.png")) for m in ("clay", "zebra", "curv")]
    for j, (t, im) in enumerate(tiles):
        ax = axs[i, j]; ax.imshow(im); ax.set_xticks([]); ax.set_yticks([])
        if i == 0: ax.set_title(t, fontsize=10)
        if j == 0: ax.set_ylabel(lab, fontsize=12, weight="bold")
fig.suptitle(title, fontsize=13, weight="bold")
fig.tight_layout(); fig.savefig(out); plt.close(fig); print("wrote", out)
