# geodiag calibration evidence

| check | n ok | ok p50 / p90 / p97 | n bad | bad p50 | sev1 / sev2 / sev3 | TPR@2 | FPR@2 |
|---|---|---|---|---|---|---|---|
| bend | 124 | 1.89 / 4.07 / 5.37 | 9 | 2.73 | 4.07 / 5.37 / 6.71 | 0.00 | 0.05 |
| centroid | 139 | 1.49 / 6.07 / 8.67 | 0 | nan | 6.07 / 10.3 / 12.9 | nan | 0.03 |
| contact_offset | 145 | 2.41 / 3.68 / 4.8 | 18 | 1.97 | 3.68 / 4.8 / 6 | 0.06 | 0.03 |
| contact_ripple | 145 | 1.53 / 2.31 / 2.64 | 31 | 1.66 | 2.31 / 2.64 / 3.3 | 0.03 | 0.03 |
| crease | 139 | 1.09 / 6.56 / 8.72 | 24 | 0.986 | 6.56 / 8.72 / 10.9 | 0.04 | 0.06 |
| ell_p90 | 124 | 0.206 / 0.283 / 0.336 | 0 | nan | 0.283 / 0.336 / 0.42 | nan | 0.03 |
| ext_max | 139 | 12 / 17 / 24.9 | 8 | 8 | 17 / 25 / 31.2 | 0.00 | 0.04 |
| interpen | 124 | 0.147 / 0.281 / 0.313 | 0 | nan | 0.281 / 0.313 / 0.391 | nan | 0.03 |
| lumps_p90 | 124 | 0.0412 / 0.0452 / 0.0491 | 0 | nan | 0.0452 / 0.0516 / 0.0646 | nan | 0.03 |
| outline_offset | 139 | 5.41 / 9.42 / 9.6 | 14 | 5.41 | 9.42 / 9.59 / 12.4 | 0.07 | 0.07 |
| outline_ripple | 139 | 1.6 / 2.31 / 2.78 | 39 | 1.81 | 2.31 / 2.71 / 3.39 | 0.05 | 0.04 |
| phase_max | 56 | 5 / 6 / 6 | 0 | nan | 5.99 / 6 / 7.5 | nan | 0.50 |
| pinch | 124 | 0.123 / 0.184 / 0.205 | 26 | 0.135 | 0.184 / 0.205 / 0.256 | 0.08 | 0.05 |
| seen_bead | 124 | 0.378 / 0.749 / 0.799 | 2 | 0.484 | 0.749 / 0.799 / 0.999 | 0.00 | 0.04 |
| spine_p90 | 56 | 2.15 / 3.75 / 3.75 | 0 | nan | 3.75 / 3.75 / 4.69 | nan | 0.04 |
| taper_visible | 14 | 0.304 / 0.337 / 0.352 | 6 | 0.304 | 0.337 / 0.353 / 0.442 | 0.33 | 0.07 |
| width_bulge | 139 | 0.0907 / 0.237 / 0.31 | 7 | 0.138 | 0.237 / 0.31 / 0.388 | 0.00 | 0.04 |
| width_dev | 139 | 0.0581 / 0.0948 / 0.114 | 19 | 0.0493 | 0.0948 / 0.0979 / 0.162 | 0.21 | 0.05 |
| width_dev_macro | 56 | 0.017 / 0.038 / 0.0488 | 0 | nan | 0.038 / 0.0489 / 0.0612 | nan | 0.04 |
| width_thin | 139 | 0.106 / 0.193 / 0.202 | 9 | 0.0507 | 0.193 / 0.202 / 0.395 | 0.00 | 0.04 |

## Change thresholds (candidate - its incumbent, same region)

| check | n ok | ok |delta| p97.5 = threshold | n bad | bad delta > threshold |
|---|---|---|---|---|
| bend | 462 | 0.0166 | 8 | 0.50 |
| centroid | 522 | 1.31 | 0 | nan |
| contact_offset | 534 | 0.551 | 16 | 0.06 |
| contact_ripple | 534 | 0.203 | 27 | 0.15 |
| crease | 522 | 0.195 | 21 | 0.14 |
| ell_p90 | 462 | 0.00947 | 0 | nan |
| ext_max | 522 | 2 | 8 | 0.00 |
| interpen | 462 | 0.0312 | 0 | nan |
| lumps_p90 | 462 | 0.00233 | 0 | nan |
| outline_offset | 522 | 1.12 | 12 | 0.00 |
| outline_ripple | 522 | 0.169 | 30 | 0.03 |
| phase_max | 217 | 2 | 0 | nan |
| pinch | 462 | 0.00466 | 20 | 0.40 |
| seen_bead | 462 | 0.0228 | 2 | 0.00 |
| spine_p90 | 217 | 1.49 | 0 | nan |
| taper_visible | 44 | 0.0397 | 4 | 0.00 |
| width_bulge | 522 | 0.0403 | 6 | 0.00 |
| width_dev | 522 | 0.0182 | 14 | 0.00 |
| width_dev_macro | 217 | 0.0172 | 0 | nan |
| width_thin | 522 | 0.0292 | 7 | 0.00 |

## Regression library: recorded defects and whether geodiag flags them
absolute: flagged at sev >= 2 in 10 of 42; relative: worse than the incumbent beyond the change threshold in 15 of 38 (cases with a judged incumbent)

| case | region | cause | strongest check (absolute) | sev | worse than its incumbent (beyond the change threshold) |
|---|---|---|---|---|---|
| r16-L16 | L15|L16 | junction_pinch | - | 0 | L16:pinch 0.113->0.136 |
| r17-L16 | L15|L16 | junction_pinch | - | 0 | L16:pinch 0.113->0.134 |
| r20-L16 | L15|L16 | junction_pinch | L16:pinch=0.209 | 2 | L16:pinch 0.113->0.209 |
| r16-L16 | L16 | flat_top | - | 0 | no |
| r12-L01 | L01 | thinning | L01:pinch=0.215 | 2 | - |
| r16-L01 | L01 | stray_blob | - | 0 | no |
| r17-L01 | L01 | flat_top | - | 0 | no |
| r19-L01 | L01 | mass_distribution | - | 0 | no |
| r18-L05 | L05 | crossing_notch | - | 0 | no |
| r19-L05 | L05 | crease | L05:bend=4.22 | 1 | L05:bend 4.07->4.22 |
| r18-L05 | L06 | crease | L06:pinch=0.19 | 1 | no |
| r16-L06 | L06 | mass_distribution | - | 0 | no |
| r14-L04 | L04 | crossing_notch | L04|L05:contact_ripple=3.18 | 2 | L04:outline_ripple 2->2.42, L03|L04:contact_ripple 1.5->1.88, L04|L05:contact_ripple 2.42->3.18 |
| r12-L13 | L13 | crease | L13:outline_ripple=2.83 | 2 | - |
| r15-L14 | L14 | crease | - | 0 | no |
| r13-L11 | L11 | crease | - | 0 | L11:pinch 0.083->0.112 |
| r22-L05+L04 | L04|L06 | junction_pinch | L06:pinch=0.19 | 1 | L04:crease 1.44->1.84 |
| r22-L05+L04 | L04 | thinning | - | 0 | no |
| r22-L05+L04 | L05 | mass_distribution | L05:width_dev=0.0979 | 1 | no |
| r22-L05+L04 | L05 | crossing_notch | - | 0 | no |
| r22-L13+L14 | L13 | fold | - | 0 | L13:bend 2.84->3.46 |
| r22-L13+L14 | L14 | thinning | - | 0 | no |
| r22-L13+L14 | L14 | fold | - | 0 | L14:bend 3.18->3.71 |
| r22-L13+L14 | L13 | mass_distribution | - | 0 | no |
| r23-L15+L16 | L15 | crossing_notch | L15|L16:contact_offset=4.94 | 2 | L14|L15:contact_ripple 1.53->1.79, L15|L16:contact_ripple 1.72->2.31, L15|L16:contact_offset 2.94->4.94 |
| r23-L15+L16 | L16 | crease | - | 0 | L16:pinch 0.113->0.135 |
| r23-L15+L16 | L15|L16 | junction_pinch | L15:outline_ripple=2.41 | 1 | L16:pinch 0.113->0.135, L15:pinch 0.118->0.124, L15|L16:contact_ripple 1.72->2.31 |
| r23-L07+L08 | L08 | flat_top | - | 0 | no |
| r23-L07+L08 | L06|L07 | junction_pinch | L06:pinch=0.196 | 1 | L06:pinch 0.19->0.196, L07:pinch 0.132->0.172 |
| r23-L07+L08 | L06 | crossing_notch | L05|L06:contact_ripple=2.31 | 1 | no |
| r24-L01 | L01 | crease | L01:pinch=0.187 | 1 | L01:crease 1.05->1.35, L01:bend 1.4->2.02 |
| r24-L01 | H1|L01 | junction_pinch | H1:crease=8.94 | 2 | H1:crease 8.72->8.94, L01:crease 1.05->1.35 |
| r24-L07 | L07 | flat_top | - | 0 | no |
| r30-hybR2 | L12|L13 | junction_seam | L13:outline_ripple=2.35 | 1 | no |
| r28-hybR | L01 | collar | tail:yellow:taper_visible=0.358 | 2 | no |
| r28-hybR | H2|L16 | collar | L16:width_dev=0.113 | 2 | no |
| r28-hybR | L15 | swelling | L15:width_dev=0.103 | 2 | no |
| r28-hybR | L16 | swelling | L16:width_dev=0.113 | 2 | no |
| poc-r2 | L04|L06 | fused | - | 0 | - |
| poc-r7 | L05 | double_bulb | - | 0 | - |
| r26-L15+L14 | L13 | dimple | L13:outline_ripple=2.71 | 1 | no |
| r30-hybR2 | L12|L13 | junction_seam | L13:outline_ripple=2.35 | 1 | no |

## Judge agreement: would 'no region worse than the incumbent (beyond its change threshold, at sev >= 2)' have agreed with the blind judge?
accepted candidates with a worse region: 1 of 6; rejected: 18 of 25

| candidate | judge | worse regions |
|---|---|---|
| r13-L01+neck1 | REJECT | - |
| r13-L01 | ACCEPT | - |
| r13-L11 | REJECT | - |
| r14-L04 | REJECT | L04:ell_p90 0.261->0.376, L04:lumps_p90 0.041->0.0758, L04|L05:contact_ripple 2.42->3.18 |
| r14-L16 | REJECT | - |
| r15-L06 | ACCEPT | - |
| r15-L14 | REJECT | L14:lumps_p90 0.0421->0.0628, L14:interpen 0.313->0.375 |
| r16-L01 | REJECT | L01:pinch 0.205->0.21 |
| r16-L06 | REJECT | L06:pinch 0.19->0.23 |
| r16-L16 | REJECT | - |
| r17-L01 | REJECT | L01:pinch 0.205->0.221 |
| r17-L16 | REJECT | - |
| r18-L05 | REJECT | L04:interpen 0.236->0.324, left valley:width_dev_macro 0.0289->0.052 |
| r18-L12 | ACCEPT | - |
| r19-L01 | REJECT | H1:crease 8.72->8.94, L01:seen_bead 0.799->1 |
| r19-L05 | REJECT | left valley:width_dev_macro 0.0289->0.0508 |
| r19-L16 | REJECT | L16:seen_bead 0.608->1.17, tail:yellow:taper_visible 0.323->0.43 |
| r20-L01 | REJECT | H1:crease 8.72->8.94, L01:seen_bead 0.799->1 |
| r20-L16 | REJECT | L16:seen_bead 0.608->1.9, L16:pinch 0.113->0.209, tail:yellow:taper_visible 0.323->0.444 |
| r22-L01w | REJECT | L01:seen_bead 0.799->0.881, L01:ell_p90 0.175->0.349, L01:pinch 0.205->0.209 |
| r22-L05+L04 | REJECT | - |
| r22-L13+L14 | REJECT | L14:interpen 0.311->0.379, right valley:spine_p90 2.91->6.06, right arm:spine_p90 1.77->6.32, right arm:phase_max 6->10 |
| r23-L07+L08 | REJECT | L08:lumps_p90 0.0369->0.0671, L07:lumps_p90 0.0446->0.0602 |
| r23-L15+L16 | REJECT | L15:width_dev 0.0686->0.117, L15:width_thin 0.175->0.232, L16:seen_bead 0.608->1.01, L15|L16:contact_offset 2.94->4.94, right arm:spine_p90 1.77->3.94, tail:yellow:taper_visible 0.323->0.371 |
| r24-L01 | REJECT | H1:crease 8.72->8.94 |
| r24-L07 | REJECT | left valley:spine_p90 1.84->5.2, left valley:width_dev_macro 0.0375->0.0586 |
| r24-L16+L15 | ACCEPT | L15:width_dev 0.069->0.102 |
| r26-L15+L14 | ACCEPT | - |
| r28-hybR | ACCEPT | - |
| r30-hybR2 | REJECT | L14:ell_p90 0.311->0.348, L14:lumps_p90 0.0387->0.0518, L13:ell_p90 0.299->0.464 |
| r31-hybR3 | REJECT | - |
