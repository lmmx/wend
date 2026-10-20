"""The geometry diagnostic sheets (geo/measure.py's numbers, drawn). No geometry is changed.
Usage (from the workspace root): python geo/sheets.py
"""

import json
import sys

import matplotlib
import numpy as np
from PIL import Image
from scipy import ndimage


matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle


sys.path.insert(0, "geo")
sys.path.insert(0, "tools")
import measure as Mz
from evaluate import load_registry


D = json.load(open("geo/diag.json"))
A = np.load("geo/diag.npz", allow_pickle=True)
REG, LAB, _ = load_registry()
FEATS = [f["id"] for f in REG["features"]]
ref = np.asarray(Image.open(Mz.SRC["ref"]).convert("RGB"))
col = np.asarray(Image.open(Mz.SRC["cand"]).convert("RGB"))
clay = np.asarray(Image.open("auto/r28/renders/r28-hybR-clay-full.png").convert("RGB"))
zebra = np.asarray(
    Image.open("auto/r28/renders/r28-hybR-zebra-full.png").convert("RGB")
)
_, sil_r, lab_r = Mz.masks(Mz.SRC["ref"])
_, sil_c, lab_c = Mz.masks(Mz.SRC["cand"])
YC, BC = "#b8860b", "#0b2a8a"
# the three defects the owner named: box (x0, y0, x1, y1), label
ISSUES = {
    1: ((330, 300, 540, 560), "1  left head: blue scarf height/shape (L01)"),
    2: ((975, 270, 1175, 500), "2  right head: bumpy nape (H2 neck)"),
    3: ((895, 380, 1115, 740), "3  RHS tubes L14-L16: non-cylindrical, puffy"),
}
TP = D["turning"]
# the measured discrepancies drawn on sheet 1: (point, text position, text)
ANNOT = [
    (
        (462, 338),
        (90, 150),
        "1a  L01 top 17 px too high: the blue tail\n     climbs the neck (s 1394→1459: y 446→363)",
    ),
    (
        (380, 470),
        (60, 235),
        "1b  tail taper visible: r 40→26 inside the\n     visible run, plus a −0.16 ring pinch at s 1436",
    ),
    (
        (1003, 393),
        (600, 120),
        "2  L16 top edge on the nape: +10 / −6 / +7 px (hump-dip-hump)\n    vs the reference's smooth diagonal: the yellow tail\n    (s 1381–1420, r 31) turning behind the blue neck",
    ),
    (
        (1098, 466),
        (1150, 230),
        "2b  throat shows 7–9 px\n      lower (L16 right end thin)",
    ),
    (
        (975, 445),
        (1000, 820),
        "3a  L16 visible width +19% mid-lobe: r(s) bead 30→46\n      + ±90° handles +0.10/+0.15 at s 1347",
    ),
    (
        (1040, 560),
        (1000, 900),
        "3b  L15 width profile off 12% (r(s) bead 38→50, skewed;\n      no handles). Strands interpenetrate 24–28% of r\n      on L14/L15 → the press flattens the sections",
    ),
]


def faded(im, k=0.35):
    g = im.mean(2, keepdims=True)
    return (255 - (255 - g) * k).repeat(3, 2).astype(np.uint8)


def boxes(ax, which=(1, 2, 3), lw=2.0, fs=9):
    for i in which:
        (x0, y0, x1, y1), t = ISSUES[i]
        ax.add_patch(
            Rectangle(
                (x0, y0), x1 - x0, y1 - y0, fill=False, ec="#d62728", lw=lw, ls="--"
            )
        )
        ax.text(
            x0 + 4, y0 - 6, t, color="#d62728", fontsize=fs, weight="bold", va="bottom"
        )


def outline(ax, m, c, lw=0.8, ls="-"):
    ax.contour(m.astype(float), [0.5], colors=[c], linewidths=lw, linestyles=ls)


def turning(ax, which="both", fs=7):
    for k, v in TP.items():
        r, c, d = np.array(v["ref"]), np.array(v["cand"]), np.array(v["d"])
        ax.plot(*r, "o", ms=6, mfc="none", mec="k", mew=1.2)
        if which == "both":
            ax.plot(*c, "x", ms=6, color="#ff7f0e", mew=1.5)
        ax.annotate(
            f"{k}\nΔ=({d[0]:+.0f},{d[1]:+.0f})px",
            r,
            xytext=(8, -18 if "valley" in k else 10),
            textcoords="offset points",
            fontsize=fs,
        )


def sheet1():
    """full-frame silhouette overlay"""
    fig, ax = plt.subplots(figsize=(14.48, 10.86), dpi=100)
    ax.set_position([0, 0, 1, 1])
    base = faded(ref, 0.30).copy()
    ro, co = sil_r & ~sil_c, sil_c & ~sil_r
    both = sil_r & sil_c
    wrong = both & (lab_r != lab_c) & np.isin(lab_r, [1, 2]) & np.isin(lab_c, [1, 2])
    base[ro] = (base[ro] * 0.3 + np.array([230, 40, 160]) * 0.7).astype(np.uint8)
    base[co] = (base[co] * 0.3 + np.array([0, 190, 220]) * 0.7).astype(np.uint8)
    base[wrong] = (base[wrong] * 0.35 + np.array([255, 140, 0]) * 0.65).astype(np.uint8)
    ax.imshow(base)
    ax.axis("off")
    # the candidate's colour boundaries, thin
    for c, k in ((YC, 2), (BC, 1)):
        outline(ax, lab_c == k, c, 0.6)
    ax.plot(*A["Sr"].T, "-", color="k", lw=1.6, label="reference W-spine (medial path)")
    ax.plot(*A["Sc"].T, "--", color="#ff7f0e", lw=1.4, label="render W-spine")
    turning(ax)
    boxes(ax, fs=11)
    for (x, y), (tx, ty), s in ANNOT:
        ax.annotate(
            s,
            (x, y),
            xytext=(tx, ty),
            fontsize=9.5,
            color="#7a0000",
            weight="bold",
            arrowprops=dict(arrowstyle="->", color="#7a0000", lw=1.2),
            bbox=dict(fc="w", ec="#7a0000", lw=0.6, alpha=0.9),
        )
    # largest other discrepancy blobs
    from skimage import measure

    lb = measure.label(ndimage.binary_opening(ro | co | wrong, iterations=1))
    props = sorted(measure.regionprops(lb), key=lambda p: -p.area)[:10]
    for p in props:
        y, x = p.centroid
        if any(
            ISSUES[i][0][0] <= x <= ISSUES[i][0][2]
            and ISSUES[i][0][1] <= y <= ISSUES[i][0][3]
            for i in ISSUES
        ):
            continue
        ax.annotate(
            f"{p.area}px²",
            (x, y),
            xytext=(0, 26),
            textcoords="offset points",
            fontsize=8,
            ha="center",
            arrowprops=dict(arrowstyle="-", lw=0.6),
        )
    from matplotlib.patches import Patch

    ax.legend(
        handles=[
            Patch(
                color=(230 / 255, 40 / 255, 160 / 255),
                label="reference only (render missing)",
            ),
            Patch(color=(0, 0.75, 0.86), label="render only (render excess)"),
            Patch(
                color=(1, 0.55, 0),
                label="both, but the other strand in front (phase/occlusion)",
            ),
            plt.Line2D([], [], color="k", lw=1.6, label="reference W-spine"),
            plt.Line2D(
                [], [], color="#ff7f0e", ls="--", lw=1.4, label="render W-spine"
            ),
            plt.Line2D([], [], color=YC, lw=1, label="render colour edges"),
        ],
        loc="lower left",
        fontsize=10,
        framealpha=0.9,
    )
    sh = D["phase"]
    txt = (
        f"silhouette IoU {D['silhouette_iou']:.3f}   spine length {D['spine_len']['ref']:.0f} vs {D['spine_len']['cand']:.0f} px   "
        f"turning points within {max(np.hypot(*v['d']) for v in TP.values()):.1f} px   colour-switch shifts {min(s['shift_px'] for s in sh if s['shift_px'] is not None):+.0f}..{max(s['shift_px'] for s in sh if s['shift_px'] is not None):+.0f} px"
    )
    ax.text(
        12,
        22,
        "Sheet 1 — silhouette overlay: frozen final geometry (r28-hybR, look6 render) over the reference",
        fontsize=14,
        weight="bold",
    )
    ax.text(12, 46, txt, fontsize=11)
    fig.savefig("geo/sheet1-silhouette.png")
    plt.close(fig)


def vis_split(C, lobe_runs, s):
    """per-station visible flag from the lobe runs"""
    v = np.zeros(len(s), bool)
    for _, a, b in lobe_runs:
        v |= (s >= a) & (s <= b)
    return v


def sheet2():
    """projected centrelines and spines"""
    fig, axs = plt.subplots(1, 2, figsize=(22, 9.2), dpi=100)
    for ax, im, t in (
        (axs[0], ref, "over the reference"),
        (axs[1], col, "over the render (look6)"),
    ):
        ax.imshow(faded(im, 0.38))
        ax.set_xlim(280, 1190)
        ax.set_ylim(800, 250)
        ax.axis("off")
        ax.set_title(
            f"Projected strand centrelines, W-spines and turning points — {t}",
            fontsize=12,
        )
        ax.plot(
            *A["model_spine"].T,
            "-",
            color="#555",
            lw=1.0,
            label="model spine (parametric)",
        )
        for name, c in (("yellow", YC), ("blue", BC)):
            C = A[f"{name}_C"]
            s = A[f"{name}_s"]
            st = D["strands"][name]
            v = vis_split(C, st["lobe_runs"], s)
            Cm = np.where(v[:, None], C, np.nan)
            Ch = np.where(~v[:, None], C, np.nan)
            ax.plot(*Ch.T, ":", color=c, lw=1.2)
            ax.plot(
                *Cm.T,
                "-",
                color=c,
                lw=2.2,
                label=f"{name} centreline (solid: visible lobe; dotted: hidden)",
            )
            for i in range(len(s)):
                if i % 60 == 0:
                    ax.text(*C[i], f"{s[i]:.0f}", fontsize=6.5, color=c)
            for k in range(st["n_ov"]):
                O = A[f"{name}_ov{k}_C"]
                ax.plot(
                    *O.T,
                    "-",
                    color="#d62728" if name == "yellow" else "#9467bd",
                    lw=1.0,
                    alpha=0.9,
                )
            for fid, a, b in st["lobe_runs"]:
                i = np.argmin(np.abs(s - (a + b) / 2))
                ax.text(
                    *C[i],
                    fid,
                    fontsize=8,
                    weight="bold",
                    color="w",
                    ha="center",
                    va="center",
                    bbox=dict(boxstyle="round,pad=0.15", fc=c, ec="none", alpha=0.85),
                )
        eff = (A["yellow_eff"], A["blue_eff"])
        ax.plot(
            *A["Sr"].T,
            "-",
            color="#2ca02c",
            lw=1.4,
            label="reference W-spine (silhouette medial path)",
        )
        ax.plot(*A["Sc"].T, "--", color="#ff7f0e", lw=1.2, label="render W-spine")
        turning(ax)
        boxes(ax)
    axs[0].plot(
        [],
        [],
        "-",
        color="#d62728",
        lw=1,
        label="hybrid overlay ring centres (yellow / purple: blue)",
    )
    axs[0].legend(loc="lower left", fontsize=8.5, framealpha=0.9)
    fig.tight_layout()
    fig.savefig("geo/sheet2-centrelines.png")
    plt.close(fig)


def sheet3():
    """neutral clay comparison: full frame and the three issue crops"""
    fig = plt.figure(figsize=(22, 21), dpi=90)
    gs = fig.add_gridspec(4, 10, height_ratios=[1.25, 1, 1, 1.15])
    for j, (im, t) in enumerate(
        ((ref, "reference"), (clay, "render, neutral clay (zebra in the crops below)"))
    ):
        ax = fig.add_subplot(gs[0, 5 * j : 5 * j + 5])
        ax.imshow(im)
        ax.set_xlim(280, 1190)
        ax.set_ylim(800, 250)
        ax.axis("off")
        ax.set_title(t, fontsize=12)
        boxes(ax, lw=1.5, fs=8)
    for r, i in enumerate((1, 2, 3)):
        (x0, y0, x1, y1), t = ISSUES[i]
        for j, (im, tt) in enumerate(
            (
                (ref, "reference"),
                (col, "render (look6)"),
                (clay, "clay"),
                (zebra, "zebra"),
                (None, "outlines: ref solid, render dashed"),
            )
        ):
            ax = fig.add_subplot(gs[r + 1, 2 * j : 2 * j + 2])
            if im is None:
                ax.imshow(faded(ref, 0.25))
                for c, k in (("#c99a00", 2), (BC, 1)):
                    outline(ax, lab_r == k, c, 1.4)
                    outline(ax, lab_c == k, c, 1.2, "--")
                outline(ax, sil_r, "k", 1.2)
                outline(ax, sil_c, "#ff7f0e", 1.2, "--")
                if i in (1, 3):
                    for name, c in (("yellow", YC), ("blue", BC)):
                        C = A[f"{name}_C"]
                        ax.plot(*C.T, "-", color=c, lw=0.9, alpha=0.8)
            else:
                ax.imshow(im)
            ax.set_xlim(x0, x1)
            ax.set_ylim(y1, y0)
            ax.set_xticks([])
            ax.set_yticks([])
            ax.set_title(tt if r == 0 else "", fontsize=11)
            if j == 0:
                ax.set_ylabel(t, fontsize=11, color="#d62728", weight="bold")
    fig.suptitle(
        "Sheet 3 — neutral clay comparison (geometry only; look frozen at look6)",
        fontsize=15,
        weight="bold",
        y=0.995,
    )
    fig.tight_layout()
    fig.savefig("geo/sheet3-clay.png")
    plt.close(fig)


def regions(ax):
    arc = lambda k: {"head_L": 0, "valley_L": None}.get(k)
    Sr = A["Sr"]
    idx = {}
    for k, v in TP.items():
        idx[k] = int(np.argmin(np.linalg.norm(Sr - np.array(v["ref"]), axis=1))) * 2.0
    for k, x in idx.items():
        ax.axvline(x, color="#777", lw=0.7, ls=":")
    return idx


def sheet4():
    """along the W-spine: offsets, band width, colour phase"""
    arc = np.arange(len(A["Sr"])) * 2.0
    fig, axs = plt.subplots(
        4,
        1,
        figsize=(16, 13),
        dpi=100,
        sharex=True,
        gridspec_kw=dict(height_ratios=[1, 1, 1, 0.55]),
    )
    ax = axs[0]
    ax.plot(
        arc,
        A["sp_off"],
        color="#ff7f0e",
        lw=1.2,
        label="render spine offset along the reference normal",
    )
    ax.plot(
        arc,
        A["mid_c"] - A["mid_r"],
        color="#1f77b4",
        lw=1.0,
        label="band (chord) centre offset, render − reference",
    )
    ax.axhline(0, color="k", lw=0.6)
    ax.set_ylim(-20, 20)
    ax.set_ylabel("px (+ = towards +N)")
    ax.legend(fontsize=9, loc="upper right")
    ax.set_title(
        "Macro path: the render's W-spine and band centre against the reference's",
        fontsize=11,
    )
    ax = axs[1]
    ax.plot(
        arc,
        A["width_r"],
        "k",
        lw=1.2,
        label="reference band width (silhouette chord on the spine normal)",
    )
    ax.plot(arc, A["width_c"], color="#ff7f0e", lw=1.2, label="render band width")
    ax2 = ax.twinx()
    ax2.plot(
        arc, 100 * (A["width_c"] / A["width_r"] - 1), color="#d62728", lw=0.8, alpha=0.7
    )
    ax2.set_ylim(-25, 25)
    ax2.set_ylabel("render/ref − 1 (%)", color="#d62728")
    ax2.axhline(0, color="#d62728", lw=0.4, ls=":")
    ax.set_ylabel("px")
    ax.legend(fontsize=9, loc="lower left")
    ax.set_title(
        "Helix envelope: band width (≈ 2 × (helix radius + tube radius) where the band is face-on)",
        fontsize=11,
    )
    ax = axs[2]
    cr, cc = A["cr"], A["cc"]
    ax.plot(arc, cr[:, 0], "k", lw=1.0, label="reference: +N side extent")
    ax.plot(arc, cc[:, 0], color="#ff7f0e", lw=1.0, label="render: +N side")
    ax.plot(arc, -cr[:, 1], "k", lw=1.0, ls="--", label="reference: −N side")
    ax.plot(arc, -cc[:, 1], color="#ff7f0e", lw=1.0, ls="--", label="render: −N side")
    ax.axhline(0, color="k", lw=0.5)
    ax.set_ylabel("px from spine")
    ax.legend(fontsize=8, ncol=4, loc="lower right")
    ax.set_title(
        "The two silhouette edges about the reference spine (the nape and the RHS shoulders show here)",
        fontsize=11,
    )
    ax = axs[3]
    cmap = np.array(
        [[255, 255, 255], [20, 70, 200], [240, 190, 20], [200, 200, 200]], np.uint8
    )
    strip = np.stack(
        [cmap[A["ph_r"].astype(int)]] * 12
        + [np.full((len(arc), 3), 255, np.uint8)] * 3
        + [cmap[A["ph_c"].astype(int)]] * 12
    )
    ax.imshow(strip, aspect="auto", extent=[0, arc[-1], 2, 0])
    ax.set_yticks([0.45, 1.55])
    ax.set_yticklabels(["reference", "render"])
    for s in D["phase"]:
        if s["shift_px"] is None:
            continue
        ax.text(
            s["arc"],
            -0.08,
            f"{s['shift_px']:+.0f}",
            fontsize=7.5,
            ha="center",
            va="bottom",
            color="#d62728" if abs(s["shift_px"]) >= 6 else "k",
        )
    ax.set_title(
        "Twist phase: which strand is in front on the spine (numbers: render switch − reference switch, px of arc)",
        fontsize=11,
        pad=14,
    )
    ax.set_xlabel("arc length along the reference W-spine, px (left head → right head)")
    for a in axs:
        idx = regions(a)
    for k, x in idx.items():
        axs[0].text(x, 21, k, fontsize=8, ha="center", va="bottom")
    fig.suptitle(
        "Sheet 4 — spine, helix envelope and twist phase along the W",
        fontsize=14,
        weight="bold",
    )
    fig.tight_layout()
    fig.savefig("geo/sheet4-spine.png")
    plt.close(fig)


def sheet5():
    """3D sections along each strand"""
    fig, axs = plt.subplots(4, 1, figsize=(17, 15), dpi=100)
    for r, name in enumerate(("yellow", "blue")):
        st = D["strands"][name]
        s = A[f"{name}_s"]
        c = YC if name == "yellow" else BC
        ax = axs[2 * r]
        ax.plot(s, A[f"{name}_r"], color="#777", lw=1.0, label="nominal radius r(s)")
        ax.plot(
            s,
            A[f"{name}_rho"],
            color=c,
            lw=1.4,
            label="tube ring mean radius (disp handles, press, sections)",
        )
        ax.plot(
            s,
            A[f"{name}_pw"] / 2,
            color=c,
            lw=0.9,
            ls="--",
            label="projected half-width (what the camera sees)",
        )
        for k in range(st["n_ov"]):
            ax.plot(
                A[f"{name}_ov{k}_s"],
                A[f"{name}_ov{k}_rho"],
                color="#d62728",
                lw=1.3,
                label="hybrid overlay ring mean radius" if k == 0 else None,
            )
            ax.plot(
                A[f"{name}_ov{k}_s"],
                A[f"{name}_ov{k}_pw"] / 2,
                color="#d62728",
                lw=0.8,
                ls="--",
            )
        lo, hi = 25, 50
        ax.set_ylim(lo, hi)
        for h in st["disp"]:
            mk = {0.0: "o", 90.0: "^", -90.0: "v"}[h["psi"]]
            y = lo + 2 + 4 * h["a"] / 0.16 + 4
            ax.plot([h["s"], h["s"]], [lo + 6, y], color="#9467bd", lw=1.0)
            ax.plot(h["s"], y, mk, color="#9467bd", ms=5)
        ax.axhline(lo + 6, color="#9467bd", lw=0.5)
        ax.text(
            st["s0"],
            lo + 0.5,
            "disp handles (stem ∝ a; o ring, ▲ +90°, ▼ −90°)",
            fontsize=8,
            color="#9467bd",
        )
        ax.set_ylabel("px (world)")
        ax.set_title(f"{name}: radius along s", fontsize=11)
        ax = axs[2 * r + 1]
        ax.plot(
            s,
            100 * A[f"{name}_ell"],
            color=c,
            lw=1.2,
            label="ellipticity (max−min)/mean, %",
        )
        ax.plot(
            s,
            100 * A[f"{name}_a2"],
            color=c,
            lw=0.9,
            ls="--",
            label="oval harmonic a2, %",
        )
        ax.plot(
            s, 100 * A[f"{name}_a3"], color="k", lw=0.9, label="lump harmonics a3–a8, %"
        )
        rr = A[f"{name}_rho"]
        tr = ndimage.gaussian_filter1d(rr, 25)
        ax.plot(
            s,
            100 * (rr - tr) / tr,
            color="#2ca02c",
            lw=1.0,
            label="radius ripple along s (vs 25-station mean), %",
        )
        for k in range(st["n_ov"]):
            ax.plot(
                A[f"{name}_ov{k}_s"],
                100 * A[f"{name}_ov{k}_ell"],
                color="#d62728",
                lw=1.2,
                label="overlay ellipticity" if k == 0 else None,
            )
            ax.plot(
                A[f"{name}_ov{k}_s"],
                100 * A[f"{name}_ov{k}_a3"],
                color="#d62728",
                lw=0.8,
                ls=":",
                label="overlay lumps" if k == 0 else None,
            )
            ov = A[f"{name}_ov{k}_rho"]
            tv = ndimage.gaussian_filter1d(ov, 25)
        sec = st["sec"]
        ss = np.linspace(st["s0"], st["s1"], len(sec["ql"]))
        ax2 = ax.twinx()
        ax2.plot(ss, sec["ql"], color="#8c564b", lw=0.9, ls="-", drawstyle="steps-mid")
        ax2.plot(ss, sec["qd"], color="#8c564b", lw=0.9, ls="--", drawstyle="steps-mid")
        ax2.set_ylim(0.4, 1.3)
        ax2.set_ylabel("sec ql (solid) / qd (dashed)", color="#8c564b")
        ax.set_ylim(-15, 60)
        ax.axhline(0, color="k", lw=0.4)
        ax.set_ylabel("%")
        ax.set_title(f"{name}: section shape along s", fontsize=11)
        for a in (axs[2 * r], axs[2 * r + 1]):
            a.set_xlim(st["s0"], st["s1"])
            for fid, x0, x1 in st["lobe_runs"]:
                a.axvspan(x0, x1, color=c, alpha=0.08)
                a.text(
                    (x0 + x1) / 2,
                    a.get_ylim()[1],
                    fid,
                    ha="center",
                    va="bottom",
                    fontsize=8,
                    color=c,
                    weight="bold",
                )
            for x0, x1 in st["cut"]:
                a.axvspan(
                    x0, x1, color="#d62728", alpha=0.06, hatch="//", ec="#d62728", lw=0
                )
            a.legend(fontsize=7.5, loc="upper left", ncol=3)
    axs[-1].set_xlabel(
        "station s along the strand (yellow: left head → right; blue: right head → left)"
    )
    fig.suptitle(
        "Sheet 5 — 3D sections: shaded = visible lobe run; red hatch = hybrid overlay replaces the tube",
        fontsize=14,
        weight="bold",
    )
    fig.tight_layout()
    fig.savefig("geo/sheet5-sections.png")
    plt.close(fig)


def longest_path(m):
    """the longest geodesic path of a mask's skeleton (double sweep), as (n, 2) x, y"""
    from scipy import sparse
    from scipy.sparse import csgraph
    from skimage import filters, morphology

    sk = morphology.skeletonize(filters.gaussian(m.astype(float), 2) > 0.5)
    ys, xs = np.nonzero(sk)
    idx = -np.ones(sk.shape, int)
    idx[ys, xs] = np.arange(len(xs))
    rows, cols, w = [], [], []
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dx == dy == 0:
                continue
            y2, x2 = ys + dy, xs + dx
            ok = (y2 >= 0) & (y2 < sk.shape[0]) & (x2 >= 0) & (x2 < sk.shape[1])
            j = np.full(len(xs), -1)
            j[ok] = idx[y2[ok], x2[ok]]
            ok = j >= 0
            rows += list(np.nonzero(ok)[0])
            cols += list(j[ok])
            w += [np.hypot(dx, dy)] * ok.sum()
    G = sparse.csr_matrix((w, (rows, cols)), shape=(len(xs), len(xs)))
    d0 = csgraph.dijkstra(G, indices=0)
    d0[~np.isfinite(d0)] = -1
    a = int(np.argmax(d0))
    d1, pred = csgraph.dijkstra(G, indices=a, return_predecessors=True)
    d1[~np.isfinite(d1)] = -1
    b = int(np.argmax(d1))
    path = [b]
    while path[-1] != a:
        path.append(pred[path[-1]])
    P = np.c_[xs[path], ys[path]].astype(float)
    return P if P[0, 0] <= P[-1, 0] else P[::-1]


def lobe_frame(m):
    yy, xx = np.nonzero(m)
    c = np.array([xx.mean(), yy.mean()])
    w, v = np.linalg.eigh(np.cov(np.c_[xx, yy].T))
    a = v[:, 1] if v[0, 1] >= 0 else -v[:, 1]  # major axis, pointing right
    return c, a, np.array([-a[1], a[0]])


def lobe_profile(m, frame, n=40):
    """visible width of a lobe across its major axis, in n strips along it; frame = the reference
    lobe's (centre, major, minor) so the reference and the render are cut identically"""
    c, a, b = frame
    yy, xx = np.nonzero(m)
    P = np.c_[xx, yy] - c
    u, v = P @ a, P @ b
    ur = np.percentile(u, [1, 99])
    edges = np.linspace(ur[0], ur[1], n + 1)
    k = np.clip(np.digitize(u, edges) - 1, 0, n - 1)
    wd = np.array(
        [np.ptp(v[k == i]) + 1 if (k == i).sum() > 3 else np.nan for i in range(n)]
    )
    return (edges[:-1] + edges[1:]) / 2, wd, ur[1] - ur[0]


def lobe_masks():
    LC = np.load("geo/lobes_cand.npy")
    return {f: (LAB == i + 1, LC[i]) for i, f in enumerate(FEATS)}


def edges(sil, y0, y1, xr):
    """left and right silhouette edge x(y) inside the column window xr, rows y0..y1"""
    ys = np.arange(y0, y1)
    L, R = [], []
    for y in ys:
        row = np.nonzero(sil[y, xr[0] : xr[1]])[0]
        L.append(xr[0] + row[0] if len(row) else np.nan)
        R.append(xr[0] + row[-1] if len(row) else np.nan)
    return ys, np.array(L, float), np.array(R, float)


def curvature(x, y, sig=3):
    x = ndimage.gaussian_filter1d(x, sig)
    y = ndimage.gaussian_filter1d(y.astype(float), sig)
    dx, dy = np.gradient(x), np.gradient(y)
    ddx, ddy = np.gradient(dx), np.gradient(dy)
    return (dx * ddy - dy * ddx) / np.maximum((dx * dx + dy * dy) ** 1.5, 1e-9)


def zoom(ax, im, box, title=""):
    x0, y0, x1, y1 = box
    ax.imshow(im)
    ax.set_xlim(x0, x1)
    ax.set_ylim(y1, y0)
    ax.set_xticks([])
    ax.set_yticks([])
    ax.set_title(title, fontsize=10)


def stations(ax, name, box, every=10, label=True, handles=True):
    c = YC if name == "yellow" else BC
    C = A[f"{name}_C"]
    s = A[f"{name}_s"]
    r = A[f"{name}_r"]
    ax.plot(*C.T, "-", color=c, lw=1.4)
    x0, y0, x1, y1 = box
    inb = lambda p: x0 < p[0] < x1 and y0 < p[1] < y1
    for i in range(0, len(s), every):
        if inb(C[i]) and label:
            ax.text(
                *C[i],
                f"{s[i]:.0f}·r{r[i]:.0f}",
                fontsize=6.5,
                color=c,
                bbox=dict(fc="w", ec="none", alpha=0.6, pad=0.3),
            )
    if inb(C[-1]):
        ax.plot(*C[-1], "*", ms=12, color="#d62728")
        ax.annotate(
            "tail tip",
            C[-1],
            xytext=(6, -10),
            textcoords="offset points",
            fontsize=8,
            color="#d62728",
        )
    if handles:
        for h in D["strands"][name]["disp"]:
            i = int(np.argmin(np.abs(s - h["s"])))
            if inb(C[i]):
                ax.plot(
                    *C[i],
                    "o",
                    ms=4 + 40 * abs(h["a"]),
                    mfc="none",
                    mec="#2ca02c" if h["a"] > 0 else "#d62728",
                    mew=1.5,
                )


def sheet6():
    LM = lobe_masks()
    fig = plt.figure(figsize=(24, 19), dpi=90)
    gs = fig.add_gridspec(3, 5, width_ratios=[1, 1, 1, 1.25, 1.25])
    issue_lobes = {1: ["L01", "L02", "L03"], 3: ["L14", "L15", "L16"]}
    prof = {}
    for f in FEATS:
        R, C = LM[f]
        if R.sum() and C.sum():
            fr = lobe_frame(R)
            ur, tr, lr = lobe_profile(R, fr)
            tc = lobe_profile(C, fr)[1]
            lc = lobe_profile(C, lobe_frame(C))[2]
            ur = uc = (ur - ur[0]) / (ur[-1] - ur[0])
            core = slice(6, 34)
            prof[f] = dict(
                ur=ur,
                tr=tr,
                uc=uc,
                tc=tc,
                lr=lr,
                lc=lc,
                var_r=np.nanmax(tr[core]) / np.nanmin(tr[core]),
                var_c=np.nanmax(tc[core]) / np.nanmin(tc[core]),
                rough_r=float(np.nanstd(np.diff(tr[core], 2))),
                rough_c=float(np.nanstd(np.diff(tc[core], 2))),
                dev=float(np.nanmean(np.abs(tc[core] - tr[core]) / tr[core])),
                bulge=float(np.nanmax((tc[core] - tr[core]) / tr[core])),
            )
    json.dump(
        {
            f: {k: float(v) for k, v in p.items() if np.isscalar(v)}
            for f, p in prof.items()
        },
        open("geo/lobe_profiles.json", "w"),
        indent=1,
    )
    for r, i in enumerate((1, 2, 3)):
        box, t = ISSUES[i]
        ax = fig.add_subplot(gs[r, 0])
        zoom(ax, ref, box, "reference")
        ax.set_ylabel(t, fontsize=12, color="#d62728", weight="bold")
        ax.yaxis.set_visible(True)
        ax.set_yticks([])
        ax = fig.add_subplot(gs[r, 1])
        zoom(ax, col, box, "render (look6)")
        ax = fig.add_subplot(gs[r, 2])
        zoom(ax, clay, box, "clay + outlines (ref solid, render dashed) + centrelines")
        outline(ax, sil_r, "k", 1.2)
        outline(ax, sil_c, "#ff7f0e", 1.2, "--")
        for k in (1, 2):
            outline(ax, lab_r == k, "#1f3fbf" if k == 1 else "#c99a00", 1.0)
        if i in (1, 3):
            for name in ("yellow", "blue"):
                stations(ax, name, box, every=12)
        else:
            for name in ("yellow", "blue"):
                stations(ax, name, box, every=12, handles=False)
        if i in issue_lobes:
            ax = fig.add_subplot(gs[r, 3])
            for f, c in zip(issue_lobes[i], ("#1f77b4", "#ff7f0e", "#2ca02c")):
                p = prof[f]
                ax.plot(
                    p["ur"],
                    p["tr"],
                    "-",
                    color=c,
                    lw=1.6,
                    label=f"{f} reference (max/min {p['var_r']:.2f})",
                )
                ax.plot(
                    p["uc"],
                    p["tc"],
                    "--",
                    color=c,
                    lw=1.6,
                    label=f"{f} render (max/min {p['var_c']:.2f})",
                )
            ax.axvspan(0, 0.15, color="#eee")
            ax.axvspan(0.85, 1, color="#eee")
            ax.set_xlabel("along the reference lobe major axis (left end → right end)")
            ax.set_ylabel("visible width, px")
            ax.legend(fontsize=8.5)
            ax.set_title(
                "Visible lobe width across its axis (same cuts for ref and render; central 70% unshaded)",
                fontsize=10,
            )
            ax = fig.add_subplot(gs[r, 4])
            name = "blue" if i == 1 else None
            for f, c in zip(issue_lobes[i], ("#1f77b4", "#ff7f0e", "#2ca02c")):
                nm = REG["features"][FEATS.index(f)]["colour"]
                st = D["strands"][nm]
                run = [x for x in st["lobe_runs"] if x[0] == f]
                if not run:
                    continue
                _, a, b = run[0]
                s = A[f"{nm}_s"]
                m = (s >= a - 30) & (s <= b + 30)
                u = (s[m] - a) / (b - a)
                ax.plot(
                    u,
                    A[f"{nm}_r"][m],
                    "-",
                    color=c,
                    lw=1.6,
                    label=f"{f} nominal r(s) ({nm} s {a:.0f}–{b:.0f})",
                )
                ax.plot(
                    u,
                    A[f"{nm}_pw"][m] / 2,
                    ":",
                    color=c,
                    lw=1.4,
                    label=f"{f} projected half-width",
                )
                for h in st["disp"]:
                    if a - 30 <= h["s"] <= b + 30:
                        ax.plot(
                            (h["s"] - a) / (b - a),
                            27 + 30 * h["a"],
                            "o" if h["psi"] == 0 else ("^" if h["psi"] > 0 else "v"),
                            color=c,
                            ms=6,
                        )
                for k in range(st["n_ov"]):
                    so = A[f"{nm}_ov{k}_s"]
                    mo = (so >= a - 30) & (so <= b + 30)
                    if mo.any():
                        ax.plot(
                            (so[mo] - a) / (b - a),
                            A[f"{nm}_ov{k}_pw"][mo] / 2,
                            "-",
                            color="#d62728",
                            lw=1.0,
                            label=f"{f} overlay projected half-width",
                        )
            ax.axhline(27, color="#999", lw=0.5)
            ax.text(
                -0.18,
                27.3,
                "disp handle a (×30) about this line",
                fontsize=7.5,
                color="#666",
            )
            ax.axvspan(-0.25, 0, color="#eee")
            ax.axvspan(1, 1.25, color="#eee")
            ax.set_xlim(-0.25, 1.25)
            ax.set_xlabel("station s, normalised to the visible run (grey: hidden)")
            ax.set_ylabel("world px")
            ax.legend(fontsize=7.5, ncol=1)
            ax.set_title(
                "3D tube: radius along the strand through each lobe, with its disp handles",
                fontsize=10,
            )
        else:
            # the nape: both neck edges, x(y), and their curvature
            ax = fig.add_subplot(gs[r, 3])
            ax2 = fig.add_subplot(gs[r, 4])
            for sil, c, ls, nm in (
                (sil_r, "k", "-", "reference"),
                (sil_c, "#ff7f0e", "--", "render"),
            ):
                ys, L, _ = edges(sil, 340, 470, (960, 1060))
                ys2, _, R = edges(sil, 395, 475, (1050, 1125))
                ax.plot(
                    L,
                    ys,
                    ls,
                    color=c,
                    lw=1.6,
                    label=f"{nm}: back of the neck (left edge)",
                )
                ax.plot(R, ys2, ls, color=c, lw=1.0, label=f"{nm}: throat (right edge)")
                kL = curvature(L, ys)
                kR = curvature(R, ys2)
                ax2.plot(
                    ys,
                    1000 * kL,
                    ls,
                    color=c,
                    lw=1.5,
                    label=f"{nm}: back edge, inflections {int((np.diff(np.sign(kL[5:-5])) != 0).sum())}",
                )
                ax2.plot(
                    ys2,
                    1000 * kR,
                    ls,
                    color=c,
                    lw=0.9,
                    alpha=0.7,
                    label=f"{nm}: throat, inflections {int((np.diff(np.sign(kR[5:-5])) != 0).sum())}",
                )
            ax.invert_yaxis()
            ax.set_xlabel("image x")
            ax.set_ylabel("image y")
            ax.legend(fontsize=8)
            ax.set_aspect("equal")
            ax.set_title("Neck edges x(y): back (nape) and throat", fontsize=10)
            ax2.axhline(0, color="k", lw=0.5)
            ax2.set_xlabel("image y (head ↑ … ↓ body)")
            ax2.set_ylabel("edge curvature ×1000 (1/px)")
            ax2.legend(fontsize=8)
            ax2.set_title(
                "Edge curvature: a smooth neck has one sign change; each extra pair is a bump",
                fontsize=10,
            )
    fig.suptitle(
        "Sheet 6 — the three named defects, measured",
        fontsize=15,
        weight="bold",
        y=0.997,
    )
    fig.tight_layout()
    fig.savefig("geo/sheet6-issues.png")
    plt.close(fig)
    for f, p in prof.items():
        print(
            f,
            "width max/min ref %.2f render %.2f   len %.0f -> %.0f   roughness %.2f -> %.2f   mean |dev| %4.1f%%  max bulge %+5.1f%%"
            % (
                p["var_r"],
                p["var_c"],
                p["lr"],
                p["lc"],
                p["rough_r"],
                p["rough_c"],
                100 * p["dev"],
                100 * p["bulge"],
            ),
        )


if __name__ == "__main__":
    which = sys.argv[1:] or ["1", "2", "3", "4", "5", "6"]
    for w in which:
        globals()[f"sheet{w}"]()
        print("sheet", w)
