# LEGACY_ABLATION_RESULTS.md — legacy-design ablation study (2026-07-12)

**Status: reference study, not a work order.** This file records a **read-only** re-processing of
the completed 34-throw live campaign (`data/sessions/2026-07-09_T*`) under the original,
pre-corrections **legacy pipeline**, to fill the `[X mm]` placeholders in
`Presentation_Flow_Deck.pdf` (Slides 6, 8–13, 15, 17). No session directory, `session.json`,
`raw_serial.log`, or any other on-disk artifact was modified — every number below comes from an
external, standalone script that re-reads the recorded raw data and the shared recorded
three-tape ground truth. See `CLAUDE.md`'s "Changelog v2.7 → v2.8" and
`IMPLEMENTATION_NOTES.md` Part 19 for the as-built pointer to this file.

Two independent scripts were run, both against the venv interpreter, both read-only:

1. **`legacy_ablation.py`** — full legacy-configuration re-run (every accuracy correction off at
   once), the number for Slide 6.
2. **`loo_ablation.py`** — **leave-one-out** ablation from the delivered, fully-corrected
   pipeline: each correction is turned off **individually**, holding every other correction (incl.
   the shipped bias model) at its production value. This is the number for Slide 13's Δ column and
   Slide 8–12's per-fix deltas — a single combined "legacy" number cannot honestly be decomposed
   into five independent deltas, because the corrections interact (see §4 below).

Both scripts are read-only, standalone (not part of the `pipeline/`/`tests/` package), and are
not part of the pytest suite; they are kept as reference material, not as regression tests. Their
full source and raw per-throw JSON/CSV output are archived alongside this file's provenance note
(§6).

---

## 1. Legacy configuration definition

Per direct instruction: "*Legacy is plain prediction run with no active error corrections... This
should use forward differencing and without all other edits to improve accuracy.*" Concretely,
starting from the fully-corrected `pipeline/process_throw.process_session` chain, the following
were turned OFF simultaneously:

| Correction | Legacy setting |
|---|---|
| Temperature-based speed of sound | **OFF** — fixed v = 343 m/s (20 °C) for all 34 throws |
| Per-sensor electronic offset | **OFF** — no offset subtraction |
| Ball-radius R2 (surface→centre range) | **OFF** — raw surface ranges into trilateration |
| Temporal-correction stencil | **Forward differencing** (not hybrid) — last triplet of every
  throw has no successor and is discarded (keeps N−1, not N) |
| Sample-time timestamps | **Nominal fixed 18 ms schedule** (S1 = n·54 ms, S2 = +18 ms,
  S3 = +36 ms) — no measured `micros()`, no mid-echo `t_TRIG + echo/2` |
| Sensor-height correction | **OFF** — `S_height_m = 0` |
| Kalman filter | **OFF** — raw trilaterated (x, y, z) fed straight into the parabola fit
  (velocity for the fit's heading export from a plain finite difference) |
| Landing contact height | **y = 0** (not y = ball radius) |
| Track-aligned bias model | **OFF** |

**Left ON** (throw *detection*, not an accuracy correction — needed so the same triplets are
being compared): the temperature-based background gate/band rule and the arm/close segmentation
state machine, run exactly as in the real pipeline. This keeps the ablation "same throws, only the
corrections differ," per the deck's own Slide 15 speaker line.

Ground truth for every throw is the **same recorded three-tape multilateration value already in
each session's `session.json`** — the ablation only changes the *prediction* side.

---

## 2. Slide 6 number — full legacy configuration, all 34 throws

**Result: the legacy pipeline predicts a landing for only 16 of the 34 recorded throws.**

The other 18 fail the `min_fit_points = 4` floor. This is not random attrition: every one of
those 18 throws had **exactly 4** triplets survive gating under the corrected pipeline (confirmed
against `gate_summary.n_triplets_used` in `session.json`, distribution `{4: 18, 5: 14, 6: 2}`).
Forward differencing discards the last triplet of every throw (no successor to difference
against), turning a 4-triplet throw into 3 usable triplets — below the fit floor. This is exactly
the effect the corrected pipeline's hybrid stencil (§3, fix ★2) is built to avoid ("keeps all N
triplets").

### 2.1 Per-throw legacy result (all 34 sessions)

| Session | n used | Legacy 2D error (mm) |
|---|---:|---:|
| 2026-07-09_T02 | — | FAIL (3 triplets, in-throw=3) |
| 2026-07-09_T04 | 4 | 95.9 |
| 2026-07-09_T05_1 | — | FAIL (3 triplets, in-throw=3) |
| 2026-07-09_T06 | — | FAIL (3 triplets, in-throw=3) |
| 2026-07-09_T07 | — | FAIL (2 triplets, in-throw=2) |
| 2026-07-09_T09_2 | — | FAIL (3 triplets, in-throw=3) |
| 2026-07-09_T10 | — | FAIL (3 triplets, in-throw=3) |
| 2026-07-09_T11 | — | FAIL (3 triplets, in-throw=3) |
| 2026-07-09_T14_2_3 | — | FAIL (3 triplets, in-throw=3) |
| 2026-07-09_T15 | — | FAIL (3 triplets, in-throw=3) |
| 2026-07-09_T17 | 4 | 182.8 |
| 2026-07-09_T20 | 4 | 119.0 |
| 2026-07-09_T24 | — | FAIL (3 triplets, in-throw=3) |
| 2026-07-09_T28 | — | FAIL (3 triplets, in-throw=3) |
| 2026-07-09_T29 | — | FAIL (3 triplets, in-throw=3) |
| 2026-07-09_T35 | — | FAIL (3 triplets, in-throw=3) |
| 2026-07-09_T37 | 4 | 173.0 |
| 2026-07-09_T46 | — | FAIL (3 triplets, in-throw=3) |
| 2026-07-09_T47 | 4 | 108.6 |
| 2026-07-09_T48 | 5 | 94.3 |
| 2026-07-09_T49 | 4 | 276.9 |
| 2026-07-09_T52 | 4 | 117.9 |
| 2026-07-09_T53 | 4 | 112.7 |
| 2026-07-09_T54 | 5 | 157.7 |
| 2026-07-09_T57 | — | FAIL (3 triplets, in-throw=3) |
| 2026-07-09_T58 | 4 | 43.0 |
| 2026-07-09_T60 | — | FAIL (3 triplets, in-throw=3) |
| 2026-07-09_T76 | 4 | 148.7 |
| 2026-07-09_T79 | 4 | 159.5 |
| 2026-07-09_T83 | 4 | 94.1 |
| 2026-07-09_T89 | 4 | 90.0 |
| 2026-07-09_T90 | — | FAIL (3 triplets, in-throw=3) |
| 2026-07-09_T95 | — | FAIL (3 triplets, in-throw=3) |
| 2026-07-09_T96 | 4 | 158.5 |

### 2.2 Legacy summary statistics (n = 16 predictable throws)

| Statistic | Value |
|---|---:|
| Throws predicted | 16 / 34 |
| Mean 2D error | **133.3 mm** |
| Median 2D error | 118.4 mm |
| Std (ddof=1) | 53.4 mm |
| Min / max | 43.0 / 276.9 mm |
| 95% CI on the mean | 107.1 – 159.4 mm |

**Recommended Slide 6 headline: "Legacy design: predicts only 16/34 throws; 133.3 mm mean 2D
error on those."** State the coverage collapse alongside the error number — it is arguably the
more damning legacy finding and is a fair, honestly-labelled campaign-measured result.

---

## 3. Matched 16-throw comparison (apples-to-apples waterfall, Slide 15 alternative framing)

Because the legacy pipeline can only be scored on the 16 throws it predicts, this table compares
legacy against the corrected pipeline **restricted to the same 16 throws**:

| Stage | n | Mean 2D error | Median |
|---|---:|---:|---:|
| Legacy design | 16 | 133.3 mm | 118.4 mm |
| Corrected pipeline, pre-bias | 16 | 88.1 mm | 85.2 mm |
| Corrected pipeline, full (post-bias) | 16 | **57.8 mm** | 44.7 mm |

**Improvement: 133.3 → 57.8 mm = 57% reduction** (matched subset only).

### 3.1 Full 34-throw corrected-pipeline numbers (for context; not matched to legacy)

| Stage | n | Mean 2D error | Median |
|---|---:|---:|---:|
| Corrected pipeline, pre-bias (raw) | 34 | 92.4 mm | 93.9 mm |
| Corrected pipeline, full (post-bias) | 34 | **64.5 mm** | 59.7 mm |

The 34-throw, post-bias **64.5 mm** is the campaign headline used throughout §4 below as the
leave-one-out baseline, and reproduces the number already stored in each session's
`prediction.corrected` / `correction_model.json`-applied field to the last 0.1 mm — this is the
cross-check that the ablation harness reimplements the real pipeline correctly.

---

## 4. Leave-one-out ablation (Slide 8–13 Δ column) — the number that actually belongs on the slides

**A single "legacy vs corrected" number cannot be honestly split into five independent per-fix
deltas**, because the corrections interact (most visibly: the bias model partially absorbs
common-mode range offsets that the offset/temperature/height corrections would otherwise remove).
The methodologically correct per-fix Δ is a **leave-one-out (LOO) ablation**: start from the full,
delivered pipeline (all corrections ON, bias model at its shipped `correction_model.json` value,
mean 2D error **64.5 mm**, n = 34), turn off **one** correction at a time, and measure the paired
per-throw increase in error against throws both configurations can predict.

### 4.1 Primary table — bias held at shipped value (this is the number for the deck)

Baseline: full pipeline, all ON, **64.5 mm** (n = 34/34). `Δ` = mean paired (variant − baseline)
2D error, 95% CI on that paired mean; `***` marks a CI that excludes zero (i.e., a statistically
resolvable effect at n = 34).

| Correction turned OFF | n predicted | Mean error w/ OFF | **Δ vs 64.5 mm baseline** | 95% CI | Significant? |
|---|---:|---:|---:|---|:---:|
| Ball-radius R2 (surface→centre) | 34/34 | 163.8 mm | **+99.3 mm** | [+82.0, +116.7] | *** |
| Hybrid stencil (→ forward) | 16/34 | 123.4 mm | **+65.6 mm** *(+18 throws lose all prediction)* | [+32.1, +99.1] | *** |
| Track-aligned bias model | 34/34 | 92.4 mm | **+27.9 mm** | [+15.5, +40.4] | *** |
| Landing y = r_ball (→ y = 0) | 34/34 | 85.7 mm | **+21.2 mm** | [+9.7, +32.8] | *** |
| Kalman filter (→ raw fit) | 34/34 | 68.7 mm | +4.3 mm | [−2.0, +10.5] | not significant |
| Per-sensor electronic offset | 34/34 | 67.7 mm | +3.2 mm | [−3.6, +10.0] | not significant |
| Temperature-based speed of sound | 34/34 | 66.3 mm | +1.9 mm | [−5.2, +8.9] | not significant |
| Sensor-height correction | 34/34 | 65.7 mm | +1.2 mm | [−4.4, +6.9] | not significant |
| Mid-echo sample instant (→ t_TRIG) | 34/34 | 64.5 mm | +0.0 mm | [−0.2, +0.2] | not significant |
| Both mid-echo + y=r_ball off | 34/34 | 85.8 mm | +21.3 mm | [+9.7, +32.9] | *** |
| Both Kalman + bias off | 34/34 | 97.6 mm | +33.1 mm | [+19.2, +47.0] | *** |

### 4.2 Cross-check — same LOO ablation with the bias model held OFF everywhere

Run to check whether the primary table's small/null deltas (offset, temperature, sensor-height)
are real or an artifact of the shipped bias model compensating for them. Baseline here: full
pipeline minus bias, **92.4 mm** (n = 34/34, matches §3.1's pre-bias row exactly).

| Correction turned OFF (bias already off) | n | Mean error | Δ vs 92.4 mm |
|---|---:|---:|---:|
| Ball-radius R2 | 34 | 103.4 mm | +11.0 mm |
| y = r_ball (→ y = 0) | 34 | 136.8 mm | +44.4 mm |
| Hybrid stencil (→ forward) | 16 | 136.9 mm | +48.8 mm |
| Kalman filter | 34 | 97.6 mm | +5.2 mm |
| Mid-echo sample instant | 34 | 92.5 mm | +0.1 mm |
| Per-sensor electronic offset | 34 | 77.2 mm | **−15.2 mm** |
| Temperature-based speed of sound | 34 | 72.2 mm | **−20.2 mm** |
| Sensor-height correction | 34 | 77.1 mm | **−15.3 mm** |

**Interpretation (important for Q&A):** without the bias model, removing the offset/temperature/
height corrections *lowers* mean error, because each correction pushes an already-long prediction
even longer, and the fixed +67.5 mm along-track bias term (`correction_model.json`,
`offset_along_m`) was fitted *with those corrections present* — removing them changes the
residual the bias term was calibrated against. This is not evidence the three corrections are
harmful; it is evidence they are **redundant with the bias model's common-mode absorption** once
both are present together. The primary table (§4.1, bias held at its shipped, as-delivered value)
is the correct number for "what does turning this off cost the delivered system" — which is what
the deck's Δ column is asking.

---

## 5. Recommended slide-by-slide edits (mapping this study back onto the deck)

- **Slide 6** — "[X mm]" → **"predicts 16/34 throws, 133.3 mm mean 2D error on those; 18 throws
  produce no prediction at all."** Label: *measured, n = 34 throws (legacy re-run)*.
- **Slide 8 (★1 offset)** — Δ = **+3.2 mm, not statistically significant at n = 34** (95% CI
  crosses zero). Consider demoting off the starred list, or keep starred but state the caveat —
  the bench significance (§7, hugely significant vs 3×SEM) is a *measurement*-significance
  finding, distinct from this *prediction-error* significance test.
- **Slide 9 (★2 hybrid stencil)** — Δ = **+65.6 mm AND +18 throws with zero coverage.** The
  coverage effect is the headline, not the mm delta; reframe the slide around "legacy loses more
  than half the campaign," with the mm number as a secondary point.
- **Slide 10 (★3 mid-echo + y=r_ball)** — **split this row.** Mid-echo alone: Δ ≈ 0.0 mm, not
  resolvable end-to-end at n = 34 (consistent with `IMPLEMENTATION_NOTES.md` finding C-1: real per-
  reading, averages out in the fit). y = r_ball alone: Δ = **+21.2 mm**, significant. Recommend the
  slide keep only "y = r_ball" as the starred, quantified fix, and demote mid-echo to the inventory
  table with the 19.13-vs-19.48 mm bench-agreement number as its (non-prediction-error) evidence.
- **Slide 11 (★4 Kalman + bias)** — **split this row.** Kalman alone: Δ = +4.3 mm, not
  significant. Bias model alone: Δ = **+27.9 mm**, significant — Production Note #1's worry ("its
  big validated numbers came from synthetic sessions with inflated drag") did **not** materialize;
  the bias model earns its star on real data. Recommend the slide keep only "track-aligned bias
  model" as the starred fix; demote the Kalman filter to the inventory table (its value is
  variable-dt robustness/dropout handling, not a resolvable landing-accuracy delta at this n).
- **Slide 12 (★5 ground truth)** — cannot be given a prediction-error Δ (it changes the truth
  reference, not the prediction — §4 does not apply). Keep starred, but change its evidence line
  to the truth-side quantity already in the deck (residual self-check / propagated σ from
  `sigma_tape_m`), not an "mm delta" framing.
- **Slide 13 (inventory table)** — fill the Δ column from §4.1 directly. **Recommended star
  reshuffle:** promote **Ball-radius R2 (+99.3 mm, by far the largest measured effect)** to a
  starred, headline row; it is currently a plain "Physical corrections" inventory line. Move
  per-sensor offset, temperature, sensor-height, Kalman, and mid-echo down to the plain inventory
  rows with their small/null Δ shown (still worth keeping — offset and height are bench-proven
  measurement-layer corrections independent of this prediction-error test).
- **Slide 15 (waterfall)** — use the **§3 matched 16-throw table** (133.3 → 88.1 → 57.8 mm, 57%)
  as the honest apples-to-apples waterfall, with a footnote that legacy failed to predict the
  other 18/34 throws entirely. Do not silently present the unmatched 34-throw corrected number
  (64.5 mm) next to the 16-throw legacy number (133.3 mm) without that footnote — an examiner will
  ask why n differs.
- **Slide 17 (conclusions)** — legacy → final: **133.3 → 57.8 mm (57%) on the matched subset**, or
  state both the matched improvement and the coverage finding (16/34 → 34/34) as two separate,
  clearly-labelled wins.

---

## 6. Provenance and reproducibility

- **Method:** two standalone, read-only Python scripts (`legacy_ablation.py`, `loo_ablation.py`),
  run against `.\venv\Scripts\python.exe`, reusing the real `pipeline/` modules
  (`corrections.py`, `trilateration.py`, `geometry.py`, `segmentation.py`, `background.py`,
  `kalman.py`, `landing.py`, `bias.py`) exactly as `pipeline/process_throw.py` does, but composing
  them with the legacy/LOO knobs described in §1/§4 instead of calling `process_session` directly.
  Ground truth and background calibration are read from each session's existing
  `session.json`/`background.json` — never recomputed or overwritten.
- **Validation:** the LOO baseline (§4, all corrections ON) reproduces the campaign's own recorded
  post-bias mean 2D error (64.5 mm, n = 34) to within numerical precision — this cross-check
  confirms the standalone harness is calling the same math the production pipeline uses.
  `.\venv\Scripts\pytest.exe` was re-run after this study (unmodified — no `pipeline/`,
  `scripts/`, or `tests/` files were changed) and remains **242 passed**.
- **Not written anywhere on disk except this file:** no `session.json`, `background.json`,
  `trajectory.csv`, `triplets_raw.csv`, `report.html`, or `campaign.html` was modified by either
  script. `correction_model.json` was read, never rewritten.
- **Provenance labels for slide use (per Production Note #2):** every number in §2–§4 is
  **"measured, n = 34 throws (ablation re-run, 2026-07-12)"** — campaign-measured, not simulation,
  not bench study. Do not present these numbers as identical in kind to the bench-measured sensor
  offsets (§7, n = 200) or the simulator-derived stencil/coverage figures already in the deck
  (the ~−24 → ~−12–15 mm number, the 93% ellipse coverage) — those remain separately labelled.
