# Round r23: report

Previous accepted best r18-L12; new accepted best r18-L12.

## L15+L16: verdict: REJECT

Diagnosis: the right arm sits up-left: L15's upper-left end rides 25 px above the reference's (evaluator: top -25 px, worst arc +21 px at 963,461; critic 25-35 px) and its lower-right tip is short; L16's top-left is hooded and rides 20 px into H2's neck (evaluator: top -20 px, arc +15 px at 992,385), its lower-left flank short (critic items 3, 5; coupled right arm)

Handle: L15: move +12,+15 px, end a +3,+9 px, end b -14,-5 px, turn +6 deg, length -25%, radius -3%, width +11%, bulge + +5%, bulge - -10%, end a -3%, end b +6%; L16: move -10,-4 px, end a +2,-3 px, end b +2,+11 px, tail radius -44%, tail turn -3 deg, turn +7 deg, length +3%, radius -6%, width +2%, bulge + +12%, end a -8%, end b -4%

| feature | IoU | p95 contour px | crease | severity (metric) |
|---|---|---|---|---|
| L15 | 0.849 -> 0.842 | 11.7 -> 11.4 | 0.87 -> 0.93 | 2 -> 2 |
| L16 | 0.857 -> 0.836 | 9.1 -> 10.6 | 0.63 -> 0.71 | 1 -> 2 |

## L07+L08: verdict: REJECT

Diagnosis: L07 (arch left leg, blue) is a lens too long at both ends (evaluator: left -12 px, right +9 px; critic: right end tapered to a point and 25-30 px long) where the reference is a plump ellipsoid with a blunt right end; L08 above it has a ledge underneath and a beak at its right end (critic items 8, 9; coupled)

Handle: L07: move +7,-5 px, end a -15,-14 px, end b +6,+8 px, turn -8 deg, length +12%, radius -8%, bulge + -9%, bulge - +9%, end a -6%, end b +6%; L08: move -8,-1 px, end a +17,+15 px, end b +8,+4 px, length +4%, radius +6%, bulge + +3%, bulge - -16%, end a +8%

| feature | IoU | p95 contour px | crease | severity (metric) |
|---|---|---|---|---|
| L07 | 0.874 -> 0.901 | 8.5 -> 6.7 | 1.09 -> 1.09 | 1 -> 1 |
| L08 | 0.919 -> 0.901 | 4.5 -> 5.0 | 1.41 -> 1.79 | 0 -> 0 |
| L06 | 0.897 -> 0.912 | 5.0 -> 4.0 | 1.11 -> 1.10 | 0 -> 0 |

