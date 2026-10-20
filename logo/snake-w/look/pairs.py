"""blind pages for the look judge: page0 the whole frame (reference | X | Y), page1 and page2 crops
at 2x (reference | X | Y). Usage: look/pairs.py X.png Y.png OUT_DIR"""

import os
import sys

from PIL import Image, ImageDraw


X, Y, out = sys.argv[1:4]
os.makedirs(out, exist_ok=True)
ref = Image.open("snakes/ref/reference.png").convert("RGB")
ims = [ref] + [
    Image.open(p).convert("RGB").resize(ref.size, Image.LANCZOS) for p in (X, Y)
]
lab = ["reference", "X", "Y"]


def page(tiles, path):
    w, h = tiles[0][1][0].size
    W = 3 * (w + 10) + 10
    H = len(tiles) * (h + 30) + 10
    S = Image.new("RGB", (W, H), (225, 225, 225))
    d = ImageDraw.Draw(S)
    y = 6
    for name, row in tiles:
        d.text((10, y), name + ": " + " | ".join(lab), fill=(0, 0, 0))
        y += 18
        for i, c in enumerate(row):
            S.paste(c, (10 + i * (w + 10), y))
        y += h + 12
    S.save(path)


box = (240, 200, 1220, 840)
page(
    [("whole frame", [im.crop(box).resize((735, 480), Image.LANCZOS) for im in ims])],
    f"{out}/page0-whole.png",
)
crops = {
    "left arm and yellow head": (300, 280, 560, 560),
    "left valley": (440, 520, 720, 800),
    "arch": (560, 380, 860, 640),
}
page(
    [
        (
            n,
            [
                im.crop(b).resize(((b[2] - b[0]) * 2, (b[3] - b[1]) * 2), Image.LANCZOS)
                for im in ims
            ],
        )
        for n, b in crops.items()
    ],
    f"{out}/page1-crops.png",
)
crops = {
    "right valley": (800, 520, 1080, 800),
    "blue head": (980, 230, 1200, 450),
    "floor and base": (380, 680, 1120, 860),
}
page(
    [
        (
            n,
            [
                im.crop(b).resize(
                    (
                        min(560, (b[2] - b[0]) * 2),
                        round(
                            min(560, (b[2] - b[0]) * 2) * (b[3] - b[1]) / (b[2] - b[0])
                        ),
                    ),
                    Image.LANCZOS,
                )
                for im in ims
            ],
        )
        for n, b in crops.items()
    ],
    f"{out}/page2-crops.png",
)
print("pages ->", out)
