# Progress log: the fair-surface pass

Newest entries last. Images are in this folder. The baseline is the art-pass final:
`snakes/stills/final.png`, `snakes/w-final.*`, shown in `00-baseline-sheet.png` as reference | before the art pass | final.

## Why another pass

The body is a stack of local corrections, each smooth on its own and kinked where they compose:
- the spine has piecewise-linear offsets;
- the twist is a C1 PCHIP with a sharp reversal;
- the swell is piecewise linear;
- beading, per-lobe Gaussians, a curvature "fold pinch" and a contact "press" sit on top.

The fold pinch fixes self-folds by squeezing the tube at tight bends, which itself makes necks. The plan:
- one C2 representation per strand (a B-spline centreline and radius);
- fairness measured on the evaluated swept surface;
- fitting with JAX autodiff and L-BFGS-B, after lmmx/page-dewarp #130/#135/#136/#139;
- the real Three.js render as the judge.

## What I took from page-dewarp (read in code)

- The forward model is a pure `jnp` function of one flat parameter vector, a line-for-line twin of the NumPy/OpenCV path.
- Discrete structure (`keypoint_index`) is frozen, so the objective is smooth.
- `jax.jit` plus `jax.value_and_grad`, passed to SciPy L-BFGS-B with `jac=True`; non-finite values are guarded.
- `jax_enable_x64` is set before compilation; `maxcor` is raised for high-dimensional problems; batching is a vmap over padded problems.
- The old approach "was flying blind" on finite-difference gradients. My 37-variable Powell valley search had the same failure, and I stopped it.

## 1. JAX pieces, gradient-checked (x64, CPU, jax 0.11.2)

`tools/jaxsurface.py`:
- Builds the swept surface the way the scene does: rotation-minimising frames as a `lax.scan`, and rings.
- Fairness is measured on that surface:
  - bending energy, the mean |d²S/ds²|² over every longitudinal surface line;
  - its variation, |d³S/ds³|²;
  - a fold barrier on each surface line's advance relative to the centreline (≈ 1 − rκ cos φ).
- Autodiff against central differences: relative error 3e-8.

`tools/jaxraster.py`:
- An occlusion-aware soft rasteriser of ball chains.
- Coverage is sigmoid((r − |q − c|)/τ), combined as a soft union. Colour is a softmax over all balls of log-coverage plus front-surface depth / γ.
- Every ball competes at every pixel, so distant parts of one strand that overlap at a tight bend occlude each other correctly. The earlier station-local surrogate could not do that, which is why it predicted wrong gradients at the valleys.
- Image-loss gradient against central differences: relative error 4e-6.
- Cost: 0.4 s per value + gradient on a 16,800-px window with 435 balls.

Parity with the real render (`tools/jaxraster_check.py`, hard limit, the current final's strands dumped from `geometry.js`):

| window | blue IoU | yellow IoU | silhouette IoU | pixel agreement |
|---|---|---|---|---|
| left valley | 0.873 | 0.880 | 0.976 | 0.948 |
| right valley | 0.897 | 0.892 | 0.976 | 0.954 |
| central arch | 0.859 | 0.839 | 0.976 | 0.935 |
| left arm (includes the yellow neck, not modelled) | 0.894 | 0.799 | 0.960 | 0.912 |

`01-soft-raster-parity.png` shows the render's labels, the raster's, and their differences in red.
- Most disagreements are 1–2 px lines along colour boundaries.
- The larger patches come from the old pipeline's centreline smoothing, fold pinch and press, which the new representation should make unnecessary.

## Subagents (both finished: see section 3)

- **A geometry architect agent:** one C2 B-spline centreline and radius per strand, fitted to the current body with fairness regularisation, rendered through the real scene. The new `body` option of `createScene` lets another representation's strands replace the centreline model.
- **A surface-diagnostics agent:** grey clay and zebra-stripe renders of the current mesh, and kinks, pinches and folds measured and attributed to each pipeline stage.

## 2. Review fixes: arc length and colour bleed

**Arc length** (`jaxsurface.py`). The fairness terms divided by a fixed `h`, so a moving spline would have been penalised for its sample spacing, not its shape. They are now independent of the parameterisation:
- On every surface line the discrete curvature vector is k = Δ(unit tangent) / local arc length.
- Bending is Σ|k|²·ds and its variation Σ|Δk/ds|²·ds, both per unit length.
- A `spread` term (the variance of the centreline spacing) keeps samples from bunching.

Test: the same surface sampled three ways (spacing CV 0.32, 0.54, 0.63) gives bending within 0.4%, where the old fixed-h version varied 4×. The variation term is also stable except under extreme bunching (u^1.8, where spacing goes to ~0 near one end), which `spread` prevents in a fit. Gradients still match central differences (1.4e-8).

**Colour bleed** (`jaxraster.py`): a real bug.
- The colour softmax used log a + z/γ, so a ball nearer the camera that does not cover a pixel could still win it, bleeding past the edge of its disc by about Δz·τ/γ.
- The score is now sharp·log a + z/γ, so bleed ≈ Δz·τ/(sharp·γ). The hard z-buffer is the limit of that going to zero, not of τ and γ alone; the earlier docstring overclaimed.
- Two-ball test (front ball 40 px nearer): the boundary was 12–25 px off with sharp = 1, and is 0.4–1.1 px off with sharp = 20. Gradients at the occlusion boundary match finite differences.

Parity with the real render after the fix:

| window | blue IoU | yellow IoU | silhouette IoU | pixel agreement |
|---|---|---|---|---|
| left valley | 0.944 (was 0.873) | 0.949 (0.880) | 0.976 | 0.974 (0.948) |
| right valley | 0.944 (0.897) | 0.932 (0.892) | 0.976 | 0.970 (0.954) |
| central arch | 0.951 (0.859) | 0.942 (0.839) | 0.976 | 0.972 (0.935) |
| left arm (includes the yellow neck, not modelled) | 0.926 | 0.836 | 0.960 | 0.930 |

`02-soft-raster-bleed-fix.png` shows render labels | raster with sharp = 1 | differences | raster with sharp = 20 | differences, for the right valley and the central arch.

**Fidelity of the surrogate to real renders:** these checks show only that JAX differentiates its own objective correctly. The comparison with real Three.js renders along a fit's path is in section 4 ("Surrogate fidelity", `tools/fidelity.py`).

## 3. First spline body: rendered, and judged in clay and zebra

The geometry-architect agent built the new representation:
- **Strands:** each strand is an independent clamped cubic B-spline in 3D, with knots every 16 px of station, about 84 control points.
- **Radius:** a cubic B-spline, knots every 12 px.
- **Fit:** both are fitted to the current body with fairness-regularised least squares (∫|X'''|², ∫r''²).
- **Evaluation:** linear in the control points (X = B @ ctrl), with JS (`snakes/strandspline.js`) and NumPy (`tools/strandspline.py`) agreeing to 1e-11 px.
- **Rendering:** through the real scene via `createScene(..., { body })` (`still-spline.html?spec=...`).
- **Head joins:** the join point is within 0.3 px and the tangent within 1.6–3.2°.

The comparison sheets render both bodies under identical lighting and materials. Columns: reference | colour | colour | clay | clay | zebra | zebra (8 bars), baseline then new, for the full frame, the central arch, both valleys and both arms. The clay/zebra page is `snakes/diag-clay.html` (surface-diagnostics agent); `cmp-spline-geo.js` feeds it the spline body.

- `03-spline-hi-vs-baseline.png`: the spline body with stronger fairing, fold pinch and press kept.
- `04-spline-nofold-vs-baseline.png`: the spline body with the fold pinch off.

**Honest verdict: the refit alone does not visibly change the sculpture.**
- spline-hi is nearly indistinguishable from the baseline in clay and zebra. The stripes flow the same way, and the right-valley crease and dimple remain.
- Turning the fold pinch off is the one visible gain: the right-valley dimple softens, and its zebra swirl becomes cleaner stripes.
- That is expected. The refit reproduces the old shape, and the old shape's problems are in the shape itself, not in how it is parameterised.

The architect's and the diagnostics agent's measurements say what those problems are:
1. **Cross-turn interpenetration at both valleys.** The spine bends so tightly that different turns of the rope pass 10–15 px apart while their radii sum to ~86 px, so they overlap by up to ~75 px. The press only pairs a strand with its twist partner at the same station, so this overlap is never resolved. It is the right-valley seam.
2. **A squeezed helix.** r·κ > 1 over 34–37% of each strand (r ≈ 43 px on a helix with ~55 px curvature radius), so the inside of every turn would fold. The fold pinch is load-bearing, and it is also what makes the right-valley dimple: it pulls the blue in by up to 15 px.
3. **Kinks from the piecewise-linear spine offsets.** The strands jump up to 10 px between 0.5 px samples at ~30 stations; the tube's 12 px smoothing hides most of it. A C2 spline for the offsets alone cuts visible >2° creases from 346 to 106.
4. **The press is visually inert.** It moves no visible vertex more than 0.5 px.

## 4. The right-valley dimple: the first JAX geometry fits

**Target:** remove the blue dimple at the bottom of the right valley without moving lobes, shrinking the blue lobe or disturbing the rest of the W. Every candidate is judged on real Three.js renders: right-valley crops in colour, clay and zebra (8 bars), the whole body, and a 3/4 view (yaw 35°).

### What the dimple is

- **It is one blue hairpin.** The blue strand comes down at shared station 1051, curls at the valley bottom (stations 1079–1115), and goes back up at 1155. (On the starting spline the closest pair of legs is 1051 / 1155; after the elliptical fit e1 it is 1053 / 1153, the stations `--leg-front` / `--leg-back` use below.)
- **The curl:** about 18 px in radius around a 37–44 px tube, so r·κ reaches 2.0–2.2. Its inside faces the camera, so the fold through itself is visible: that is the notch (`tools/dimple.py`).
- **The collision:** the two legs, 1051 and 1155, are only 19 px apart in 3D with radii 39 + 45. That is a 65 px overlap between non-adjacent parts of the same strand (`tools/contact_map.py`).
- A C2 spline does not prevent this. It can be perfectly smooth and still pass through itself.

### The fitter (`tools/regionfit.py`)

Free: the control points of both strands whose support reaches a small window around the curl. The neck joins are pinned. Objective, all on the evaluated spline:
- **Image:** soft-raster cross-entropy against the reference labels. The window is sized automatically to wherever the movable geometry projects.
- **Self-collision:** non-adjacent sections of the same strand (≥ 90 px of station apart) must not overlap. The threshold is calibrated on the straight parts, where nothing that far apart ever overlaps.
- **Soft contact** between the strands: an allowance of 12 px.
- **Visible-fold barrier:** the swept surface's advance, weighted by how much it faces the camera. A weaker **global** fold barrier stops a fit from just turning a fold away.
- **Fairness:** arc-length invariant, relative to the start.
- **Trust region** on the evaluated centreline: screen and depth separately. A penalty on depth oscillation.
- **Crossing order:** every clearly ordered over/under pair keeps its order.
- **Solver:** L-BFGS-B, x64.

Mesh-level validity is measured on the real tube (`tools/mesh_check.mjs`), as areas, not vertex counts, and split into:
- **local folds:** surface lines running backwards;
- **non-local self-penetration:** a ring vertex inside a section ≥ 90 px of station away.

### Round 1 (rejected): no trust region

`05-rejected-loop-full.png`, `05b-rejected-loop-crops.png`.
- **The crop looked fixed:** a clean convex blue bead and concentric zebra rings.
- **The whole body was destroyed:** a large new blue loop across the middle of the W. Control points moved up to 290 px, mostly in depth, outside the window the image term could see.
- **Lesson:** the nearly frontal reference barely constrains depth. Since then every candidate is shown with its whole body, and the fits have a trust region, crossing order and an automatically sized image window.

### Round 2: circular tubes with a trust region (depth 10 / 20 / 35 px; screen 12 px)

`06-circular-trust-crops.png`, `07-circular-trust-full.png`.
- **The W is intact** in the hero and the 3/4 view. There are no loops, and the colour layout moves towards the reference (agreement with the reference 0.885 → 0.918 in the window).
- **The notch is shallower but still there.** Clay shows a crease ending in a pit; zebra a closed loop.
- **The depth budget does not matter.** All three stall at about 30 px of remaining self-overlap: the collision is in the screen plane, so more depth buys nothing.

### Round 3: elliptical cross-sections (e1)

`08-elliptical-e1-crops.png`, `08b-curl-zoom-base-z20-e1.png` (clay and zebra: baseline | z20 | e1), `09-elliptical-e1-full.png`.

**The new section field.** Each strand carries a C2 section field (cubic B-splines, knots every 24 px):
- **ql:** the lateral semi-axis, which lies exactly in the screen plane;
- **qd:** the depth semi-axis;
- **ψ:** orientation, bounded and costed.

How the terms use it:
- ql alone sets the visible width.
- A cost on any departure from round makes sections deform only where contact asks for it.
- A soft area term, (ql·qd − 1)², is a preference, not a constraint: with ql ≤ 1.12, strong flattening cannot keep its area.
- The fold pinch is off, so the ellipse replaces it. The press (`tube.press` of `w-final.params.json`) stays on in the scene; the surface-diagnostics agent measured it inert (no visible vertex moves more than 0.5 px, section 3).

**One section map everywhere.** The same map is used by:
- JAX: `tools/jaxsurface.py ellipse()`;
- the raster: screen half-width and front depth of each ellipse;
- the contact terms: the ellipses' combined extent along each separation;
- the scene: `geometry.js strandSurface`, `strandspline.js` sec;
- the mesh check.

Round sections reproduce the old mesh to 2.5e-13 px.

**The result:**
- **Visibly the best so far.** The surrounding curvature is smoother and the pit is smaller.
- **The W is unchanged elsewhere.** Hero, 3/4 colour and clay are intact, and the depth moves are only 6 px.
- **But the dimple is not gone.** A short crease still runs down into a pinch point, and zebra still shows a teardrop loop.

Mesh check, right-valley window:

| | baseline spline | circular z20 | elliptical e1 |
|---|---|---|---|
| blue visible local-fold area | 2,771 px² | 1,603 px² | **710 px²** |
| blue non-local self-penetration | 12,276 px², 45.6 px deep | 9,311 px², 29.8 px | 7,194 px², 31.3 px |
| yellow visible local-fold area | 1,935 px² | 255 px² | 661 px² |

### Why e1 stops short (`tools/legs.py`)

**What remains:** the crease where the two blue legs (stations ~1053 and ~1153) **fuse**. The pit is where that intersection curve ends.
- **Screen:** the fit pushed the legs apart on screen, from 19 to 53 px. Their lateral radii sum to 80, so they still overlap.
- **Depth:** they sit at **exactly** the same depth (Δz = 0.0). With the flattened depth radii they need about 43 px of depth separation.

**Why the fit can't find it:**
- **A symmetric saddle.** The collision term depends on depth only through Δz², so at Δz = 0 its depth gradient is exactly zero. Which leg goes in front is a discrete choice that gradient descent cannot make.
- **No room in depth.** Each leg has yellow both in front of it (+38 px) and behind it (−56 px). The crossing-order constraint freezes the starting order, which is probably wrong exactly here.
- **The reference** shows one blue bead at the bottom, with the two yellow lobes meeting above it, so the other blue leg is hidden behind yellow.

### Surrogate fidelity (`tools/fidelity.py`)

Along the z20 fit's path, the JAX raster and real Three.js renders improve together:

| step along the path | raster vs reference | render vs reference | raster vs render |
|---|---|---|---|
| 0 | 0.884 | 0.885 | 0.989 |
| 0.5 | 0.898 | 0.900 | 0.989 |
| 1 | 0.916 | 0.918 | 0.989 |

The image term is a faithful surrogate: it predicts the render's change to within 0.002.

### Round 4: choose which blue leg goes in front (e2a, e2b)

`regionfit.py --leg-front S1 --leg-back S2` orders the two legs in depth, by a 45 px margin wherever they overlap on screen. That breaks the saddle. Crossing order is not enforced for those two legs alone, because their layering is the thing being decided. Both runs start from e1.

`10-leg-order-crops.png` (baseline | e1 | e2a | e2b), `10b-curl-zoom-e1-e2a-e2b.png` (clay, zebra, colour of the curl), `11-leg-order-full.png` (hero and 3/4 views).

- **e2a, leg 1053 in front: worse.** The crease and pit stay, and the zebra swirl remains.
- **e2b, leg 1153 in front: the notch is gone.**
  - **Clay:** the front leg is a clean convex bead. Where it overlaps the back leg there is a soft contact groove, not a pit.
  - **Zebra:** the bead's stripes flow cleanly.
  - **Whole body:** the W is intact in the hero and the 3/4 view.
- **e2b's residual flaws:**
  - At the lower left, where the back leg tucks under, the zebra stripes still converge. The blue visible-fold area there is 1,365 px² (e1: 710).
  - The blue bead reaches further right than the reference's: agreement with the reference 0.907, against 0.908 for e1.

Mesh check, right-valley window:

| | baseline spline | e1 | e2b |
|---|---|---|---|
| blue non-local self-penetration | 12,276 px², 45.6 px deep | 7,194 px², 31.3 px | **1,581 px², 6.1 px** |
| blue visible local-fold area | 2,771 px² | 710 px² | 1,365 px² |
| yellow visible local-fold area | 1,935 px² | 661 px² | 587 px² |

### Round 5: refine e2b (e3): the right-valley candidate

The same fit from e2b, with the visible-fold weight 20 → 60 and the image weight 100 → 150.

`12-refine-e3-curl.png`: rows baseline (reference beside it) | e2b | e3; columns colour, clay, zebra. `13-refine-e3-full.png`: whole body, hero and 3/4 views.

- **The dimple is gone,** in clay and in zebra.
- **The tuck is cleaner than e2b's.** The stripes where the back leg tucks under fan out instead of bunching, and e2b's small singular spot at the right edge is gone.
- **The W is intact** in the hero and the 3/4 view.
- **The blue lobe still reads as full** from the front. Its sections flatten only in depth at the hairpin (qd ≥ 0.62); the lateral axis stays at 0.95–1.0.

Mesh check, right-valley window:

| | baseline spline | e2b | e3 |
|---|---|---|---|
| blue non-local self-penetration | 12,276 px², 45.6 px deep | 1,581 px², 6.1 px | **0** |
| blue visible local-fold area | 2,771 px² | 1,365 px² | 799 px² |
| yellow visible local-fold area | 1,935 px² | 587 px² | 381 px² |
| yellow non-local self-penetration | 5,585 px², 11 px | 1,160 px², 5.7 px | 1,983 px², 8.2 px |

**Still different from the reference:** its blue lobe is a narrow teardrop between the two yellows, ours a broader bead. That is lobe-shape correspondence, not a surface defect.

**The committed baseline is unchanged.** e3 was a candidate (`snakes/spline-rv-e3.json`, rendered with `still-spline.html?params=w-final.params.json&spec=spline-rv-e3.json`). **The audit of section 5 rejects e3 and e2b:** L14, the right valley's rising yellow lobe, falls from IoU 0.76 to 0.40 (e2b) and 0.41 (e3) (the leg-order change made it), which the crop-by-crop review above missed. e1 is the accepted best.

## 5. The audit loop (supersedes the per-region narrative above)

The judging is now separate from the fitting and covers every feature: `audit/README.md` describes the loop, `audit/LEDGER.md` records every candidate, and `audit/iterNN/` holds each iteration's metrics, critic reports, paired judgements and ledger.

- **Anatomy:** 18 numbered reference features (H1, L01–L16, H2) and six negative spaces (`audit/reference-annotated.png`).
- **Evaluator:** per-feature measurements on real renders (`tools/evaluate.py`), with a lobe split that reproduces the reference registry and flags its own doubtful splits.
- **Blind critics:** fresh subagents that see only anonymised images. Absolute critics (`tools/critic_pages.py`) and paired judges (`tools/pair_pages.py`, reference | X | Y in random order).

### Iteration 0

- **Baseline:** severity 5 at L04; severity 4 at L05 and L13.
- **e2b, e3: rejected.** L14 IoU 0.76 → 0.41.
- **e1: accepted best.** It passes the gates against the baseline (L13 IoU 0.54 → 0.66, L12 0.59 → 0.73, L06 0.77 → 0.82). The paired judge finds it closer at L09–L14 and H2, with no defect of its own.

**Consensus of the four independent critics** (`audit/iter00/ledger.md`):
1. **L05:** a hard-edged cap with yellow in front of its lower part (wrong over/under), not reaching the floor.
2. **L13/L14:** L13 too broad and creased, in front of L14 where the reference has L14 in front.
3. **L04/L06:** the left valley's yellows fused into one bent tube.
4. **G1, whole-body character:** a rope where the reference has stacked convex cushions. The arm lobes are 15–20° too steep and elongated, with saddle surfaces, and the rolled crevices between lobes are about 20× too light.
5. **L01/L16:** the opposite-colour collar on each neck climbs 7–12 px too high.

### Iteration 1: targets L04, L05 (left valley), from e1

- **i1a** (centreline and sections) and **i1b** (radius free too): the metrics show small mixed gains.
  - The paired judges call i1a a trade (L05 +1, L06 −1) and prefer e1 over i1b.
  - **Both rejected.**
- **i1c** (explicit depth order, blue in front of yellow inside L05): **rejected.** L04 IoU fell 0.69 → 0.59. Bringing blue forward over L05 also brought it forward over L04.
- **Diagnosis** (`tools/who.py`): the reference's L04 and L05 sit side by side on the floor. In e1 the twist partners at the valley bottom are front and back, a twist-phase difference that neither local fits nor a depth flip reach.
- **Next test:** `tools/twist.py` turns the left-valley pair about the local spine. +45° / +90° raise the blue shown inside L05's reference mask from 62% to 69% / 73%. Refining fits from those starts are running.
- **Judge calibration:** one paired judge preferred e1 by one step on L12 and L13, features the fit did not touch. So paired verdicts count only beyond about one step.

### Iteration 2: coarse moves

- **Twist phase, left valley** (`tools/twist.py`, chosen by a raster screen `tools/screen.py` of 16 windows × angles): turning only the valley bottom (stations 420–500) by 60° makes L05 a round ball on the floor.
  - **Measured:** L05 severity 4 → 2, IoU 0.56 → 0.71.
  - **Confirmed blind:** the paired judge finds it closer at L05, with every other feature the same.
  - **lvt60 is the accepted best** (`snakes/spline-lvt60.json`).
- **Proportions** (parametric body, helix radius against tube radius): R = a = 40 (touching strands) gains 0.03–0.04 IoU on most arm and arch lobes and leaves the valleys unchanged. Heavier beads are worse.
- **Twist phase, right valley:** −30° fixes L14 in the screen, but the refit and the real render collapse L12 and L14. **Rejected.** L13's error is its shape (too broad), not its phase.

### Iteration 3: refits from lvt60, proportions on the spline body

- **lv60 / lv75** (regionfit from lvt60 and from a 75° twist, L04 and L05 targeted): the metrics improve at L04 (0.66 → 0.73 / 0.76) and L06. The paired judges see a new crease at L06 in both and prefer lvt60. **Both rejected.**
- **p110 / p106** (iteration 2's c1 proportions carried to the spline body: helix radius ×1.10 / ×1.06, tube radius ×0.92 / ×0.95):
  - The arch lobes gain 0.01–0.03.
  - The valley yellows move about 50 px (L04 0.66 → 0.46, L06 0.65 → 0.39).
  - **Rejected.** A proportion move must leave the valleys out, because the twist sets their geometry, not the helix radius.

### Iteration 4: a lobe-primitive body for the left valley (bounded prototype)

**The prototype (`tools/beads.py`).** Over the left valley's stations, each strand becomes a signed distance field:
- a core tube (the spec's own centreline and elliptical sections);
- smooth-min blended with one ellipsoid per reference lobe, initialised from the lobe mask's moments;
- meshed by marching cubes.

`scene.js` takes the result as `extra`: it cuts the swept tube over the same stations and adds the meshes with the strand's material.

**h2 (1.5 px voxels): rejected.** L05 rises 0.71 → 0.81, but the paired judge sees seams at the tube junctions, faceted zebra and a lumpy L06.

**h3: rejected.** The one bounded correction used 1 px voxels, normals from the field's gradient, and overlapping cuts.
- Most of the faceting is gone.
- The judge still prefers lvt60 at L02–L07, by 1–2:
  - junction seams at L02, L03 and L07;
  - a crease down L05's left side;
  - a notch and a squared end at L06.

**h3b (full-radius core): no better.**

**What it showed:**
1. **The L04/L06 pinch is inherited.** It survives a full core (h3b) and is present in lvt60 itself. It comes from the yellow centreline's tight bend, so additive primitives cannot remove it.
2. **Junctions between separately meshed surfaces read as seams** to the blind judge, even when they are out of sight in the colour render's silhouette. A replacement surface has to be one continuous surface.
3. **The judge rates lvt60's L04/L06 at severity 2** (a soft fold, band-like), where the metric says 5. The metric's severity there is driven by the merged/unstable segmentation flags, so it overstates them.

**Next:** the competing strand-local deformation prototype (one continuous swept surface, deformed in place), then a single side-by-side against the reference and lvt60.
