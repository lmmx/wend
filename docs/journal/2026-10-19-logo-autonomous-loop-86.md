# Snake-W logo: the autonomous correction loop (PR #86)

## Current State

- `logo/snake-w/snakes/ffd-flat.html` renders the spline body's real geometry (`strandsFromSpec`, the neck slicing, the press, `strandSurface`) together with the baked heads (`heads-final.json`), in flat colours, in about 0.3 s a build.
  - `__ids` writes a surface-point buffer: for each pixel, the strand, its own station and its section angle.
  - `__run` reports the local fold area, the press depth, a ring second-difference kink measure and the floor height inside a box.
- `logo/snake-w/tools/ffd_worker.mjs` drives `ffd-flat.html` from one persistent Chromium, one JSON request per line.
  - A request takes an inline spec (`spec_obj`) or a file.
  - With `ids`, it writes the surface-point buffer as raw RGBA bytes.
- `logo/snake-w/tools/lobekit.py` `attribute()` maps a registry lobe to the run of its strand's own stations that draws the candidate's matching lobe, from the surface-point buffer.
  - The incumbent `lvt60` maps every lobe L01–L16 to one run: L06 to yellow 504–583, L13 to blue 408–469 (`tools/lobemap.py`, `auto/lobemap-lvt60.png` in the workspace).
- `logo/snake-w/tools/lobekit.py` `apply()` acts on one station run of a strand with eleven lobe-handle controls:
  - screen translation, depth, rotation about the view axis, and stretch along the lobe's axis, applied to the centreline control points with a smooth bump weight;
  - radius and section width, applied to the radius and section spline controls;
  - side bulges and end rounding, as `geometry.js` `dispField` displacement handles.
- `logo/snake-w/snakes/geometry.js` `dispField` adds strand-local radial displacement to the swept surface from a spec strand's `disp` list. Without `disp`, renders are pixel-identical to the previous engine.
- `logo/snake-w/tools/discrepancy.py` ranks the sixteen lobes of a real render by a score:
  - 10 (1 − IoU) + p95 / 8 + |worst 40 px contour arc| / 4 + 1.5 × the blind judges' latest severity (`auto/sev.json`);
  - each row names the worst stretch of outline and its direction, for example "upper right edge overshoots by 15 px" for L01 of `lvt60`.
- `logo/snake-w/tools/lobefit.py` fits one ranked lobe's handle by CMA-ES on flat renders.
  - Target cost: IoU, boundary distances, the worst contour arc, the centroid offset, and since round 4 elongation, tilt and solidity against the reference lobe.
  - Guards: every other feature in the crop, the silhouette, the negative spaces, the fold area, the clay crease, the press depth, and since round 4 the count of sharp corners on the colour boundaries (`lobekit.corners`).
- `logo/snake-w/tools/autoround.py propose` runs one round without the judge:
  - takes up to three ranked targets that are not each other's neighbours;
  - fits each with `lobefit.py`;
  - renders each through the real scene (`audit_render.py`) and measures it (`evaluate.py`);
  - applies the gates;
  - writes a delta sheet and blind pair pages, including an enlarged focus page.
- `logo/snake-w/tools/autoround.py merge` composes the judge-accepted handles onto the incumbent. With more than one handle, it renders and gates the composite.
  - `logo/snake-w/auto/state.json` holds the incumbent.
  - `logo/snake-w/auto/LEDGER.md` holds every round's ranking, targets, handles, numbers and verdicts.
- `logo/snake-w/LOOP.md` holds the loop's instructions for a scheduled `/loop`, and `logo/snake-w/auto/JUDGE_PROMPT.md` holds the blind pair judge's prompt.
- Rounds 1–4 fitted twelve candidates on targets the ranking chose. All twelve passed the gates on real renders, and the blind judges accepted five:
  - r1-L13 (closer at L13 and L14);
  - r2-L01 (neutral);
  - r4-L04 (closer at L04 by 3);
  - r4-L12 (closer at L12 and L13);
  - r4-L08 (neutral).
- The incumbent after round 4, `auto/r4/spec-r4-merged.json`, measures against `lvt60` on real renders:
  - L04 IoU 0.66 → 0.85 (severity 5 → 2);
  - L06 0.65 → 0.82 (5 → 1);
  - L12 0.74 → 0.88;
  - L11 0.73 → 0.84;
  - L08 0.85 → 0.92;
  - L01 0.80 → 0.84;
  - L13 0.66 → 0.72.
- The blind judges rejected seven candidates. Each rejection names a defect:
  - a zebra notch from round 1's narrow end rounding;
  - an exposed notch in the baked yellow head's neck surface below the lowered L01 collar;
  - lobes widened into a neighbour;
  - thinned and creased lobes;
  - a kink at a crossing;
  - a pale sliver under L13;
  - zebra blips.
- `logo/snake-w/snakes/geometry.js` `headSurface2` takes an optional per-neck C² cubic blend (`necks[i].blend = "cubic"`, `necks[i].k`) and an optional nape round-cone (`necks[i].nape`). Both are off by default; a bake of `w-final.params.json` stays byte-identical. `logo/snake-w/snakes/w-neck1.params.json` turns both on for the yellow neck. That candidate (`auto/neck1/`) measured identically to the incumbent, and its blind judge preferred the incumbent's head by one low-confidence step.

## Missing

- The L06 lobe still reads as a band in every judge's report, where the reference has a round bulb.
- The L13 and L14 dimples remain in the incumbent.
- The L08 lobe ends in a pointed wedge, where the reference has a rounded cushion.
- The rendered crevices between lobes stay lighter than the reference's.
- The blue L01 collar's outline, where it passes in front of the yellow neck, has no handle that targets it apart from the L01 lobe handle.
