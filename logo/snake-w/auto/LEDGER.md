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

## Round r10 (incumbent r7-merged)

Ranking (top 8):

1. L13 score 8.1: IoU 0.72, bottom edge falls short by 11 px (40 px of outline at 953,766); centroid +1,-2 px
2. L16 score 7.5: IoU 0.86, lower left edge overshoots by 8 px (40 px of outline at 1005,499); centroid +0,+0 px
3. L05 score 6.9: IoU 0.72, bottom edge falls short by 13 px (40 px of outline at 566,758); centroid +8,-5 px
4. L03 score 6.9: IoU 0.87, lower right edge falls short by 7 px (40 px of outline at 504,648); centroid -0,+1 px
5. L10 score 6.7: IoU 0.90, upper left edge overshoots by 7 px (40 px of outline at 760,536); centroid -0,-1 px
6. L11 score 6.2: IoU 0.90, upper left edge overshoots by 6 px (40 px of outline at 784,624); centroid -3,+3 px
7. L02 score 6.0: IoU 0.91, lower right edge overshoots by 6 px (40 px of outline at 487,554); centroid +1,+1 px
8. L14 score 5.8: IoU 0.82, bottom edge falls short by 10 px (40 px of outline at 995,724); centroid -1,-6 px

| target | station run | handle | IoU | worst arc | gates | judge | verdict |
|---|---|---|---|---|---|---|---|
| L13 | blue 406-462 | move +6,+1 px, turn +9 deg, length +16%, radius -6%, width -8%, bulge + +11%, bulge - -13%, end a +2%, end b -4% | 0.72 -> 0.75 | -11 -> -8 | pass | REJECT | REJECT |
| L16 | yellow 1306-1389 | move +2,-2 px, depth +5 px, turn +7 deg, length -4%, radius -3%, width -10%, bulge + -2%, bulge - +14%, end a +3%, end b +10% | 0.86 -> 0.86 | +8 -> -8 | fail: L16 (the target) not improved: IoU 0.86 -> 0.86, worst arc +8 -> -8 px | - | REJECT |
| L05 | blue 1051-1076 | move +1,+6 px, depth -7 px, turn -10 deg, length -17%, radius +2%, bulge + -7%, bulge - -9%, end b +15% | 0.72 -> 0.76 | -13 -> -10 | pass | REJECT | REJECT |

Outcome: no correction accepted

## Round r11 (incumbent incms)

Ranking (top 8):

1. L13 score 16.1: IoU 0.72, bottom edge falls short by 11 px (40 px of outline at 953,766); centroid +1,-2 px
2. L03 score 6.9: IoU 0.87, lower right edge falls short by 7 px (40 px of outline at 504,648); centroid -0,+1 px
3. L10 score 6.7: IoU 0.90, upper left edge overshoots by 7 px (40 px of outline at 760,536); centroid -0,-1 px
4. L11 score 6.2: IoU 0.90, upper left edge overshoots by 6 px (40 px of outline at 784,624); centroid -3,+3 px
5. L02 score 6.0: IoU 0.91, lower right edge overshoots by 6 px (40 px of outline at 487,554); centroid +1,+1 px
6. L14 score 5.8: IoU 0.82, bottom edge falls short by 10 px (40 px of outline at 995,724); centroid -1,-6 px
7. L06 score 5.4: IoU 0.82, left edge falls short by 7 px (40 px of outline at 571,629); centroid +5,+0 px
8. L07 score 5.2: IoU 0.85, bottom edge overshoots by 7 px (40 px of outline at 630,608); centroid -0,-0 px

| target | station run | handle | IoU | worst arc | gates | judge | verdict |
|---|---|---|---|---|---|---|---|
| L13 | blue 406-462 | move +6,+1 px, turn +9 deg, length +16%, radius -6%, width -8%, bulge + +11%, bulge - -13%, end a +2%, end b -4% | 0.72 -> 0.75 | -11 -> -8 | pass | REJECT | REJECT |
| L03 | blue 1148-1246 | move -0,+3 px, depth -3 px, turn -2 deg, length +1%, radius -3%, width +5%, bulge + +13%, bulge - -7%, end a -3%, end b -6% | 0.87 -> 0.89 | -7 -> -6 | fail: L03 (the target) not improved: IoU 0.87 -> 0.89, worst arc -7 -> -6 px | - | REJECT |
| L10 | yellow 816-899 | move +2,+1 px, depth +7 px, turn -1 deg, length -4%, width +2%, bulge + -4%, bulge - -11%, end a +2% | 0.90 -> 0.91 | +7 -> -6 | fail: L10 (the target) not improved: IoU 0.90 -> 0.91, worst arc +7 -> -6 px | - | REJECT |

Outcome: no correction accepted

## Round r12 (incumbent incms)

Ranking (top 8):

1. L01 score 7.7: IoU 0.86, top edge overshoots by 15 px (40 px of outline at 454,336); centroid +2,-3 px
2. L13 score 6.7: IoU 0.72, right edge overshoots by 12 px (40 px of outline at 988,686); centroid +1,-2 px
3. L02 score 6.4: IoU 0.91, upper right edge overshoots by 7 px (40 px of outline at 498,443); centroid +1,+1 px
4. L06 score 6.3: IoU 0.82, right edge overshoots by 14 px (40 px of outline at 692,585); centroid +5,+0 px
5. L11 score 6.2: IoU 0.90, upper left edge overshoots by 6 px (40 px of outline at 779,621); centroid -3,+3 px
6. L15 score 5.6: IoU 0.85, upper left edge overshoots by 21 px (40 px of outline at 963,461); centroid -2,-3 px
7. L16 score 4.7: IoU 0.86, upper left edge overshoots by 15 px (40 px of outline at 992,384); centroid +0,+0 px
8. L04 score 4.7: IoU 0.85, upper right edge overshoots by 13 px (40 px of outline at 565,744); centroid +3,-2 px

| target | station run | handle | IoU | worst arc | gates | judge | verdict |
|---|---|---|---|---|---|---|---|
| L01 | blue 1340-1438 | move -4,+3 px, depth -1 px, turn -10 deg, length -5%, radius -7%, width +2%, bulge - +6%, end a -7%, end b -7% | 0.86 -> 0.87 | +15 -> +11 | pass | REJECT | REJECT |
| L01+neck1 | blue 1340-1438 | move -2,-1 px, depth +22 px, turn -7 deg, length -9%, radius -6%, width -6%, bulge - +14%, end a +6%, end b -1%, head w-neck1.params.json | 0.86 -> 0.86 | +15 -> -11 | pass | REJECT | REJECT |
| L13 | blue 406-462 | move +7,+4 px, depth +8 px, turn +3 deg, length +19%, radius -10%, width -7%, bulge + +20%, bulge - -11%, end a +4%, end b -15% | 0.72 -> 0.74 | +12 -> +11 | pass | REJECT | REJECT |
| L06 | yellow 513-585 | move +6,-5 px, depth -3 px, turn +6 deg, length -16%, radius -4%, width -10%, bulge + +10%, bulge - +15%, end a +9%, end b -1% | 0.82 -> 0.84 | +14 -> -6 | pass | ACCEPT | ACCEPT |

Outcome: new incumbent r12-L06

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

Outcome: no correction accepted

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

## Round r6 (incumbent r5-L02)

Ranking (top 8):

1. L14 score 8.7: IoU 0.82, left edge falls short by 10 px (40 px of outline at 977,693); centroid -1,-6 px
2. L09 score 8.2: IoU 0.86, lower right edge falls short by 16 px (40 px of outline at 748,556); centroid +2,-4 px
3. L10 score 8.2: IoU 0.78, upper left edge overshoots by 12 px (40 px of outline at 752,549); centroid +2,+0 px
4. L16 score 8.2: IoU 0.81, lower left edge overshoots by 12 px (40 px of outline at 1001,496); centroid -6,-2 px
5. L06 score 7.9: IoU 0.82, left edge falls short by 7 px (40 px of outline at 571,629); centroid +5,+0 px
6. L03 score 7.7: IoU 0.85, lower left edge overshoots by 8 px (40 px of outline at 455,712); centroid -5,+7 px
7. L15 score 7.7: IoU 0.83, upper right edge falls short by 12 px (40 px of outline at 1003,498); centroid -1,-1 px
8. L01 score 7.6: IoU 0.86, right edge falls short by 8 px (40 px of outline at 500,407); centroid +2,-3 px

| target | station run | handle | IoU | worst arc | gates | judge | verdict |
|---|---|---|---|---|---|---|---|
| L14 | yellow 1151-1203 | move -2,+5 px, depth -7 px, turn -11 deg, length +13%, radius +1%, width -3%, bulge + -9%, bulge - -1%, end a +12%, end b +3% | 0.82 -> 0.87 | -10 -> -7 | pass | REJECT | REJECT |
| L09 | blue 745-818 | move -3,+4 px, turn -5 deg, length +5%, radius -1%, width -7%, bulge - +1%, end a +6%, end b -11% | 0.86 -> 0.88 | -16 -> -12 | pass | REJECT | REJECT |
| L03 | blue 1152-1245 | move +3,-6 px, depth +3 px, turn -8 deg, length -5%, radius -7%, width -7%, bulge + +3%, bulge - -2%, end a -15%, end b +9% | 0.85 -> 0.87 | +8 -> -7 | pass | ACCEPT | ACCEPT |

Outcome: new incumbent r6-L03

## Round r7 (incumbent r6-L03)

Ranking (top 8):

1. L10 score 8.2: IoU 0.78, upper left edge overshoots by 12 px (40 px of outline at 752,549); centroid +2,+0 px
2. L16 score 8.2: IoU 0.81, lower left edge overshoots by 12 px (40 px of outline at 1001,496); centroid -6,-2 px
3. L06 score 7.9: IoU 0.82, left edge falls short by 7 px (40 px of outline at 571,629); centroid +5,+0 px
4. L15 score 7.7: IoU 0.83, upper right edge falls short by 12 px (40 px of outline at 1003,498); centroid -1,-1 px
5. L01 score 7.6: IoU 0.86, right edge falls short by 8 px (40 px of outline at 500,407); centroid +2,-3 px
6. L07 score 7.4: IoU 0.85, bottom edge overshoots by 7 px (40 px of outline at 630,608); centroid -0,-0 px
7. L04 score 7.3: IoU 0.85, right edge overshoots by 11 px (40 px of outline at 546,739); centroid +3,-2 px
8. L11 score 7.3: IoU 0.84, upper left edge overshoots by 12 px (40 px of outline at 796,603); centroid -4,+5 px

| target | station run | handle | IoU | worst arc | gates | judge | verdict |
|---|---|---|---|---|---|---|---|
| L10 | yellow 809-903 | move -2,-4 px, depth +17 px, turn +9 deg, length +25%, radius -8%, width -2%, bulge + -11%, end a -9%, end b +2% | 0.78 -> 0.90 | +12 -> +7 | pass | ACCEPT | ACCEPT |
| L16 | yellow 1307-1388 | move +6,+0 px, depth +4 px, turn +6 deg, length -4%, radius -10%, width -2%, bulge + +15%, bulge - +10%, end a +6%, end b +8% | 0.81 -> 0.86 | +12 -> +8 | pass | ACCEPT (neutral) | ACCEPT |
| L06 | yellow 513-584 | move +11,-5 px, depth -1 px, turn +9 deg, length -9%, radius -1%, width -8%, bulge + -4%, bulge - -7%, end a -1%, end b +6% | 0.82 -> 0.86 | -7 -> -6 | pass | REJECT | REJECT |

Outcome: new incumbent r7-merged

## Round r8 (incumbent r7-merged)

Ranking (top 8):

1. L01 score 7.6: IoU 0.86, right edge falls short by 8 px (40 px of outline at 500,407); centroid +2,-3 px
2. L07 score 7.4: IoU 0.85, bottom edge overshoots by 7 px (40 px of outline at 630,608); centroid -0,-0 px
3. L04 score 7.3: IoU 0.85, right edge overshoots by 11 px (40 px of outline at 546,739); centroid +3,-2 px
4. L12 score 7.2: IoU 0.88, right edge falls short by 8 px (40 px of outline at 917,751); centroid -1,-2 px
5. L15 score 6.4: IoU 0.85, lower left edge falls short by 8 px (40 px of outline at 1027,633); centroid -2,-3 px
6. L02 score 6.0: IoU 0.91, lower right edge overshoots by 6 px (40 px of outline at 487,554); centroid +1,+1 px
7. L16 score 6.0: IoU 0.86, lower left edge overshoots by 8 px (40 px of outline at 1005,499); centroid +0,+0 px
8. L13 score 5.8: IoU 0.72, bottom edge falls short by 11 px (40 px of outline at 953,766); centroid +1,-2 px

| target | station run | handle | IoU | worst arc | gates | judge | verdict |
|---|---|---|---|---|---|---|---|
| L01 | blue 1340-1438 | move -3,+3 px, depth +4 px, turn -6 deg, length +1%, radius -7%, width -4%, bulge + +11%, bulge - +15%, end a -1%, end b -1% | 0.86 -> 0.87 | -8 -> -8 | fail: L01 (the target) not improved: IoU 0.86 -> 0.87, worst arc -8 -> -8 px | - | REJECT |
| L07 | blue 891-972 | move -1,+4 px, depth +4 px, turn -7 deg, length -1%, radius -6%, width -7%, bulge + +14%, end a +2% | 0.85 -> 0.88 | +7 -> +5 | pass | REJECT | REJECT |
| L12 | yellow 1016-1048 | move +3,+5 px, depth +1 px, turn -5 deg, length -2%, radius -5%, width -3%, bulge + +13%, end a -6%, end b +11% | 0.88 -> 0.90 | -8 -> +8 | fail: L12 (the target) not improved: IoU 0.88 -> 0.90, worst arc -8 -> +8 px | - | REJECT |

Outcome: no correction accepted

## Round r9 (incumbent r7-merged)

Ranking (top 8):

1. L04 score 7.3: IoU 0.85, right edge overshoots by 11 px (40 px of outline at 546,739); centroid +3,-2 px
2. L15 score 6.4: IoU 0.85, lower left edge falls short by 8 px (40 px of outline at 1027,633); centroid -2,-3 px
3. L02 score 6.0: IoU 0.91, lower right edge overshoots by 6 px (40 px of outline at 487,554); centroid +1,+1 px
4. L16 score 6.0: IoU 0.86, lower left edge overshoots by 8 px (40 px of outline at 1005,499); centroid +0,+0 px
5. L13 score 5.8: IoU 0.72, bottom edge falls short by 11 px (40 px of outline at 953,766); centroid +1,-2 px
6. L08 score 5.6: IoU 0.92, lower right edge falls short by 5 px (40 px of outline at 617,537); centroid +1,-0 px
7. L03 score 5.4: IoU 0.87, lower right edge falls short by 7 px (40 px of outline at 504,648); centroid -0,+1 px
8. L10 score 5.2: IoU 0.90, upper left edge overshoots by 7 px (40 px of outline at 760,536); centroid -0,-1 px

| target | station run | handle | IoU | worst arc | gates | judge | verdict |
|---|---|---|---|---|---|---|---|
| L04 | yellow 415-444 | move +1,-3 px, turn -4 deg, length -3%, radius -3%, width -5%, bulge + -4%, bulge - -11%, end b +2% | 0.85 -> 0.49 | +11 -> +23 | fail: L04: split flagged merged,unstable; colour cover 0.981 -> 0.905; L04 (the target) not improved: IoU 0.85 -> 0.49, worst arc +11 -> +23 px | - | REJECT |
| L15 | blue 240-316 | move +6,+1 px, depth +10 px, turn -3 deg, length -5%, radius +6%, width -6%, bulge + +6%, bulge - -7%, end a -10% | 0.85 -> 0.87 | -8 -> +8 | pass | REJECT | REJECT |
| L08 | yellow 646-724 | move -4,+1 px, depth -5 px, turn +4 deg, radius +2%, width -5%, bulge + -9%, bulge - +8%, end a +10%, end b +13% | 0.92 -> 0.91 | -5 -> -4 | fail: L08 (the target) not improved: IoU 0.92 -> 0.91, worst arc -5 -> -4 px | - | REJECT |

Outcome: no correction accepted

Current incumbent: r12-L06 (auto/r12/spec-r12-L06.json)
