# Corresponding edges: reference vs production r28-hybR (look 6)

`tools/edges.py`. Every edge between registry neighbours (contact A|B) and each lobe's edge on the background (outer A), paired by lobe identity, ordered and resampled by arc length. The bracketed figures are the noise floor: the same comparison between two renders of one geometry (look 6 against the loop's look).

**Usable** means:
- both curves are at least 25 px long and in one piece;
- the edge is stable in the noise test (position under 5 px, length within 10%).

**Measures:**
- **position:** mean distance between corresponding points;
- **local direction:** mean tangent angle difference;
- **end-to-end angle:** signed chord rotation;
- **curvature:** rms difference ×1000;
- **length:** relative projected length.

| edge | arm | usable | position px (noise) | local direction ° (noise) | end-to-end angle ° (noise) | curvature (noise) | length % (noise) |
|---|---|---|---|---|---|---|---|
| L04|L06 | arch | yes | 6.6 (0.5) | 5.8 (0.0) | -5.9 (+0.0) | 16.9 (0.0) | +5 (+2) |
| L05|L06 | arch | no | 13.2 (0.6) | 14.6 (1.4) | -5.1 (-0.3) | 21.8 (7.4) | +155 (+2) |
| L06|L07 | arch | no | 26.7 (0.3) | 16.7 (1.8) | +8.3 (-0.5) | 18.2 (5.0) | +126 (+1) |
| L07|L08 | arch | no | 30.0 (1.1) | 19.2 (1.8) | -14.3 (-0.7) | 12.5 (3.3) | +123 (-3) |
| L08|L09 | arch | yes | 2.2 (1.6) | 5.6 (1.9) | +1.8 (-1.5) | 9.4 (6.2) | +5 (-1) |
| L09|L10 | arch | yes | 8.8 (1.5) | 5.9 (1.8) | -1.5 (-1.2) | 6.7 (5.1) | -5 (-2) |
| L10|L11 | arch | yes | 2.7 (0.9) | 4.1 (1.0) | -2.5 (-0.5) | 6.4 (1.3) | +1 (-2) |
| L11|L12 | arch | no | 29.8 (0.6) | 5.9 (1.1) | -1.7 (-0.1) | 10.8 (2.4) | +88 (-1) |
| outer L05 | arch | yes | 12.3 (1.0) | 9.0 (1.6) | -5.6 (-0.6) | 20.3 (6.1) | -2 (+0) |
| outer L06 | arch | yes | 14.9 (1.0) | 17.6 (2.2) | +10.7 (-0.4) | 21.3 (4.3) | -13 (-0) |
| outer L07 | arch | no | 126.3 (0.7) | 41.3 (0.9) | -19.3 (-0.4) | 59.8 (3.9) | -23 (+2) |
| outer L08 | arch | no | 3.0 (0.6) | 3.6 (1.9) | -0.9 (+0.1) | 12.1 (6.7) | +4 (-1) |
| outer L09 | arch | yes | 1.6 (0.8) | 2.4 (1.8) | +1.3 (-0.5) | 2.8 (4.2) | +4 (+1) |
| outer L10 | arch | no | 2.6 (1.0) | 2.3 (0.9) | -1.9 (-0.7) | 2.5 (1.4) | +1 (-1) |
| outer L11 | arch | no | 3.7 (0.1) | 5.7 (0.7) | +0.6 (-0.0) | 6.3 (2.3) | +9 (+0) |
| outer L12 | arch | no | 3.8 (0.9) | 4.5 (2.0) | +2.7 (+0.7) | 10.1 (10.0) | -13 (-3) |
| H1|L01 | left arm | yes | 9.2 (2.2) | 11.0 (2.9) | +8.1 (-1.8) | 10.3 (3.1) | +18 (-4) |
| L01|L02 | left arm | yes | 18.1 (1.3) | 10.9 (1.4) | +4.7 (-0.2) | 10.2 (3.6) | +44 (+0) |
| L02|L03 | left arm | yes | 4.6 (1.3) | 9.9 (1.3) | +2.9 (-0.5) | 7.2 (4.7) | +9 (-1) |
| L03|L04 | left arm | yes | 9.7 (0.3) | 8.3 (1.7) | +3.2 (+0.1) | 10.9 (2.7) | +35 (-0) |
| L04|L05 | left arm | no | 23.0 (16.4) | 30.8 (14.6) | +30.0 (-14.7) | 21.8 (21.9) | -8 (+48) |
| outer H1 | left arm | yes | 9.3 (1.0) | 8.7 (1.0) | +6.6 (-0.6) | 3.0 (0.5) | -5 (+0) |
| outer L01 | left arm | no | 17.7 (1.2) | 14.1 (1.3) | +4.2 (-0.8) | 9.4 (1.5) | -6 (-2) |
| outer L02 | left arm | no | 7.5 (1.3) | 6.3 (2.5) | +2.7 (-0.4) | 12.2 (4.4) | +2 (-3) |
| outer L03 | left arm | no | 10.2 (0.2) | 10.3 (1.1) | -1.3 (-0.0) | 11.3 (4.4) | -1 (+0) |
| outer L04 | left arm | no | 13.7 (1.0) | 14.6 (1.8) | +15.1 (-0.8) | 6.2 (5.6) | +2 (-3) |
| L12|L13 | right arm | yes | 18.3 (4.1) | 7.4 (2.8) | +5.2 (-1.4) | 16.8 (5.2) | +64 (-6) |
| L12|L14 | right arm | no | 12.0 | 17.8 | -16.9 | 136.9 | -87 |
| L13|L14 | right arm | no | 13.4 (18.3) | 14.5 (11.3) | +2.3 (+4.5) | 22.8 (23.3) | -23 (+46) |
| L14|L15 | right arm | yes | 11.1 (0.5) | 11.1 (1.2) | -1.8 (+0.1) | 7.8 (3.0) | +25 (-1) |
| L15|L16 | right arm | yes | 11.9 (0.7) | 14.5 (1.6) | -4.3 (+0.4) | 10.7 (2.6) | +32 (-1) |
| L16|H2 | right arm | yes | 8.2 (0.7) | 17.0 (1.4) | -6.8 (-0.1) | 16.6 (2.4) | +28 (+1) |
| outer H2 | right arm | yes | 13.7 (0.2) | 10.3 (0.3) | -7.2 (+0.0) | 4.0 (0.2) | +2 (-0) |
| outer L13 | right arm | yes | 10.3 (1.6) | 6.8 (1.9) | +3.6 (-1.3) | 17.6 (4.6) | +8 (-1) |
| outer L14 | right arm | no | 5.0 (0.5) | 8.0 (1.4) | -8.0 (+0.9) | 7.6 (8.4) | -4 (+1) |
| outer L15 | right arm | no | 22.0 (162.1) | 19.0 (31.0) | -1.7 (-7.4) | 23.3 (28.7) | -14 (+5) |
| outer L16 | right arm | no | 151.6 (0.7) | 46.7 (1.1) | +7.3 (+0.4) | 38.0 (2.4) | -16 (-2) |
