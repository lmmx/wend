# The reconstruction audit loop

The reconstruction is judged against the reference, feature by feature, on real Three.js renders. A candidate is accepted only when the measurements and an independent blind judge agree that it is closer, and no feature regresses.

## The reference's anatomy (fixed)

`tools/anatomy.py` defines the anatomy on the reference only, never on a reconstruction.
- **Features:** 18 numbered regions, from the yellow head along the W to the blue head: H1, L01–L16, H2.
- **Negative spaces:** N1–N6, the background regions inside the W's hull.

It writes:
- `registry.json`: per feature its colour, bbox, centroid, area and neighbours.
- `registry-labels.png` and `registry-negatives.png`.
- `reference-annotated.png`: each feature in its own colour, outlined and labelled.

Two yellow regions of the reference each hold two touching lobes, L04/L06 and L12/L14. A seeded watershed splits them along their crease.

## One iteration

1. **Render** a candidate through the real scene: `tools/audit_render.py TAG spec.json|- OUTDIR`.
   - Colour, clay and zebra for the whole frame, and for every feature's window, each window with its own camera.
   - The mesh check's visible fold points.
2. **Measure** it: `tools/evaluate.py colour.png --clay clay.png --folds mesh.json --out metrics.json`.
   - **Candidate lobes** are split by the rule that reproduces the reference registry (all 18 features at IoU ≥ 0.97).
   - **Per feature:** IoU, centroid offset, area ratio, extremal offsets, boundary distance, signed error per side, colour coverage, merges, segmentation-validity flags, clay crease, visible fold area, and a metric severity 0–5.
   - **Global:** silhouette and per-colour IoU, boundary distance, negative-space intrusion.
3. **Judge blind** with a fresh subagent that sees only images, anonymised:
   - `tools/critic_pages.py` (absolute: reference | candidate colour | clay | zebra | outline overlay);
   - `tools/pair_pages.py` (paired: reference | X | Y, in random order).
   - The judge is never told what was changed, what the optimiser reports, or which candidate is meant to be better.
4. **Rank and gate:** `tools/ledger.py ITERDIR --rank TAG --against BEST`. Per feature it combines the metric severity with the critic's severity, then applies the regression gates.
5. **Fit** the top-ranked features: `tools/regionfit.py` with
   - `--w-feat` and `--targets` (per-feature soft Dice, every lobe in view protected);
   - `--order` (feature-scoped depth order);
   - the self-collision, fold, fairness and trust-region terms.

   `tools/who.py` maps each reference feature to the strand stations that render it, so the targets reach the right control points.
6. Re-render, re-measure **all** features, and re-judge (paired, blind, against the accepted best). Accept or reject.

`LEDGER.md` records every candidate: targets, measurements, judgement, regressions and verdict. The accepted best is never overwritten by a rejected candidate.
