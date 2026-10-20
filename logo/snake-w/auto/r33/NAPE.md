# The right nape and the left scarf, isolated (r28-hybR, unchanged)

The owner still sees a bump at the right head's nape. That is an unresolved art-direction issue: it is not closed by r32's measures, nor by geodiag. These renders separate the three possible causes. They are diagnostic renders only: `snakes/diag-clay.html` gained the render-only switches `only=` and `nopress=`; the committed model is unchanged.

## Nape: `nape-isolation.png`, `nape-waist.png`

| test | result | conclusion |
|---|---|---|
| contact press off | identical to the normal render | not the press |
| production head bake vs heads meshed in the page | identical | not the bake |
| blue alone (yellow hidden) | the bump is still there | the blue neck's own surface |

**What the blue surface does.** The back of the neck carries a dome just below the head, then a pinch at about y 420–440, then a flare into the body at the join (y 474). In zebra it is a closed ring on the back of the neck, in clay an hourglass. Nothing else in the body has this.

**Cause: the neck's radius profile, `w-final.params.json` `necks[1].waist` = 12.9 px.**
- The radius is `r_top + (rJ - r_top) e(tau) - waist sin^2(pi tau)` (`geometry.js` `neckCurve`, `headmodel.neck_curve`).
- So it runs 50.4 px under the head, down to 37.5 px at mid-neck (tau 0.5, image y ≈ 430), and back to 50.5 px at the join.
- The waist was added to slim the throat, but a radius waist pinches both sides of the neck, the back as much as the throat.

**How it reads as a bump.** The yellow L16 coil crosses the neck right at that pinch, so its top edge dips into it. That is the hump-dip-hump contact line measured before (+10 / −6 / +7 px against the reference's smooth diagonal).

**Diagnostic waists (renders only):**
- **Waist 0:** the blue neck reads as one smooth tube (straight zebra bands) and the contact line goes straight. But the throat is 5–10 px wider than the reference's.
- **Waist 6:** about half of each.

**Proposed correction (not applied): a one-sided waist.**
- Halve the radius pinch, and move the neck's centreline towards the back by the other half: (waist / 2) sin^2(pi tau), in the head's own plane.
- The throat edge then stays exactly where it is now, on the reference's line, and the back edge stays straight: no dome, no pinch.
- This is one optional neck parameter (the share of the waist taken from the back; 1 = today's symmetric waist), set for the blue neck only, then a re-bake of `heads-w-final.json`.
- It touches no body stations, handles or overlays.

## Scarf: `scarf-isolation.png`

- **Yellow alone (blue hidden):** the yellow neck has a step on its right side where the head's neck meets the body tube: a ledge in clay, a red streak in curvature. The blue scarf normally covers it.
  - This is the step that lowering the collar uncovered in r1 (the reason for the old `neck1` head variant, which was dropped for a zebra blob under the jaw).
  - So the scarf's height is held up by what it hides: the tail's pinch handles keep it covering the step, which is why removing them in r32 raised the scarf further.
- **Blue alone:** the tail ends in a tight hook climbing the back of the neck (high curvature at the hook).
- **The scarf cannot come down cleanly until the yellow neck's step is gone.** The order is:
  1. smooth the yellow neck join (the neck curve's join to the body: its position and tangent at J, `necks[0]`);
  2. then lower the scarf.

## Results (rounds 34-36)

**r34, the nape's one-sided waist** (`necks[1].waist_back` = 1, faded out over tau 0.35–0.6).
- **Geometry:**
  - The hourglass is gone: the blue neck alone shows no dome or pinch (`auto/r34/closeups-iso.png`).
  - The back edge above the coil sits within 3 px of the reference.
  - The contact line's hump is gone.
- **What remains:** the dip at x 1010 (419 against the reference's 409). That is the yellow coil's own tapering edge, the second contributor to the bump.
- **Two first attempts introduced seams:**
  - filling to the join made the neck overhang the tube;
  - a shift with an along-neck component bunched the chain into a crease ring.
- **Verdict:** the judge was inconclusive (all features "same", L16 weakly to the incumbent). Not promoted.

**r35, scarf stage 1** (`tools/neckjoin.py`). The ring at the yellow neck's join is removed (r 47.8 → 40.5 px). A crease at the head-mesh / tube junction remains in isolation, as in the incumbent. It is invisible in the assembly, so it was not judged.

**r36, scarf stage 2** (flat sweep).
- Moving the tail's last half-turn rigidly, along the neck axis or straight down, lowers its top but opens notches in the yellow neck and stray blue at its left.
- Only shapes the overlap measures flag as clearly worse come out of it.
- The scarf needs its last turn reshaped (a fuller cushion wrapping across the neck), not moved.
