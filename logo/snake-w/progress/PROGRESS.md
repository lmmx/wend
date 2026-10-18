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

## In progress

- **A geometry architect agent:** one C2 B-spline centreline and radius per strand, fitted to the current body with fairness regularisation, rendered through the real scene. The new `body` option of `createScene` lets another representation's strands replace the centreline model.
- **A surface-diagnostics agent:** grey clay and zebra-stripe renders of the current mesh, and kinks, pinches and folds measured and attributed to each pipeline stage.

## Next

- Fix the representation.
- A JAX fit of one region (the left valley or the central arch), with these terms:
  - surface fairness;
  - the soft image and outline terms;
  - a contact band between the strands;
  - L-BFGS-B, x64.
- Before trusting a fit: directional derivatives against finite differences of real Three.js renders.
- Deliver grey and colour renders beside the reference and the baseline.

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

**Still to do:** fidelity of the surrogate to real renders. These checks show only that JAX differentiates its own objective correctly. Once the spline body exists, small control-point perturbations will be rendered through Three.js, and the measured change compared with the JAX-predicted one.

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

## Next: the first JAX fit, on one region

Start from spline-hi and free only the control points covering one valley. Objective:
- the soft image term against the reference, and the outline term;
- surface fairness (arc-length invariant);
- **contact**: twist-partner overlap held in a band (~5–25 px), and a hinge penalty max(0, r1 + r2 − d − allowance)² between different turns;
- a fold barrier at r·κ ≈ 2 (not 1: that would be 35% of the shape);
- the neck-join control points pinned.

Then L-BFGS-B, x64. Before accepting:
- check its predicted direction against finite differences of real renders;
- render through Three.js and compare in colour, clay and zebra with the baseline;
- accept only if it visibly looks better.
