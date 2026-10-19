verdict: REJECT
# Blind paired judge: L13ms (Y: r10-L13 with mesh-placed contact shadows) vs incms (X: the incumbent r7-merged, mesh shadows)
Tied; Y "a hair closer, low confidence" (L12 by 1, untouched by the L13 handle: noise; L13 "same, Y marginally"). No unique defects; the
pale crescent under L13 is gone with the mesh shadows.
Verdict: REJECT (no clear gain): L13 IoU 0.720 -> 0.747 (+0.027 < 0.03), worst arc -10.9 -> -8.2 px (2.7 < 5).
The mesh-shadow fix (look.shadowCard.fromMesh) is adopted for the incumbent: it changes no IoU by more than 0.0002 and removes the
defect behind three L13 rejections (r3, r5, r10); L13's rejected-attempt count is reset.
