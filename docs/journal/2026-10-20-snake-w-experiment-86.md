# 2026-10-20: Snake W, a Three.js reconstruction of the logo: a retrospective

This entry covers PR [#86](https://github.com/lmmx/wend/pull/86), `experiments/snake-w/`. It replaces the
PR's five working entries of 2026-10-18 and 2026-10-19. Those, and every round's specs, metrics,
judgements and sheets, are archived on the branch
[`archive/logo-snake-w-research`](https://github.com/lmmx/wend/tree/archive/logo-snake-w-research)
(commit `4a40bcf`).

Labels: **[Fact]**, **[Measured]**, **[Interpretation]**, **[Decision]**.

---

## What shipped

**[Fact]** The logo is a Three.js scene of two snakes, one blue and one yellow, twisted into a W.
It is built to match one reference image (`snakes/ref/reference.png`) at the reference's own
orthographic camera, one world unit per reference pixel. `snakes/index.html` loads the final files
and builds in about 3–5 s:

| file | what |
|---|---|
| `w-final.params.json` | the parametric model: the camera, the swept-profile head fields, the quintic Hermite necks, the tube options |
| `w-final.spec.json` | the body: per strand, a clamped cubic B-spline centreline in 3D and a radius spline, over a shared station |
| `w-final.extra.json` | both valleys' overlay: the tube cut out over each valley, its mesh moved onto fitted implicit cushions |
| `w-final.look.json` | the look: lighting, clear-coat material, per-strand tone curves, the floor shadow |
| `heads-w-final.json` | the head meshes baked for this body, keyed by a hash of what they depend on |

**[Measured]** The trimmed tree renders the approved final pixel-identically: 0 of 1,572,528 px
differ from the image approved on 2026-10-20. Re-baking the heads from the trimmed tools
reproduces `heads-w-final.json` byte for byte.

## How it got there

`final/progress.mp4` shows the 38 milestones, each re-rendered through the current renderer at
the reference camera. **[Measured]** The score is the mean IoU of the blue and yellow regions
against the reference's:

| phase | milestones | colour overlap |
|---|---|---|
| Parametric body: centreline + twist angle, stacked local corrections (offsets, swell, beads, fold pinch, contact press) | 1–14 | 0.712 → 0.767 |
| C2 spline body, then JAX region fits of the right valley | 15–16 | 0.759 → 0.782 |
| Audit loop: an 18-feature anatomy registry, an evaluator, blind critics | 17 | 0.794 |
| Autonomous loop: rank, attribute, fit lobe handles, real render, blind judge, accept | 18–31 | 0.799 → 0.866 |
| Six blind-judged looks (lighting, material, colour) | 32–37 | 0.865 → 0.871 (peak 0.873) |
| r38-edge: right-arm contact-edge fit, promoted by owner override | 38 | 0.872 |

**[Fact]** Across 38 rounds the loop accepted 15 incumbents.
- Most were single-lobe handle fits: CMA-ES on flat renders, guarded by every other feature.
- The rest:
  - two cushion overlays, one per valley: implicit lobes ray-cast in JAX, then meshed;
  - one owner override.

## What worked

- **One smooth representation.** **[Interpretation]** The stacked local corrections of the parametric body caused the creases. Swapping them for one C2 spline per strand was the change that made every later fit well-posed.
  - **[Measured]** A C2 spline for the spine offsets alone cut visible creases over 2° from 346 to 106.
- **A differentiable surrogate, checked against the real renderer.** **[Measured]** The JAX soft raster had occlusion and no colour bleed (`sharp` 20). It predicted the Three.js render's change in agreement to within 0.002, and its gradients matched finite differences to 1e-8.
- **Constraints over freedom.** **[Fact]** The unconstrained right-valley fit moved control points by up to 290 px and grew a new loop. What fixed the dimple was the constrained fit:
  - a trust region;
  - self-collision terms;
  - an explicit depth order for the two hairpin legs (e2b): **[Measured]** self-penetration in the window fell from 12,276 px² to 0.
- **Real renders and blind judges.** **[Interpretation]** Accepting a candidate on metrics alone repeatedly let through creases and notches that only shading shows. Every accepted change was judged on real renders, with clay and zebra views, by a blind pair judge.
- **Implicit cushions where tube handles fail.** **[Fact]** L13's dimple resisted eight handle attempts. A hybrid overlay removed it, moving the tube's vertices along the cushions' field gradient.
- **Measuring corresponding edges.** **[Measured]** Pairing each blue/yellow contact boundary with the reference's and comparing the whole curve was reliable. Each boundary had a noise floor from two renders of one geometry. It disproved a highlight-based pitch diagnosis: edge directions matched within 2–7°.

## What did not

- **Masks miss shading-only defects.** **[Measured]** The advisory geometry diagnosis flagged 10 of 42 recorded defects in absolute terms. Two shading-only failures, the fused yellow T and the L05 double sphere, were not flagged at all.
- **Rigid moves of the collar and scarf failed.** **[Fact]** Lowering the blue scarf as a rigid block always exposed a step in the yellow neck.
- **Edge length did not respond to the parameters tried.** **[Measured]** r38 halved the right-arm boundaries' direction and curvature errors. The boundaries stayed 23–28% too long, so the remaining lever is the contact press or the pitch.
- **Cost.** **[Interpretation]** The loop was thorough but slow: about a day of rounds for a 0.08 gain in overlap from the audit loop's start. The owner's eye stayed the deciding signal throughout.

## Known residuals at the freeze

**[Fact]** Recorded with the r38-edge override, against r28-hybR:
- H2 IoU 0.944 → 0.925;
- L16 outline p95 7.9 → 8.5 px;
- small zebra notches on L14 and L15;
- the L14|L15 boundary 28% too long;
- L16|H2 10.3 px off.

The gains were L15 IoU 0.853 → 0.885 and an even tube radius along the right arm.

## Decisions

**[Decision]** The official logo is the original image-generated artwork (`assets/logo.png`),
which the README shows. The reconstruction is an experiment under `experiments/snake-w/`, kept for
future development; the research archive keeps its historical paths under `logo/snake-w/`.
**[Decision]** The geometry and look are frozen at r38-edge with look 6.
**[Decision]** Only the production page, its final files, the bake and render tools, the final
still, the progress video and a static milestone sheet ship. The research machinery is archived,
not shipped: about 100 tools, the loop's state and the judgements. Its scripts need archived inputs
to run.
