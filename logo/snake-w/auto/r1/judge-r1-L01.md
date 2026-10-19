verdict: REJECT
# Blind paired judge: r1-L01 (Y) vs lvt60 (X); mapping.json, not shown to the judge. Sonnet (xhigh), pages only.
First judge (standard pages): "same" at every feature. Second judge (with page4-focus.png, H1 and L01 enlarged):

| ID | closer | by | sev X | sev Y | note |
|---|---|---|---|---|---|
| H1 | Y | 1 | 2 | 2 | X's blue coil pokes up behind the head beyond the reference silhouette; Y's ends lower (silhouette overlap 0.96 vs 0.94), but Y has a small dent in the yellow neck where the blue meets it |
| L01 | Y | 2 | 3 | 2 | the reference is a fat rounded cushion; X a longer narrower band, too high behind the head; Y rounder, wider, closer |
| L02-H2 | same | 0 | | | pixel-identical (the judge measured) |

Defect only in Y: a small dent / pinch in the yellow neck at the right where the blue coil meets it (notch in colour and clay, zig-zag zebra).
Verdict: REJECT (closer at the target by 2, but a defect shows). Diagnosis (surface-point buffer of the flat render at the notch,
x 425-465, y 355-395): only the blue strand and the baked yellow head mesh are visible there, so the notch is on the head's own neck
surface (heads-final.json), which the lowered collar uncovers: that part of the neck was built to sit behind the wrap. The press is
not the cause (the deepest strand overlap in the crop: 25.7 -> 26.2 px). The L01 handle cannot fix it: the head is fixed in this
loop. A bounded head/neck task smooths that patch; L01's rejected-attempt count is not raised, and it is retried on the new head.
