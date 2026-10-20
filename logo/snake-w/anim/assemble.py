"""The progress animation: every milestone's real render beside the reference, with its caption
and a running chart of how much of the reference's blue and yellow it covers (mean IoU of the
two colour regions, geodiag.masks). Writes anim/progress.gif, anim/progress.mp4, anim/score.json.
Usage (from the logo root): assemble.py"""

import json
import os
import subprocess
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont


sys.path.insert(0, "tools")
import geodiag as G


CROP = (230, 200, 1240, 850)  # the W with a margin, in reference pixels
S = 0.56  # panel scale
caps = json.load(open("anim/captions.json"))
caps = [c for c in caps if os.path.exists(f"anim/frames/{c['tag']}.png")]
Mr = G.masks(G.REF)


def score(png):
    lab = G.masks(png)["lab"]
    iou = [
        ((lab == k) & (Mr["lab"] == k)).sum() / ((lab == k) | (Mr["lab"] == k)).sum()
        for k in (1, 2)
    ]
    return float(np.mean(iou))


for c in caps:
    c["score"] = score(f"anim/frames/{c['tag']}.png")
json.dump(caps, open("anim/score.json", "w"), indent=1)

pw, ph = int((CROP[2] - CROP[0]) * S), int((CROP[3] - CROP[1]) * S)
W, CAP, CH = 2 * pw + 30, 54, 92
H = 16 + ph + CAP + CH
try:
    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 19)
    small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 13)
except OSError:
    font = small = ImageFont.load_default()


def panel(p):
    return Image.open(p).convert("RGB").crop(CROP).resize((pw, ph), Image.LANCZOS)


ref = panel(G.REF)
sc = [c["score"] for c in caps]
lo, hi = min(sc) - 0.01, max(sc) + 0.01
x0, x1, y0, y1 = 60, W - 20, H - CH + 18, H - 22


def X(i):
    return x0 + (x1 - x0) * i / max(len(caps) - 1, 1)


def Y(v):
    return y1 - (y1 - y0) * (v - lo) / (hi - lo)


PH = {
    "a": "parametric body",
    "b": "spline body",
    "c": "autonomous loop",
    "d": "look",
    "e": "final",
}
os.makedirs("anim/out", exist_ok=True)
for i, c in enumerate(caps):
    im = Image.new("RGB", (W, H), "#fdfdfb")
    d = ImageDraw.Draw(im)
    im.paste(ref, (10, 16))
    im.paste(panel(f"anim/frames/{c['tag']}.png"), (20 + pw, 16))
    d.text((14, 18), "reference", fill="#666", font=small)
    d.text((24 + pw, 18), f"{i + 1}/{len(caps)}", fill="#666", font=small)
    d.text(
        (14, 16 + ph + 12), f"{PH[c['tag'][0]]}  ·  {c['cap']}", fill="#222", font=font
    )
    d.text(
        (W - 230, 16 + ph + 16),
        f"colour overlap {c['score']:.3f}",
        fill="#222",
        font=small,
    )
    # the running chart: every milestone faint, the ones so far solid, this one marked
    d.text((8, y0 - 4), f"{hi:.2f}", fill="#999", font=small)
    d.text((8, y1 - 12), f"{lo:.2f}", fill="#999", font=small)
    pts = [(X(j), Y(v)) for j, v in enumerate(sc)]
    d.line(pts, fill="#ddd", width=2)
    d.line(pts[: i + 1], fill="#0058f2", width=3) if i else None
    for j in range(1, len(caps)):
        if caps[j]["tag"][0] != caps[j - 1]["tag"][0]:
            d.line([(X(j - 0.5), y0 - 6), (X(j - 0.5), y1)], fill="#eee", width=1)
    px, py = pts[i]
    d.ellipse([px - 5, py - 5, px + 5, py + 5], fill="#ffc420", outline="#222")
    im.save(f"anim/out/{i:03d}.png")
# hold the first and last frames
dur = [
    1800 if i == 0 else 3500 if i == len(caps) - 1 else 700 for i in range(len(caps))
]
frames = [Image.open(f"anim/out/{i:03d}.png") for i in range(len(caps))]
pal = [f.convert("P", palette=Image.ADAPTIVE, colors=255) for f in frames]
pal[0].save(
    "anim/progress.gif",
    save_all=True,
    append_images=pal[1:],
    duration=dur,
    loop=0,
    optimize=True,
)
with open("anim/concat.txt", "w") as f:
    for i, t in enumerate(dur):
        f.write(f"file 'out/{i:03d}.png'\nduration {t / 1000}\n")
    f.write(f"file 'out/{len(caps) - 1:03d}.png'\n")
subprocess.run(
    [
        "ffmpeg",
        "-y",
        "-loglevel",
        "error",
        "-f",
        "concat",
        "-i",
        "anim/concat.txt",
        "-vf",
        "fps=25,format=yuv420p,pad=ceil(iw/2)*2:ceil(ih/2)*2",
        "-c:v",
        "libx264",
        "-crf",
        "20",
        "anim/progress.mp4",
    ],
    check=True,
)
for c in caps:
    print(f"{c['tag']:<4} {c['score']:.3f}  {c['cap']}")
print(
    "gif",
    os.path.getsize("anim/progress.gif") // 1024,
    "KB; mp4",
    os.path.getsize("anim/progress.mp4") // 1024,
    "KB",
)
