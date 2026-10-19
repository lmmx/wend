"""DETECT: rank every registry lobe of a real render by how far it is from the reference, from
the evaluate.py match plus the signed contour error along the reference outline and, from round
12, along the candidate's own outline (lobekit.arcs2), which finds a displaced stretch of edge or a
tip that pokes out past the reference, both of which the IoU averages away. Each row says, in words
generated from the numbers, where the worst stretch is and which way it is wrong.
  score = 10 (1 - IoU) + p95 / 8 + |worst arc| / 4 + VSEV x visual severity (VSEV 3; 1.5 before round 10)
  (px; arc = 40 px of outline; visual severity 0-5: the blind judges' latest severity for the
  incumbent's feature, auto/sev.json, which catches what the masks do not: a lobe that is thin,
  rope-like or creased in the right place). From round 12 the visual severity is the larger of
  the judges' and the owner's (auto/owner.json: {fid: {sev, said, date}}, what the owner said about
  a feature of the incumbent), until an accepted round corrects that feature (`addressed`).
The heads (H1, H2) are listed but not ranked (their geometry is fixed in this loop).
Usage (from the logo root): discrepancy.py colour.png OUT.json [--tried state.json] [--sev sev.json] [--owner owner.json]
  --tried: features with rejected attempts are ranked x TRIED per attempt (0.8; 0.5 to round 20)"""
import json, os, sys
import numpy as np
from PIL import Image
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from lobekit import LAB, FEATS, FIDS, lobes, match, arcs2

# the weight of the blind judges' visual severity: 1.5 for rounds 1-9; 3 from round 10, once the
# mask errors had converged (most lobe IoUs 0.85-0.92) and the judges' remaining faults (a dimple,
# a band where a bulb should be, angular shoulders) were what separated the lobes
VSEV = 3.0
# each rejected attempt scales a feature's score by TRIED: 0.5 until round 20, which after two
# rejections sank the worst lobes (L05 IoU 0.71, L13 0.74, L14 0.82) below near-converged ones,
# so the loop kept polishing L01 and L16; 0.8 from round 21, so the worst unresolved errors lead
TRIED = 0.8
NAMES = {"N": "top", "S": "bottom", "E": "right", "W": "left", "NE": "upper right", "NW": "upper left", "SE": "lower right", "SW": "lower left"}


def owner_sev(owner):
    """the owner's severities that no accepted round has addressed yet"""
    return {k: v["sev"] for k, v in (owner or {}).items() if not v.get("addressed")}


def rank(png, tried=None, sev=None, owner=None):
    im = np.asarray(Image.open(png).convert("RGB"))
    L = lobes(im)
    rows = []
    for i, f in enumerate(FEATS):
        R = LAB == i + 1
        K = match(L[f["colour"]], R)
        A = arcs2(R, K)
        if K is None:
            rows.append(dict(id=f["id"], score=99.0, iou=0.0, what="missing")); continue
        iou = float((K & R).sum() / (K | R).sum())
        from evaluate import boundary
        from scipy import ndimage
        bR, bK = boundary(R), boundary(K)
        d = np.r_[ndimage.distance_transform_edt(~bK)[bR], ndimage.distance_transform_edt(~bR)[bK]]
        p95 = float(np.percentile(d, 95))
        ry, rx = np.nonzero(R); ky, kx = np.nonzero(K)
        js, os_ = (sev or {}).get(f["id"], 0), owner_sev(owner).get(f["id"], 0)
        vs = max(js, os_)
        sc = 10 * (1 - iou) + p95 / 8 + abs(A["worst"]) / 4 + VSEV * vs
        n = (tried or {}).get(f["id"], 0)
        word = "overshoots" if A["worst"] > 0 else "falls short"
        what = f"{NAMES[A['faces']]} edge {word} by {abs(A['worst']):.0f} px (40 px of outline at {A['at'][0]:.0f},{A['at'][1]:.0f}); centroid {kx.mean() - rx.mean():+.0f},{ky.mean() - ry.mean():+.0f} px"
        rows.append(dict(id=f["id"], colour=f["colour"], score=float(sc * TRIED ** n), raw=float(sc), attempts=n, iou=iou, p95=p95,
                         arc=A["worst"], arc_mean=A["mean_abs"], arc_at=A["at"], arc_faces=A["faces"],
                         dx=float(kx.mean() - rx.mean()), dy=float(ky.mean() - ry.mean()), what=what, vsev=vs, jsev=js, osev=os_))
    lobes_ = sorted([r for r in rows if r["id"].startswith("L")], key=lambda r: -r["score"])
    return lobes_ + [r for r in rows if not r["id"].startswith("L")]


def table(rows):
    out = ["| rank | ID | score | IoU | p95 | worst arc | visual sev | what |", "|---|---|---|---|---|---|---|---|"]
    for k, r in enumerate(rows):
        rk = str(k + 1) if r["id"].startswith("L") else "-"
        out.append(f"| {rk} | {r['id']} | {r['score']:.1f}{' (' + str(r['attempts']) + ' rejected)' if r.get('attempts') else ''} | {r['iou']:.2f} | {r.get('p95', 0):.0f} | {r.get('arc', 0):+.0f} | {r.get('vsev', '-')}{' (owner)' if r.get('osev', 0) > r.get('jsev', 0) else ''} | {r['what']} |")
    return "\n".join(out)


if __name__ == "__main__":
    argv = sys.argv[1:]
    tried = None
    if "--tried" in argv:
        i = argv.index("--tried"); tried = json.load(open(argv[i + 1])).get("tried", {}) if os.path.exists(argv[i + 1]) else {}; del argv[i:i + 2]
    sev = None
    if "--sev" in argv:
        i = argv.index("--sev"); sev = json.load(open(argv[i + 1])) if os.path.exists(argv[i + 1]) else None; del argv[i:i + 2]
    owner = None
    if "--owner" in argv:
        i = argv.index("--owner"); owner = json.load(open(argv[i + 1])) if os.path.exists(argv[i + 1]) else None; del argv[i:i + 2]
    rows = rank(argv[0], tried, sev, owner)
    json.dump(rows, open(argv[1], "w"), indent=1)
    md = table(rows)
    open(os.path.splitext(argv[1])[0] + ".md", "w").write(md + "\n")
    print(md)
