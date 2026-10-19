verdict: REJECT
mapping: X = r28-hybR (incumbent), Y = r30-hybR2 (candidate: the right valley's hybrid from the refit cushions poc/right/fit2-final, alpha 1, along the field, xw 1, rim 0.6)
judge: one blind Sonnet (xhigh) agent, pair-r30-hybR2/ only (focus: L13, L12, L14, L12|L13, L13|L14)

Closer: X (the incumbent) at L12 by 1 ("Y's yellow lobe has a straight vertical right flank, and a sliver of blue to its right with a dead-straight left edge; the zebra stripes are cut off along that line") and L13 by 1 ("Y has a planar vertical cut on the left flank of the blue lobe ... Y's right shoulder is rounder, which is closer to the reference; X ... has a small crease or dent mid-lobe"). Every other feature: same.
Severities X / Y: L12 2/3, L13 3/4.
Y-only defect: "a planar vertical seam at L12|L13 ... in clay a hard vertical line, in zebra stripes sheared into flat horizontal bands with a discontinuity"; X-only: "a small crease or dent in the middle of blue L13 ... a slightly angular right-shoulder corner".
Remaining, in X: L13 broad at the top (the reference tapers to a narrow tip under L14), its bottom 15-20 px (crop) high, the right shoulder a corner, the mid-lobe crease; L12's lower right missing the swell over the blue; L12|L13 a straight diagonal where the reference is an S.
Real renders: L12 IoU 0.893 -> 0.896, L13 0.777 -> 0.782, L12 / L13 severity 1 / 2 -> 0 / 1; the flat check had L13's crease 1.57 -> 0.76.
Cause: with the rim moved (rim 0.6) and the cross-strand junction weighted (xw 1), both strands' rims land on their own cushions' surfaces, which cut each other along a plane at L12|L13.
