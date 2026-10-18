"""Build the model straight from the reading: spine polyline, theta anchored at each lobe."""
import json, sys
import numpy as np
sys.path.insert(0, __file__.rsplit("/", 1)[0])
import snakefit as sf

reading, out_dir = sys.argv[1:3]
flip_at = float(sys.argv[3]); sign = float(sys.argv[4]); tag = sys.argv[5]
over = json.loads(sys.argv[6]) if len(sys.argv) > 6 else {}
R = json.load(open(reading))
lobes = R["lobes"][1:-1]  # without the two heads
anchors, th = [], np.pi / 2 if lobes[0]["colour"] == "blue" else -np.pi / 2
for i, L in enumerate(lobes):
    if i: th += (sign if L["s"] <= flip_at else -sign) * np.pi
    anchors.append([L["cx"], L["cy"], th])
p = sf.initial()
p.update({"polyline": R["spine"], "anchor_xy": anchors, "a": 35.0, "R": 30.0,
          "helix": [lobes[0]["s"] / R["length"] - 0.03, lobes[-1]["s"] / R["length"] + 0.03],
          "head_len": [95.0, 95.0], "tail": [110.0, 110.0], "neck": 60.0, "head_r": 1.25})
p["cam"]["elev"] = 6.0
p.update(over)
small, full = sf.ref_labels(sys.argv[7] if len(sys.argv) > 7 else "ref/reference.png", sf.SCALE)
print(tag, "loss", round(sf.Loss(small, sf.SCALE)(p), 3))
json.dump(p, open(f"{out_dir}/{tag}.json", "w"), indent=1)
sf.overlay(p, full, f"{out_dir}/{tag}.png")
