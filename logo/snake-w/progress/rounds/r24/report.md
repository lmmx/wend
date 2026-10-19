# Round r24: report

Previous accepted best hyb-L456; new accepted best r24-L16+L15.

## L16+L15: verdict: ACCEPT

Diagnosis: the right arm sits 15-25 px up-left along its axis as one offset (critic items 2-4): L16's top-left a spike 25-30 px above and left of the reference, climbing H2's neck; L15's upper-left end 15-20 px high, its lower-right tip 20 px short; L14's upper-left tip 20 px long

Handle: L16: move -2,-4 px, end a -4,-1 px, end b -2,+17 px, length -3%; L15: move +4,+15 px, end a +9,-1 px, end b -2,-6 px, length -3%

| feature | IoU | p95 contour px | crease | severity (metric) |
|---|---|---|---|---|
| L16 | 0.857 -> 0.861 | 9.2 -> 7.6 | 0.62 -> 0.62 | 1 -> 1 |
| L15 | 0.849 -> 0.829 | 11.7 -> 11.8 | 0.86 -> 0.95 | 2 -> 2 |

## L07: verdict: REJECT

Diagnosis: L07 about 8% oversized, its lower-left tip 20-25 px past the reference's, its top 8 px high and its lower edge 8-10 px low (critic item 8)

Handle: move +4,+1 px, end a -2,-13 px, end b +2,+3 px, turn -6 deg, length -15%

| feature | IoU | p95 contour px | crease | severity (metric) |
|---|---|---|---|---|
| L07 | 0.885 -> 0.908 | 8.5 -> 6.3 | 1.06 -> 1.14 | 1 -> 1 |
| L06 | 0.922 -> 0.932 | 4.5 -> 4.0 | 1.25 -> 1.23 | 0 -> 0 |

## L01: verdict: REJECT

Diagnosis: L01 (the collar) too thin: its upper-right flank 15-20 px inside the reference's, its mid-left flank 10 px, its lower-left end 10-20 px short (critic item 5; N2 agrees)

Handle: end a +4,-12 px, end b +19,+19 px, radius +15%, width -1%, bulge + -8%, bulge - -9%

| feature | IoU | p95 contour px | crease | severity (metric) |
|---|---|---|---|---|
| L01 | 0.861 -> 0.881 | 11.2 -> 9.0 | 1.05 -> 1.35 | 2 -> 1 |
| L02 | 0.909 -> 0.894 | 5.7 -> 7.1 | 1.31 -> 1.32 | 0 -> 1 |
