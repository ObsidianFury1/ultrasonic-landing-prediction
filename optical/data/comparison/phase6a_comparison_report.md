# Phase 6a Detector Comparison — HSV baseline vs zero-shot YOLO

## SYNTHETIC-ONLY — NOT EVIDENTIARY FOR COMMISSIONING

**Caveat (mandatory, §10).** Every number below is measured on the §6 SIMULATOR scenario library, not real footage. The simulator's basketball-orange colour is defined in `simulator/render.py::basketball_bgr` at hue **H=12**, COMPUTED as the centre of the configured HSV detection band, so it sits **dead-centre of that band** by construction (WO-OPT-1 Stage 6.5; retargeted yellow-green -> orange by WO-OPT-4 Stage 2, Decision D18). The synthetic footage is therefore **structurally optimistic for the HSV baseline**: HSV meets an idealised, perfectly-in-band, shadow-controlled target it will not see outdoors. These results characterise the comparison HARNESS and the ML detector's floor behaviour ONLY; they carry **no evidentiary weight for commissioning**. The evidentiary ablation is Phase 6b, on real commissioning + campaign clips after Phase 5, where the HSV band is tuned against real sun/shadow/ball-wear at checklist step C6.

_Generated from `compare_detectors_results.json` (2026-07-10T21:35:00); environment Python 3.14.3, Windows-11-10.0.26200-SP0._

## 1. Per-scenario comparison (every §6 scenario)

| scenario | detector | detection rate | scatter σ_px | landing error (mm) | note |
|---|---|---|---|---|---|
| nominal | hsv | 1.00 | 0.03 | 3.17 | analytic_centroid |
| nominal | ml | 0.00 | — | — | no prediction: no ball track: only 0 valid detections - cannot segment a descent (no landing is reported) |
| blurred | hsv | 1.00 | 0.10 | 3.55 | analytic_centroid |
| blurred | ml | 0.00 | — | — | no prediction: no ball track: only 0 valid detections - cannot segment a descent (no landing is reported) |
| shadowed | hsv | 1.00 | 0.04 | 3.08 | analytic_centroid |
| shadowed | ml | 0.00 | — | — | no prediction: no ball track: only 0 valid detections - cannot segment a descent (no landing is reported) |
| low_contrast | hsv | 1.00 | 0.03 | 4.04 | analytic_centroid |
| low_contrast | ml | 0.00 | — | — | no prediction: no ball track: only 0 valid detections - cannot segment a descent (no landing is reported) |
| grazing | hsv | 1.00 | 0.04 | 15.65 | analytic_centroid |
| grazing | ml | 0.13 | 0.36 | 368.81 | analytic_centroid |
| survey_perturbed | hsv | 1.00 | 0.03 | 3.17 | analytic_centroid |
| survey_perturbed | ml | 0.00 | — | — | no prediction: no ball track: only 0 valid detections - cannot segment a descent (no landing is reported) |
| no_ball | hsv | — | — | — | scenario has no contact (no-ball) |
| no_ball | ml | — | — | — | scenario has no contact (no-ball) |
| with_dropouts | hsv | 0.93 | 0.03 | 3.27 | analytic_centroid |
| with_dropouts | ml | 0.00 | — | — | no prediction: no ball track: only 0 valid detections - cannot segment a descent (no landing is reported) |
| bounce | hsv | 1.00 | 0.04 | 0.17 | analytic_centroid |
| bounce | ml | 0.00 | — | — | no prediction: no ball track: only 0 valid detections - cannot segment a descent (no landing is reported) |
| bounce_oblique | hsv | 1.00 | 0.04 | 0.57 | analytic_centroid |
| bounce_oblique | ml | 0.00 | — | — | no prediction: no ball track: only 0 valid detections - cannot segment a descent (no landing is reported) |

**Aggregate landing across ball-present scenarios** (§10 end-to-end-RMS analogue; single throw per synthetic scenario):

| detector | scenarios landed | landing RMS (mm) | median (mm) | max (mm) | no-prediction |
|---|---|---|---|---|---|
| hsv | 9 | 5.91 | 3.17 | 15.65 | 0 |
| ml | 1 | 368.81 | 368.81 | 368.81 | 8 (nominal, blurred, shadowed, low_contrast, survey_perturbed, with_dropouts, bounce, bounce_oblique) |

## 2. ML confidence-threshold sweep

Over nominal, shadowed, low_contrast (subsample 1/4). The ML analogue of the single HSV band knob.

| ML conf cutoff | mean detection rate | mean σ_px |
|---|---|---|
| 0.01 | 0.06 | 0.14 |
| 0.02 | 0.03 | — |
| 0.05 | 0.00 | — |
| 0.10 | 0.00 | — |
| 0.25 | 0.00 | — |
| 0.50 | 0.00 | — |

HSV at its configured band (its single tuning knob): mean detection rate **1.00**, mean σ_px **0.04**. Lowering the ML cutoff trades higher detection rate for more scatter, but does not reach HSV's rate on this footage.

## 3. Runtime and footprint

| detector | CPU inference median (ms/frame) | IQR (ms) | install footprint |
|---|---|---|---|
| hsv | 2.12 | 0.36 | 0 MB extra (core deps only) |
| ml | 37.04 | 4.36 | ~816 MB (ultralytics + CPU PyTorch) |

(Timing over 204 frames, ≥ 200 per §10; CPU-only PyTorch, one warm-up call discarded.)

## 4. Negative-control outcomes

- **hsv**: 0 false positives → ✅ clean — no detections on the empty floor
- **ml**: 0 false positives → ✅ clean — no detections on the empty floor

## 5. Limitations

This is **zero-shot** detection only: the pretrained `models/yolo11n.pt` COCO 'sports ball' class is used with **no training and no labelling** of our footage. **No fine-tuning was performed.** Per the §10 escalation gate, fine-tuning on hand-labelled frames of our own footage is considered ONLY if zero-shot demonstrably fails AND the HSV baseline ALSO fails on real footage — i.e. only if the module would otherwise be NO-GO. Otherwise fine-tuning remains Future Works (§13). The synthetic-optimism caveat above means the real verdict on both detectors is deferred to Phase 6b; nothing here should be read as HSV 'winning' — only that, on an idealised target, the classical baseline is exact, fast, and cheap, while zero-shot YOLO is slower, heavier, and fragile near contact where detections thin out.
