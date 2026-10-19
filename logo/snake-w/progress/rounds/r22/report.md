# Round r22: report

Previous accepted best r18-L12; new accepted best r18-L12.

## L05+L04: verdict: REJECT

Diagnosis: L05 (left valley, blue) is a boxy block where the reference has a ball resting on the floor: its bottom floats 13 px above the reference's (critic: 20-25 px), its upper-right corner sticks out 16 px, its lower-left swell is missing (left edge 8 px in), and it is tilted 34 degrees off; L04 must give way where L05 overlaps it (critic items 2, 7; coupled left valley)

Handle: L05: move -11,+13 px, depth +2 px, end a -4,+8 px, end b +11,-11 px, turn -4 deg, length +8%, radius +2%, width -4%, bulge + -7%, bulge - -5%, end a +6%, end b -15%; L04: move -2,-3 px, depth +4 px, end a +9,-8 px, end b -7,-8 px, turn +2 deg, length +11%, radius -5%, width -2%, bulge + +9%, bulge - -12%, end a -15%, end b -5%

| feature | IoU | p95 contour px | crease | severity (metric) |
|---|---|---|---|---|
| L05 | 0.708 -> 0.836 | 14.5 -> 9.2 | 0.90 -> 1.04 | 2 -> 1 |
| L04 | 0.869 -> 0.876 | 10.9 -> 7.8 | 1.44 -> 1.84 | 2 -> 1 |

## L13+L14: verdict: REJECT

Diagnosis: L13 (right valley, blue) has a dimple where L12, L13 and L14 meet; its upper-right flank is too full against L14 (5 px, critic 10-15 px) and its bottom is short and flat (10 px, critic 12-15 px) where the reference sags round to the floor; L14's lower end steps where it meets L13 (critic items 1, 4; coupled right valley)

Handle: L13: move -1,+9 px, depth +4 px, end a +9,-8 px, end b +12,-14 px, turn +5 deg, length +3%, width -7%, bulge + +8%, bulge - +12%, end a +3%, end b -8%; L14: move +1,+9 px, depth -10 px, end a +7,-0 px, end b +6,-14 px, turn -1 deg, radius +3%, width -6%, bulge + +4%, bulge - +9%, end a -1%, end b -5%

| feature | IoU | p95 contour px | crease | severity (metric) |
|---|---|---|---|---|
| L13 | 0.736 -> 0.835 | 12.0 -> 9.8 | 5.90 -> 3.52 | 2 -> 1 |
| L14 | 0.821 -> 0.818 | 11.7 -> 9.2 | 0.68 -> 0.68 | 2 -> 1 |

## L01w: verdict: REJECT

Diagnosis: L01 (the scarf) is too narrow: its right flank is flat and straight, 11 px short of the reference's (critic 15-20 px) in the upper two-thirds, and its left flank 8-10 px short; the reference's collar is a plump dome bulging right past the neck (critic item 6)

Handle: end a -0,-9 px, radius -4%, width +9%, bulge + +17%, bulge - -7%, end a +9%

| feature | IoU | p95 contour px | crease | severity (metric) |
|---|---|---|---|---|
| L01 | 0.861 -> 0.865 | 11.2 -> 12.0 | 1.06 -> 1.04 | 2 -> 2 |
| L02 | 0.908 -> 0.890 | 5.7 -> 8.7 | 1.31 -> 1.32 | 0 -> 1 |
