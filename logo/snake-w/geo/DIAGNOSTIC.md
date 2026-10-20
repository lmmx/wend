# Geometry diagnostic: scarf, nape, RHS tubes

The frozen final geometry is r28-hybR: spec `snakes/w-final.spec.json` plus the overlay `snakes/w-final.extra.json`, rendered with look6. Nothing was changed. The measurements come from `geo/measure.py` (output in `geo/diag.json`, `geo/lobe_profiles.json`), and the sheets from `geo/sheets.py`.

| sheet | content |
|---|---|
| `sheet1-silhouette.png` | full-frame silhouette overlay (reference-only, render-only, wrong-front), both W-spines, turning points, the three defects annotated |
| `sheet2-centrelines.png` | projected strand centrelines (visible vs hidden), station labels, model spine, overlay ring centres, over the reference and over the render |
| `sheet3-clay.png` | reference vs neutral clay; per-issue crops: reference / look6 / clay / zebra / outlines |
| `sheet4-spine.png` | along the W-spine: spine and band-centre offset, band width, both silhouette edges, twist phase strip |
| `sheet5-sections.png` | 3D sections along s per strand: nominal r(s), ring mean radius, projected half-width, ellipticity and lumps, sec ql/qd, disp handles, overlay ranges |
| `sheet6-issues.png` | the three defects measured: visible lobe width profiles (reference vs render, same cuts), r(s) and handles through each lobe, neck edge profiles and curvature |

## 1. Macro path: spine, helix envelope and twist phase are already right

| quantity | result |
|---|---|
| W-spine length | 1284 px (reference) vs 1288 px (render) |
| render spine offset from the reference spine | ≤ 4 px p90 in every region (≤ 2.3 px at both heads) |
| turning points (both heads, both valley bottoms, arch top) | all within 5.3 px |
| band width (≈ 2 × (helix radius + tube radius)) | within 1–2% on both arms and the arch; −3.5% / −4.7% in the two valleys (the accepted, frozen overlay regions) |
| twist phase: front-strand switch positions | −6 … +6 px against a half-period of 65–105 px, so ≤ 13° of twist phase except one 2-px flicker at the arch |
| per-lobe centroid | within 4 px for every lobe except L05 (+6, −6; frozen) |

A coherent global adjustment of the spine, helix radius or twist phase therefore has almost nothing to correct. It would move regions that already match, the right-valley blue base included, to fix defects that sit in three local places.

## 2. The three defects

### 1. Left head: blue scarf too high, wrong shape (L01, blue s 1322–1447)

* **Measured**
  * The top of L01 is 17 px too high.
  * The right of the neck is about 10 px narrower than the reference over arc 40–110 (sheet 4, −N edge).
  * The visible width tapers 1.47× along the lobe, against 1.19× in the reference (sheet 6).
* **Path:** the blue tail climbs the yellow neck steeply. Image y goes 446 → 382 → 363 over s 1394 → 1434 → 1459. The visible run ends at s 1447, only 27 before the tail tip (s1 = 1474.5).
* **Radius:** r(s) falls 40 → 26 inside the visible run (the tail taper).
* **Handles:** a −0.158 ring handle at s 1436 pinches the tail further. Two +0.13 side handles at s 1389 make it oval: the projected half-width is 46 against a ring radius of 42.
* **Cause:**
  * The tail end's path climbs too high and steeply, wrapping up the neck instead of across it.
  * The taper falls inside the visible run.
  * The pinch handle compensates for the high path, keeping the climbing tail from overshooting the top.
  * This is a tail-termination problem (local path plus taper), not a spine or helix-radius problem.

### 2. Right head: bumpy nape (H2 neck, where the yellow L16 tail crosses it)

* **Measured**
  * The blue neck's own silhouette matches the reference within 3 px from the head down to y ≈ 408, on both edges.
  * The bump is the contact line where the yellow L16 top edge crosses the nape. Against the reference's smooth descending diagonal it runs:
    * +10 px higher at x = 1000,
    * 6 px lower at x = 1010–1020,
    * 7 px higher again at x = 1050–1070.
  * Below that, the throat shows 7–9 px lower than in the reference (the H2 lobe bottom is +16 px).
* **Path:** the yellow tail (s 1381 → 1420) turns up behind the blue neck: (996, 443) → (1017, 421) → (1061, 415).
* **Radius:** the tail has r ≈ 31 there, against 46 mid-L16.
* **Handles:** a +0.077 ring handle sits at s 1388, right at the turn.
* **Cause:** the same as defect 1, mirrored. The yellow tail ends visibly against the blue neck: tapered, turning behind the neck too early and too high, with a handle on the turn. The head and neck mesh itself is not the problem.

### 3. RHS tubes non-cylindrical and puffy (L15 blue s 233–334, L16 yellow s 1284–1405; L14 mostly fine)

* **Measured:** mean deviation of the visible width profile from the reference's, using the same cuts (sheet 6):

  | lobe | mean deviation | max bulge | width max/min, render | width max/min, reference |
  |---|---|---|---|---|
  | L16 | 11.8% | +19% | 1.57 | 1.24 |
  | L15 | 12.3% | +15% | 1.61 | 1.19 |
  | L14 | 1.8% | | | |

  For comparison, the left-arm lobes deviate by 1–6%, and L05 by 12% (frozen).

* **Radius:** every lobe carries a radius "bead": r(s) peaks mid-lobe and dips in the hidden stretches, with a within-lobe max/min of about 1.2–1.35. The two worst are on the right arm, together with L01 at the scarf:

  | lobe | r(s) | max/min | projected half-width max/min |
  |---|---|---|---|
  | L16 | 30 → 46 | 1.52 | 1.61 |
  | L01 | 26 → 40 | 1.52 | 1.80 |
  | L12 (frozen overlay) | 35 → 56 | 1.59 | 1.78 |

  L15's bead (38 → 50) has no handles, so it is the nominal r(s) itself, skewed against the visible run.
* **Handles:** L16 carries ±90° side handles of +0.10/+0.15 at s 1347, plus rings at 1307 and 1388. These blow up the middle of L16.
* **Interpenetration:** on L14 and L15 the two strands interpenetrate by 24–28% of r. Measured as r + r_mate − |P − mate|, with the helix radius R/r = 0.83–0.87. The left arm's L01–L03 sit at 10–13%. The contact press then flattens the sections into D shapes. That is the non-cylindrical look: the oval harmonic and the ellipticity rise in the L14 overlay to 20–27%.
* **Cause:**
  * The main cause is local strand volume: an uneven radius profile plus inflating handles.
  * It is compounded by the helix radius being too small for the tube radius on the right arm. The beads and handles probably compensate for that: they keep the visible width while the strands overlap.

## 3. Proposed single adjustment (for review; not applied)

One low-dimensional change, confined to the two strand tails and the top of the right arm, replacing local handles instead of adding any:

* **Tail collars, ×2 (blue tail s ≥ 1340, yellow tail s ≥ 1300).** Three parameters per tail:
  * Δs1: extend the tail about 30–50 so the taper finishes behind the partner's neck.
  * Δφ_tail: a twist-phase offset ramped in over the last half-turn, so the collar wraps across the neck at the reference height instead of climbing it.
  * A tail-radius floor: hold r near the lobe mean until the tail is hidden.

  This removes the blue −0.158 pinch (s 1436), the blue ±90° pair (s 1389) and the yellow s 1388 ring handle.
* **Right-arm radius/helix pair (blue s 200–350 and yellow s 1280–1340; tapered to zero before the right valley).** Two parameters:
  * Smooth r(s) towards the lobe mean (bead amplitude halved).
  * Raise the helix radius R by the same amount, so the band width 2(R + r), which already matches, stays fixed and the interpenetration falls to the left arm's ~12%.

  This removes L16's ±90° side handles (s 1347).

That is 8 parameters, fitted once against the reference silhouette, the lobe width profiles and the neck contact line, with gates on every lobe outside the windows. The blend windows stop short of everything frozen: the left valley, the arch, and the right valley's overlays (blue s 359–497 and yellow s 968–1247, which also contains L14, left untouched).

**Alternative:** declare the geometry final and proceed to task #32 (preview, animation, derived assets). Defects 1 and 2 are the most visible at icon sizes, because they sit at the heads.
