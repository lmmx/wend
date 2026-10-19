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

## Round r3 (incumbent r2-L01)

Ranking (top 8):

1. L06 score 19.6: IoU 0.65, left edge overshoots by 22 px (40 px of outline at 572,635); centroid -17,-3 px
2. L13 score 12.3: IoU 0.69, bottom edge falls short by 11 px (40 px of outline at 953,766); centroid -0,+0 px
3. L05 score 11.0: IoU 0.71, bottom edge falls short by 13 px (40 px of outline at 573,760); centroid +4,-7 px
4. L11 score 10.9: IoU 0.73, right edge falls short by 18 px (40 px of outline at 840,676); centroid -6,-3 px
5. L04 score 10.7: IoU 0.66, upper right edge falls short by 42 px (40 px of outline at 549,602); centroid -5,+14 px
6. L03 score 9.4: IoU 0.80, upper left edge falls short by 12 px (40 px of outline at 485,558); centroid -6,+11 px
7. L08 score 8.8: IoU 0.85, bottom edge overshoots by 7 px (40 px of outline at 690,529); centroid -0,+0 px
8. L02 score 8.7: IoU 0.86, lower right edge overshoots by 11 px (40 px of outline at 482,559); centroid +1,+0 px

| target | station run | handle | IoU | worst arc | gates | judge | verdict |
|---|---|---|---|---|---|---|---|
| L06 | yellow 504-583 | move +18,-1 px, depth +1 px, turn +17 deg, length -13%, radius -20%, width +5%, bulge + -3%, bulge - +4%, end a +12%, end b +1% | 0.65 -> 0.83 | +22 -> -7 | pass | REJECT | REJECT |
| L13 | blue 408-463 | move +2,+6 px, depth +2 px, turn +2 deg, length +5%, radius -8%, width -15%, bulge + +5%, bulge - +5%, end a +16%, end b -17% | 0.69 -> 0.72 | -11 -> -10 | pass | REJECT | REJECT |
| L02 | yellow 210-288 | move -9,+2 px, depth +3 px, turn -3 deg, length -7%, radius +4%, width -15%, bulge + -14%, bulge - +6%, end a -15%, end b +3% | 0.86 -> 0.90 | +11 -> -7 | pass | REJECT | REJECT |

Outcome: -

## Round r4 (incumbent r2-L01)

Ranking (top 8):

1. L04 score 21.4: IoU 0.66, upper right edge falls short by 42 px (40 px of outline at 549,602); centroid -5,+14 px
2. L06 score 19.6: IoU 0.65, left edge overshoots by 22 px (40 px of outline at 572,635); centroid -17,-3 px
3. L12 score 12.6: IoU 0.74, upper left edge overshoots by 19 px (40 px of outline at 843,671); centroid -8,-7 px
4. L13 score 12.3: IoU 0.69, bottom edge falls short by 11 px (40 px of outline at 953,766); centroid -0,+0 px
5. L05 score 11.0: IoU 0.71, bottom edge falls short by 13 px (40 px of outline at 573,760); centroid +4,-7 px
6. L11 score 10.9: IoU 0.73, right edge falls short by 18 px (40 px of outline at 840,676); centroid -6,-3 px
7. L03 score 9.4: IoU 0.80, upper left edge falls short by 12 px (40 px of outline at 485,558); centroid -6,+11 px
8. L08 score 8.8: IoU 0.85, bottom edge overshoots by 7 px (40 px of outline at 690,529); centroid -0,+0 px

| target | station run | handle | IoU | worst arc | gates | judge | verdict |
|---|---|---|---|---|---|---|---|
| L04 | yellow 422-444 | move -0,+9 px, depth +8 px, turn -8 deg, length +3%, radius -7%, width -3%, bulge + +6%, bulge - +9%, end a +7%, end b +2% | 0.66 -> 0.85 | -42 -> +11 | pass | ACCEPT | ACCEPT |
| L12 | yellow 1017-1049 | move +9,+4 px, depth -5 px, turn +7 deg, length +14%, radius -6%, width -8%, bulge + -4%, bulge - -8%, end a -6%, end b +8% | 0.74 -> 0.88 | +19 -> -8 | pass | ACCEPT | ACCEPT |
| L08 | yellow 647-723 | move +2,-4 px, depth +13 px, turn -1 deg, length +4%, radius -6%, width -4%, bulge + +2%, bulge - -10%, end a +9%, end b -6% | 0.85 -> 0.92 | +7 -> -5 | pass | ACCEPT (neutral) | ACCEPT |

Outcome: new incumbent r4-merged

## Round r5 (incumbent r4-merged)

Ranking (top 8):

1. L05 score 10.9: IoU 0.72, bottom edge falls short by 13 px (40 px of outline at 566,758); centroid +8,-5 px
2. L13 score 10.1: IoU 0.72, bottom edge falls short by 11 px (40 px of outline at 953,766); centroid +1,-2 px
3. L06 score 9.4: IoU 0.82, left edge falls short by 7 px (40 px of outline at 571,629); centroid +5,+0 px
4. L03 score 9.2: IoU 0.82, upper left edge falls short by 12 px (40 px of outline at 485,558); centroid -5,+10 px
5. L14 score 8.7: IoU 0.82, left edge falls short by 10 px (40 px of outline at 977,693); centroid -1,-6 px
6. L02 score 8.7: IoU 0.86, lower right edge overshoots by 11 px (40 px of outline at 482,559); centroid +1,+0 px
7. L09 score 8.2: IoU 0.86, lower right edge falls short by 16 px (40 px of outline at 748,556); centroid +2,-4 px
8. L10 score 8.2: IoU 0.78, upper left edge overshoots by 12 px (40 px of outline at 752,550); centroid +2,+0 px

| target | station run | handle | IoU | worst arc | gates | judge | verdict |
|---|---|---|---|---|---|---|---|
| L05 | blue 1051-1076 | move -6,+7 px, depth +3 px, turn -9 deg, length -8%, radius -10%, width +1%, bulge - +10%, end a -2%, end b +9% | 0.72 -> 0.80 | -13 -> -9 | pass | REJECT | REJECT |
| L13 | blue 406-462 | move +4,+11 px, depth +3 px, turn +4 deg, length +1%, radius -7%, width -8%, bulge + +12%, bulge - -20%, end a +3%, end b -15% | 0.72 -> 0.76 | -11 -> -8 | pass | REJECT | REJECT |
| L02 | yellow 210-288 | move -7,+3 px, depth +1 px, turn +2 deg, length +2%, radius -4%, width -10%, bulge + -4%, end a -15%, end b -3% | 0.86 -> 0.90 | +11 -> -6 | pass | ACCEPT | ACCEPT |

Outcome: new incumbent r5-L02

Current incumbent: r5-L02 (auto/r5/spec-r5-L02.json)
