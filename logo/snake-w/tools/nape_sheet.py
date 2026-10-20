"""The nape (or scarf) isolation sheet: rows = both strands / the near strand alone / contact press
off / the heads meshed in the page (the audit renders) instead of the production bake; columns =
reference | production colour | clay | zebra (bands about up) | zebra (about x) | curvature.
Usage (from the logo root): nape_sheet.py VIEW OUT.png TITLE"""
import sys
import numpy as np
from PIL import Image
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
view, out, title = sys.argv[1:4]
box = {"nape": (960, 270, 1175, 500), "scarf": (330, 290, 540, 560)}[view]
alone = {"nape": "onlyblue", "scarf": "onlyyellow"}[view]
D = "auto/r33/nape"
rows = [("both strands", "prod-both"), ({"nape": "blue alone (yellow hidden)", "scarf": "yellow alone (blue hidden)"}[view], f"prod-{alone}"),
        ("contact press off", "prod-nopress"), ("heads meshed in the page (audit renders)", "both")]
if view == "scarf": rows.insert(2, ("blue alone (yellow hidden)", "prod-onlyblue"))
modes = ["clay", "zebra", "zebrav", "curv"]
x0, y0, x1, y1 = box
crop = lambda p: Image.open(p).convert("RGB").crop(box)
ref = crop("snakes/ref/reference.png"); col = crop("look/look6.png")
fig, axs = plt.subplots(len(rows), 2 + len(modes), figsize=(3.0 * (2 + len(modes)), 3.25 * len(rows)), dpi=90)
for i, (lab, pre) in enumerate(rows):
    for j in range(2 + len(modes)):
        ax = axs[i, j]; ax.set_xticks([]); ax.set_yticks([])
        if j == 0:
            if i == 0: ax.imshow(ref); ax.set_title("reference", fontsize=10)
            else: ax.axis("off")
            ax.set_ylabel(lab, fontsize=10)
            if i: ax.text(0.5, 0.5, lab, transform=ax.transAxes, ha="center", va="center", fontsize=10, weight="bold", wrap=True)
            continue
        if j == 1:
            if i == 0: ax.imshow(col); ax.set_title("production (look 6)", fontsize=10)
            else: ax.axis("off")
            continue
        m = modes[j - 2]; ax.imshow(np.asarray(Image.open(f"{D}/{pre}-{m}-{view}.png").convert("RGB")))
        if i == 0: ax.set_title({"clay": "clay", "zebra": "zebra (bands about up)", "zebrav": "zebra (bands about x)", "curv": "curvature x 40 px"}[m], fontsize=10)
fig.suptitle(title, fontsize=13, weight="bold")
fig.tight_layout(); fig.savefig(out); plt.close(fig)
print("wrote", out)
