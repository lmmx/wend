# Iteration ledger

Each iteration: measure every registry feature on real renders (tools/evaluate.py), blind-judge
(critics see only images, anonymised), rank, fit the top targets (tools/regionfit.py), render,
re-measure everything, re-judge (paired, blind), accept or reject (tools/ledger.py gates).
The accepted best is never overwritten by a rejected candidate.

| iter | candidate | targets | measured | blind judgement | regressions | verdict | next |
|---|---|---|---|---|---|---|---|
| 0 | base (committed old body) | - | sev 5: L04; sev 4: L05, L13 | critic C: L05/L04 over-under wrong (yellow in front at the left foot), L13 squat and dimpled, junction tucks too light | - | reference point | - |
| 0 | e3 (rv region fit, leg order + refine) | right-valley dimple | L14 IoU 0.76 -> 0.41 (sev 3 -> 5) | critic A: L13 balloons over L14's lower third (over-under reversed); arms read as a rope | L14 | REJECT | - |
| 0 | e2b (leg order) | right-valley dimple | L14 IoU 0.76 -> 0.40 (e3: 0.41) | critic B: L13 notched kidney in front of neighbours, L14 40% rendered blue | L14 | REJECT | - |
| 0 | e1 (rv region fit, elliptical sections) | right-valley dimple | gates vs base pass; L13 0.54 -> 0.66, L12 0.59 -> 0.73, L06 0.77 -> 0.82 | critic D (absolute) + paired judge: e1 closer (L09-L14, H2), no defect unique to e1 | none | ACCEPT (best) | L04, L05 (combined 9, 8), then L13, L14 |
| 1 | i1a (left valley, centreline + sections, per-feature term) | L04, L05 | L05 0.56 -> 0.60 (sev 4 -> 3), L04 sev 5 -> 4 (IoU 0.69 -> 0.67), L06 0.82 -> 0.79 | paired judge: a trade (L05 +1, L06 -1), e1 marginally closer | L06 (within gates) | REJECT (no net gain) | - |
| 1 | i1b (as i1a, radius free) | L04, L05 | L03 0.79 -> 0.84, L05 0.57, L06 0.80; global IoU +0.007 | paired judge: e1 closer at L04-L06 (by 1-2) | - | REJECT (judge disagrees with the metrics) | - |
| 1 | i1c (as i1a + blue in front of yellow inside L05) | L05 over-under | L04 0.69 -> 0.59, L05 0.56 -> 0.52 | - | L04 (gate) | REJECT | twist phase: L04/L05 are side by side in the reference, front/back in e1 |
| 1 | i1t45 (left valley twisted +45 deg over stations 390-570, then refit) | L04, L05 | L04 0.69 -> 0.76 (sev 5 -> 3), L05 0.56 -> 0.63, but L06 0.82 -> 0.63 (sev 2 -> 4), L07 0.84 -> 0.80 | - | L06 (gate) | REJECT | the window also turned L06: narrow it |
| 1 | i1t90 (+90 deg, same window, refit) | L04, L05 | L05 0.62, L06 0.56 | - | L06 (gate) | REJECT | - |
| 2 | c1 / c2 / c3 (parametric body: helix radius vs tube radius 40/40, 39/41 + bead 0.45, 42/38 + bead 0.35) | G1 proportions | c1: L02 0.85 -> 0.89, L08 0.86 -> 0.89, L09 0.84 -> 0.87, L10 0.79 -> 0.82, L11 0.71 -> 0.74, H1 0.93 -> 0.96, L16 0.81 -> 0.78; valleys unchanged. c2: worse (blue IoU 0.788 -> 0.769). c3: mixed | - | - | metric screen only (not on the spline body) | carry c1's proportions to the spline body |
| 2 | rv30 (right valley twisted -30 deg over 1040-1170, then refit with L13 targeted) | L13, L14 | L12 0.73 -> 0.36, L14 0.77 -> 0.36, clay crease 1.0 -> 9.4 | - | L12, L14 (gates) | REJECT | L13's error is shape (too broad), not phase |
| 2 | lvt60 (left valley twisted +60 deg over stations 420-500, no refit; chosen by a raster screen of 16 windows x angles) | L04, L05 | L05 0.56 -> 0.71 (sev 4 -> 2); L04 / L06 flagged merged + unstable (segmentation uncertain; reference masks 89-96% their colour) | paired judge: X (lvt60) closer at L05 by 1, all else same (untouched features: no noise) | none confirmed | **ACCEPT (best)** | L13 shape; L04/L06 fused yellow; G1 |
