# Snake W: the logo as a Three.js reconstruction

Two snakes, one Python blue and one yellow, twisted into a W. Built to match one reference
image (`snakes/ref/reference.png`) at its own camera. This is work in progress: see the
latest render in `snakes/stills/final.png`.

## Layout

- `snakes/`: the scene.
  - `index.html`: the page.
  - `still.html`: headless stills.
  - `scene.js`: lights, materials, eyes, shadow.
  - `geometry.js`: centrelines, tubes, heads.
  - `w-final.params.json`: the parametric model (necks, heads, camera, tube).
  - `w-final.spec.json`: the final body, a spline per strand (`strandspline.js`; round 26 of the loop).
  - `w-final.extra.json`: the final valleys' overlay (`scene.js` extra: both valleys' tubes moved towards fitted cushions, `tools/hybrid.py`; round 28).
  - `w-final.look.json`: the final look.
  - `heads-w-final.json`: the heads baked for the final body (`heads-final.json`: the parametric body's, which the fitting tools read).
  - `checkpoints/`: earlier stages.
- `tools/`: fitting, measuring and rendering scripts.
  - Python: `snakefit.py` and `headmodel.py` hold the model; the rest measure, fit and compare.
  - Node: `snake_still.mjs` / `snake_batch.mjs` render stills; `bake_heads.mjs` bakes the heads; `check_page.mjs` loads a page headless.

## View it

    cd logo/snake-w/snakes && python3 -m http.server 8000    # http://localhost:8000/

Three.js r170 loads from jsdelivr (pinned). The page builds in about 3 s with the baked heads,
and keeps the reference framing at any window size. `?params=`, `?spec=`, `?extra=`, `?look=` and
`?heads=` select other files; `?spec=none` falls back to the parametric body and `?heads=none`
meshes the heads in the page (about 25 s). The geometry is frozen at the loop's round 28
(`auto/state.json`); `progress/final/` compares it with the reference at use sizes.

## Stills and baking

Run these from `snakes/`. They need Node with Playwright and a Chromium: `$CHROME`, or the
pre-installed one.

    node ../tools/snake_still.mjs out.png w-final.params.json look="$(cat w-final.look.json)" ss=2 heads=heads-final.json
    node ../tools/bake_heads.mjs w-final.params.json heads-w-final.json w-final.spec.json

- `ss=2` renders at twice the resolution and lets the browser filter it down.
- Put `three.module.js` r170 in `vendor/` (next to `tools/`) to render offline.
- A bake is keyed by what the heads depend on: the head and neck parameters, and the strands at
  the neck joins. Body changes elsewhere keep it valid. On a mismatch the scene meshes the heads
  itself and logs a warning.

## Python tools

They need numpy, scipy, scikit-image and pillow; the fitting and raster tools (`jaxraster.py`, `jaxsurface.py`, `regionfit.py`, `fidelity.py`, `calib.py`) also need jax (x64, CPU).

- The original fitting tools (`snakefit.py`, `fit_splines.py`, the head and lobe scripts) run from `snakes/`, as `../tools/name.py`, and read `ref/reference.png` relative to that folder.
- The audit and region-fit tools (`anatomy.py`, `evaluate.py`, `audit_render.py`, `critic_pages.py`, `pair_pages.py`, `ledger.py`, `who.py`, `twist.py`, `render.py`, `fidelity.py`, `vsheet.py`, `fullsheet.py`) run from this folder (`logo/snake-w`), as `tools/name.py`; `audit/README.md` describes the loop.

Spline specs render with `snakes/still-spline.html?params=w-final.params.json&spec=spline-….json`.

## Checkpoints

The JSON files in `snakes/checkpoints/` are the stages, newest first:

- `final-art.json` / `look-final-art.json`: the current version (also the `w-final.*` files).
- `final-before-artpass.*`, `body-art1..5.json`, `look-art1/2.json`: the art-direction pass.
- `final.json`, `body-valleys.json`, `body-rvalley1.json`, `body-press18.json`, `body-fold.json`: the body passes.
- `artpass-best.json`, `heads2-fieldfix.json`: the head passes.
- `pre-bead-best.json`: the original fit.
