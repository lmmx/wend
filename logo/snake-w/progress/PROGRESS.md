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
