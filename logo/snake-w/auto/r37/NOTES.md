# r37: the right collar's shape (owner, 2026-10-20: "the blue head has a completely different shaped scarf")

Exploratory only. Nothing was promoted, and r28-hybR stays the incumbent.

- **The outline already matches.** In flat colours the collar region matches the reference to within 4.7% of the crop (`colourfit.png`). Its boundaries match too (`boundaries.png`), apart from the left end, where the blue L15 rises in front.
- **So outline fits cannot see the problem.** That is why every mask- or colour-driven fit here (`collarfit`, `ringcollar` in the neck frame, `collarcolour`) stayed near the incumbent or got worse.
- **What differs is the 3D direction of the tubes inside those regions, which the shading shows** (`tube-direction.png`, measured from each lobe's highlight streak):

  | lobe | reference | production | difference |
  |---|---|---|---|
  | L16 | 147° | 134° | 13° |
  | L15 | 145° | 123° | 22° |
  | L14 | 140° | 111° | 29° |

  The left arm agrees within about 7° (L01 45/44, L02 43/50, L03 49/56).
- **In the blue neck's frame the yellow's last turn crosses the front of the neck while still climbing** (68 px along the axis over s 1290–1340). The reference's collar crosses the front level.
- **Rigid shifts and depth reorders make knots or move the collar off the reference's region.** A level ring in the neck frame, or in the world frame, gives the right reading in places but the wrong region (`ring-variants*.png`).
- **The fix is a re-wind of the right arm** (L14–L16 and the collar, both strands): its coils' tube direction brought onto the reference's while the region layout is kept. The objective must include the tube direction (shading), not only the outline.
