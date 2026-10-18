# Discrepancy ledger: iter00

Severity 0 (matches the reference) to 5 (wrong). m = evaluator (tools/evaluate.py, real renders), c = blind critic (images only, anonymised). Combined = m + c.

| ID | base m / c | e2b m / c | e3 m / c | e1 m / c | e1 combined | e1 IoU | critic: discrepancy | critic: correction |
|---|---|---|---|---|---|---|---|---|
| H1 | 1 / 2 | 1 / 1 | 1 / 2 | 1 / 2 | 3 | 0.94 | Throat/neck underside too full and low, so neck reads thicker; clay shows eye as a stuck-on ball with no socket blending. | Raise/tuck jaw–throat line; round crown; slightly shrink eye and add a clear white highlight; blend eye into a socket; add faint mouth line. |
| L01 | 3 / 4 | 3 / 2 | 3 / 3 | 3 / 2 | 5 | 0.80 | Lacks the strong down-left diagonal belly; looks like a collar hugging the neck rather than a separate fat lobe. | Increase diagonal sweep and lower-left belly girth; pull upper-right end down ~10 px. |
| L02 | 2 / 2 | 2 / 1 | 2 / 2 | 2 / 2 | 4 | 0.85 | Lobe thin/rope-like and shifted slightly right; blue neighbours look relatively too big. | Fatten lobe, especially lower-left bulge; shift centre left ~10 px, add more diagonal tilt. |
| L03 | 2 / 3 | 2 / 2 | 2 / 3 | 2 / 3 | 5 | 0.79 | Over/under order wrong at bottom; lobe too short; lower-left belly missing; yellow above-left also overextended. | Lower and extend the blue lobe; move L04's top down/right so it no longer overlaps L03 tail. |
| L04 | 5 / 4 | 5 / 4 | 5 / 3 | 5 / 4 | 9 | 0.69 | Creases/abrupt cuts; clay shows concave step, zebra stripes break at the right edge; does not read as a round balloon. | Widen yellow lobe rightward to fill cyan; remove slit and vertical blue wedge; make blue recede smoothly behind yellow. |
| L05 | 4 / 5 | 4 / 5 | 4 / 4 | 4 / 4 | 8 | 0.56 | Wrong shape (not round, does not touch floor); over/under wrong — yellow in front where blue should be. | Extend blue downward to floor; round lower-left corner and bottom edge into a belly; place yellow behind/beside it. |
| L06 | 3 / 4 | 2 / 3 | 2 / 3 | 2 / 3 | 5 | 0.82 | Clay shows a sharp crease and zebra stripes pinch at the blue/yellow junction; more angular and less inflated. | Round the lower-right of the lobe; soften the blue overlap edge; pull the yellow's left spread back so it separates from L04. |
| L07 | 1 / 3 | 1 / 3 | 1 / 3 | 1 / 3 | 4 | 0.84 | Thin/rope-like, lacks a defined round end; the lower yellow neighbour appears too prominent. | Shorten along axis, thicken, round both ends into an ellipse. |
| L08 | 1 / 3 | 1 / 2 | 1 / 2 | 1 / 3 | 4 | 0.85 | Angular silhouette, not round; clay shows a crease, zebra stripes bunch at the right junction. | Round the top and right tip; reduce right overextension; soften the junction with blue. |
| L09 | 2 / 3 | 2 / 2 | 2 / 2 | 2 / 2 | 4 | 0.84 | Lower tail missing (~40 px short); zebra stripes slightly bunch at the right fold. | Extend blue downward and let it taper to a point; round the left boundary. |
| L10 | 2 / 3 | 2 / 2 | 2 / 2 | 2 / 2 | 4 | 0.77 | Slight offset and over-width at the top; the lower pointed end is shorter. | Narrow the top and shift left ~10 px; lengthen the lower taper. |
| L11 | 3 / 3 | 2 / 1 | 2 / 2 | 3 / 1 | 4 | 0.73 | Minor. | Slightly fatten the upper end. |
| L12 | 3 / 4 | 3 / 2 | 2 / 2 | 3 / 2 | 5 | 0.73 | Small pinch at the valley bottom and a harder bottom edge. | Round the bottom edge; remove the pinch where the two lobes meet. |
| L13 | 4 / 5 | 4 / 5 | 4 / 4 | 3 / 4 | 7 | 0.66 | Clear surface defect (pinch/dimple) and wrong silhouette; the top lacks the upward taper. | Fill the dimple; make the top a smooth narrow taper; trim the right overextension ~35 px; round the belly. |
| L14 | 3 / 3 | 5 / 4 | 5 / 4 | 3 / 3 | 6 | 0.77 | Lower end blunt and too long; crease visible in clay. | Taper the lower tip; pull back ~30 px; fix the L13 pinch below it. |
| L15 | 2 / 3 | 2 / 2 | 2 / 3 | 2 / 3 | 5 | 0.83 | Thin/long instead of a plump oval. | Widen ~20% and shorten; shift down-right ~10–15 px. |
| L16 | 2 / 3 | 2 / 2 | 2 / 3 | 2 / 2 | 4 | 0.81 | Slimmer, S-like, slightly off axis. | Widen; tilt more diagonally; pull the lower-right end back ~20 px. |
| H2 | 1 / 2 | 1 / 1 | 1 / 1 | 1 / 2 | 3 | 0.94 | Neck/chin curve off ~10 px; clay shows the eye as a stuck-on ball. | Thin the neck slightly; deepen the chin concavity; enlarge the head a little; add a white eye highlight. |

## Ranking for e1 (largest first)

1. **L04** combined 9, IoU 0.69: Creases/abrupt cuts; clay shows concave step, zebra stripes break at the right edge; does not read as a round balloon.
2. **L05** combined 8, IoU 0.56: Wrong shape (not round, does not touch floor); over/under wrong — yellow in front where blue should be.
3. **L13** combined 7, IoU 0.66: Clear surface defect (pinch/dimple) and wrong silhouette; the top lacks the upward taper.
4. **L14** combined 6, IoU 0.77: Lower end blunt and too long; crease visible in clay.
5. **L15** combined 5, IoU 0.83: Thin/long instead of a plump oval.
6. **L06** combined 5, IoU 0.82: Clay shows a sharp crease and zebra stripes pinch at the blue/yellow junction; more angular and less inflated.
7. **L01** combined 5, IoU 0.80: Lacks the strong down-left diagonal belly; looks like a collar hugging the neck rather than a separate fat lobe.
8. **L03** combined 5, IoU 0.79: Over/under order wrong at bottom; lobe too short; lower-left belly missing; yellow above-left also overextended.
9. **L12** combined 5, IoU 0.73: Small pinch at the valley bottom and a harder bottom edge.
10. **L02** combined 4, IoU 0.85: Lobe thin/rope-like and shifted slightly right; blue neighbours look relatively too big.
11. **L08** combined 4, IoU 0.85: Angular silhouette, not round; clay shows a crease, zebra stripes bunch at the right junction.
12. **L09** combined 4, IoU 0.84: Lower tail missing (~40 px short); zebra stripes slightly bunch at the right fold.
13. **L07** combined 4, IoU 0.84: Thin/rope-like, lacks a defined round end; the lower yellow neighbour appears too prominent.
14. **L16** combined 4, IoU 0.81: Slimmer, S-like, slightly off axis.
15. **L10** combined 4, IoU 0.77: Slight offset and over-width at the top; the lower pointed end is shorter.
16. **L11** combined 4, IoU 0.73: Minor.
17. **H2** combined 3, IoU 0.94: Neck/chin curve off ~10 px; clay shows the eye as a stuck-on ball.
18. **H1** combined 3, IoU 0.94: Throat/neck underside too full and low, so neck reads thicker; clay shows eye as a stuck-on ball with no socket blending.

base: silhouette IoU 0.938, boundary p95 11.4 px, blue IoU 0.788, yellow IoU 0.790

e2b: silhouette IoU 0.941, boundary p95 11.2 px, blue IoU 0.793, yellow IoU 0.795

e3: silhouette IoU 0.942, boundary p95 11.2 px, blue IoU 0.797, yellow IoU 0.798

e1: silhouette IoU 0.941, boundary p95 11.2 px, blue IoU 0.803, yellow IoU 0.806

## Regression gates: e1 against base

**Regressions (gate failures):** none

**Improvements:**
- L01: metric severity 3 -> 3, IoU 0.81 -> 0.80, critic 4 -> 2
- L05: metric severity 4 -> 4, IoU 0.56 -> 0.56, critic 5 -> 4
- L06: metric severity 3 -> 2, IoU 0.77 -> 0.82, critic 4 -> 3
- L09: metric severity 2 -> 2, IoU 0.84 -> 0.84, critic 3 -> 2
- L10: metric severity 2 -> 2, IoU 0.79 -> 0.77, critic 3 -> 2
- L11: metric severity 3 -> 3, IoU 0.71 -> 0.73, critic 3 -> 1
- L12: metric severity 3 -> 3, IoU 0.59 -> 0.73, critic 4 -> 2
- L13: metric severity 4 -> 3, IoU 0.54 -> 0.66, critic 5 -> 4
- L16: metric severity 2 -> 2, IoU 0.81 -> 0.81, critic 3 -> 2

**Verdict:** ACCEPT (if the critic page review agrees)

## Consensus of the four independent critics (A: e3, B: e2b, C: base, D: e1)

1. **L05** (all four, ranked 1st or 2nd): the left valley's bottom blue lobe is a hard-edged cap or wedge, stops short of the floor, and yellow L04 passes in front of its lower part: wrong over-under.
2. **L13 / L14** (A, B, C, D): L13 too broad (~35-40%), dimpled or creased, and in front of L14's lower left where the reference has L14 in front.
3. **L04 / L06** (all four): the left valley's two yellow lobes fused into one bent tube with a V crease; L04 too wide to the right.
4. **G1, whole-body character** (A, C, D): reads as a twisted rope rather than stacked convex cushions: arm lobes 15-20 deg too steep and elongated with pointed ends, saddle-shaped (S-swirl zebra) surfaces on L01-L03, L10-L11, L15-L16; the dark rolled crevices between lobes are ~20x lighter (C: ~36 near-black px vs ~750).
5. **L01 / L16** (A, B, C): the opposite-colour collar on each neck climbs 7-12 px too high.
