# Snake-W logo: the autonomous correction loop (PR #86)

## Current State

- `logo/snake-w/snakes/ffd-flat.html` renders the spline body's real geometry (`strandsFromSpec`, the neck slicing, the press, `strandSurface`) together with baked heads, in flat colours, in about 0.3 s a build.
  - `?params=` and `?heads=` choose the params file and head bake (default `w-final.params.json`, `heads-final.json`).
  - `__ids` writes a surface-point buffer: for each pixel, the strand, its own station and its section angle.
  - `__run` reports the local fold area, the press depth, a ring second-difference kink measure and the floor height inside a box.
- `logo/snake-w/tools/ffd_worker.mjs` drives `ffd-flat.html` from one persistent Chromium, one JSON request per line.
  - A request takes an inline spec (`spec_obj`) or a file.
  - With `ids`, it writes the surface-point buffer as raw RGBA bytes.
  - `FFD_PARAMS` and `FFD_HEADS` in its environment choose the params file and head bake.
- `logo/snake-w/tools/lobekit.py` `attribute()` maps a registry lobe to the run of its strand's own stations that draws the candidate's matching lobe, from the surface-point buffer.
- `logo/snake-w/tools/lobekit.py` `apply()` acts on one station run of a strand with eleven lobe-handle controls:
  - screen translation, depth, rotation about the view axis, and stretch along the lobe's axis, applied to the centreline control points with a smooth bump weight;
  - radius and section width, applied to the radius and section spline controls;
  - side bulges and end rounding, as `geometry.js` `dispField` displacement handles.
- `logo/snake-w/tools/discrepancy.py` ranks the sixteen lobes of a real render. The score is 10 (1 − IoU) + p95 / 8 + |worst 40 px contour arc| / 4 + 3 × the visual severity.
  - From round 12, the contour arc is measured along both outlines (`lobekit.arcs2`).
    - Measured along the reference outline only, a thin tip poking past the reference's edge read as a few px: the blue collar L01's top end rode 18 px above the reference's, and this measure missed it.
    - Along the candidate's own outline the same tip reads +15 px.
    - The same blind spot hid tip overshoots on L05, L06, L15 and L16.
  - From round 12, the visual severity is the larger of the blind judges' (`auto/sev.json`) and the owner's (`auto/owner.json`).
    - The owner's entry for L01 ("that scarf still isnt right", severity 3) put the collar at the top of the ranking. The judges had rated it 1.
    - Each accepted correction of the feature takes one step off the owner's severity.
- `logo/snake-w/tools/lobefit.py` fits one ranked lobe's handle by CMA-ES on flat renders.
  - The target cost is IoU, boundary distances, the worst contour arc, the centroid offset, elongation, solidity and tilt.
    - From round 12, tilt is weighted by the reference lobe's elongation.
    - From round 13 the cost adds the waist (`lobekit.waist`): how much more the lobe's width profile along its axis dips than the reference's.
  - The guards cover every other feature in the crop, the silhouette, the negative spaces, the fold area, the clay crease, the press depth, sharp corners on the colour boundaries, and the floor line.
    - From round 13 they also cover the waist.
- `logo/snake-w/tools/autoround.py propose` runs one round without the judge.
  - It takes up to three ranked targets that are not each other's neighbours.
  - It fits each with `lobefit.py`, renders each through the real scene (`audit_render.py`), measures each (`evaluate.py`), applies the gates, and writes a delta sheet and blind pair pages with an enlarged focus page.
  - A target whose crop holds a head with a variant (`HEAD_VARIANTS`) gets a second candidate fitted and rendered with that head.
- `logo/snake-w/tools/autoround.py merge` composes the judge-accepted handles onto the incumbent.
  - `logo/snake-w/auto/state.json` holds the incumbent (spec, params, head bake, look).
  - `logo/snake-w/auto/LEDGER.md` holds every round's ranking, targets, handles, numbers and verdicts.
- `logo/snake-w/LOOP.md` holds the loop's instructions; a scheduled `/loop` runs it unattended. `logo/snake-w/auto/JUDGE_PROMPT.md` holds the blind pair judge's prompt.
- `logo/snake-w/snakes/w-meshshadow.look.json` places the contact shadows from the mesh (`shadowCard.fromMesh`) instead of from the AO balls. The balls' placement left a pale crescent under L13. The incumbent renders with it from round 10.
- Rounds 1–13 accepted eleven corrections, all on targets the ranking chose:
  - r1-L13, r2-L01, r4-L04, r4-L12, r4-L08, r5-L02, r6-L03, r7-L10, r7-L16, r12-L06, r13-L01.
  - Rounds 3 and 8–11 accepted nothing.
- The incumbent is `auto/r13/spec-r13-L01.json`. Against `lvt60` on real renders:
  - L04 IoU 0.66 → 0.86, L06 0.65 → 0.84, L11 0.73 → 0.90, L12 0.74 → 0.88, L10 0.78 → 0.90, L08 0.85 → 0.92, L13 0.66 → 0.72, L16 0.81 → 0.86.
- The blind judges' rejections each name a defect:
  - a zebra notch from round 1's narrow end rounding;
  - an exposed step in the yellow neck below a lowered collar;
  - lobes widened into a neighbour;
  - thinned, pinched or creased lobes (r12-L01, r13-L11);
  - a lengthened crease on L13 (r11, r12);
  - a pale sliver under L13, which was the shadow placement;
  - zebra blips.
- `logo/snake-w/snakes/w-neck1.params.json` (a C² cubic neck blend and a nape round-cone on the yellow head; bake `snakes/heads-neck1.json`) removes the neck step that a lowered collar uncovers. It was a head variant in rounds 12–13. Both times its judges found the collar closer, and the second judge named a dark zebra blob under the yellow jaw, which is neck1's head. The variant is off from round 14.
- Round 13's collar candidate moved the top end 2 px lower (worst arc +15 → +12 px, tilt 6.4 → 5.7°) with a smoother clay crease. The judge found it one step closer, plumper at the top right.

## Missing

- The collar L01 still rides high: its top end overshoots the reference by 12 px, and it stands about 6° too upright. Its right shoulder is 9–11 px short of the reference's round shoulder.
  - The lobe handle moves the whole run, so lowering the top end also lowers the bottom end, which already overshoots by 7 px. The tip is drawn by stations just past the run's end.
  - End translations (version 3 handles: `ea_x`, `ea_y`, `eb_x`, `eb_y`, a bump centred on either end) are staged for round 15.
  - Moving end b down alone makes the right shoulder fall short instead (flat probe: worst arc +13 → −12 px). The fit has to pair it with the shoulder's bulge.
- The L13 and L14 dimples remain after six attempts at L13. Each candidate either kept the crease or lengthened it.
- L05 measures IoU 0.71, the lowest of the lobes. Its two attempts were rejected.
- neck1's head has a zebra blob under the jaw. Until that is fixed, a lowered collar uncovers the incumbent head's neck step.
