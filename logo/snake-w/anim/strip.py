"""A static fallback for the progress animation: the reference and seven milestones in a grid,
each with its caption and colour-overlap score (anim/score.json). Writes anim/progress-strip.png.
Usage (from the logo root, after assemble.py): strip.py"""

import json

from PIL import Image, ImageDraw, ImageFont


CROP = (230, 200, 1240, 850)
S = 0.36
sc = {c["tag"]: c for c in json.load(open("anim/score.json"))}
picks = [
    ("ref", "reference"),
    ("a01", "1. first parametric fit"),
    ("a16", "2. art-directed parametric"),
    ("b01", "3. C2 spline body"),
    ("b03", "4. audit loop start"),
    ("c05", "5. loop round 7"),
    ("c13", "6. valley cushions (r28)"),
    ("e1", "7. final: r38-edge, look 6"),
]
pw, ph = int((CROP[2] - CROP[0]) * S), int((CROP[3] - CROP[1]) * S)
CAP = 26
font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 14)
im = Image.new("RGB", (4 * pw + 50, 2 * (ph + CAP) + 30), "#fdfdfb")
d = ImageDraw.Draw(im)
for i, (tag, cap) in enumerate(picks):
    x, y = 10 + (i % 4) * (pw + 10), 10 + (i // 4) * (ph + CAP + 10)
    src = "snakes/ref/reference.png" if tag == "ref" else f"anim/frames/{tag}.png"
    im.paste(
        Image.open(src).convert("RGB").crop(CROP).resize((pw, ph), Image.LANCZOS),
        (x, y),
    )
    d.text(
        (x + 2, y + ph + 4),
        cap + ("" if tag == "ref" else f"  ({sc[tag]['score']:.3f})"),
        fill="#222",
        font=font,
    )
im.save("anim/progress-strip.png", optimize=True)
print(im.size)
