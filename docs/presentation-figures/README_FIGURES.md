# Figure pack — Presentation Flow Deck

21 PNGs in `figures/`, one per visual called for in `Presentation_Flow_Deck.pdf`.
All are 220 dpi, transparent-free white background, sized for a 16:9 slide body.
Source in `src/` — edit and re-run to regenerate everything.

## File map

| Slide | File | Status of numbers |
|---|---|---|
| 2  | `slide02_measurement_chain.png` | schematic |
| 3  | `slide03_hardware_geometry.png` | **measured** (r = 119.4 mm, m = 0.620 kg, s = 1.000 m, 55°) |
| 4  | `slide04_timing_diagram.png` | design (18 ms slots, 54 ms period) |
| 5  | `slide05_legacy_pipeline.png` | schematic; legacy choices in red |
| 6  | `slide06_legacy_scatter.png` | ⚠ **PLACEHOLDER geometry** — re-plot from the legacy ablation |
| 7  | `slide07_error_budget.png` | schematic |
| 8  | `slide08_fix1_sensor_offsets.png` | **bench-measured** offsets; Δ is placeholder |
| 9  | `slide09_fix2_hybrid_stencil.png` | **simulator-characterised** (−24 → −12…−15 mm); Δ placeholder |
| 10 | `slide10_fix3_instant_and_contact.png` | **test-measured** (19.13 vs 19.48 mm); Δ placeholder |
| 11 | `slide11_fix4_kalman_bias.png` | **campaign-measured** (+67.5 mm, CI [45.7, 89.4]); Δ placeholder |
| 12 | `slide12_fix5_ground_truth.png` | schematic geometry; 5 mm tape σ → ≈4 mm position σ is measured |
| 13 | `slide13_correction_inventory.png` | table; Δ column placeholder |
| 14 | `slide14_campaign.png` | **campaign-measured** (N = 31 ground-truthed, 4.6 triplets/throw) |
| 15 | `slide15_waterfall_RESULTS.png` | ⚠ **PLACEHOLDER deltas** — the one figure that must be rebuilt |
| 16 | `slide16_uncertainty_ellipse.png` | σ_r = 44 mm, σ_θ = 2.9° measured; 93 % coverage is **simulation, n = 54** |
| 17 | `slide17_conclusions_sensor.png` + `slide17_waterfall_thumbnail.png` | inherits the waterfall |
| 19 | `slide19_optical_method.png` | schematic |
| 20 | `slide20_pre_registered_gate.png` | the gate, RMS ≤ 15 mm over ≥ 8 points |
| 21 | `slide21_optical_nogo.png` | **measured** (64.4 / 152.1 / 61.9 / ~17 mm) — from your deck, not the project files |
| 22 | `slide22_verdict.png` | text |

Slides 1 and 18 need photographs, not generated graphics.

## To fill in the ablation

Every placeholder is driven by ONE dictionary in `src/deck_common.py`:

```python
PLACEHOLDER = True          # set to False once the numbers are real
ABLATION = dict(
    legacy_error = 185.0,   # mm, mean 2-D error, legacy config
    steps = [ ... ],        # mm removed by switching each fix ON
    final_error = 66.0,     # mm (currently anchored to the real in-sample 66 mm)
)
```

Re-run:
```
python fig_speakerA.py && python fig_speakerB.py && python fig_speakerCD.py
```
Setting `PLACEHOLDER = False` removes every red watermark and re-colours the Δ badges green.

## Caveats worth stating out loud

- The **ablation has not been run.** The legacy error (185 mm) and all five Δ values are
  invented for layout purposes only. They are watermarked. Do not present them.
- The waterfall currently *assumes* the five starred fixes dominate. Production Note #1 in
  your own deck flags this as a hypothesis. If Fix 4 turns out small on real data, swap the
  step order and demote it — the figure code handles any ordering.
- `slide16` mixes provenance deliberately: the ellipse is campaign, the 93 % coverage is
  synthetic (n = 54). Both are labelled on the figure, per Production Note #2.
