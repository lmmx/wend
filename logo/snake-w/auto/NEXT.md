# Next action (for the next loop invocation)

- r2 propose is running (background), from incumbent r1-L13. When it finishes: judge each gate-passing candidate (JUDGE_PROMPT.md; the pages now include page4-focus.png), write judge-*.md, update sev.json, merge, autoledger, autosync, commit, propose r3.
- A subagent is smoothing the yellow head mesh's hidden neck patch (exposed when the L01 collar is lowered) in scratchpad/logo-neck: deliverable snakes/heads-neck1.json (+ w-neck1.params.json if params changed) and neck-sheet.png. When it reports: if the visible head is unchanged and the patch is smooth, adopt the new heads in the loop workspace (copy heads-neck1.json over the flat renderer's heads and audit_render's heads file, re-render the incumbent, re-measure), then retry L01 (its rejected count was not raised).

## 2026-10-19 ~00:45 UTC
- Round 2 merged: L01 accepted as neutral (IoU 0.80 -> 0.84; the judge saw no difference and no defect); L04 and L12 rejected (judge: merged / thinner + creased). Incumbent r2-L01.
- Round 3 propose running (background).
- Neck subagent, second bounded attempt in scratchpad/logo-neck: a per-neck C2 blend (removes the zebra Z-kinks) + nape volume (fills the 6 px valley the lowered collar uncovers). Deliverable: geometry.js patch, snakes/w-neck1.params.json, renders, neck-sheet.png. If it succeeds: apply the patch and params in the loop workspace BETWEEN rounds (real renders re-mesh the heads from params: the baked heads never match a spline spec's hash), re-render the incumbent, re-measure, judge it against the incumbent, then let L01 be ranked again.
- Look experiment ao1 (contact AO 0.75, fall 20, k 0.14): a subtle crevice darkening, metrics unchanged; not judged. The reference's form shading has much more contrast (dark undersides): the judges' "less inflated" may be partly lighting. Candidate for a bounded look fit later.
- Finding: mask IoU gains of +0.1-0.2 on L04 / L12 were rejected by the judges (lobes widened into a neighbour, or thinned and creased). The judges call our lobes band-like where the reference has distinct cushions; the incumbent's lobes are mostly fatter in 2D than the reference (largest inscribed radius, e.g. L12 51 vs 39 px).

## ~01:10 UTC
- Round 3: L06, L13, L02 all rejected by the judges (a notch at the L06 crossing; a sharper L13 dimple + a pale sliver under it; zebra blips at L02). Incumbent unchanged (r2-L01).
- Fitter changed after r3 (rejection causes): shape terms in the target cost (elongation, tilt, solidity vs the reference lobe), a guard on sharp corners of the colour boundaries (lobekit.corners: 23 -> 30 and 38 -> 41 for the rejected L06 / L13), tighter handle bounds (radius / width within -10..+15%, rotation 20 deg, moves 25 px, end rounding 15%). The rejected-attempt counts were reset for this new fitter.
- Measured and not used as guards (they did not separate the rejected candidates): the ring second-difference kink (ffd-flat.html kink_max / kink_995) and the floor height (ground).

## ~01:20 UTC
- Neck subagent (second attempt): geometry.js gains an optional per-neck C2 cubic blend (`necks[i].blend = "cubic"`, `k`) and a nape round-cone (`necks[i].nape`); both off by default (a bake of w-final.params.json is byte-identical). snakes/w-neck1.params.json turns them on for the yellow neck: the zebra Z-kinks at the head-neck blend go, the yellow silhouette's valley fills (6 -> < 0.5 px). The visible notch where the lowered collar meets the neck stays: there the visible edge is the blue coil in front of the yellow neck (a depth-order edge), so it is the coil's outline, which the L01 handle (depth, and the new corner guard) can reach.
- The patch is applied in the loop workspace (snakes/geometry.js; the original is ffd/geometry.pre-neck1.js). Candidate nk1 = the incumbent r2-L01 rendered with w-neck1.params.json (auto/neck1/): metrics identical (H1 0.959, L01 0.843). Blind judge running (X = nk1, Y = r2-L01).
- Order: let r4 finish and merge against r2-L01 first. If nk1 is accepted, then set the new incumbent's params to w-neck1.params.json, re-render it (autoround render_and_measure with params), gate it against the pre-neck incumbent, and from then on rounds render with it (state.incumbent.params; autoround passes it to audit_render).

## ~03:00 UTC: the waist experiment (a composition move; tools/waists.py)
- The incumbent r7-merged with each strand's radius narrowed at the 14 hidden gaps between consecutive lobes (from the lobe-to-surface map), by 12 / 22 / 32% at the gap's centre (auto/waists/).
- Real renders: mean lobe IoU 0.852 -> 0.856 / 0.854 / 0.852, silhouette 0.950 -> 0.951 / 0.950 / 0.949, no lobe worse by 0.03; the colour, clay and zebra crops are visually indistinguishable from the incumbent (auto/waists/cmp.png). The pinched stations are behind the partner strand, so the visible lobes keep their shape.
- Not judged (no measured gain to accept, no visible change). Finding: the reference's distinct-cushion read comes from the visible lobes' own shape and shading, not from waists in the hidden stretches.
- Seen on the same sheet: the reference's bands on the arch legs (L10-L12) run flatter (closer to horizontal) and fatter than ours, which are more diagonal: a helix-pitch difference along the arch legs, a candidate for a composition move (tools/twist.py with --helix) if the per-lobe rounds stall there.

## ~03:20 UTC: the blue look (auto/look2/)
- Measured (per-lobe luminance inside the reference masks): the incumbent's blue lobes have a p95 of 180 against the reference's 131 (spread 126 vs 70); the yellow is close (p95 244 vs 235).
- Per-material envMapIntensity has no effect (the scene's environment and environmentIntensity override it): b1 / b2 are pixel-identical to the incumbent.
- c4 (the blue's clearcoat 0, specular 0.2 #4a74c8, roughness 0.5: p95 163): REJECTED by the judge, the blue flat and matte with no crisp highlight (the reference's highlight is small and sharp).
- d1 (a sharp clearcoat 0.35 / 0.06 over a rougher base): indistinguishable to the judge (7689 px changed).
- Finding: the material parameters move the blue little; the broad lit zone comes from the lighting (env key / fill / envLevel), which the earlier look work fitted. Not pursued further tonight.
r20 stopped 08:02 to switch to the look; resumable with propose r20
r21 stopped 08:20: score-driven targets (L16 again after three junction pinches); the loop now starts each round from a visual diagnosis
