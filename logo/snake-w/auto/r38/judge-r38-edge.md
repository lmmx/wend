verdict: REJECT
mapping: X = r28-hybR (incumbent), Y = r38-edge (candidate)
judge: one blind Sonnet (xhigh) agent, pair-r38-edge/ only (focus: L16, L15, L16|H2)

Y closer by 1 at L16 (a target: its position and the neck edge above it nearer the reference) and by 1 at L12, which is untouched (noise at the same size). Everything else 'same'. Y introduces small zebra notches on the right edges of L14 and L15 (not visible in colour); X has a slight knee on L15's lower right. By the loop's rule (closer at the target, no defect of its own) not accepted.
Measured (real renders, loop look): L15 IoU 0.853 -> 0.885, crease 1.18 -> 0.74; H2 0.944 -> 0.925 (p95 6.2 -> 8.1). Boundaries against the reference (incumbent -> candidate): L14|L15 direction 10.9 -> 6.7 deg, curvature 7.0 -> 4.7, length +24 -> +28 %; L15|L16 14.6 -> 6.7 deg, 10.5 -> 9.3, +30 -> +25 %; L16|H2 16.8 -> 8.5 deg, 16.5 -> 9.2, +29 -> +23 %, position 8.4 -> 10.3 px.

**Owner override (2026-10-20): ACCEPTED as the new incumbent.**

The owner's reason: r28-hybR's right-arm tubes swell beyond the reference's lobes into inflated, irregular volumes. r38-edge's controlled cross-sections follow the reference's surface contours more closely, and the gains in boundary direction and curvature support that. The blind judge missed the reduced bulging.

Known regressions are recorded in `auto/state.json`, under `incumbent.override.known_regressions`.
