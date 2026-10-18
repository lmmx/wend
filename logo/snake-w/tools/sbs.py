"""Reference and renders side by side, same framing (crop box), labelled."""
import sys
from PIL import Image, ImageDraw
out, box, files = sys.argv[1], tuple(int(v) for v in sys.argv[2].split(",")), sys.argv[3:]
scale = 0.5 if box[2] - box[0] > 700 else 1.0
tiles = []
for f in ["ref/reference.png"] + files:
    im = Image.open(f).convert("RGB").crop(box)
    im = im.resize((int(im.width * scale), int(im.height * scale)), Image.LANCZOS)
    ImageDraw.Draw(im).text((6, 4), f.split("/")[-1], fill=(0, 0, 0)); tiles.append(im)
cols = 2 if len(tiles) > 2 else len(tiles)
rows = (len(tiles) + cols - 1) // cols
W, H = tiles[0].size
sheet = Image.new("RGB", (W * cols, H * rows), "white")
for i, t in enumerate(tiles): sheet.paste(t, ((i % cols) * W, (i // cols) * H))
sheet.save(out)
