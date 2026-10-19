verdict: REJECT (no difference)
mapping: X = r28-hybR (incumbent), Y = r31-hybR3 (candidate: r28's hybrid with the rim moved only over L13's base and right shoulder, rim 0.6, kept 25 px from L12: hybrid.py --rim-on L13 --rim-off L12)
judge: one blind Sonnet (xhigh) agent, pair-r31-hybR3/ only (focus: L13, L12, L14, L12|L13, L13|L14)

"X and Y are practically indistinguishable. I found no feature where I can honestly say one is closer": same at all 18, severities equal (L13 3/3, L12 2/2, L14 2/2). No defect in either that the other lacks.
Remaining (both): L13 broad and flat on top with an angular right shoulder where the reference is a teardrop with a narrow tip, a small crease in its upper middle; L12 fullest too high, its bottom 10-20 px (crop) high; L14's lower edge straight, its end less bulbous; L12|L13 a straight diagonal where the reference is an S; L13|L14 a short steep step.
Real renders: L13 IoU 0.777 -> 0.785 (severity 2 -> 1), L14 0.841 -> 0.849; the L12|L13 band unchanged (40 edge px differ on the flat render, against 473 with the rim moved everywhere).
The owner's last bounded experiment; the geometry freezes at r28-hybR.
