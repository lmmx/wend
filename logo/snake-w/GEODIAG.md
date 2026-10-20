# geodiag: the advisory geometry diagnosis

`tools/geodiag.py` measures every region of a rendered candidate. It reports what looks wrong, where, how sure it is, what probably causes it, and whether it got better or worse than the incumbent.

It exists so the owner no longer has to spot whole classes of defect by eye. Examples are a collar at the wrong height, a tail taper that shows, a bumpy contact line, a beaded tube, or flattened sections. It was generalised from the one-off diagnostic in `geo/` (`geo/DIAGNOSTIC.md`, 2026-10-20).

It never rejects a candidate.

## Three kinds of criteria (owner's rule, 2026-10-20)

| kind | what | who decides |
|---|---|---|
| **hard** | The existing structural checks, unchanged. `autoround.gates`: no feature's severity up by 2, no IoU down by more than 0.08, the silhouette not down by more than 0.01, the target improved. Plus the mesh check's folds and self-penetration. | automatic |
| **soft** | The numbered-feature ledger (IoU, contour p95, worst arc) and the blind pair judge. | the judge, with the gates |
| **advisory** | Everything geodiag measures. | nobody: it ranks and explains |

**Measure broadly, gate narrowly:**
- An accepted candidate does not need every warning resolved. It only needs to be a worthwhile improvement over the incumbent.
- A small regression somewhere is acceptable when the judge prefers the candidate.
- A low-confidence finding is capped at severity 1.
- **Disagreement is data, not an override.** Where geodiag and the judge disagree, the disagreement is logged (`auto/geodiag/judge_log.jsonl`: accepted with regressions, or rejected with none).
- **Gate proposals go to the owner first.** Any proposal to turn a geodiag check into a gate, or to tighten an existing gate, is put to the owner separately. It must come with the evidence below, from previously accepted and rejected candidates. It is never applied automatically.

## Where it runs

**`autoround.py propose`:**
- **Diagnose the incumbent.** Run geodiag on it once and record the result in `state.json` as `incumbent.geodiag`.
- **Feed the ranking.** Its high- and medium-confidence findings join the ranking as one more visual-severity source (`discrepancy.geo_sev`). A geodiag severity 3 counts as a judge's 2, so a measured defect that nobody has flagged yet still brings its feature up. It never outranks what a judge or the owner said.
- **Suggest next experiments.** `auto/rN/rank.md` ends with the geodiag report and its next experiments: the dominant defects, their likely causes and the controls to try. The LOOK and DESCRIBE steps read them alongside the critic.
- **Diagnose each candidate.** After each candidate's real render and gates, geodiag runs against the incumbent's diagnosis (about 20 s). `summary.json` gets `geodiag: {new, regressed, improved, resolved}` for the round report.

**`autoround.py merge`:**
- One line per judged candidate goes to `auto/geodiag/judge_log.jsonl`.
- The new incumbent's diagnosis is recorded.
- `current_best` refreshes `progress/current-best/` (colour, clay, zebra of the accepted incumbent).

**By hand:**
```
python tools/geodiag.py run TAG COLOUR.png SPEC.json OUTDIR [--extra snakes/X.json] [--clay C.png] [--zebra Z.png] [--metrics M.json] [--inc INC_geodiag.json]
python tools/geodiag.py calibrate    # rebuild the thresholds and auto/geodiag/EVIDENCE.md from the library
python tools/geodiag.py regress      # the regression library: is each recorded defect flagged?
```
Outputs `geodiag-TAG.json` (every value, every finding) and `geodiag-TAG.png`. The PNG shows the full frame with the worst findings circled and numbered, their causes, the next experiments, and reference | candidate | clay crops of the worst six.

## Regions and measurements

Every value is measured against the reference image (`snakes/ref/reference.png`) and the anatomy registry (`audit/registry.json`). Candidate lobes are the evaluator's split (`evaluate.split_lobes`) matched to the registry by overlap.

**Macro regions:** L head/neck, left arm, left valley, arch, right valley, right arm, R neck/head. They are bounded by the turning points of the reference's W-spine.

| check | definition |
|---|---|
| `spine_p90` | The W-spine is the shortest skeleton path between the heads of the silhouette blurred (σ 24) past its lobe notches. This is the candidate spine's offset along the reference spine's normal, p90 in px. |
| `width_dev_macro` | The silhouette chord on the reference spine's normals: the band width, about 2 × (helix radius + tube radius). This is the candidate/reference mean ratio − 1. |
| `phase_max` | Along the spine, which strand is in front. This is the largest shift (px of arc) of a front-strand switch against the reference's. |

**Features** (L01–L16, H1, H2):

| check | definition |
|---|---|
| `outline_ripple` | The candidate's signed offset along the reference contour (+ = it reaches past), band-passed (σ 2 … 20 px), rms. Bumps and dips on the outline. |
| `outline_offset` | The smooth (σ 20) part of that offset, p95: a displaced stretch of edge. |
| `width_dev` / `width_bulge` / `width_thin` | The visible width across the reference lobe's major axis, in 40 strips cut identically for both images. Over the central 70%: the mean \|relative difference\|, the largest swelling, the deepest thinning. |
| `ext_max` | The largest displaced extremum (top, bottom, left, right), px. |
| `centroid` | The lobe's centre offset, px. |
| `crease` | `evaluate.py`'s clay crease (99th percentile \|Laplacian\| inside the lobe), reported where metrics are given. |

**Lobes on the 3D tube:** each feature's visible station run is the stations whose ring centre projects into the candidate's lobe of that strand's colour. The rings come from `ffd_worker` `__rings`; where the hybrid overlay replaces the tube, its own rings are used.

| check | definition |
|---|---|
| `seen_bead` | Projected half-width max/min − 1 along the run: the tube's seen width varying (the "puffy" look). |
| `ell_p90` | Ring ellipticity (max − min)/mean, p90: sections not round. |
| `lumps_p90` | Radial harmonics 3–8, p90: lumpy sections. |
| `pinch` | The deepest dip of the ring mean radius below its local (σ 25 stations) mean. |
| `interpen` | (r + r_mate − \|P − mate\|)/r, mean over the run: how far the strands overlap before the contact press flattens them. |
| `bend` | Curvature × r of the ring-centre line, p98. |
| *(context, not checks)* | Handle load and position (handles within the run, \|a\|), the overlay share, R/r. |

**Junctions:** every pair of registry features whose reference regions touch.

| check | definition |
|---|---|
| `contact_ripple` | The band-passed offset along the stretch of one feature's reference contour next to the other, rms: a bumpy contact line, e.g. the nape. |
| `contact_offset` | Its smooth part, mean: the contact line displaced, e.g. a collar too high. |

**Tails:**

| check | definition |
|---|---|
| `taper_visible` | Of the tail's last 120 stations that are visible, the share thinner than 85% of the tail lobe's median radius. |
| `tip_visible` | Whether the tip's own stations show. |

## Severity, confidence, cause, status

**Severity 0–3** comes from per-check thresholds in `tools/geodiag_calib.json`. `geodiag_lib.calibrate` sets them:

| severity | threshold |
|---|---|
| 1 | the accepted incumbents' p90 |
| 2 | between their p95 and p97.5, where it best separates the recorded defects |
| 3 | max(p99.5, 1.25 × the severity-2 threshold) |

**Confidence:**

| confidence | when |
|---|---|
| low | the lobe split is flagged (merged or unstable) |
| med | small regions, short station runs, short junctions, macro values |
| high | otherwise |

**Status:** compared with the incumbent's value for the same region and check. It is `regressed` (or `new`), `improved` or `unchanged`. The test is whether the value moved by more than that check's calibrated change threshold: the 97.5th percentile of the change between judged candidates and their incumbents where no defect was recorded.

**Causes** are inferred from the region's other measures (`geodiag.causes_for`):

| cause | inferred when |
|---|---|
| spine | displacement with a matching width, and the region's spine offset ≥ 4 px |
| twist_phase | displacement with a matching width otherwise, or a switch shift |
| helix_radius | band-width error, or interpenetration ≥ 0.2 / R/r < 0.88 |
| tube_radius | `seen_bead` ≥ 0.45, or a width bulge with a radius bead |
| handles | a disp handle with \|a\| ≥ 0.08 in the run, with the defect |
| section_shape | ellipticity ≥ 0.25 |
| contact_deformation | interpenetration |
| overlay | the hybrid overlay covers the run |
| tail | a tail check, or an extremum of a tail lobe |

Each cause maps to a suggested control in `geodiag.SUGGEST`, listed under "next experiments".

## The library: calibration and regression cases

`tools/geodiag_lib.py`:

| set | what |
|---|---|
| **good** | The accepted incumbents from r12 (r12-L06 … r28-hybR), at regions with no recorded defect. |
| **bad** | Every recorded rejection cause (`auto/causes.json`, 34 entries). The owner's four flags on r28-hybR (the scarf, the nape, the swollen L15 and L16). The named historical failures: the fused yellow T (poc-r2), the L05 double sphere (poc-r7), the right-valley dimple (r26-L15+L14), the flat vertical seam (r30-hybR2). |
| **judged** | Every blind-judged candidate from r12 and its incumbent: the agreement study. |

`auto/geodiag/EVIDENCE.md` holds the full tables. As calibrated on 2026-10-20:

- **The final incumbent:**
  - 29 advisory findings, 6 at severity 2.
  - Unprompted, they include three of the owner's four flags: the L01 pinch (the tail's visible taper), L15 and L16's width profiles, and the yellow tail's visible taper at the nape.
- **Recorded defects:**
  - 10 of 42 are flagged at severity ≥ 2 in absolute terms.
  - 15 of 38 are worse than their incumbent beyond the change threshold.
  - Most recorded rejections are creases, notches and junction pinches seen in clay and zebra, which mask-based measures barely see.
- **Blind spots** (shading-only defects): the fused yellow T and the L05 double sphere are not flagged at all. Their silhouettes match the reference; only the shading shows them. **The blind judge stays essential**, and a clay/zebra-based measure is the open item.
- **Judge agreement:** a "no region worse than the incumbent at severity ≥ 2" rule would have flagged 18 of 25 rejected candidates and 1 of 6 accepted ones.
  - This is evidence for a possible future gate proposal, with only six accepted candidates behind it.
  - It is **not adopted**. Proposing it is the owner's call.

Re-run `calibrate` after any change to geodiag, the evaluator or the modelling system; `regress` should still flag what it flagged before. New rejections land in `auto/causes.json` as before, so the library grows by itself.
