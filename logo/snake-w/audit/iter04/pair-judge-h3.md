# Paired blind judge: h3 (bead prototype, 1 px voxels, field normals, overlap 3) vs lvt60 (X = lvt60, Y = h3; pair-mapping.json, not shown to the judge)

Model: Sonnet (xhigh). Inputs: only pair-h3/.

| ID | closer | by | sev X | sev Y | note |
|---|---|---|---|---|---|
| H1, L01 | same | 0 | 1 | 1 | |
| L02 | X | 1 | 1 | 2 | Y: a stepped notch at the right edge, torn zebra patch |
| L03 | X | 2 | 1 | 3 | Y: a thin dark vertical seam at the top of the yellow, stepped clay ridge |
| L04 | X | 2 | 2 | 3 | Y: notch + seam at the top, faceted clay, a white speck at the base. X: a soft fold between two yellow bulges (the reference: one plump lobe) |
| L05 | X | 2 | 1 | 2 | Y: a vertical crease down the left side, broken zebra |
| L06 | X | 2 | 2 | 4 | Y: a jagged notch at the left, a squared, pinched right end, chaotic zebra (the worst single defect). Both more band-like than the reference's round bulb |
| L07 | X | 1 | 1 | 2 | Y: a small notch at the lower-left edge |
| L08-H2 | same | 0 | | | untouched: all "same" (L13 / L14: the same pinch in both, sev 2) |

Whole frame: X (lvt60) closer; every difference is in L02-L07, where Y has seams, notches and faceting, all Y-only.
**Verdict: REJECT h3.** The bounded correction (1 px voxels, field-gradient normals, overlap) removed most of the faceting
that sank h2, but the junctions with the swept tube (L02/L03, L07: the cut ends) and the blend creases between the
ellipsoids (L05 left, L06 left) still read as seams. The metric gain at L05 (0.71 -> 0.81) does not survive the
judgement. Note the judge rates lvt60's L04 / L06 at severity 2 (a soft fold, band-like), where the metric gives 5
(driven by the merged / unstable segmentation flags): the metric overstates them.
