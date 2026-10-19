verdict: REJECT
mapping: X = r15-L06 (incumbent), Y = r18-L05 (candidate)
judge: one blind Sonnet (xhigh) agent, pair-r18-L05/ only

Closer: Y (the candidate) at L05 by 2 ("X: the blue lobe is a wide, boxy rounded rectangle. Its right edge bulges about 7% of the crop width past the reference, and its bottom sits too high, with a white gap under it ... Y: the lobe is a tilted, teardrop-like cushion whose left edge slants and whose bottom-right curves diagonally, close to the reference's right edge and bottom depth") and at L04 by 1 (the blue bulb rounder and lower, as in the reference); X (the incumbent) at L06 by 1 ("Y has a sharper dark crease along the lower edge of the yellow lobe in clay"). Every other feature: same.
Severities X / Y: H1 1/1, L01 1/1, L02 1/1, L03 1/1, L04 2/2, L05 3/2, L06 2/3, L07 1/1, L08 1/1, L09 1/1, L10 1/1, L11 1/1, L12 1/1, L13 2/2, L14 2/2, L15 1/1, L16 1/1, H2 1/1.
Defects: Y only, "a small torn or notched seam in the zebra at the top-left of the L05 blue lobe, where it emerges from under the yellow lobe" and the sharper crease under L06.
Rule: closer at its target by 2, but with defects of its own -> REJECT. Real renders: L05 IoU 0.708 -> 0.918, worst arc +17 -> -3 px (L05 has been the lowest-IoU lobe since lvt60); metric severity L05 2 -> 0, L04 2 -> 1.
Seed: the judge found it two steps closer and named a small defect, so round 19 re-fits L05 from this handle (merge --seed L05): a repair fit, sigma 0.4, guards' crease tolerance 1.15 instead of 1.4.
