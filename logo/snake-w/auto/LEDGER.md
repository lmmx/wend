# Autonomous correction loop: ledger

Each round: rank every lobe of the incumbent's real render by its discrepancy from the reference (tools/discrepancy.py); take the top targets that are not each other's neighbours; attribute each to the run of strand stations that draws it (the surface-point buffer, tools/lobekit.py); fit that run's lobe handle with the neighbours guarded (tools/lobefit.py); render for real, measure, gate (tools/autoround.py); blind paired judge (images only); accept or reject; merge the accepted.

## Round r1 (incumbent lvt60)

Ranking (top 8):

1. L04 score 18.4: IoU 0.66, upper right edge falls short by 42 px (40 px of outline at 549,602); centroid -5,+14 px
2. L06 score 15.1: IoU 0.65, left edge overshoots by 22 px (40 px of outline at 572,635); centroid -17,-3 px
3. L13 score 11.1: IoU 0.66, upper right edge overshoots by 19 px (40 px of outline at 974,690); centroid +1,-4 px
4. L12 score 9.8: IoU 0.73, upper left edge overshoots by 19 px (40 px of outline at 843,671); centroid -10,-8 px
5. L14 score 9.5: IoU 0.77, lower left edge falls short by 19 px (40 px of outline at 976,690); centroid -0,-10 px
6. L11 score 9.4: IoU 0.73, right edge falls short by 18 px (40 px of outline at 840,676); centroid -6,-3 px
7. L01 score 8.1: IoU 0.80, upper right edge overshoots by 15 px (40 px of outline at 475,361); centroid +6,-11 px
8. L05 score 8.0: IoU 0.71, bottom edge falls short by 13 px (40 px of outline at 573,760); centroid +4,-7 px

| target | station run | handle | IoU | worst arc | gates | judge | verdict |
|---|---|---|---|---|---|---|---|
| L04 | yellow 422-444 | move +1,-1 px, depth +5 px, turn +1 deg, length -4%, radius +2%, width +8%, bulge + +8%, bulge - -6%, end a -10%, end b -5% | 0.66 -> 0.84 | -42 -> +10 | pass | REJECT | REJECT |
| L13 | blue 408-469 | move -1,+2 px, depth -7 px, turn +8 deg, length -12%, radius -11%, bulge + +12%, end a +4%, end b -5% | 0.66 -> 0.69 | +19 -> -11 | pass | ACCEPT | ACCEPT |
| L01 | blue 1344-1436 | move -6,+13 px, depth -4 px, turn -9 deg, length -10%, radius -11%, width -2%, bulge + -3%, bulge - +11%, end a -10%, end b -2% | 0.80 -> 0.85 | +15 -> -8 | pass | REJECT | REJECT |

Outcome: new incumbent r1-L13

## Round r2 (incumbent r1-L13)

Ranking (top 8):

1. L04 score 21.4: IoU 0.66, upper right edge falls short by 42 px (40 px of outline at 549,602); centroid -5,+14 px
2. L06 score 19.6: IoU 0.65, left edge overshoots by 22 px (40 px of outline at 572,635); centroid -17,-3 px
3. L01 score 12.6: IoU 0.80, upper right edge overshoots by 15 px (40 px of outline at 475,361); centroid +6,-11 px
4. L12 score 12.6: IoU 0.74, upper left edge overshoots by 19 px (40 px of outline at 843,671); centroid -8,-7 px
5. L05 score 11.0: IoU 0.71, bottom edge falls short by 13 px (40 px of outline at 573,760); centroid +4,-7 px
6. L11 score 10.9: IoU 0.73, right edge falls short by 18 px (40 px of outline at 840,676); centroid -6,-3 px
7. L13 score 10.8: IoU 0.69, bottom edge falls short by 11 px (40 px of outline at 953,766); centroid -0,+0 px
8. L03 score 9.4: IoU 0.80, upper left edge falls short by 12 px (40 px of outline at 485,558); centroid -6,+11 px

| target | station run | handle | IoU | worst arc | gates | judge | verdict |
|---|---|---|---|---|---|---|---|
| L04 | yellow 422-444 | move -4,+10 px, depth +9 px, turn -9 deg, length +9%, radius -13%, width +7%, bulge + -3%, end a +14%, end b -12% | 0.66 -> 0.86 | -42 -> +8 | pass | REJECT | REJECT |
| L01 | blue 1344-1436 | move -3,+5 px, depth +3 px, turn -2 deg, length -7%, radius -13%, width +3%, bulge - +4%, end b -16% | 0.80 -> 0.84 | +15 -> -8 | pass | ACCEPT (neutral) | ACCEPT |
| L12 | yellow 1017-1049 | move +10,+8 px, depth +21 px, turn -3 deg, length +14%, radius -12%, width -9%, bulge + -7%, bulge - -12%, end a -5%, end b +14% | 0.74 -> 0.88 | +19 -> -8 | pass | REJECT | REJECT |

Outcome: new incumbent r2-L01

Current incumbent: r2-L01 (auto/r2/spec-r2-L01.json)
