# Iteration ledger

Each iteration: measure every registry feature on real renders (tools/evaluate.py), blind-judge
(critics see only images, anonymised), rank, fit the top targets (tools/regionfit.py), render,
re-measure everything, re-judge (paired, blind), accept or reject (tools/ledger.py gates).
The accepted best is never overwritten by a rejected candidate.

| iter | candidate | targets | measured | blind judgement | regressions | verdict | next |
|---|---|---|---|---|---|---|---|
| 0 | base (committed old body) | - | sev 5: L04; sev 4: L05, L13 | critic C: L05/L04 over-under wrong (yellow in front at the left foot), L13 squat and dimpled, junction tucks too light | - | reference point | - |
| 0 | e3 (rv region fit, leg order + refine) | right-valley dimple | L14 IoU 0.76 -> 0.41 (sev 3 -> 5) | critic A: (pending) | L14 | REJECT | - |
| 0 | e2b (leg order) | right-valley dimple | L14 IoU 0.76 -> 0.40 | critic B: L13 notched kidney in front of neighbours, L14 40% rendered blue | L14 | REJECT | - |
| 0 | e1 (rv region fit, elliptical sections) | right-valley dimple | gates vs base pass; L13 0.54 -> 0.66, L12 0.59 -> 0.73, L06 0.77 -> 0.82 | critic D (absolute) + paired judge: e1 closer (L09-L14, H2), no defect unique to e1 | none | ACCEPT (best) | L04, L05 (combined 9, 8), then L13, L14 |
| 1 | i1a (left valley, centreline + sections, per-feature term) | L04, L05 | L05 0.56 -> 0.60 (sev 4 -> 3), L04 sev 5 -> 4 (IoU 0.69 -> 0.67), L06 0.82 -> 0.79 | paired judge: a trade (L05 +1, L06 -1), e1 marginally closer | L06 (within gates) | REJECT (no net gain) | - |
| 1 | i1b (as i1a, radius free) | L04, L05 | L03 0.79 -> 0.84, L05 0.57, L06 0.80; global IoU +0.007 | paired judge: e1 closer at L04-L06 (by 1-2) | - | REJECT (judge disagrees with the metrics) | - |
| 1 | i1c (as i1a + blue in front of yellow inside L05) | L05 over-under | L04 0.69 -> 0.59, L05 0.56 -> 0.52 | - | L04 (gate) | REJECT | twist phase: L04/L05 are side by side in the reference, front/back in e1 |
