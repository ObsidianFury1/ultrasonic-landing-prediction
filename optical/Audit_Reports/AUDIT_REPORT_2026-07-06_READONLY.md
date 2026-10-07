# Read-Only Audit Report — Optical Ground-Truth Landing Module

**Audit type:** Read-only review pass (no files modified, refactored, fixed, or created during the audit itself; this report is the only artifact).
**Date of audit:** 2026-07-06
**Auditor:** Claude (Fable 5), acting on an explicit read-only audit request.
**Subject:** The standalone Optical Ground-Truth Landing Module (spec = `Optical.md` / `CLAUDE.md`, currently at v1.3).
**Build state audited:** Phases 0–4 complete, WO-OPT-1 audit remediation (Stages 0–6) complete, WO-OPT-2 Phase 6a (Stages 0–3) complete. Phase 5 (physical commissioning) NOT yet executed; Phase 6b NOT yet executed.
**Purpose of this document:** A complete, self-contained record of the audit for downstream analysis by another agent/chat. It restates the method, the evidence examined, every finding ranked by severity, and the explicit limits of what code review alone can establish.

---

## 0. Scope, method, and provenance

### 0.1 What was requested

A read-only audit of everything built so far, with the following explicit constraints and structure:

1. **Context** — read `CLAUDE.md` (the spec) and `IMPLEMENTATION_NOTES_OPTICAL.md` in full, including every phase entry; build a mental model of what was specified, what was built, what judgment calls were made where the spec left room, and what deviations/problems were self-reported.
2. **Full codebase pass** — read every file under `optical/`, `simulator/`, `scripts/`, `tests/`, and `config.yaml`; check each module against the specific `CLAUDE.md` section it implements.
3. **Cross-cutting checks** — Zone violations (ML in geometry/parallax/contact), coupling to the main/parent project, silently-passing negative controls, uncertainty-by-unjustified-constant, unlogged silent fallbacks, placeholder config used as real, test-suite health (real numeric tolerances vs vacuous asserts), and any discrepancy between the notes' claims and the actual code.
4. **Run the existing test suite** (read-only) and report actual pass/fail plus whether the suite validates end-to-end correctness or only isolated units.
5. **Report back** structured as: overall assessment; major flaws (wrong landing / wrong uncertainty / false GO); moderate issues; minor/cosmetic; and explicit statements of what could NOT be verified by reading code alone.

**No fixes were implemented.** No `IMPLEMENTATION_NOTES_OPTICAL.md` or other file was created or edited as part of the audit. (This report file is produced only on the later explicit instruction to convert the spoken report into a `.md` file.)

### 0.2 Environment facts relevant to the audit

- OS: Windows 11; Shell: PowerShell. Python interpreter used for tests: `.\venv\Scripts\python.exe` (per spec §0, never bare `python`/`pytest`).
- Project is **not** a git repository (Decision O1: no version control; manual folder backups before each execution phase are the safety net).
- The venv contains `opencv-python 5.0.0.93`, `numpy 2.5.1`, and (from the Phase-6a ML install) `ultralytics 8.4.89` → `torch 2.12.1+cpu`, `torchvision 0.27.1+cpu`. Python 3.14.3.

### 0.3 Files examined (complete inventory)

Non-venv, non-cache project files read in full during the audit:

```
AUDIT_REPORT_PHASES_0-4.md          (prior audit, referenced by the spec's amendment history)
CHANGES_OPTICAL.md                  (staged work orders; referenced)
CLAUDE.md  (== Optical.md, v1.3)    (authoritative spec — read in full)
IMPLEMENTATION_NOTES_OPTICAL.md     (as-built record — read in full, all 993 lines)
config.yaml
requirements.txt
requirements-ml.txt

optical/__init__.py
optical/geometry.py
optical/errors.py
optical/calibration.py
optical/detect.py
optical/detect_ml.py
optical/track.py
optical/contact.py
optical/uncertainty.py
optical/io_session.py
optical/overlay.py

simulator/__init__.py
simulator/render.py
simulator/scenarios.py

scripts/__init__.py
scripts/calibrate_homography.py
scripts/calibrate_intrinsics.py
scripts/process_clip.py
scripts/validate_static.py
scripts/compare_detectors.py

tests/__init__.py
tests/conftest.py
tests/test_geometry.py
tests/test_simulator.py
tests/test_calibration.py
tests/test_detect.py
tests/test_track.py
tests/test_contact.py
tests/test_uncertainty.py
tests/test_end_to_end_synthetic.py
tests/test_io_session.py
tests/test_process_clip.py
tests/test_validate_static.py
tests/test_detect_ml.py
tests/test_ml_import_guard.py
tests/test_compare_detectors.py

data/comparison/compare_detectors_report.md      (Phase 6a Stage 2 draft output)
data/comparison/compare_detectors_results.json   (machine-readable results)
data/comparison/phase6a_comparison_report.md      (Phase 6a Stage 3 final report)
yolo11n.pt                                         (auto-downloaded YOLO weights, regenerable)
```

Grep sweeps were additionally run across the whole project for: external-path / parent-project coupling (`session.json`, `../`, `parents[2]`, absolute `C:\` paths, `sys.path.append`), and for the `check_point_fail` flag's producers/consumers.

### 0.4 What the module is (one paragraph, from the spec)

A single phone high-speed camera (OnePlus 12R baseline) films a tennis-ball throw over the ultrasonic triangle array. The module recovers the landing point on the floor — video in, `(r, θ)` out, no operator measurement — by planar-homography mapping of the tracked ball's contact point, with a first-contact instant bracketed/solved to sub-frame resolution. It is an **automation demonstrator and independent cross-validation instrument** for the main 3D ultrasonic projectile landing-prediction system; the three-tape multilateration protocol remains the metrological ground-truth reference. The module is **standalone**: its own directory, venv, tests, simulator; it never imports from, writes into, or modifies the main pipeline. The only planned coupling is a read-only consumer of the frozen `optical_gt.json` schema (§12).

---

## 1. The build history (as reconstructed from IMPLEMENTATION_NOTES_OPTICAL.md)

This section records what the notes claim was done, phase by phase, so the downstream analyst can compare claims against the code findings in later sections. Every claim below was checked against the actual code; discrepancies are called out in §5–§7.

### 1.1 Phase 0 — Scaffold (2026-07-05) — PASS, 14 tests

Directory tree, venv (Python 3.14.3), `requirements.txt` (exactly the §0.1 core ceiling: `opencv-python`, `numpy`, `matplotlib`, `pyyaml`, `pytest`), `config.yaml` (array geometry duplicated from main project with per-field source citations, ball radius, marker-survey placeholders, tolerances `check_point_tol_m: 0.005` and `rms_gate_m: 0.015`, HSV/tracking placeholders), `optical/geometry.py` + tests.

**Geometry convention (§2):** origin = triangle centroid on floor; +x toward S1 (θ=0 axis); +y up; +z right-handed; polar range half-open `(-180, 180]`. `cart_to_polar` folds the single `-180` boundary (reached from `z = -0.0`) to `+180`. Anchors verified: +x→0, +z→+90, −x→+180, −z→−90.

Noted risks: Python 3.14 dependency risk (resolved — wheels installed cleanly); pytest rootdir reported as the grandparent `...\Project` folder (benign; `conftest.py` injects the correct root).

### 1.2 Phase 1 — Simulator (2026-07-05) — PASS, 29 tests (14+15)

`simulator/render.py`, `simulator/scenarios.py`. Pinhole camera (OpenCV conventions), look-at construction, closed-form floor homography `H = K[R[:,0] | R[:,2] | t]`. Nominal pose: camera at `(3.5, 1.5, 0.0)` looking at `(0.4, 0, 0)` — inside the §3.1 envelope. HFOV 62°. 8 fiducials spread near/far/left/right; marker id 6 at `(0.2, -0.2)` is the held-out check point. Reference trajectory `p0=(0,0.9,0.3)`, `v0=(1.4,0.5,-0.9)` → contact at `t*≈0.4743 s`, landing `≈(0.664, -0.127)`.

**Sub-pixel validation numbers (gate run):** hand-computed nadir vs both code paths < 1e-9 px; disc-fiducial render→recover max 0.0807 px / mean 0.0481 px (tol 0.3); ArUco corner max error 0.8784 px (tol 1.0 — detector-bound); rendered ball centre vs truth 0.0221 px.

Judgment calls: two fiducial styles (real ArUco bitmaps + symmetric discs — discs carry the sub-pixel gate); sub-pixel rasterisation via OpenCV `shift=4` (1/16 px); sphere drawn as a circle (truth = what was drawn); no bounce in v1 (ball not drawn past `t*`, truth NaN there); blur/noise/shadow magnitudes are scenario config, not physics claims.

### 1.3 Phase 2 — Calibration chain (2026-07-05) — PASS, 44 tests (29+15)

`optical/calibration.py`, `scripts/calibrate_homography.py`, `scripts/calibrate_intrinsics.py`.

Direction convention: calibrated `H` maps **pixels → floor (x,z) metres**; simulator's `H_true` is floor→pixel (inverses). ArUco detection (`DICT_4X4_50`); marker position = centroid of 4 corners. Plain-LS fit (`cv2.findHomography, method=0`), no RANSAC. Reprojection RMS in px. Held-out check point mandatory; error above tol → loud `UserWarning` + `check_point_fail` flag, never silent, never an abort. Stability re-check (start vs end frame). Atomic YAML writes.

**Validation numbers:** exact-correspondence fit RMS ≈ 2.2e-5 px, grid error < 1e-6 m. Nominal full synthetic calibration: reproj RMS 0.179 px, check-point error 3.94 mm (tol 5), fitted-H grid max 4.21 mm. Negative control (corrupted survey, markers 0/1/3 off by 3–4 cm): reproj RMS jumps to 6.2 px, held-out error 19.7 mm > 5 → warning + flag. Stability: 6 cm camera bump → 64.0 mm drift → flagged; still camera → < 2 mm. Intrinsics corner-level: fx rel err 1.0e-7, k1 abs err 4.4e-7. Intrinsics image-level (zero distortion): fx rel err 0.11%.

Problems found + fixed (both caught by tests): `cv2.findHomography` computes in float32 (tolerance re-justified honestly rather than replacing OpenCV); collinear markers do NOT make `findHomography` return None (it returns finite garbage) — added `_assert_noncollinear` (2nd singular value of centred cloud, relative threshold 1e-8) on BOTH point sets before fitting.

### 1.4 Phase 3 — Measurement chain (2026-07-05) — PASS, 93 tests (44+49)

`optical/detect.py`, `optical/track.py`, `optical/contact.py`, `optical/uncertainty.py`; `optical/geometry.py` gained `CameraGeometry`, `decompose_camera`, `estimate_camera_position`, `parallax_correct`, `reconstruct_world_point`. Parallax lives in `geometry.py`, not a dedicated module (flagged deviation — §5's module list has none). Simulator gained `ball_world_position` (first-bounce arc, default restitution 0.0 = vanish) and a truth `ball_bottom_px` (true 3D bottom pole).

**Parameters chosen:** HSV band [25,60,60]–[45,255,255]; morphology open 3×3 then close 5×5; area band [30, 20000] px²; circularity ≥ 0.6; largest plausible blob wins; `radius_px = minEnclosingCircle`. Tracking `max_jump_px 150`, gap-scaled. Descent: last 8–12 (config 10) frames of rising image-v before FIRST reversal/track-end. Contact fits: degree 2 when ≥ 6 frames else degree 1.

**Measured landing errors:** contact fit on EXACT truth track: t* error 0.16 frame, landing 3.1 mm. Camera-position decomposition from exact H+K: 1.2e-15 m; from fitted H: 12.2 mm. End-to-end: nominal/true-H 7.2 mm, nominal/fitted 9.6 mm, blurred 7.5, shadowed 7.3, low-contrast 7.4, dropouts 7.2 mm; corrupted-survey control 141 mm (flagged); no-ball → clean "no ball track" ValueError. Detector localisation scatter ≈ 0.1 px.

**Contact-time solve — three designs tried, two rejected (load-bearing history):**
1. **Image-vertical crossing** (`v_bot = v_floor`) — REJECTED: detected silhouette bottom inflated ~1–2 px by mask morphology vs the true 3D bottom pole; the crossing is ill-posed and often has no real root.
2. **Apparent-size height reconstruction** (`depth = fx·r_ball/r_px`) — exact on noise-free truth but REJECTED as primary: the ball's pixel radius changes only ~0.05 px across the ~10-frame window while the detector radius carries a ~0.9 px bias → signal-starved; drove t* off by ~26 frames on detected data. Geometry retained (`reconstruct_world_point`) dormant.
3. **Bounce reversal-apex** (parabola vertex of image-v) — REJECTED: under an oblique camera the image-v extremum is offset ~1 frame from the world-height minimum → ~20 mm landing error.

**Adopted: the descent-end BRACKET.** t* = last-descent-frame + 0.5 frame; σ_t = one frame / √12. Key finding: landing accuracy is dominated by the clean sub-pixel centroid track, not by t*; the ~7 mm residual on zero-noise nominal is the ±0.5-frame quantisation, far inside the 15 mm gate. Landing = centroid PIXEL track fitted, evaluated at t*, mapped through H, then parallax-corrected ONCE with r_ball.

Also flagged: lowest-pixel fallback is CLOSER to truth here (3.4 mm) than analytic centroid (7.2 mm) because a near-floor feature is less t*-sensitive — but §5.4 keeps analytic primary (more robust FEATURE under real blur/shadow); the dual-method commissioning cross-check exists to surface this on real footage.

### 1.5 Phase 4 — Outputs and workflow (2026-07-05) — PASS, 115 tests (93+22)

`optical/io_session.py` (frozen schema build/validate/atomic-write, `FLAG_VOCAB`), `optical/overlay.py`, `scripts/process_clip.py`, `scripts/validate_static.py`. Simulator gained `render_static_scene`.

Frozen top-level keys asserted verbatim. Byte-stable round-trip verified. Atomic write = temp + fsync + `os.replace`; validate before write; crash-tolerance test (stale `.tmp` of garbage leaves the real file valid). Failure mode: no ball / no descent / < 4 frames → valid `optical_gt` with `landing: null` + `no_prediction` + reason in notes; never raises for a data-shape problem, never fabricates a landing.

**Static validation:** resting synthetic ball recovered to 0.21 mm at one point; RMS 0.58 mm over 8 spread points → GO (gate 15 mm). GO/NO-GO logic tested exactly (< 8 points → INSUFFICIENT/NO-GO even at zero error; RMS above gate → NO-GO).

Flagged for Phase 5: `min_fit_points` hard-coded (≥ 4 frames); no `landing:` block in this config (that key lives in the main project); mp4v round-trip is lossy (prefer processing raw.mp4 directly); `main` writes the day manifest under real `data/manifests/`; camera K falls back to fx-from-60°-HFOV when `--intrinsics` omitted (smoke-testing only).

### 1.6 WO-OPT-1 — Audit Remediation (2026-07-06)

Triggered by `AUDIT_REPORT_PHASES_0-4.md` (115/115 passing at audit time). Six stages:

- **Stage 0 (doc-only):** spec v1.0 → v1.1. §5.5 rewritten to the as-built ±0.5-frame bracket (M5); §7 item 1 annotated (raw isotropic survey σ, conservative, full propagation deferred to §13, Decision D5); §5.6 vocabulary extended additively (`fallback_intrinsics`, `fps_mismatch`, `unmeasured_uncertainty_components`, `stability_unchecked`); §3.2 gained `capture.fps_tol_pct` (0.5% placeholder). No code touched.
- **Stage 1 (M1):** `uncertainty:` block added to config (four `{value, measured}` pairs, all `measured: false`); `read_uncertainty_config()` hard-errors on missing block/key/malformed entry; `process_clip` + `validate_static` read the four budget inputs only from that block; `sigma_C_m` and `rolling_shutter_m` now passed into `build_budget` (previously silently zero); `unmeasured_uncertainty_components` flag + `UserWarning` + notes echo when any consumed component is a placeholder. 115 → 122 tests.
- **Stage 2 (M2):** `capture.fps_tol_pct: 0.5` added to config; `read_container_fps()` reads `CAP_PROP_FPS`; `resolve_fps()` precedence `--fps-measured > container > refuse` (nominal NEVER used for timing); mismatch = any two available rates differ > tol% of mean → `fps_mismatch` + warn + continue. 122 → 127.
- **Stage 3 (M3):** `detect_check_point_pixel()` + `stability_between_frames()` reusable core; `process_clip.evaluate_stability()` runs the drift re-check every run (checks and reports, or flags `stability_unchecked`); `validate_static.session_stability()` spans the full §8 gate session. 127 → 133.
- **Stage 4 (M4) — HALTED at the 4.3 gate, then resolved:** added `bounce` (restitution 0.75, nominal cam) and `bounce_oblique` (~12° elevation). Measured the v1.1 bracket on a **reversal** end: `bounce` 10.12 mm, `bounce_oblique` 17.62 mm (OVER the 15 mm gate), vs vanish reference 7.22 mm. The bracket runs ~0.63 frame late on a bounce because the last descending frame IS touchdown. Per the gate stop rule, execution halted and the anchor-semantics decision was escalated. **Decision D8 (Hari-delegated): the kink-intersection solve.** The ball's image position is continuous through the bounce; only vertical velocity flips sign, so image-v(t) is a rising branch meeting a falling branch in a kink exactly at contact, invariant to camera obliquity. `min_rise` confirmed-reversal rule (default 2) added to `track.py`; `_reversal_kink_offset()` + t*-selection restructure in `contact.py`; peak-anchor fallback when unsolvable; `contact_time_kink` flag. **Measured after fix:** `bounce` 10.12 → 0.15 mm, `bounce_oblique` 17.62 → 0.51 mm (34× improvement), ≤ 0.70 mm across noise/blur/shadow, t* error ≤ 0.04 frame; `track_end` path bit-identical. 134+1xfail → 141 passed, 0 xfail.
- **Stage 5 (Moderate findings):** typed errors (`OpticalError(ValueError)` base, `OpticalDataError`, `OpticalConfigError`); `run_clip_pipeline`'s catch narrowed from `except ValueError` to `except OpticalDataError` (a config error now propagates and kills the run); `resolve_camera_K()` fallback-intrinsics gating (opt-in `--allow-fallback-intrinsics` + `fallback_intrinsics` flag + warn; hard error otherwise); real `validate_static` CLI over an on-disk gate tree, forces NO-GO on drift; `conditioning_ratio()` + soft `cond_warn` band (ratio < 0.05); `blur_suspected` deferred to Phase 5; `trimmed_undistorted.mp4` rename. 141 → 149.
- **Stage 6 (punch list):** contact docstring rewritten; vestigial `ContactResult.fit_rms_v_px` removed; persistent detection ambiguity (≥ 2 ambiguous frames) sets `detection_gaps`; manifest dedup key documented as `session_id`; synthetic-hue caveat comment added; rootdir quirk left as-is. 149 → 150.
- **CLOSEOUT:** 150 passed, 0 failed, 0 xfail, 3 warnings. Spec advanced v1.0 → v1.1 → v1.2. All audit findings M1–M5 + eight Moderate + Minor punch list addressed. Backups taken before each stage.

### 1.7 WO-OPT-2 — Phase 6 split (2026-07-06)

- **Stage 0 (doc-only):** spec v1.2 → v1.3. §10/§14/§15 amended for the Phase 6a/6b split (Decision O17). **Key state recorded:** Phase 5 physical commissioning has NOT been executed — a *not-yet-run* state, explicitly distinct from a formal NO-GO. Suite unchanged at 150.
- **Stage 1 (Phase 6a part 1):** `requirements-ml.txt` (pins `ultralytics==8.4.89`); `optical/detect_ml.py` (`YoloDetector`, `MLDetectorUnavailable`, `COCO_SPORTS_BALL=32`); `tests/test_detect_ml.py` (8 tests, `importorskip`); `tests/test_ml_import_guard.py` (subprocess). `Detection` gained an additive defaulted `confidence` field. Model `yolo11n.pt` (~2.6 M params, 5.35 MB); venv footprint +~816 MB. 150 → 159. Deviations flagged: `confidence` field added; `imgsz=640` (not native 1280); model is yolo11n not yolov8n; test conf 0.02 vs config default 0.25; weights auto-download to project root.
- **Stage 2 (Phase 6a part 2):** `scripts/compare_detectors.py` (ablation harness); comparison runs on the TRUE simulator homography (detector is the only variable); production `run_clip_pipeline` left untouched. Metrics: detection rate, localisation scatter, end-to-end landing, CPU inference time (204 frames), confidence sweep, negative-control roll-up. **Both detectors clean on no_ball (0 false positives).** HSV 7.2–7.5 mm vanish / 0.15–0.51 mm bounce / 27.7 mm grazing; ML zero-shot detection 0.00–0.71, landing 5.65 mm (bounce) to catastrophic (768 mm shadowed, 1479 mm grazing, no-prediction on low_contrast); runtime HSV 3.86 ms vs ML 40.71 ms/frame. 159 → 166.
- **Stage 3 (Phase 6a closeout):** final report `phase6a_comparison_report.md` with mandatory watermark "SYNTHETIC-ONLY — NOT EVIDENTIARY FOR COMMISSIONING" + HSV-optimism caveat (synthetic hue H=35 dead-centre of the config band H 25–45). Aggregate landing RMS: HSV 10.99 mm, ML 591 mm. 166 → 168. Spec↔code consistency confirmed, zero corrections needed.

### 1.8 Decision register (from the notes closeout)

| # | Decision | Resolution |
|---|----------|-----------|
| D1 | fps mismatch tolerance | `capture.fps_tol_pct = 0.5` (placeholder; tighten after C1) |
| D2 | fps mismatch behaviour | flag + warn + continue (raw data sacred; no hard fail) |
| D3 | fallback intrinsics | opt-in `--allow-fallback-intrinsics` + flag; hard error otherwise |
| D4 | synthetic restitution | 0.75, parameterized |
| D5 | §7 marker-survey deviation | conservative isotropic constant accepted; full fit-propagation → §13 |
| D6 | `blur_suspected` | deferred to Phase 5 (reserved flag); `trimmed_undistorted.mp4` rename |
| D7 | new `stability_unchecked` flag | added to vocabulary (additive) |
| D8 | reversal-anchor semantics | Kink-intersection solve adopted; measured 0.15 / 0.51 mm |

---

## 2. Test-suite execution result (Step 4)

Command: `.\venv\Scripts\python.exe -m pytest tests -q`

**Result: 168 passed, 0 failed, 0 xfail, 3 warnings, in 153.82 s (2m 34s).**

This exactly matches the IMPLEMENTATION_NOTES closeout claim of 168 passing. The 3 warnings are the intended `UNMEASURED UNCERTAINTY COMPONENTS` `UserWarning`s emitted by three `test_process_clip.py` tests that deliberately run the placeholder config — the flag machinery working, not a defect. (The warning text renders `§` as a mojibake `�` in the Windows console; cosmetic only.)

### 2.1 Does the suite validate end-to-end correctness or only units?

**Both, genuinely.** The standing regression anchor is `tests/test_end_to_end_synthetic.py`, which runs the FULL chain (render → HSV detect → track → descent → sub-frame contact → parallax → landing) against exact injected truth for: nominal (true-H and fitted-calibration variants), blurred, shadowed, low-contrast, dropouts, bounce (nominal + oblique + noisy), plus the two mandatory negative controls (no-ball never fabricates; corrupted survey trips the guard AND materially poisons the landing). Unit tests cover each module in isolation with numeric tolerances. The import-guard test independently re-runs the entire core suite in a subprocess with `ultralytics`/`torch`/`torchvision` import-blocked and asserts rc=0 — proving the core's independence from the ML stack rather than assuming it.

### 2.2 Test-count reconciliation

Prior audit baseline 115 → WO-OPT-1 closeout 150 → WO-OPT-2 Stage 1 159 → Stage 2 166 → Stage 3 168. The +18 over WO-OPT-1: 8 `test_detect_ml` + 1 `test_ml_import_guard` (Stage 1) + 9 `test_compare_detectors` (Stages 2–3). Core suite is still 150 (the ML-gated tests skip or are excluded when the stack is absent).

---

## 3. Overall assessment

**The pipeline is logically sound and does what CLAUDE.md intends, end to end.** This is an unusually spec-faithful codebase: the notes' claims match the code in every case checked, deviations are surfaced rather than buried, and the tests genuinely validate end-to-end correctness. Concretely:

- **The math is correct (verified by hand, not just by test):**
  - The parallax closed form (§5.4) `P_floor = P_mapped − (h/C_y)(P_mapped − C_ground)` is the exact ray–plane inversion; it is additionally checked against exact synthetic geometry to < 1e-9 m.
  - The camera decomposition `H_f2p = K[r1 | r3 | t]` (world +y is the floor normal, so columns 1 and 3 of R appear) is the correct floor-plane factorisation; the sign is fixed by `C_y > 0`; recovery from exact H+K is < 1e-6 m.
  - The uncertainty partials — parallax σ (`dP/dh`, `dP/dC_y`, `dP/dC_ground`), polar σ propagation (`σ_r`, `σ_θ`), and the local pixel-scale Jacobian by central differences — are all correct and cross-checked against Monte-Carlo references at the 5% level.
  - Geometry polar conversions round-trip to 1e-12 with the `(-180, 180]` boundary handled correctly from both sign-of-zero sides.
- **All five §7 budget components are implemented and combined in quadrature** (`uncertainty.py` `build_budget`, per-axis where a direction exists, isotropic for the two scalar empirical proxies). `sigma_C_m` and `rolling_shutter_m` demonstrably grow the final numbers at the orchestrator level, not just inside the pure function.
- **The frozen §5.6 schema matches the spec verbatim**; writes are genuinely atomic (temp + fsync + `os.replace`) with a crash-tolerance test; `FLAG_VOCAB` matches the amended spec vocabulary exactly (all 14 entries).
- **Zone rules hold and the project is standalone:** `detect_ml.py` imports only `numpy` + the `Detection` dataclass; no core module imports `ultralytics`/`torch` at load time (proven by the subprocess import-guard). A project-wide grep for `session.json`, `../`, `parents[2]`, absolute `C:\` paths, and `sys.path.append` found only venv-internal and matplotlib-internal hits — **no coupling to the main/parent project**. Shared constants are duplicated into `config.yaml` with source-section citations, per §12's "duplication over coupling."
- **Negative controls are load-bearing, not decorative:** the corrupted-survey test asserts BOTH that the guard trips loudly AND that the resulting landing is materially wrong (> 5 mm); the no-ball test asserts a clean failure with no fabricated landing.

**Bottom line:** software-side, the module is ready for Phase 5 in its current state. Nothing found suggests the measured commissioning-rehearsal numbers (0.58 mm static RMS; 0.15–0.51 mm bounce landing) are artifacts of a bug.

---

## 4. Major flaws (would produce a wrong landing, a wrong uncertainty, or a false GO)

**No confirmed defect produces a wrong number on the paths the software controls.** The two findings below are the closest to "major"; both are false-*negative* guard gaps (a bad condition passing undetected), not wrong-arithmetic paths. They are ranked most-severe first.

### 4.1 A camera bump between calibration and the clip passes the stability check undetected

- **Where:** `optical/calibration.py` → `stability_check` (the `StabilityResult` computes `err_start_m`, `err_end_m`, `drift_m`, `drifted`), consumed by `process_clip.evaluate_stability` and `validate_static.session_stability`.
- **Mechanism:** Only **drift** (start-frame mapping vs end-frame mapping) is thresholded against `check_point_tol_m` and flagged (`homography_drift`). `err_start_m` — the check point mapped through the session's H at the *start* frame vs its surveyed position, i.e. the absolute correctness of the calibration at the moment the clip begins — is **computed and then discarded**. If the tripod is bumped *after* the calibration frame is captured but *before* the throw clip starts, and then stays still through the clip, drift ≈ 0 → no flag, and every landing from that session is systematically wrong while the JSON looks clean.
- **Why it matters:** the whole point of the §5.1 integrity philosophy (mirroring the main project's `ls_residual_m` guard) is that a bad calibration cannot pass silently. The data to catch this is already in hand; thresholding `err_start_m` (and `err_end_m`) against `check_point_tol_m` is a near-free fix.
- **Scope of exposure:** the C7 static gate itself is protected — a bad H shows up directly in the static-point RMS, so this cannot cause a false GO. The exposure is **campaign throws after commissioning**, where a mid-session bump is exactly the audit's flagged concern.
- **Nature:** the code implements §5.1 step 5 *as written* (the spec defines the re-check as start-vs-end drift). So this is a **spec-design gap**, not an implementation bug — per §0.2 it needs a one-line spec amendment before the ~5-line code change.

### 4.2 A grossly wrong temporal base is flagged but still used

- **Where:** `scripts/process_clip.py` → `resolve_fps` (Decision D2: flag-and-continue).
- **Mechanism:** precedence is `--fps-measured` > container `CAP_PROP_FPS` > refuse; nominal is never used for timing. A mismatch beyond `fps_tol_pct` (0.5%) sets `fps_mismatch` + warns, but the run **continues** and writes a landing.
- **Why it matters:** real phone slow-mo containers sometimes store the *playback* rate (e.g., 30 fps) rather than the capture rate. If the operator forgets `--fps-measured`, the pipeline times a 480 fps clip at 30 fps — a ~16× wrong temporal base — emits `fps_mismatch`, and still writes a landing whose `temporal_m` and `t*` are garbage. A 0.5% drift and a 16× error are qualitatively different, but the code treats them the same way.
- **Recommendation:** a hard refuse (`OpticalConfigError`) above a generous sanity band (e.g., used-rate vs nominal disagreeing by > 10–20%), keeping flag-and-continue *inside* that band. Until then, the field procedure must treat `--fps-measured` as mandatory (the Stage 2 hand-off note says so, but nothing enforces it).

---

## 5. Moderate issues (work, but fragile / under-tested / diverge from spec; fix before Phase 5)

### 5.1 `check_point_fail` never reaches the per-throw JSON

`process_clip.main` propagates calibration flags with `[f for f in calib.flags if f in io_session.FLAG_VOCAB]`. But `check_point_fail` (defined as `CHECK_POINT_FAIL_FLAG` in `calibration.py`) is **not** in `FLAG_VOCAB`, so a throw processed against a guard-tripped calibration carries **no** quality flag marking that fact. It remains discoverable — the warning fired once at calibration time, `check_point_ok: false` sits in the calib YAML, and `check_point_err_m` is echoed into each JSON — but it is not machine-flagged the way `cond_warn` is. Fix: add `check_point_fail` to the vocabulary (additive, O7-compliant, one-line §5.6 amendment).

### 5.2 `markers.survey_sigma_m` is a placeholder outside the unmeasured-flag machinery

The four `uncertainty:` block components carry `{value, measured}` and trigger `unmeasured_uncertainty_components`; the survey σ (0.0025, a placeholder per its own comment) feeds the budget (`marker_survey_m`) with no such marker. In practice C4 forces a real survey before any real run (the empty-`fit_points` guard in `survey_from_config`), and the surveyor would presumably record the real σ then — but nothing enforces or flags it. Inconsistent with the Stage 1 "no placeholder consumed silently" philosophy.

### 5.3 `process_clip.main()` is not covered by automated tests

`run_clip_pipeline` and every helper (`resolve_fps`, `resolve_camera_K`, `evaluate_stability`, `append_manifest`, `read_container_fps`, `load_clip_frames`, `write_trimmed`) are well tested individually, but the `main()` wiring — the order in which `extra_flags` accumulate (fps → fallback-intrinsics → calib flags → stability), the overlay-frame selection (`frames[contact.t_frame]` vs `frames[-1]`), and the manifest write to the real `data/manifests/` — is verified only by the Phase 4 manual demo. The notes cite the real-manifest side-effect as the reason for not testing `main()`. A `main()` test (with a manifest-path override or `tmp_path` redirection) would close the gap; as is, a wiring regression in `main()` would not be caught by the suite.

### 5.4 `_quality_flags` silently filters unknown flags

`process_clip._quality_flags` keeps only in-vocabulary flags from `descent.flags` and `contact.flags`. Today every producer is in-vocab, so nothing is lost — but a future producer typo would vanish silently instead of tripping `build_optical_gt`'s loud unknown-flag `ValueError`. Inverting the behaviour (let unknown flags through so the writer rejects them loudly) would match the project's fail-loud philosophy.

### 5.5 No tooling for the §5.4 tape cross-check of camera position

The spec says camera C is "decomposed from H + intrinsics, **refined by a direct measurement** of camera height and horizontal distance with the tape — record both." The code only decomposes (`decompose_camera` / `estimate_camera_position`); there is no input path for a tape-measured C nor a recorded comparison of decomposed-vs-measured. It is a commissioning-procedure item, but currently that comparison would have to happen entirely off-tool. Worth a small hook (or at least an explicit C3 checklist line) before Phase 5.

### 5.6 Unconfirmed reversal at the very end of a clip degrades to the biased bracket

`find_descent`'s `_reversal_confirmed` requires `min_rise` (default 2) consecutive non-increasing image-v steps with a net strict decrease. If a clip ends 0–1 frames after the bounce peak, confirmation fails, the descent ends as `track_end`, and the +0.5-frame bracket is applied *after* the peak — reintroducing the ~0.5-frame late bias that M4 measured, silently (the flag reads `contact_time_bracket`, which is the "correct" semantics for a true vanish, so nothing signals that this was actually a truncated bounce). Real clips should carry plenty of rebound frames, so exposure is low, but the trim procedure should be documented to always include ≥ 3 post-bounce frames. (This is the flip side of the otherwise-correct §5.3 `min_rise` robustness rule.)

---

## 6. Minor / cosmetic (would not block Phase 5)

- **`test_read_container_fps_positive_and_none`** asserts `fps is None or fps > 0` — effectively a tautology for the readable-clip half; it can only fail on a negative rate. The one genuinely weak assertion in an otherwise rigorous suite.
- **`decompose_camera` SVD snap** uses `R = U @ Vt` without the `det=+1` correction (`R = U · diag(1, 1, det(U·Vt)) · Vt`). For near-rotation inputs (the tested regime) it is fine, but it is not the reflection-safe textbook form; a badly-conditioned fit could in principle snap to a reflection.
- **`validate_schema`** enforces top-level keys, `schema_version`, and flag vocabulary, but not nested-key presence (`clip.mode`, `landing.x_m`, `contact.t_frame`, …). The frozen contract is enforced fully at *build* time and loosely at *read* time; `overlay.summary_text` would `KeyError` on a hand-built dict missing nested keys rather than raising a schema error.
- **Spec module tree (§5) is stale:** it does not list `errors.py` (added Stage 5) or `detect_ml.py` (added Phase 6a). Both additions are recorded in the notes, but the tree itself was never amended — a two-line doc fix.
- **§9 manifest content divergence:** the spec lists wind/lighting notes and operator initials as manifest fields and says `process_clip.py` writes them "interactively"; the implementation writes a non-interactive entry with a generic `notes` field and no initials/wind/lighting fields. Fields can be added additively; low risk.
- **Overlay tests** assert file existence, byte size (> 1000 / > 1 KB), and summary-text substrings, not rendered pixel content — acceptable for a PNG artifact, noted for completeness.
- **Repo hygiene:** `yolo11n.pt` at the project root and the committed `data/comparison/` outputs are regenerable artifacts living alongside the sacred `data/optical/` tree; harmless, but worth a line in the data-hygiene notes.
- **pytest rootdir quirk** (reports the grandparent `...\Project` folder as rootdir because there is no `pyproject.toml`/`pytest.ini`) is still present and still benign; recorded since Phase 0.
- **Console mojibake:** the `§` symbol in warnings renders as `�` in the Windows PowerShell console (encoding, not a logic issue).

---

## 7. Explicit limits — what could NOT be verified by reading code

These are outside the reach of a code audit and align with the audit-report Section 6 / Phase 5 hand-offs. The code is *structured* to absorb them; the audit does **not** establish that the real-world values will hold.

- **HSV band on real footage.** The synthetic tennis-ball hue sits dead-centre of the config band by construction (self-documented in `simulator/render.py::tennis_ball_bgr`, H=35 vs band H 25–45). Every synthetic detection number is therefore structurally optimistic for HSV. Real sun/shadow/ball-wear tuning is checklist step C6. The shadowed-scenario test proves the *mechanism* (low saturation excludes the shadow ellipse from the mask), not the real thresholds.
- **Real intrinsics and lens distortion.** The image-path intrinsics flow is unit-tested only at *zero* distortion (stated and justified — rendering a distorted checkerboard needs a nonlinear remap, not a homography warp). Nonzero-distortion recovery through real photographs and corner detectability under real print quality/lighting are checklist step C2.
- **Rolling-shutter magnitude, real pixel-localisation scatter, camera-position σ** — all currently placeholder `measured: false` values. The flag machinery correctly taints every output (`unmeasured_uncertainty_components`) until each is measured and flipped to `measured: true` at C6/C5/§3.2.
- **Container/codec behaviour of real phone footage.** `CAP_PROP_FPS` semantics for OnePlus 12R slow-mo files (directly relevant to §4.2 above), and `CAP_PROP_POS_FRAMES` seek accuracy on real HEVC — the trim path (`load_clip_frames` with `--in/--out`) assumes frame-exact seeking, which some codecs/containers do not honour. The §3.2 frame-rate verification (C1) and the §9 post-transfer metadata check exist precisely to catch this, but they are human-procedure steps not yet executed.
- **The kink solve's assumptions on real bounces.** The rebound is fitted as *linear* in image-v over a few frames — exact for the simulator's idealised constant-restitution model. Spin, deformation, and real surface compliance on paving could bend the rebound branch. σ_t is deliberately kept at the conservative `(1/fps)/√12` pending real-footage residuals, which is the correct posture.
- **ArUco detectability** at real print quality, floor texture, oblique sun, and the cropped slow-mo FOV — checklist steps C4/C5, plus the §3.1 [C0] phone re-verification gate.
- **Phase 5 GO/NO-GO itself.** No fieldwork has occurred; there is no §8 verdict. The state is *not-yet-run*, explicitly distinct from a formal NO-GO (spec v1.3). Phase 6b (real-footage ablation) is correctly gated behind this and must not begin without a new work order quoting the [C0] device verdict and the §8 result.

---

## 8. Recommended action ordering (for the analyst / next executor)

Software-side, the module is ready for Phase 5. Before fieldwork, the highest-value fixes are, in order:

1. **§4.1** — threshold `err_start_m` (and `err_end_m`) against `check_point_tol_m` so a pre-clip camera bump is caught, not just mid-clip drift. Requires a one-line §5.1 spec amendment (the re-check is currently defined as drift-only) + ~5 lines of code.
2. **§4.2** — add an fps sanity band above which `resolve_fps` hard-refuses instead of flag-and-continue, or make `--fps-measured` mandatory in the field procedure.
3. **§5.1** — add `check_point_fail` to `FLAG_VOCAB` (additive, O7-safe) so a guard-tripped calibration taints every downstream throw's JSON.

Everything in §5.2–§5.6 and §6 can ride along or wait. None of it changes a computed number today; they are robustness, coverage, and spec-consistency items.

---

## 9. One-line verdict

A rigorously built, spec-faithful, well-tested standalone module whose mathematics and end-to-end behaviour are correct on every synthetic path checked; the only pre-commissioning concerns are three false-negative guard/enforcement gaps (a pre-clip camera bump, a grossly-wrong fps, and an unpropagated `check_point_fail` flag), all cheap to close, none of which can cause a false GO at the C7 gate. The genuine unknowns are all real-world quantities (HSV band, intrinsics/distortion, pixel scatter, rolling shutter, codec fps/seek behaviour) that only Phase 5 hardware can settle — and the code is correctly structured, and correctly flagged, to absorb them.
