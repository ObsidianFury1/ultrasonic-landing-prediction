# Detector comparison — HSV vs zero-shot YOLO (SYNTHETIC-ONLY DRAFT)

> **SYNTHETIC-ONLY — NOT EVIDENTIARY FOR COMMISSIONING.** Draft output of WO-OPT-2 Stage 2. The synthetic ball hue sits dead-centre of the config HSV band (WO-OPT-1 Stage 6.5), so these numbers are structurally optimistic for the HSV baseline and carry no evidentiary weight; the finalised caveat/watermark is applied in Stage 3 (§10).

Generated: 2026-07-10T21:35:00 · ML available: True

## Negative control (no-ball scene)
- **hsv**: 0 false positives → ✅ clean (no detections)
- **ml**: 0 false positives → ✅ clean (no detections)

## Per-scenario metrics

| scenario | detector | det.rate | scatter σ_px | RMS_px | landing err (mm) | note |
|---|---|---|---|---|---|---|
| nominal | hsv | 1.00 | 0.03 | 0.05 | 3.17 | analytic_centroid |
| nominal | ml | 0.00 | — | — | — | no prediction: no ball track: only 0 valid detections - cannot segment a descent (no landing is reported) |
| blurred | hsv | 1.00 | 0.10 | 0.19 | 3.55 | analytic_centroid |
| blurred | ml | 0.00 | — | — | — | no prediction: no ball track: only 0 valid detections - cannot segment a descent (no landing is reported) |
| shadowed | hsv | 1.00 | 0.04 | 0.06 | 3.08 | analytic_centroid |
| shadowed | ml | 0.00 | — | — | — | no prediction: no ball track: only 0 valid detections - cannot segment a descent (no landing is reported) |
| low_contrast | hsv | 1.00 | 0.03 | 0.04 | 4.04 | analytic_centroid |
| low_contrast | ml | 0.00 | — | — | — | no prediction: no ball track: only 0 valid detections - cannot segment a descent (no landing is reported) |
| grazing | hsv | 1.00 | 0.04 | 0.05 | 15.65 | analytic_centroid |
| grazing | ml | 0.13 | 0.36 | 1.21 | 368.81 | analytic_centroid |
| survey_perturbed | hsv | 1.00 | 0.03 | 0.05 | 3.17 | analytic_centroid |
| survey_perturbed | ml | 0.00 | — | — | — | no prediction: no ball track: only 0 valid detections - cannot segment a descent (no landing is reported) |
| no_ball | hsv | — | — | — | — | scenario has no contact (no-ball) |
| no_ball | ml | — | — | — | — | scenario has no contact (no-ball) |
| with_dropouts | hsv | 0.93 | 0.03 | 0.05 | 3.27 | analytic_centroid |
| with_dropouts | ml | 0.00 | — | — | — | no prediction: no ball track: only 0 valid detections - cannot segment a descent (no landing is reported) |
| bounce | hsv | 1.00 | 0.04 | 0.06 | 0.17 | analytic_centroid |
| bounce | ml | 0.00 | — | — | — | no prediction: no ball track: only 0 valid detections - cannot segment a descent (no landing is reported) |
| bounce_oblique | hsv | 1.00 | 0.04 | 0.06 | 0.57 | analytic_centroid |
| bounce_oblique | ml | 0.00 | — | — | — | no prediction: no ball track: only 0 valid detections - cannot segment a descent (no landing is reported) |

## CPU inference time per frame

| detector | n_frames | median (ms) | IQR (ms) |
|---|---|---|---|
| hsv | 204 | 2.12 | 0.36 |
| ml | 204 | 37.04 | 4.36 |

## ML confidence-threshold sweep

Scenarios: nominal, shadowed, low_contrast (subsample 1/4).

| ML conf cutoff | mean det.rate | mean σ_px |
|---|---|---|
| 0.01 | 0.06 | 0.14 |
| 0.02 | 0.03 | — |
| 0.05 | 0.00 | — |
| 0.10 | 0.00 | — |
| 0.25 | 0.00 | — |
| 0.50 | 0.00 | — |

HSV at its configured band (single knob analogue): mean det.rate 1.00, mean σ_px 0.04.
