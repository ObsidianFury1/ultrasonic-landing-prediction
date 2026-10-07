# Optical.md (v1.6) — Optical Ground-Truth Landing Module — PROJECT CLOSED (Phase 5: NO-GO)

> **STATUS (2026-07-11): Phase 5 physical commissioning is COMPLETE. Verdict: NO-GO** against
> the pre-registered §8 gate (RMS ≤ 15 mm over ≥ 8 static points). Measured RMS 64.4 mm
> as-captured (55.3 mm best-case diagnostic), both ≥3× the gate. The gate was **not**
> renegotiated. Per §8, this is reported as a **characterised negative result with its
> diagnosis** — no campaign integration is attempted. Full detail: `Phase5_Commissioning_
> Report_2026-07-11.md` and `IMPLEMENTATION_NOTES_OPTICAL.md`'s Phase 5 / closeout entries.
> This project is closed as of this result; see §16 v1.6 for the closeout changelog entry.

**Project:** Measurements for Mechanical Engineering (Politecnico di Milano, A.Y. 2025–26).
A single phone high-speed camera (OnePlus 12R) films a basketball throw over the ultrasonic
triangle array. From the footage, this module recovers the landing point on the floor —
video in, (r, θ) out, no operator measurement — by planar homography mapping of the tracked
ball's contact point, with a first-contact instant bracketed to sub-frame resolution (§5.5).
[AMENDED v1.5 — D17; was: tennis-ball throw]

**Purpose.** This module is an **automation demonstrator and independent cross-validation
instrument** for the main 3D Ultrasonic Projectile Landing-Prediction System. The three-tape
multilateration protocol (main project CLAUDE.md §5.5–5.6, G1) remains the metrological
ground-truth reference. This module demonstrates that ground-truth acquisition *could* be
fully automated, and quantifies how close the automated path gets to the reference. A small
measured disagreement makes integration a documented option; a large one is a characterised
limitation. Either outcome is a valid measurement-engineering result.

**This is a standalone project.** It has its own directory, virtual environment, test suite,
simulator, and version control. It never imports from, writes into, or modifies the main
pipeline. The only planned coupling is the read-only integration contract in §12.

This file is the authoritative build specification for the optical module. Where it conflicts
with the discussion draft PDF (`Camera_GroundTruth_Proposal.pdf`), **this file wins**. Note
in particular: the draft references the retired "two-tape" protocol; the reference protocol
is the **three-reference (centroid + two sensors) least-squares multilateration** built in
main-project v2.5 (IMPLEMENTATION_NOTES Part 9).

---

## §0 Development Environment

- OS: Windows. Shell: PowerShell.
- Project root: a **separate directory** from the main project (e.g. `optical-gt/`),
  with its **own virtual environment**.
- Python interpreter: `.\venv\Scripts\python.exe`. Always use the venv interpreter for every
  command. Never bare `python` or `pytest`.
- Run tests as: `.\venv\Scripts\pytest.exe` or `.\venv\Scripts\python.exe -m pytest`.
- Use `pathlib.Path` throughout for Windows compatibility.
- **Version control (O1):** **No git.** This project matches the main project's no-version-control
  status. Take a **manual folder backup of the whole project directory before every execution
  prompt** (i.e. before any AI or human executor begins a phase that edits files). Backups are the
  safety net; there is no commit history to fall back on.

### §0.1 Dependency ceiling

Core (Phases 0–5): `opencv-python`, `numpy`, `matplotlib`, `pyyaml`, `pytest`.
Nothing else without a spec amendment.

Optional gated ML phase (Phase 6a/6b only, droppable without trace): `ultralytics` (pinned
version recorded in `requirements-ml.txt`; pulls in PyTorch — install only if the ML phase
is executed). Core phases must never import from it.
[AMENDED v1.3 — Phase 6 split; see §16]

### §0.2 Documentation discipline (mirrors the main project)

- `Optical.md` (this file) — authoritative spec. Amend before building, never after.
- `IMPLEMENTATION_NOTES_OPTICAL.md` — as-built record: per-phase files touched, problems,
  deviations, test counts.
- `CHANGES_OPTICAL.md` — staged work orders beyond the initial build (§14 is the initial
  work order and lives here in the spec for self-containment).
- Section numbers (§) are the citation standard in all discussion and documents.

---

## §1 Scope and Non-Goals

**In scope (v1):**
- Landing point (x, z) → (r, θ) in the array frame, from one fixed camera, per throw.
- Per-throw uncertainty (σ_x, σ_z, σ_r, σ_θ) from a propagated budget (§7).
- Full commissioning procedure with a pre-registered GO/NO-GO accuracy gate (§8).
- Simulator-first validation against exact synthetic ground truth (§6).
- Optional, gated, droppable ML-detector comparison study (§10).

**Out of scope (v1) — recorded so nobody scope-creeps silently:**
- Full 3D trajectory recovery (requires stereo; §13 Future Works).
- Validation of the Kalman filter or any main-pipeline internals.
- Real-time operation. Everything is offline post-processing.
- Automated throw detection / clip trimming (manual trim in v1; §13).
- Any write into the main project's `session.json` or data tree (§12).
- ML anywhere in the *measurement geometry* (§10 Zone rules).

---

## §2 Coordinate and Geometry Contract

- **Array frame (O2 — contract):** all module outputs are expressed in the main project's
  array coordinate frame — origin at the triangle centroid, +x toward the S1 floor mark,
  y up, z completing the right-handed set; polar (r, θ) from the centroid per the main
  spec's convention. This holds **even in standalone operation**: without a shared frame,
  no comparison to the tape reference or to predictions is meaningful.
- Consequence: the marker survey (§3.3) must be expressed in array coordinates, i.e.
  measured relative to the centroid mark and the S1/S2/S3 floor marks.
- The homography maps image pixels → floor-plane (x, z) directly in metres in the array
  frame. Conversion to (r, θ) reuses the standard formulas; implement locally in
  `optical/geometry.py` (no import from the main project — §12).
- **Ball radius:** r_ball = 0.1194 m (basketball), the same constant as main spec §5.3.
  Used by the analytic parallax correction (§5.4).
  **[AMENDED v1.5 — D17; was: 0.0335 m tennis ball]** Provenance: measured 2026-07-09,
  circumference C = 0.750 m by tape, r = C/(2π), mass 0.620 kg; main-project D6 register.
  Duplicated here per §12 — this module does not import that value.

---

## §3 Physical Setup

### §3.1 Camera and mount
- Phone: OnePlus 12R (baseline for this build). Slow-motion modes available: 1080p @ 240 fps
  and 720p @ 480 fps. The slow-motion capture is **more cropped** than normal video — plan the
  field of view with the cropped FOV, verified on-site, not from the normal camera preview.
- **[C0] Phone re-verification gate (before Phase 5 / physical testing):** the whole software
  pipeline is built against the OnePlus 12R's capabilities. Before any physical commissioning,
  **re-confirm the phone actually being used.** If a different or better phone is available at
  that point, re-check its slow-motion capability against the selection criteria (real captured
  frames not interpolated — non-negotiable; then highest real frame rate at usable resolution;
  then exposure/shutter lock; then least aggressive slow-mo crop) and only switch if it wins on
  criterion 1 and improves on the rest. A switch requires re-doing intrinsics (§3.4) and the
  frame-rate verification (§3.2) for the new device, nothing else — the pipeline is
  device-agnostic by design.
- Tripod: available. **Height (O3 — FLAGGED ASSUMPTION, resolved at commissioning):**
  start at ~1.2–1.5 m elevation at ~3–4 m horizontal standoff from the centroid.
  Constraints, in priority order: (a) all homography markers AND the expected landing
  sector fit inside the cropped slow-mo FOV; (b) the floor is viewed obliquely enough
  that the homography stays well-conditioned (grazing views compress the far field and
  blow up per-pixel uncertainty); (c) the camera never moves between calibration and the
  last throw of a session.
- Exposure: outdoors, daylight (venue decision — also avoids the ultrasonic ceiling
  ghost). Prefer high overcast; avoid direct low sun (hard moving shadows, HSV washout).
  If the slow-mo mode exposes an exposure/shutter lock, lock it; if not, daylight
  auto-exposure at high frame rate yields short shutters anyway. Verify blur visually in
  the first test clip.
- Outdoor risk register (carried into every session's manifest notes): wind (calm
  conditions required; note per session — a steady crosswind violates the main pipeline's
  parabola assumption too), ground planarity (choose smooth level paving; deviation shows
  up in the §8 static validation as position-dependent error), sun angle/shadows.

### §3.2 Frame-rate verification — datasheet values are not ground truth
Before any metrology: film a millisecond stopwatch (phone/laptop screen) in **both**
slow-mo modes. Step through frames. PASS = distinct, monotonically advancing timestamps
every frame, no ghosted/blended digits, no repeated values. Also read the container
metadata for the **delivered** frame rate (`fps_measured`) — some phones deliver slightly
variable rates; the measured value, not the nominal one, feeds all timing math.
A FAIL in a mode bans that mode from the project. (Public specs and the Snapdragon 8 Gen 2's
native HFR support make genuine capture likely in both modes, but this is unverified for
the 12R specifically — hence this test.)

> **[AMENDED v1.1 — 2026-07-06, trigger: AUDIT_REPORT_PHASES_0-4.md finding M2.]**
> The container-delivered rate (`fps_measured`) must be compared against the nominal
> rate and against the C1 stopwatch-verified rate; a disagreement beyond a named
> tolerance flags the clip with `fps_mismatch` (§5.6). That tolerance is a config key,
> **`capture.fps_tol_pct`, default 0.5 %** — a deliberately loose *starting placeholder*
> chosen to avoid false alarms before the phone is characterised. It is to be tightened
> once C1 measures the actual device's rate stability (a phone with rock-steady delivery
> warrants a tighter bound; a variable one a looser, documented one). Rationale: M2 found
> the production path was copying the nominal rate into `fps_measured` and never reading
> the real delivered rate; §3.2 has always required the *measured* value to feed all
> timing math, and this named tolerance makes the disagreement check enforceable rather
> than aspirational.

> **[AMENDED v1.4 — 2026-07-06, WO-OPT-3 Stage 0, trigger: AUDIT_REPORT_2026-07-06_READONLY.md
> Major 4.2; Decision D9.]** A second config key, **`capture.fps_refuse_pct`, default 20 %**,
> is added beside `fps_tol_pct`. It defines a HARD-REFUSE band on top of the existing
> flag-and-continue band. Semantics of `resolve_fps` (which decides the single rate used for
> ALL timing math):
> - If the rate **USED for timing** (the one chosen by precedence — `--fps-measured` if given,
>   else the container-delivered rate) disagrees with **`fps_nominal`** by **more than
>   `fps_refuse_pct` % of their mean**, the run is REFUSED: raise `OpticalConfigError`, write
>   **no** `optical_gt.json` and **no** manifest entry. (`OpticalConfigError` already propagates
>   and kills the run — WO-OPT-1 Stage 5 narrowed the pipeline catch to `OpticalDataError`.)
> - Between `fps_tol_pct` and `fps_refuse_pct`: the existing behaviour is unchanged — the
>   `fps_mismatch` flag is set, a warning fires, and the run completes (Decision D2).
> - Below `fps_tol_pct`: clean, no flag.
>
> **The refuse compares the USED rate against nominal — NOT every available pair** (tightened
> WO-OPT-3 Stage 2, Hari-approved 2026-07-06; the Stage-0 draft said "any two available
> sources", which is wrong for the real workflow and was corrected once implemented — §0.2
> ordering note). Reason: phone slow-mo containers routinely report the *playback* rate (e.g.
> 30 fps) for a 480 fps capture, and §8 makes `--fps-measured` MANDATORY, so the normal state of
> every real clip is `{--fps-measured = 480, container = 30, nominal = 480}`. A literal
> "any two available sources" refuse would trip on `--fps-measured`-vs-container (~176 %) and
> **refuse every real slow-mo clip**, making `--fps-measured` — the operator's prescribed remedy
> — useless. The danger the refuse exists to catch is a wrong *temporal base*, which is the
> USED rate; so USED-vs-nominal is the correct guard. A container reading that has been
> correctly SUPERSEDED by `--fps-measured` is not a timing source for the refuse (it still
> participates in the D2 `fps_mismatch` FLAG comparison, so the anomaly is surfaced, not
> hidden).
>
> **Rationale (Major 4.2).** Some phone slow-mo containers store the *playback* rate (e.g.
> 30 fps) rather than the *capture* rate (e.g. 480 fps). If the operator forgets
> `--fps-measured`, the USED rate becomes the container's 30 fps — timing a 480 fps clip at
> 30 fps is a ~16× wrong temporal base; the v1.1–v1.3 flag-and-continue posture would emit
> `fps_mismatch` and still write a plausible-looking landing whose `temporal_m` and t* are
> garbage. A gross USED-vs-nominal disagreement must refuse, not flag. A mistyped
> `--fps-measured` (e.g. 48 for 480) is caught the same way, since it becomes the USED rate.
> 20 % is generous enough that genuine per-device rate variation and the 480-vs-479.82 kind of
> drift stay well inside the flag-and-continue band, while a playback/capture confusion (tens of
> percent to multiples) always trips the refuse. `resolve_fps`'s precedence for the USED rate
> (`--fps-measured` > container > refuse) is unchanged; the refuse-band check is an additional
> gate on the USED rate, not a change to which rate is selected.

### §3.3 Floor markers — both kinds (O4)
- **Printed ArUco markers** (recommended dictionary: `DICT_4X4_50`), ~6–8, laid flat on
  the floor spread across the *used* image region (near and far, left and right — spatial
  spread partially absorbs residual lens distortion and conditions the fit). Detected
  automatically by OpenCV — this is the automation-story-consistent calibration path.
- **Surveyed pod floor marks + centroid mark** from the main array as additional reference
  points (manually clicked in a calibration frame).
- Every marker's floor position surveyed in array coordinates (tape from centroid and
  sensor marks; record survey σ, expected ±2–3 mm, into `config.yaml`).
- **Held-out check point:** at least ONE surveyed marker is excluded from the homography
  fit and used only for integrity checking (§5.1, §8).

### §3.4 One-time intrinsic calibration (O5)
Checkerboard calibration of the 12R (`cv2.calibrateCamera`), done once per camera **per
video mode actually used** (the crop differs between modes, so intrinsics differ):
- Print a checkerboard (e.g. 9×6 inner corners, square size measured with a rule and
  recorded), capture ~15–20 stills/frames at varied poses filling the frame.
- Store camera matrix + distortion coefficients in `calib/intrinsics_<mode>.yaml` with
  the RMS reprojection error.
- All measurement frames are **undistorted** (`cv2.undistort`) before any homography use.

---

## §4 Mode Selection (empirical, at commissioning)

720p/480 halves the temporal quantum (~2.1 ms/frame ≈ ~6 mm of ball travel at ~3 m/s)
at the cost of spatial resolution (~2–3 mm/px over a 1.5–2 m working field, vs
~1–1.5 mm/px at 1080p/240). Time is the expected limiter, so **720p/480 is the working
default**, but the decision is made by data: run the §8 static-point validation in BOTH
modes and keep whichever yields the lower RMS. Record both results in the commissioning
report — the comparison is itself reportable content.

---

## §5 Pipeline Architecture

Module layout:

```
optical-gt/
  Optical.md  IMPLEMENTATION_NOTES_OPTICAL.md  CHANGES_OPTICAL.md
  config.yaml  requirements.txt  requirements-ml.txt
  calib/            intrinsics_<mode>.yaml, homography_<calib_id>.yaml
  optical/          geometry.py, calibration.py, detect.py, track.py,
                    contact.py, uncertainty.py, io_session.py, overlay.py, errors.py,
                    detect_ml.py (Phase 6a ML detector, §10)
  simulator/        render.py, scenarios.py
  scripts/          calibrate_intrinsics.py, calibrate_homography.py,
                    process_clip.py, validate_static.py, compare_detectors.py (Phase 6a)
  models/           yolo11n.pt (Phase 6a ML weights; regenerable, auto-downloaded)
  tests/
  data/optical/<session_id>/   raw.mp4 (sacred), trimmed.mp4, optical_gt.json,
                               landing_overlay.png
  data/comparison/             compare_detectors_*.md/.json (Phase 6a outputs; regenerable)
  data/manifests/<YYYY-MM-DD>_manifest.yaml
```

**Raw data is sacred:** `raw.mp4` is verbatim from the phone and never modified; every
other artefact in the session directory is derived and regeneratable from it plus the
calibration files. Atomic writes (temp + `os.replace`) for every JSON/YAML output.
**Regenerable vs sacred (WO-OPT-3 Stage 5):** `models/` (ML weights, auto-downloaded) and
`data/comparison/` (Phase 6a ablation outputs) are **regenerable** artifact directories —
they may be deleted and rebuilt. Only `data/optical/<session_id>/raw.mp4` is **sacred**
(never overwritten); everything else is derived.

### §5.1 Homography calibration (`calibration.py`)
1. Load a calibration frame (or short clip; median frame) from the session, undistort.
2. Detect ArUco corners automatically; prompt manual clicks for the pod/centroid marks
   (matplotlib click UI, zoomable).
3. Fit H by least squares over ALL fit markers (`cv2.findHomography`, plain LS — the
   marker set is trusted and small; RANSAC only if an outlier is proven).
4. Report **reprojection RMS (px)** over fit markers and the **check-point error (m)**
   — the held-out marker mapped through H vs its surveyed position. Both stored in
   `homography_<calib_id>.yaml` and echoed into every `optical_gt.json` that uses it.
5. **Stability protocol:** the check-point mapping is re-run on a frame from the START
   and the END of each session. Drift beyond `check_point_tol_m` (config; default
   0.005 m) flags every throw in the session `homography_drift` — the optical result is
   reported but excluded from headline statistics. (Same philosophy as the main
   project's `ls_residual_m` integrity guard.)

> **[AMENDED v1.4 — 2026-07-06, WO-OPT-3 Stage 0, trigger: AUDIT_REPORT_2026-07-06_READONLY.md
> Major 4.1; Decision D10.]** Step 5 is redefined from **drift-only** to **drift AND absolute
> check-point error**. The start/end re-check already computes three quantities in
> `stability_check`: `err_start_m` (check point mapped through H in the session-START frame vs
> its surveyed position), `err_end_m` (same, session-END frame), and `drift_m` (distance
> between the two mapped points). The v1.0–v1.3 protocol thresholded only `drift_m` against
> `check_point_tol_m`. **Now `err_start_m` and `err_end_m` are EACH also thresholded against
> `check_point_tol_m`.** A breach of either sets a new flag **`stability_abs_fail`** (§5.6)
> with a loud `UserWarning` — never silent, never an abort; the operator decides — the same
> posture as the `check_point_fail` guard (step 4). The `drift_m` / `homography_drift`
> behaviour is unchanged.
>
> **Rationale (Major 4.1).** A tripod bump *between the calibration frame and the clip start* —
> then held still through the clip — produces near-zero start-to-end drift but a large absolute
> mapping error at both frames. Drift alone cannot see it: every landing in the session would be
> systematically wrong while the JSON looked clean. The absolute error is the quantity that
> catches a stale/bumped calibration. `stability_abs_fail` is kept DISTINCT from
> `check_point_fail` (Decision D10) because a camera bumped after calibration and a bad original
> fit have different field remediations and must be distinguishable in the JSON. The static gate
> (§8, C7) is not exposed to this — a bad H shows up directly in the static-point RMS — so the
> exposure is campaign throws after commissioning.

### §5.2 Ball detection — HSV baseline (`detect.py`)
- Undistort → HSV threshold (basketball orange band, config-tunable) →
  morphological open/close → contour extraction → largest plausible blob by area band
  and circularity → centroid + bounding box + lowest-pixel point, per frame.
  **[AMENDED v1.5 — D18; was: tennis-ball yellow-green band]** The band's literal values
  live in `config.yaml`, never here; the shipped orange values are an unverified
  PLACEHOLDER to be tuned at commissioning checklist item C6 (§8).
- Must be tested on footage WITH shadows present (outdoor reality), not only clean clips.
- Emits per-frame detection confidence flags; frames with no/ambiguous detection are
  recorded, not silently dropped.
- This baseline is permanent: it is also the diagnostic tool and the control arm of the
  Phase 6a/6b comparison. The detector is a swappable interface (`detect(frame) ->
  Detection | None`) so the ML detector plugs in without touching anything downstream.
  [AMENDED v1.3 — Phase 6 split; see §16]

### §5.3 Tracking and descent segmentation (`track.py`)
- Simple nearest-neighbour association across frames (one ball, high frame rate — no
  need for anything heavier), with a max-jump gate.
- Segment the final descent: the last N frames (config; default 8–12) of monotonically
  decreasing image-height before the vertical-motion reversal/stop that marks contact
  or bounce. First touchdown, not the bounce, is the target: at 240–480 fps the
  reversal is sharp; the segmentation takes the FIRST reversal.

> **[AMENDED v1.2 — 2026-07-06, trigger: WO-OPT-1 Stage 4.4 (audit M4 + Moderate
> "reversal has no noise robustness").]** A reversal is declared only when **confirmed**:
> after the rising (descending-ball) run, `track.min_rise` (config; default 2) consecutive
> non-increasing image-v steps with a net strict decrease are required. A single noisy
> non-increase inside a genuine descent neither ends the window (the walk-back steps over
> an isolated one-frame dip) nor fakes a touchdown. Default 2 is free on real bounces
> (the rebound descends in image-v for many frames) while single-frame noise — the only
> plausible false trigger at the ~5–15 px/frame near-contact image speeds — cannot
> satisfy two consecutive steps. Confirmation also guarantees the ≥ 2 rebound frames the
> §5.5 kink solve consumes.

### §5.4 Parallax correction (O6)
**Primary — analytic centroid correction.** The tracked centroid sits ~r_ball above the
floor at contact; mapped through the floor homography it lands at a shifted point along
the camera-ray ground projection. With the camera position C = (C_x, C_y, C_z) in the
array frame (estimated once per calibration: decompose from H + intrinsics, refined by a
direct measurement of camera height and horizontal distance with the tape — record
both), the correction for a point at height h above floor position P is the ray–plane
shift, applied in closed form:

  P_floor = P_mapped − (h / C_y) · (P_mapped − C_ground),  with h = r_ball at contact,
  C_ground = (C_x, C_z).

Deterministic, testable in the simulator against exact geometry, and its residual (from
σ_h and camera-position uncertainty) enters the §7 budget analytically.

> **[AMENDED v1.5 — D20, 2026-07-10, trigger: WO-OPT-4 (basketball substitution);
> CORRECTED at WO-OPT-4 Stage 5 after inspecting the actual budget output.]** The
> closed-form correction above is **parametric in h and unchanged** — no formula moves. But
> h = r_ball at contact has grown from 0.0335 m to 0.1194 m, a factor of **×3.56**, so the
> correction's **absolute magnitude** (the systematic shift applied to the point) scales by
> that factor: a correction that was of order a centimetre becomes of order several
> centimetres. At the §3.1 working standoff this is material, not a rounding term.
>
> **Its uncertainty CONTRIBUTION does NOT simply scale ×3.56 — the Stage-0 draft of this note
> overstated that, and Stage 5's budget inspection corrected it.** `parallax_sigma` has three
> quadrature terms: (1) from σ_h, sensitivity `∂P/∂h = −(P−C_ground)/C_y`, which is
> **independent of h**; (2) from σ_C_y, `∝ h·(P−C_ground)/C_y²`; (3) from σ_C_xz, `∝ h/C_y`.
> Only terms (2) and (3) — the camera-position ones — scale with h. Consequences, MEASURED
> from the budget at the nominal geometry: with the **shipped config** (`sigma_C_m = [0,0,0]`,
> an unmeasured placeholder), the residual is purely term (1) and is **identical at both
> radii, 5.35 mm** — it does not move with r_ball at all yet. Once σ_C is measured nonzero at
> C6, terms (2)/(3) switch on and *those* contributions scale ×3.56 with the basketball. So
> the correct statement is: the **systematic correction** grows ×3.56 now; the **uncertainty**
> grows ×3.56 only in its camera-position part, only once σ_C is measured. This makes the
> camera-position tape cross-check of §5.4's "record both" MORE load-bearing (a given σ_C now
> hurts ×3.56 harder), and the lowest-pixel fallback — a *zero*-h observable — a comparatively
> stronger cross-check. Both are computed and compared at commissioning, as before.

**Fallback — lowest-pixel method.** Map the blob's lowest pixel (approximately the
contact point at the contact frame) directly through H. Kept as a cross-check and as
the fallback if the camera-position estimate proves unreliable; noisier (blur, shadow
contamination of the blob boundary). `optical_gt.json` records which method produced
the headline number; during commissioning both are computed and compared.

**Commissioning-only cross-check — chalk mark.** During §8 validation and the first few
live throws, the chalk mark (already produced for the tape protocol) is ALSO mapped
through H: it lies ON the floor plane, so it is a zero-parallax optical observable.
Disagreement chalk-vs-tape isolates homography error; disagreement tracker-vs-chalk
isolates tracking/parallax error. Two error sources, two diagnostics. The chalk route is
NOT a production method (manual marking defeats the automation story) and is retired
after commissioning.

> **[AMENDED v1.4 — 2026-07-06, WO-OPT-3 Stage 0, trigger: AUDIT_REPORT_2026-07-06_READONLY.md
> Moderate 5.5; Decision D13.]** The "record both" instruction above (decompose C from
> H + intrinsics AND measure it with the tape) gains a tool hook. `scripts/calibrate_homography.py`
> accepts an OPTIONAL `--camera-measured X Y Z` argument (metres, in the §2 array frame). When
> supplied, the calibration YAML additionally records:
> - `camera_measured_m` — the tape-measured camera centre (X, Y, Z) as given;
> - `camera_decomposed_m` — the centre from the existing `decompose_camera` /
>   `estimate_camera_position` path;
> - `camera_delta_m` — the per-axis difference {dx, dy, dz} plus its norm.
>
> This is **informational only**: no threshold, no flag, no abort — it surfaces the
> decomposed-vs-measured agreement for the commissioning report (the Phase-3 fitted-H
> decomposition measured ~12 mm against exact synthetic truth, so a real tens-of-mm delta is the
> expected order). When `--camera-measured` is ABSENT, the calibration YAML shape is unchanged
> from today (additive-only). The tape measurement remains the §5.4 sanity reference for the
> decomposed pose, per "record both".

### §5.5 Sub-frame first contact (`contact.py`) — physics, not ML

> **[AMENDED v1.1 — 2026-07-06, trigger: AUDIT_REPORT_PHASES_0-4.md finding M5.]**
> The original v1.0 text promised a sub-frame *polynomial-fit* solve for t* ("t* = the
> instant the ball-bottom height reaches the floor, solved from the fit — resolution well
> below one frame"). That design was **built, measured, and rejected during Phase 3**; the
> as-built `contact.py` uses a fixed ±0.5-frame *bracket* instead. This section now
> documents what is actually implemented. Rationale is condensed from
> IMPLEMENTATION_NOTES_OPTICAL.md Phase 3.

**Adopted design — the descent-end bracket.** The landing point is (x(t*), z(t*)), where
the horizontal **centroid** track is fitted with low-order polynomials (linear/quadratic;
time base = frame index / `fps_measured`), evaluated at t*, then parallax-corrected once
with r_ball at contact (§5.4). The contact instant t* is **not** solved from a height fit;
it is bracketed by the descent segment:

  t* = (time of the last tracked descent frame) + 0.5 / `fps_measured`
  σ_t = (1 / `fps_measured`) / √12

The last frame in which the ball is still descending brackets first contact to the
following inter-frame interval; the unbiased point estimate is the interval midpoint
(+0.5 frame), and σ_t is the standard deviation of a uniform distribution over that
one-frame window. Every throw taking this path carries the `contact_time_bracket` flag
(§5.6); the coarser no-camera-pose fallback additionally carries `contact_time_coarse`
and `parallax_fallback_used`.

> **[AMENDED v1.2 — 2026-07-06, trigger: WO-OPT-1 Stage 4 measurement (audit M4).]**
> The v1.1 bracket above is now the adopted design **only for a `track_end` descent**
> (ball vanishes/leaves frame — where the last frame is strictly pre-contact and +0.5 is
> unbiased). For a **`reversal` descent** — a real bounce, the case ALL real footage
> produces — the bracket was **measured to be wrong**: the descent's last frame is the
> image-v peak, i.e. touchdown itself, so "+0.5 after it" runs systematically ~0.6 frame
> late. Measured on the full synthetic chain: 10.12 mm landing error at the nominal
> camera and **17.62 mm at a ~12° oblique camera — over the 15 mm §8 gate** (vs 7.22 mm
> for the vanish case). The adopted v1.2 design for a reversal end is the **kink
> intersection**:
>
> - The ball's image position is CONTINUOUS through the bounce; only the vertical
>   velocity flips sign. Image-v(t) is a rising branch meeting a falling branch in a
>   kink **exactly at contact, under any camera obliquity** (the horizontal-motion tilt
>   of image-v is continuous and cannot move the kink — this is precisely what the
>   rejected Phase-3 parabola-VERTEX idea missed: a smooth extremum shifts with the
>   tilt; the intersection of the two branches does not).
> - t* = the intersection of the pre-contact image-v fit (the descent window, excluding
>   the ambiguous peak sample) with a linear fit of the ≥ 2 post-peak rebound frames
>   (guaranteed by the §5.3 `min_rise` confirmation), sanity-clamped to ±1.5 frames of
>   the peak. Flag: **`contact_time_kink`**. σ_t is kept at the conservative
>   (1/`fps_measured`)/√12 until real-footage residuals justify shrinking it.
> - Fallback when the kink cannot be solved (too few rebound frames, degenerate fits,
>   no root in the clamp): t* anchored **at the peak frame** (no +0.5), σ_t =
>   (1/`fps_measured`)/√3 (uniform over ±1 frame), flag `contact_time_bracket`.
> - Zone 3 compliance: this is a closed-form physics fit (two polynomial branches, one
>   intersection), no ML.
>
> **Measured result (same chain, same scenarios):** nominal-camera bounce 10.12 mm →
> **0.15 mm**; oblique bounce 17.62 mm → **0.51 mm**; robust ≤ 0.7 mm across noise
> σ=2 px, motion blur, and shadow variants; t* error ≤ 0.04 frame. The `track_end`
> path is bit-identical to v1.1 (nominal vanish reference 7.22 mm, unchanged).

**Why the sub-frame fit was rejected (measured, Phase 3).** Two literal sub-frame designs
were implemented and measured on synthetic footage with exact known truth, and both
failed on this geometry: **(1) an image-vertical crossing fit** (fit the ball-bottom image
row and the floor row under the ball, solve where they meet) — defeated by a ~1–2 px
systematic offset between the detected silhouette bottom (mask-morphology inflated) and
the true 3-D bottom pole, so the crossing is ill-posed and often has no real root; and
**(2) an apparent-size height reconstruction** (depth = fx · r_ball / r_px → world height →
solve height = r_ball) — exact on noise-free truth but signal-starved here (the ball's
pixel radius changes only ~0.05 px across the whole ~10-frame window while the detector
radius carries a ~0.9 px bias). A third variant, a **bounce reversal-apex** fit, was also
rejected: under an oblique camera the image-v extremum is offset ~1 frame from the true
world-height minimum (steady horizontal motion shifts it), giving ~20 mm landing error.
The decisive finding: **landing accuracy is dominated by the clean, sub-pixel centroid
track, not by t* resolution** — at ~1.7 m/s a 0.5-frame timing error is only ~1.7 mm
along-track, and the ~7 mm residual on the zero-noise nominal scenario is this
frame-quantisation term, far inside the 15 mm §8 GO gate. The bracket buys robustness (no
fragile feature to break under real blur/shadow) at no material accuracy cost on the
tested geometry.

**Apparent-size route: dormant, not deleted.** The height-reconstruction geometry
(`reconstruct_world_point`, `CameraGeometry`) is retained in the codebase as
*investigated-and-dormant* public geometry — available for reporting and for
re-evaluation on real footage (a camera closer to nadir, or a ball faster in depth, could
revive either the size cue or the reversal-apex). It is simply not on the default t* path.
Re-checking it on real 480 fps clips is a Phase 5 / Future-Works item, not a v1 deletion.

> **[AMENDED v1.5 — D21, 2026-07-10, trigger: WO-OPT-4 (basketball substitution).]** The
> v1.0–v1.4 text asserted, as a stated fact, that contact duration is "of order a few ms …
> possibly zero or one true contact frames even at 480 fps." That was a tennis-ball claim
> and it is **withdrawn**, not transferred: it is not a basketball figure, and no
> basketball figure is asserted in its place.

Contact duration for a basketball has **NOT** been verified against a primary source and
may span more frames at 480 fps than the tennis ball did. This must be confirmed
empirically at commissioning (Phase 5), **not assumed** — and no millisecond figure is to
be quoted in any report until it comes from a primary source or our own measurement. The
reasoning that motivates a bracket/fit rather than a single raw frame is unchanged and, if
anything, strengthened: whether contact spans zero frames or several, the instant of first
contact still falls between samples, so a bracket/fit — not a raw frame — defines the
answer. What *does* need re-examining on real footage is the §5.5 kink solve's frame
margin: a longer contact means the post-peak rebound frames the kink consumes may sit
further from t*, and the §5.3 `min_rise` confirmation window may need revisiting (Stage 5,
Phase 5 item — not a v1 change).

### §5.6 Outputs (`io_session.py`, `overlay.py`) — schema FROZEN (O7)
Per throw, `optical_gt.json` (keys frozen NOW so future integration is a pure
consumer-side change; additive extension allowed, renames forbidden):

```json
{
  "schema_version": "1.0",
  "session_id": "2026-07-18_T03",
  "clip": {"file": "raw.mp4", "mode": "720p480",
            "fps_nominal": 480, "fps_measured": 479.82},
  "calibration": {"calib_id": "2026-07-18_A",
                   "reproj_rms_px": 0.7,
                   "check_point_err_m": 0.004,
                   "intrinsics": "intrinsics_720p480.yaml"},
  "method": {"detector": "hsv", "parallax": "analytic_centroid"},
  "landing": {"x_m": 0.412, "z_m": -1.103,
               "r_m": 1.177, "theta_deg": -69.5},
  "uncertainty": {"sigma_x_m": 0.006, "sigma_z_m": 0.009,
                   "sigma_r_m": 0.008, "sigma_theta_deg": 0.4,
                   "components": {"marker_survey_m": 0.003,
                                   "homography_m": 0.004,
                                   "pixel_localisation_m": 0.003,
                                   "parallax_residual_m": 0.002,
                                   "temporal_m": 0.004}},
  "contact": {"t_frame": 143, "t_subframe": 143.5,
               "n_descent_frames": 10},
  "quality": {"flags": [], "n_tracked_frames": 47},
  "notes": ""
}
```

`quality.flags` vocabulary (extend additively): `homography_drift`, `low_frame_count`,
`detection_gaps`, `blur_suspected`, `parallax_fallback_used`, `cond_warn`.

> **[AMENDED v1.1 — 2026-07-06, trigger: AUDIT_REPORT_PHASES_0-4.md (M1/M2/M3 + audit
> Moderate findings).]** The vocabulary is extended additively (existing entries are
> never renamed or removed, per O7). **Four new flags** are reserved by this amendment:
> - `fallback_intrinsics` — the §3.4 intrinsics file was not supplied; an HFOV-guess
>   camera matrix K was used instead of measured intrinsics (smoke-testing only).
> - `fps_mismatch` — the container-delivered frame rate disagreed with the nominal rate
>   or with the C1-measured rate beyond `capture.fps_tol_pct` (§3.2).
> - `unmeasured_uncertainty_components` — one or more §7 budget components were taken
>   from a placeholder (not-yet-measured) config value rather than a real measurement.
> - `stability_unchecked` — the §5.1 step-5 homography-drift re-check could not be run
>   for this session (required start/end frames or check point unavailable).
>
> **Already emitted by the as-built pipeline** (recorded here so the spec vocabulary
> matches `optical/io_session.py::FLAG_VOCAB`, and because §5.5 above now references the
> first two by name): `contact_time_bracket` (the §5.5 bracket path was taken),
> `contact_time_coarse` (the no-camera-pose fallback bracket), and `no_prediction` (a
> valid failure-mode artifact was written with `landing: null` — no ball / no descent /
> too few frames). These are additive extensions introduced in Phase 3/4; they are noted,
> not newly reserved.

> **[AMENDED v1.2 — 2026-07-06, trigger: WO-OPT-1 Stage 4 (audit M4).]** One flag added
> additively: `contact_time_kink` — the §5.5 (v1.2) kink-intersection sub-frame solve
> produced t* for this throw (a `reversal` descent with a solvable pre/post-branch
> intersection). Mutually exclusive with `contact_time_bracket` on the same throw.

> **[AMENDED v1.2 — 2026-07-06, WO-OPT-1 Stage 5, Decision D6.]** Producer status of the
> vocabulary is now: `fps_mismatch`, `unmeasured_uncertainty_components`,
> `fallback_intrinsics` (all Stage 1/2/5), `homography_drift`, `stability_unchecked`
> (Stage 3), `cond_warn` (Stage 5.4 — soft marker-conditioning band, propagated from the
> calibration), `contact_time_*` / `parallax_fallback_used` / `detection_gaps` /
> `low_frame_count` / `no_prediction` (Phase 3/4 + Stage 4) all have live producers.
> **`blur_suspected` is RESERVED with its producer deferred to Phase 5:** a defensible
> blur metric (e.g. variance-of-Laplacian on the descent-window frames) needs real
> footage to set its threshold against genuine motion blur, so it is not implemented in
> v1 (implementing it against synthetic blur would only encode a synthetic threshold). It
> stays in the frozen vocabulary so the Phase-5 producer is a pure additive change.

> **[AMENDED v1.4 — 2026-07-06, WO-OPT-3 Stage 0, trigger: AUDIT_REPORT_2026-07-06_READONLY.md
> Moderate 5.1 + Major 4.1; Decisions D10, D12.]** Two flags added **additively** (O7 preserved
> — no renames/removals); `FLAG_VOCAB` grows 14 → 16 entries:
> - **`check_point_fail`** — the §5.1 step-4 held-out check-point guard tripped for the
>   calibration this throw used (the held-out marker maps beyond `check_point_tol_m` from its
>   surveyed position). **The PRODUCER already existed** in `optical/calibration.py`
>   (`CHECK_POINT_FAIL_FLAG`) since Phase 2, but the flag was never in `FLAG_VOCAB`, so the
>   `process_clip` vocabulary filter (`[f for f in calib.flags if f in FLAG_VOCAB]`) silently
>   dropped it and it never reached any per-throw `optical_gt.json`. Adding it to the vocabulary
>   closes that gap (Moderate 5.1). (WO-OPT-3 Stage 3, Decision D12, additionally inverts that
>   filter so a future out-of-vocabulary producer flag fails loudly rather than vanishing.)
> - **`stability_abs_fail`** — the §5.1 step-5 absolute check-point error exceeded
>   `check_point_tol_m` at the session start and/or end frame (a stale/bumped calibration; see
>   the §5.1 v1.4 amendment). Kept DISTINCT from `check_point_fail` (Decision D10): a camera
>   bumped after calibration and a bad original fit have different field remediations and must be
>   distinguishable in the JSON.

**Human-readable landing display:** alongside the JSON, `landing_overlay.png` — the
contact-adjacent frame with the tracked path drawn, the estimated contact point marked,
and a text block printing session ID, (r, θ) ± (σ_r, σ_θ), method, and flags. Readable
at a glance without opening JSON. No HTML layer in v1 (§13).

`process_clip.py` also prints the same summary block to the terminal.

---

## §6 Simulator-First Discipline (O8)

Built BEFORE any real-footage code path is trusted, exactly as in the main project.
`simulator/render.py` synthesises frame sequences with **exact known ground truth**:
- A floor plane with a KNOWN homography (choose camera pose + intrinsics, project).
- Rendered ArUco-like fiducials at known floor positions (or direct injection of known
  pixel↔floor correspondences for calibration tests — both).
- A drawn ball (filled circle, basketball orange, radius scaled by distance) following
  a known parabolic trajectory with known contact time and point; optional additives:
  Gaussian pixel noise, motion-blur smear, a fake shadow blob, missing-frame dropouts.
  [AMENDED v1.5 — D18; was: tennis-ball colour] The draw colour is held dead-centre of
  the `config.yaml` HSV band (the WO-OPT-1 Stage 6.5 invariant), so the §10 Phase-6a
  HSV-optimism caveat remains true after the substitution.
- Scenario library in `simulator/scenarios.py`: nominal, blurred, shadowed, low-contrast,
  grazing camera angle, marker-survey perturbation.

**Synthetic end-to-end acceptance test (the gate for Phases 2–3):** render a nominal
scenario → run the full pipeline → recovered landing within a tight tolerance of the
injected truth (tolerance derived from injected noise, e.g. ≤ 3 mm at zero noise;
scaled for noisy scenarios). Plus **negative controls**: a scenario with a corrupted
marker survey must trip the check-point guard; a no-ball clip must produce a clean
"no detection" result, never a fabricated landing.

---

## §7 Uncertainty Budget

Per-throw σ propagated from measured components, same discipline as the main chain:
1. **Marker survey** σ (from §3.3, config). **[AMENDED v1.1 — 2026-07-06, trigger:
   AUDIT_REPORT_PHASES_0-4.md §7-item-1 finding; Decision D5.]** *As-built:* the survey σ
   is charged as a **raw isotropic per-axis constant** (σ on each of x and z), **not**
   propagated through the homography least-squares fit as the original v1.0 text ("→
   propagated through the homography fit") implied. This is a deliberate, conservative
   simplification: it **inflates** the budget rather than shrinking it (a genuine fit over
   ~7 markers would average the survey error down and make it anisotropic), and it
   **partially double-counts** with the check-point error already folded into
   `homography_m` (item 2). The commissioning report **must state this** when printing the
   budget next to the measured static-point spread, so the propagated σ is not mistaken
   for a fully-propagated quantity. Full propagation of survey σ through the fit is
   **deferred to §13 Future Works**, not implemented in v1.

   > **[AMENDED v1.4 — 2026-07-06, WO-OPT-3 Stage 0, trigger:
   > AUDIT_REPORT_2026-07-06_READONLY.md Moderate 5.2; Decision D11.]** The config key
   > `markers.survey_sigma_m` changes SHAPE from a bare number to the
   > `{value: 0.0025, measured: false}` form — matching the four `uncertainty:`-block
   > components (`pixel_sigma_px`, `sigma_h_m`, `sigma_C_m`, `rolling_shutter_m`) already
   > promoted to that form by WO-OPT-1 Stage 1. The numeric value (**0.0025 m is unchanged**),
   > so no budget number moves; the point is machinery, not magnitude. The survey σ is now
   > consumed only through the same unmeasured-component path, so while `measured: false` (the
   > shipped placeholder) it contributes `markers.survey_sigma_m` to the
   > `unmeasured_uncertainty_components` flag (§5.6), the naming `UserWarning`, and the `notes`
   > echo — exactly like the four already-promoted components. A malformed shape hard-errors (no
   > silent default). It is flipped to `measured: true` only when a real tape-survey σ is
   > recorded at checklist C4. Rationale: the survey σ was the one budget input still feeding
   > the propagation as an unflagged placeholder, inconsistent with the Stage-1 "no placeholder
   > consumed silently" posture.
2. **Homography** — reprojection RMS + check-point error as the empirical proxy for
   map error at working distance.
3. **Pixel localisation** of the ball feature — measured, not assumed: scatter of the
   detector on static-ball frames (part of §8), converted to metres via the local
   pixel scale (which varies across the oblique image — evaluate at the landing pixel).
4. **Parallax residual** — from σ(r_ball surrogate = ball compression at contact) and
   camera-position uncertainty through the §5.4 formula.

   > **[AMENDED v1.5 — D20, 2026-07-10, trigger: WO-OPT-4; scaling claim CORRECTED at
   > Stage 5 after inspecting the budget output.]** σ(r_ball surrogate = ball compression at
   > contact) is now a **basketball** quantity and is **unmeasured**. No basketball
   > compression figure exists in this project and none is invented here: the component ships
   > as a placeholder (`measured: false`) and must therefore keep raising the
   > `unmeasured_uncertainty_components` flag (§5.6) until a real value is recorded at checklist
   > item **C6** (§8) — VERIFIED at Stage 5: `read_uncertainty_config` still lists `sigma_h_m`
   > (and `sigma_C_m`, `rolling_shutter_m`, `pixel_sigma_px`) in its `unmeasured` set, and
   > `markers.survey_sigma_m` in the sibling reader's. **Correction to the Stage-0 wording:** it
   > is NOT true that "the residual is amplified ×3.56 even at unchanged relative σ". The σ_h
   > sensitivity `∂P/∂h = −(P−C_ground)/C_y` is **h-independent**, so the σ_h-driven residual
   > term does not scale with r_ball; only the camera-position terms (∝ h) do (see the §5.4
   > correction to this decision). MEASURED with the shipped config (`sigma_C_m = [0,0,0]`): the
   > `parallax_residual_m` budget line is **5.35 mm at both the tennis and basketball radius** —
   > it does not move yet. What genuinely grows ×3.56 is the *systematic* correction magnitude,
   > and the σ_C-driven residual once σ_C is measured at C6. Independent reasons to MEASURE
   > rather than scale the old σ_h: an inflatable ball's contact compression is plausibly a
   > larger *fraction* of its radius than a tennis ball's, and is pressure-dependent.
5. **Temporal / sub-frame** — the §5.5 contact-time σ_t (the bracket value
   (1/`fps_measured`)/√12) × the floor velocity, plus a
   rolling-shutter term: characterise once (film a falling ball next to a plumb line or
   the stopwatch; estimate skew) and either bound it as negligible or include it. Do not
   assume it away; magnitude is phone-dependent and unknown a priori.

Combined in quadrature per axis → (σ_x, σ_z) → propagated to (σ_r, σ_θ). The whole
budget prints in the commissioning report next to the *measured* static-point spread —
budget vs reality on the same page.

The cross-validation statistic for campaign throws: per-throw difference
(camera − tape) compared against the combined uncertainty of both instruments —
a normalised-error (E_n-type) check. |E_n| ≤ 1 for the bulk of throws = the error
budgets are honest.

---

## §8 Commissioning Procedure and Acceptance Gate

Physical-task checklist — each item independently ownable (the build may be split
between two people; the checklist is the interface between them):

1. **[C1] Frame-rate verification** (§3.2), both modes. Owner: ____
2. **[C2] Checkerboard intrinsics** (§3.4), per used mode. Owner: ____
3. **[C3] Tripod geometry** — choose height/standoff per §3.1 constraints; measure and
   record camera position (tape: height, horizontal distance, bearing). Owner: ____
4. **[C4] Marker survey** — ArUco + pod marks in array coordinates, with survey σ;
   designate the held-out check point. Owner: ____ (whoever knows the array conventions
   should at least review this one)
5. **[C5] Homography calibration** + stability re-check (§5.1).
6. **[C6] Detector characterisation** — static ball at ≥ 3 surveyed positions; measure
   pixel-localisation scatter (feeds §7 item 3).
7. **[C7] Static-point validation — THE GATE.**

> **[AMENDED v1.4 — 2026-07-06, WO-OPT-3 Stage 0, trigger: AUDIT_REPORT_2026-07-06_READONLY.md
> Major 4.2 field-procedure item; Decision D15.]** **`--fps-measured` is MANDATORY for every
> real-footage processing run.** All timing math uses the delivered rate (§3.2); on real footage
> the operator must pass the C1 stopwatch-verified rate explicitly
> (`process_clip.py --fps-measured <fps>`) rather than relying on the container-reported rate,
> which some phones populate with the *playback* rather than the *capture* rate (§3.2). This is
> a PROCEDURAL requirement (field checklist), cross-referenced to **[C1]**; the code-side
> backstop is the `capture.fps_refuse_pct` hard refuse (§3.2, Major 4.2) that kills a run when
> the available rates disagree grossly.

**Gate (O9 — pre-registered, confirmed):** place the ball statically at **≥ 8
independent surveyed points** (NOT the ultrasonic static-characterisation points — an
independent set, surveyed the same way with the same recorded σ), spread across the
working FOV including near/far and off-axis. Run each through the full pipeline (as a
"clip" of the static scene). Compare against the **three-tape multilateration solve** at
the same points.

> **GO if RMS disagreement ≤ 1.5 cm over the ≥ 8 points. Otherwise NO-GO.**

Run in both video modes (§4); the mode decision and both RMS values go in the
commissioning report. NO-GO in both modes = the module is reported as a characterised
negative result with its diagnosis (the chalk-mark diagnostics in §5.4 localise the
dominant error source); no campaign integration is attempted. The criterion is fixed
NOW, before first data — it is not renegotiated after seeing results.

**Campaign coverage (O10):** the fixed camera validates only the
subset of campaign throws whose landing falls inside its FOV. Committed subset:
**> 8 of the 15–20 ground-truthed throws.** Throws are NOT steered toward the camera;
if natural coverage falls short, extra camera-sector throws are appended to the
campaign, never substituted.

---

## §9 Data Management

- **Slate every clip:** the first second of every recording films a paper slate with
  the session/throw ID handwritten. Footage is self-identifying; no mapping can be
  lost or mistyped.
- **Transfer:** USB-C, plain MTP file copy to the Windows PC, immediately after each field
  session. NO cloud round-trips (some services re-encode video; direct copy removes the
  question entirely). After copy, **verify the imported file's frame-rate metadata matches
  capture** (`fps_measured` from §3.2) before trusting timing — a re-encode or transcode on
  transfer would silently corrupt the temporal base. (If the §3.1 [C0] gate ever switches the
  device to an iPhone, the transfer path changes: on Windows use the Apple Devices app or the
  Photos import — iTunes proper is largely legacy for this and I'm not certain of the current
  exact flow, so verify at the time — and be especially careful of Apple's HEVC / "optimised"
  handling re-encoding on export. The OnePlus USB-C MTP path above has none of these concerns.)
- **Naming:** `optical_<YYYY-MM-DD>_T##.mp4`, matching the main pipeline's session
  IDs so campaign analysis joins the datasets on ID alone. Renamed-on-copy into
  `data/optical/<session_id>/raw.mp4`.
- **Manifest:** `data/manifests/<YYYY-MM-DD>_manifest.yaml` — one entry per clip.
  **[AMENDED v1.4 — WO-OPT-3 Stage 0, Decision D16; see §16.]** As built, `process_clip.py`
  writes each entry **non-interactively**: `session_id`, `file` (`raw.mp4`), `mode`, `calib_id`,
  `in_frame` / `out_frame` (trim), and a single free-text `notes` field. Wind/lighting
  conditions and operator initials (the §3.1 outdoor risk register) are recorded as free text
  **within `notes`** for now — passed via `process_clip.py --notes "..."`. Entries dedup by
  `session_id` (append-or-replace). Dedicated `wind` / `lighting` / `operator` fields remain a
  possible additive extension, not built in v1. (The v1.0–v1.3 spec described dedicated fields
  and an "interactive" write; that never matched the as-built code — this reconciles the spec to
  reality, D16.)
- **Trimming (v1 = manual):** the operator notes trim in/out frames (any player);
  `process_clip.py --in N --out M` extracts `trimmed.mp4`. `raw.mp4` untouched, ever.
  Automated throw detection is Future Works (§13), the manifest already carries the
  fields it will need.

> **[AMENDED v1.4 — 2026-07-06, WO-OPT-3 Stage 0, trigger: AUDIT_REPORT_2026-07-06_READONLY.md
> Moderate 5.6; Decision D14.]** **Trim requirement for bounce clips:** any clip that contains a
> bounce must retain **at least 3 frames after the bounce (image-v) peak** in the trimmed range.
> Rationale: the §5.5 kink solve needs ≥ 2 post-peak rebound frames, and the §5.3 `min_rise`
> confirmation needs enough frames to CONFIRM the reversal. If a clip ends 0–1 frames after the
> peak, the reversal cannot be confirmed, the descent degrades to a `track_end` end, and the
> +0.5-frame bracket is applied *after* the peak — silently reintroducing the ~0.6-frame late
> bias that WO-OPT-1 Stage 4 measured (10–18 mm landing error), while the throw is flagged only
> `contact_time_bracket`, indistinguishable from a legitimate vanish-ending clip. Three post-peak
> frames guarantee both a confirmable reversal and a solvable kink. This is a manual-trim
> procedure requirement in v1 (no heuristic flag — Decision D14; revisit only if Phase 5 footage
> exhibits the failure mode).

---

## §10 Optional Gated ML Phase — Detector Comparison (O11)

**[AMENDED v1.3 — Phase 6 split; see §16]**

**Zone rules (binding on all phases, present and future):**
- **Zone 1 — geometry (homography, parallax, pixel→floor mapping, sub-frame timing):
  no ML, ever.** Exact projective mathematics with analytically propagatable
  uncertainty; a learned replacement trades a closed-form budget for a black box for
  zero benefit. ML frame interpolation is specifically banned (it hallucinates frames —
  the exact failure §3.2 exists to detect).
- **Zone 2 — ball detection: ML permitted, as a characterised transducer.** This phase.
- **Zone 3 — contact identification: physics-based only** (§5.5). A fitted kink has an
  argument attached; a classifier trained on twenty bounces does not.

**Phase 6 content (shared across 6a/6b — see the sub-phase split below; self-contained,
droppable without touching anything else): [AMENDED v1.3 — Phase 6 split; see §16]**
- Zero-shot detection with a small pretrained YOLO-family model via `ultralytics`
  (COCO includes a "sports ball" class; plausibly works with no training and no
  labelling). Offline CPU inference; nothing is real-time.
- Implemented as a second `Detector` behind the §5.2 interface. All downstream code
  identical.
- **The study:** on IDENTICAL footage (commissioning clips + available campaign clips),
  benchmark HSV vs zero-shot ML on: detection rate per frame, localisation scatter
  (px σ) on static points, behaviour under the shadow/blur/low-contrast simulator
  scenarios and real degraded clips, and end-to-end landing RMS at the §8 static
  points. Report as a proper ablation: classical baseline vs learned detector, same
  geometry, measured behaviour — the detector is characterised like a transducer, which
  directly answers the black-box objection rather than hiding from it.
- **Escalation gate:** fine-tuning on hand-labelled frames of our own footage is only
  considered if zero-shot demonstrably fails AND the HSV baseline also fails — i.e.
  only if the module is otherwise NO-GO. Otherwise fine-tuning is Future Works.
- If the ML phase is dropped (neither Phase 6a nor 6b run): `requirements-ml.txt` never
  installed, `compare_detectors.py` never written, zero trace in the core module.
- (A published line of work on **ball tracking in sports video** exists — TrackNet-family,
  by recollection — but the citation must be verified from a primary source before it
  appears in any report; do not cite from memory. **[AMENDED v1.5 — D18/D22; was: "tennis-ball
  tracking"]** The recollection is of work on racquet-sport balls/shuttlecocks, i.e. the
  *old* target, and is retained only as an unverified pointer to the general problem. **No
  verified basketball-tracking reference is known to this project**, and none is invented
  here — if the report needs one, it must be found and read, not recalled. Nothing in this
  module's design depends on that literature: §10's ML arm is zero-shot COCO "sports ball",
  not a tracking paper's method.)

**Phase 6 is executed in two sub-phases (Decision O17): [AMENDED v1.3 — Phase 6 split; see §16]**
- **Phase 6a — software + synthetic-only comparison (may run BEFORE Phase 5).** Builds
  `requirements-ml.txt` (pinned `ultralytics`), the zero-shot ML detector as a second
  `Detector` behind the §5.2 interface, `compare_detectors.py`, and the import-guard
  test. Comparison runs on the §6 simulator scenario library only. Report watermarked
  "SYNTHETIC-ONLY — NOT EVIDENTIARY FOR COMMISSIONING".
- **Phase 6b — real-footage completion (only after Phase 5).** Re-runs the unchanged 6a
  harness on commissioning + campaign clips; produces the final ablation report. No new
  detector code in 6b.
- **Metrics (both sub-phases), extended beyond the original list:** detection rate,
  localisation scatter (px σ), degraded-scenario behaviour, end-to-end landing RMS,
  **confidence-threshold sweep** (detection rate + scatter vs. cutoff — the ML analogue
  of the HSV band), **runtime/footprint** (CPU inference time per frame, install size vs.
  HSV path).
- **Mandatory caveat in the 6a report:** the synthetic ball hue is dead-centre of the
  config HSV band (WO-OPT-1 Stage 6.5), so synthetic results are structurally optimistic
  for the HSV baseline; 6a carries no evidentiary weight for commissioning.

---

## §11 Test Discipline

- pytest suite, green at every phase gate; no phase closes red.
- Unit tests per module: geometry conversions (incl. array-frame polar convention
  round-trips), homography fit + check-point guard, detector on synthetic frames
  (incl. shadowed scenario), tracker association + descent segmentation, parallax
  correction against exact synthetic geometry, sub-frame contact bracket against injected
  contact time, schema round-trip (write → read → byte-stable re-write), atomic-write crash
  tolerance (temp file left behind ≠ corrupted output).
- The §6 synthetic end-to-end acceptance test WITH negative controls is the standing
  regression anchor, exactly as in the main project.
- Numeric tolerances stated per test with a one-line justification (no bare
  `assert abs(x) < 1e-6` without a reason).

---

## §12 Integration Contract with the Main Project

The module is standalone; integration is **read-only, consumer-side, and optional**:
- The ONLY artefact the main project ever reads is `optical_gt.json` (schema §5.6,
  frozen v1.0). The optical module never reads or writes `session.json`, never imports
  main-project code, and vice versa. Shared constants (array geometry, r_ball) are
  duplicated into this project's `config.yaml` with a comment naming their source
  section in CLAUDE.md — deliberate duplication over coupling.
- **Integration point:** campaign analysis only. A future main-project CHANGES.md work
  order (written only if the §8 gate is GO and the team opts in) adds: join on
  session_id → a comparison table camera vs tape vs prediction, with per-throw E_n →
  one section in `campaign.html`. It NEVER replaces the tape solve inside
  `session.json`; the tape protocol remains the reference.
- Precondition for that work order: the §8 gate result and the campaign-subset E_n
  distribution, quoted in the order itself.
- Deeper integration (optical as an accepted ground-truth *source*) is explicitly a
  separate future decision requiring its own spec amendment on BOTH sides, and is
  conditional on sustained |E_n| ≤ 1 performance across a full campaign.

---

## §13 Future Works (recorded, not committed)

- Automated throw detection / clip trimming (motion energy in an ROI; manifest fields
  already reserved).
- HTML report layer mirroring the main project's §12 pages.
- Stereo (second phone) for full 3D trajectory validation of the Kalman output —
  substantially bigger job; explicitly out of v1 scope.
- ML detector fine-tuning on own footage (gated per §10).
- Optical-as-source integration (gated per §12).
- **Full propagation of marker-survey σ through the homography least-squares fit**
  (§7 item 1, Decision D5). v1 charges survey σ as a conservative isotropic constant;
  a proper propagation through the fit Jacobian would yield the (smaller, anisotropic)
  true contribution and remove the partial double-count with `homography_m`. Deferred
  because the conservative constant only inflates the budget — it cannot cause a false
  GO — and the fit-Jacobian propagation is non-trivial to validate. (Added v1.1.)

---

## §14 Staged Work Order (initial build)

**This work order is the final build command and architecture for any executor — AI or
human — that builds this project.** It is written to be followed with no context beyond this
file. Execution discipline: plan the phase first, then build; **stop and confirm at every phase
gate** before proceeding; update IMPLEMENTATION_NOTES_OPTICAL.md as part of each phase, not
after; take a manual folder backup of the project directory before beginning each phase (per
O1 — there is no version control). The executor **self-inspects actual file state before every
edit**; line references in this document are not to be trusted over what is actually on disk.
No phase closes with a red test suite.

**Phase 0 — Scaffold.**
Directory tree (§5), venv, `requirements.txt`, `config.yaml`
(array geometry constants duplicated per §12, marker survey placeholders, tolerances:
`check_point_tol_m: 0.005`, gate `rms_gate_m: 0.015`, HSV band placeholders),
`optical/geometry.py` (array frame, polar conversions) + tests.
*Gate:* suite green; config loads; geometry round-trips pass. STOP — confirm.

**Phase 1 — Simulator.**
`render.py` + `scenarios.py` per §6; known-homography projection verified against
hand-computed points; scenario library incl. negative controls. No pipeline code yet.
*Gate:* rendered fiducial pixel positions match analytic projection to sub-pixel;
suite green. STOP — confirm.

**Phase 2 — Calibration chain.**
`calibration.py` (§5.1): ArUco detection, manual-click UI, LS homography, reprojection
RMS, held-out check point, stability re-check, `homography_<id>.yaml`. Validated
entirely on synthetic frames (known H recovered within tolerance; corrupted-survey
negative control trips the guard). `scripts/calibrate_homography.py`,
`scripts/calibrate_intrinsics.py` (checkerboard flow, testable on synthetic
checkerboard or documented as hardware-only with its unit scope stated).
*Gate:* synthetic H recovery + negative control green. STOP — confirm.

**Phase 3 — Measurement chain.**
`detect.py` (HSV, swappable interface), `track.py`, §5.4 parallax (analytic primary +
lowest-pixel fallback), `contact.py` sub-frame fit, `uncertainty.py` (§7 propagation).
*Gate:* the §6 synthetic END-TO-END acceptance test green, incl. shadowed/blurred
scenarios within their scaled tolerances and both negative controls. STOP — confirm.

**Phase 4 — Outputs and workflow.**
`io_session.py` (frozen schema, atomic writes), `overlay.py` (`landing_overlay.png`),
`process_clip.py` (trim, manifest interaction, terminal summary),
`validate_static.py` (batch static-point runner producing the §8 comparison table and
budget-vs-measured page). Schema round-trip + crash-tolerance tests.
*Gate:* full suite green; a synthetic clip processed end-to-end produces valid JSON +
overlay + manifest entry. STOP — confirm. **Software complete.**

**Phase 5 — Physical commissioning. [COMPLETE — 2026-07-11 — VERDICT: NO-GO. See §16 v1.6.]**
**First, execute the [C0] phone re-verification gate (§3.1)** — confirm the device in use and
switch only if a better one wins on the criteria. Then execute checklist C1–C7 (§8) with owners
filled in. Produce the commissioning report (both modes: frame-rate verification, intrinsics
RMS, homography RMS + check point, detector scatter, static-point RMS vs gate, mode decision,
GO/NO-GO). STOP — the GO/NO-GO is a human decision recorded in
IMPLEMENTATION_NOTES_OPTICAL.md.
**As executed: device switched to iPhone 15 Pro Max at [C0] (single-mode collapse, no
720p/480-equivalent); C1–C6 PASS (C5 accepted with `check_point_fail` documented); C7 static-
point gate NO-GO, RMS 64.4 mm vs the pre-registered 15 mm criterion (not renegotiated). Full
diagnosis in `Phase5_Commissioning_Report_2026-07-11.md` and `IMPLEMENTATION_NOTES_OPTICAL.md`.
Per §8, reported as a characterised negative result; no campaign integration attempted; project
CLOSED at this outcome.**

**Phase 6a — OPTIONAL, droppable: ML detector comparison, software + synthetic-only
(§10). [AMENDED v1.3 — Phase 6 split; see §16]**
May run BEFORE Phase 5 (no fieldwork dependency). `requirements-ml.txt` (pinned
`ultralytics`), YOLO detector behind the §5.2 interface, `compare_detectors.py`, and the
import-guard test; the ablation runs on the §6 simulator scenario library only. The report
is watermarked "SYNTHETIC-ONLY — NOT EVIDENTIARY FOR COMMISSIONING" and states the
HSV-optimism caveat (§10).
*Gate:* comparison report produced with the mandatory watermark + caveat; full suite green
with ML installed; core suite still green with ML uninstalled (import-guard test). STOP —
confirm. **Phase 6a complete.**

**Phase 6b — OPTIONAL, droppable: ML detector comparison, real-footage completion (§10).
[AMENDED v1.3 — Phase 6 split; see §16]**
Only on explicit instruction AFTER Phase 5 (requires the [C0] device verdict and the §8
GO/NO-GO). Re-runs the unchanged Phase 6a harness/detector on commissioning + campaign
clips; no new detector code. Produces the final, evidentiary ablation report.
*Gate:* real-footage comparison report produced; core suite still green with ML uninstalled
(import-guard test). STOP — confirm.

---

## §15 Design-Decision Register

| ID  | Decision | Status |
|-----|----------|--------|
| O1  | No git; manual folder backup before every execution phase (matches main project) | Confirmed |
| O2  | All outputs in the array frame, even standalone | Confirmed |
| O3  | Tripod height resolved empirically at C3 (start 1.2–1.5 m @ 3–4 m) | Flagged default |
| O4  | Markers: ArUco AND surveyed pod/centroid marks; one held out | Confirmed |
| O5  | One-time checkerboard intrinsics per used mode | Confirmed |
| O6  | Parallax: analytic centroid correction primary; lowest-pixel fallback; chalk cross-check commissioning-only | Confirmed |
| O7  | `optical_gt.json` schema frozen at v1.0; additive extension only | Confirmed |
| O8  | Simulator-first with negative controls | Confirmed |
| O9  | Gate: RMS ≤ 1.5 cm over ≥ 8 independent static points, pre-registered | Confirmed |
| O10 | Camera validates > 8 campaign throws in-FOV; no throw steering | Confirmed |
| O11 | ML: option B — gated, droppable Phase 6 detector comparison (split into 6a/6b per O17); zone rules binding | Confirmed |
| O12 | Independent static-validation points (not the ultrasonic characterisation set) | Confirmed |
| O13 | Mode decision (720p480 vs 1080p240) made empirically at commissioning; 480 is the working default | Confirmed |
| O14 | v1 outputs = JSON + overlay PNG + terminal summary; no HTML | Confirmed |
| O15 | Integration = read-only campaign-analysis consumer of the frozen schema; never replaces the tape solve | Confirmed |
| O16 | Build on OnePlus 12R; re-verify actual device at [C0] before physical testing, switch only if a better phone wins on the criteria; pipeline is device-agnostic | Confirmed |
| O17 | Phase 6 split into 6a (software + synthetic-only comparison, may run pre-Phase-5, report watermarked non-evidentiary) and 6b (real-footage ablation, only post-Phase-5); §5.2 detector interface, harness, and detector code are shared and built once in 6a — see §16 v1.3 | Confirmed 2026-07-06 |
| O18 | [C0] device switch to iPhone 15 Pro Max is an operator judgment call (simpler file handling), not a criterion-2 win; single-mode collapse (no 720p/480 equivalent) is a permanent, accepted consequence — see §16 v1.6 | Confirmed 2026-07-11 |
| O19 | [C1]'s literal digit-reading genuine-capture test is unworkable at 240 fps on any ordinary display (refresh-rate limited); an inter-frame pixel-difference (duplicate-buffer) test is the accepted substitute — see §16 v1.6 | Confirmed 2026-07-11 |
| O20 | `HsvDetector` circularity measured on the blob's convex hull, not the raw contour (real basketballs' seams/shadow notch the raw contour below any reasonable threshold); `detect.min_area_px` raised 30->1000 to match — see §16 v1.6 | Confirmed 2026-07-11 |
| O21 | [C7] gate (15 mm, O9) NOT renegotiated at closeout despite a NO-GO; project closed as a characterised negative result per §8, with a recorded (not executed) path to a future GO — see §16 v1.6 | Confirmed 2026-07-11 |

---

## §16 Document Changelog

Amendments to this spec after v1.0. Section numbers (§) are the citation standard; each
amendment is also marked inline in its own section with an `[AMENDED …]` note and its
rationale (per §0.2: *amend before building, never after*).

### v1.1 — 2026-07-06

**Trigger:** `AUDIT_REPORT_PHASES_0-4.md` (read-only audit of the Phases 0–4 build,
115/115 tests passing at audit time). This was a **documentation-only** amendment stage
(WO-OPT-1, Stage 0 in `CHANGES_OPTICAL.md`): the spec was brought into line with the
as-built code and audit findings **before** any remediation code is written. No code was
changed in this stage.

Sections amended:

- **§3.2** — Added the named config key `capture.fps_tol_pct` (default 0.5 %, a
  placeholder to be tightened after C1) as the tolerance governing the new `fps_mismatch`
  check. *(Audit finding M2: the production path copied nominal into `fps_measured` and
  never read the real delivered rate.)*
- **§5.5** — Rewritten to describe the **adopted fixed ±0.5-frame bracket** (t* =
  last-descent-frame time + 0.5/`fps_measured`; σ_t = (1/`fps_measured`)/√12) in place of
  the v1.0 sub-frame polynomial-fit promise. Records why the two literal sub-frame designs
  (image-v crossing fit; apparent-size height reconstruction) and the reversal-apex
  variant were built, measured, and rejected in Phase 3, and that the apparent-size route
  is retained investigated-and-dormant, not deleted. *(Audit finding M5.)*
- **§5.6** — Flag vocabulary extended **additively** (O7 preserved — no renames/removals)
  with four reserved flags: `fallback_intrinsics`, `fps_mismatch`,
  `unmeasured_uncertainty_components`, `stability_unchecked`. Also documents the three
  flags the as-built pipeline already emits (`contact_time_bracket`, `contact_time_coarse`,
  `no_prediction`) so the spec matches `optical/io_session.py::FLAG_VOCAB`. *(Audit
  findings M1/M2/M3 + Moderate findings.)*
- **§7 item 1** — Annotated to record that marker-survey σ is charged as a raw isotropic
  per-axis constant (conservative; inflates the budget; partially double-counts with
  `homography_m`), **not** propagated through the fit. Full propagation deferred to §13
  Future Works (Decision D5). *(Audit §7-item-1 finding.)*
- **§13** — Added a Future-Works bullet for the deferred full survey-σ propagation
  (referenced by the §7 item 1 amendment).

**Consistency fixes folded in** (the four §5.5-adjacent statements the rewrite rendered
inconsistent — originally surfaced rather than silently edited, then folded in on Hari's
explicit approval): the **intro sentence** (line ~7) now reads "first-contact instant
bracketed to sub-frame resolution" in place of "sub-frame first-contact fit"; **§7 item 5**
now points at the §5.5 bracket σ_t = (1/`fps_measured`)/√12 × floor velocity rather than
"fit covariance of the §5.5 polynomial at t*"; **§11** now lists "sub-frame contact bracket
against injected contact time"; and the **§5.6 JSON example** now shows `t_subframe: 143.5`
(= `t_frame + 0.5`, which the bracket always yields) in place of the stale `143.38`.

### v1.2 — 2026-07-06

**Trigger:** WO-OPT-1 Stage 4 (audit finding M4) — the Stage 4.3 measurement gate. Adding
bounce scenarios (restitution 0.75) to the simulator and running the full chain showed the
v1.1 bracket is systematically ~0.6 frame late on a `reversal` descent (a real bounce —
the case all real footage produces): landing error 10.12 mm at the nominal camera and
**17.62 mm at a ~12° oblique camera, over the 15 mm §8 gate**. Per the Stage 4.3 stop
rule, execution halted and the anchor-semantics decision was escalated; Hari delegated the
choice (2026-07-06), and the **kink-intersection solve** was adopted (recorded as Decision
D8 in `CHANGES_OPTICAL.md`). Note on §0.2 ordering: the candidate was implemented and
*measured* first, then this amendment written from the measured result — measurement was
the decision input, so the amendment records reality rather than intention.

Sections amended:

- **§5.3** — Confirmed-reversal rule: `track.min_rise` (default 2) consecutive
  non-increasing image-v steps with net strict decrease required to declare a reversal;
  walk-back tolerates an isolated one-frame dip. *(Also resolves the audit Moderate
  "reversal detection has no noise robustness".)*
- **§5.5** — Reversal descents now use the **kink intersection** (pre-contact image-v fit
  × post-peak rebound fit; contact is the kink, invariant to camera obliquity), flag
  `contact_time_kink`; peak-anchor fallback (no +0.5, σ_t = (1/fps)/√3) when unsolvable.
  The v1.1 +0.5 bracket is retained, unchanged, for `track_end` descents where it is
  correct. Measured: bounce 10.12 → 0.15 mm, oblique 17.62 → 0.51 mm, ≤ 0.7 mm under
  noise/blur/shadow; `track_end` path bit-identical.
- **§5.6** — Flag vocabulary extended additively with `contact_time_kink` (Stage 4). Stage 5
  (Decision D6) further annotated §5.6 with the live producer status of the whole vocabulary
  and marked `blur_suspected` **reserved** (producer deferred to Phase 5, where a real-footage
  blur threshold can be set).

### v1.3 — 2026-07-06

**Trigger:** Phase 6 sequencing decision (WO-OPT-2, Stage 0 in `CHANGES_OPTICAL.md`).
Phase 6 (§10) is gated to run "only on explicit instruction after Phase 5," but **Phase 5
physical commissioning has NOT yet been executed** — no fieldwork has occurred and there is
no §8 GO/NO-GO verdict. This is a *not-yet-run* state, **distinct from a formal NO-GO**, and
is recorded as such. To let the Phase 6 software be built now — without weakening the
ablation's evidentiary standard — Phase 6 is split into **6a** (software + synthetic-only
comparison, may run before Phase 5, report watermarked non-evidentiary) and **6b**
(real-footage ablation, only after Phase 5). Decision O17. This is a **documentation-only**
amendment applied **before any Phase 6a code exists** (§0.2: amend before building, never
after); no code and no tests were changed in this stage.

Sections amended:

- **§10** — Appended the Phase 6a/6b split (Decision O17): 6a builds the pinned
  `requirements-ml.txt`, the zero-shot ML detector behind the §5.2 interface,
  `compare_detectors.py`, and the import-guard test, comparing on the §6 simulator library
  only, with a mandatory "SYNTHETIC-ONLY — NOT EVIDENTIARY FOR COMMISSIONING" watermark and
  the HSV-optimism caveat (synthetic ball hue sits dead-centre of the config HSV band per
  WO-OPT-1 Stage 6.5, so 6a is structurally optimistic for the HSV baseline); 6b re-runs the
  unchanged harness on real footage after Phase 5. Metrics extended beyond the original list
  with a **confidence-threshold sweep** and a **runtime/footprint** (CPU inference time per
  frame, install size) line, in both sub-phases.
- **§14** — Replaced the single "Phase 6" work-order entry with separate **Phase 6a** and
  **Phase 6b** entries, each carrying its own stop-and-confirm gate.
- **§15** — Appended row **O17** recording the split; annotated **O11** to point at it.

**Reconciliation (consistency fixes, no substantive change):** references to the old
single-phase "Phase 6" elsewhere in the spec were reconciled to the split and inline-marked —
the **§0.1** dependency ceiling ("Phase 6a/6b only"), the **§5** module-layout tree
(`compare_detectors.py (Phase 6a)`), and the **§5.2** detector-interface note (control arm of
the Phase 6a/6b comparison). Every touched section carries an inline
`[AMENDED v1.3 — Phase 6 split; see §16]` marker so the spec on disk cannot silently drift
from the code built in later stages.

### v1.4 — 2026-07-06

**Trigger:** WO-OPT-3, audit 2026-07-06 remediation (`AUDIT_REPORT_2026-07-06_READONLY.md` —
read-only audit of Phases 0–4 + WO-OPT-1 + WO-OPT-2 Phase 6a, 168/168 tests passing at audit
time). This is **Stage 0** of WO-OPT-3: a **documentation-only** amendment stage (§0.2: amend
before building, never after) that hardens the spec ahead of the Stage 1–5 code changes. **No
code, config, or test file was changed in this stage** — only `CLAUDE.md`. No finding in
WO-OPT-3 changes a computed number on any currently-passing path; it is a false-negative-guard,
robustness, and spec-consistency hardening pass to be completed before Phase 5 commissioning.
(Header note: the v1.0 header number had been advanced to "v1.4" prematurely without a matching
changelog entry; this entry makes the file genuinely v1.4 and reconciles the header with the
history.)

Sections amended:

- **§5.1 (step 5)** — Stability re-check redefined from **drift-only** to **drift AND absolute
  check-point error**: `err_start_m` and `err_end_m` (both already computed by `stability_check`)
  are each thresholded against `check_point_tol_m`; a breach sets the new `stability_abs_fail`
  flag (loud warning, never silent, never an abort). Rationale: a camera bump between calibration
  and clip start yields near-zero drift but a large absolute error — drift alone cannot detect
  it. *(Major 4.1; Decision D10.)*
- **§3.2** — Added `capture.fps_refuse_pct` (default 20 %) beside `fps_tol_pct`. When the rate
  USED for timing disagrees with `fps_nominal` by > 20 % of their mean, `resolve_fps`
  hard-refuses (`OpticalConfigError`, no output written); between `fps_tol_pct` and
  `fps_refuse_pct` the existing `fps_mismatch` flag-and-continue (Decision D2) is unchanged.
  Rationale: playback-rate containers must not let a ~16× wrong temporal base produce a
  plausible-looking JSON. *(Major 4.2; Decision D9.)* **[Wording tightened WO-OPT-3 Stage 2,
  Hari-approved 2026-07-06: "USED rate vs nominal", not "any two available sources" — the
  literal any-pair rule would refuse every real slow-mo clip whose container reports the
  playback rate while `--fps-measured` correctly supersedes it; the superseded container still
  trips the D2 flag, never the refuse.]*
- **§5.6 (flag vocabulary, additive)** — Added `check_point_fail` (producer existed in
  `calibration.py` since Phase 2 but was never in `FLAG_VOCAB`, so it silently never reached
  per-throw output — this closes that gap) and `stability_abs_fail` (new, per the §5.1
  amendment). `FLAG_VOCAB` grows 14 → 16; both additive under O7. *(Moderate 5.1 + Major 4.1;
  Decisions D10, D12.)*
- **§7 item 1** — `markers.survey_sigma_m` changes shape from a bare number to
  `{value: 0.0025, measured: false}`, matching the four `uncertainty:`-block components from
  WO-OPT-1 Stage 1; it now participates in the same `unmeasured_uncertainty_components` flag +
  warning + notes-echo machinery. Numeric value (0.0025 m) unchanged — no budget number moves.
  *(Moderate 5.2; Decision D11.)*
- **§5.4** — Documented the optional camera-position tape cross-check hook:
  `calibrate_homography.py --camera-measured X Y Z` (metres, §2 frame) records
  `camera_measured_m`, `camera_decomposed_m`, and `camera_delta_m` (per-axis + norm) in the
  calibration YAML. Informational only — no threshold, no flag, no abort. Absent the argument,
  the YAML shape is unchanged. *(Moderate 5.5; Decision D13.)*
- **§9 (trimming)** — Added the requirement that any clip containing a bounce must retain ≥ 3
  frames after the bounce peak, with rationale (an unconfirmed reversal at clip end degrades to
  the +0.5-frame bracket under `contact_time_bracket`, reintroducing the ~0.6-frame late bias
  with no distinguishing signal from a normal vanish-ending clip). Manual-trim procedure
  requirement; no heuristic flag. *(Moderate 5.6; Decision D14.)*
- **§8 (checklist)** — Declared `--fps-measured` mandatory for all real-footage processing runs,
  cross-referenced to [C1]. Procedural guidance; the §3.2 `fps_refuse_pct` refuse is the
  code-side backstop. *(Major 4.2 field item; Decision D15.)*
- **§5 (module tree)** — Added `errors.py` (typed errors, WO-OPT-1 Stage 5) and `detect_ml.py`
  (Phase 6a ML detector, §10), which exist in the codebase but were never in the spec's module
  list. *(Minor.)*
- **§9 (manifest fields)** — Amended the manifest description to the as-built reality: a
  non-interactive write with `session_id`, `file`, `mode`, `calib_id`, `in_frame`/`out_frame`,
  and a single free-text `notes` field; wind/lighting/operator initials are captured within
  `notes` for now (dedicated fields remain a possible additive extension). *(Minor;
  Decision D16.)*

**Decisions D9–D16** are embedded in the WO-OPT-3 work order (`CHANGES_OPTICAL.md`) and are cited
inline above; per project convention they are appended to the design-decision register at the
work-order closeout (in `IMPLEMENTATION_NOTES_OPTICAL.md`), not in §15 at this stage.

### v1.5 — 2026-07-10

**Trigger:** Main-project Decision **D6** (main `CLAUDE.md` v2.6/v2.7 — the throw target changed
from a tennis ball to a basketball, with a **measured** `radius_m = 0.1194 m`), executed here as
work order **WO-OPT-4**, Stage 0. The optical module is the independent cross-validation
instrument for the *same physical throws*; it must track the same ball or it is no longer
measuring the same object as its reference instrument.

**Why this is not automatic.** §12 forbids importing from the main project: `r_ball` and the
array geometry are **duplicated** into this module's `config.yaml`, not shared at runtime.
Therefore the main project's D6 config edit does **not** propagate here. Every live tennis→basketball
reference in the optical spec, config, simulator, and code must be changed independently. That
is the whole of WO-OPT-4.

This is Stage 0: a **documentation-only** amendment stage (§0.2: *amend before building, never
after*). **No code, config, or test file was changed in this stage** — only this file. No
computed number on any currently-passing path moves as a result of this stage; the numbers move
in Stages 1–4, and Stage 4's synthetic end-to-end acceptance re-run is the load-bearing gate
that proves they moved correctly. Baseline at drafting: **168 passing tests** (WO-OPT-3
audit-time count).

**Approved parameters** (copied from the main D6 measured record — *not* re-measured and *not*
re-placeholdered, so the two configs cannot drift):

| Quantity | Old (tennis) | New (basketball) | Provenance |
|---|---|---|---|
| `ball.radius_m` | 0.0335 m | **0.1194 m** | Measured 2026-07-09; circumference C = 0.750 m (tape, ±2 mm), r = C/2π, size-7 |
| ball mass (record only) | ~0.058 kg | **0.620 kg** | Main D6 register (scale) |
| detection colour | tennis yellow-green | **basketball orange** | This work order (**placeholder band — unverified**) |

Exact geometric consequences, used throughout: radius ratio 0.1194/0.0335 = **×3.56**; rendered
pixel-area ratio = 3.56² ≈ **×12.7**; the §5.4 parallax centroid height at contact grows the same
**×3.56**.

> **Honesty flag (carried from the work order).** `radius_m = 0.1194 m`, C = 0.750 m and mass
> 0.620 kg are the main project's *measured* figures and are authoritative for the shared ball.
> The **HSV orange band** and the **detector area band** are **placeholders, not measured
> values**; they must be tuned on real footage at checklist **C6** (§8), exactly as the tennis
> band was a placeholder. They are marked as such at every point they appear.

Sections amended:

- **Header / intro (line ~4)** — "films a **tennis-ball** throw" → "films a **basketball**
  throw". Version header v1.4 → **v1.5**.
- **§2 (Coordinate/Geometry Contract)** — `r_ball` 0.0335 m (tennis ball) → **0.1194 m
  (basketball)**, with the measured provenance recorded inline and the §12 duplication note.
  The cross-reference to main spec §5.3 is retained. *(D17.)*
- **§5.2 (Ball detection)** — "tennis-ball yellow-green band" → "basketball orange band", with
  an explicit note that the literal values live in `config.yaml` (never in this file) and that
  the shipped orange values are an unverified placeholder for C6. *(D18.)*
- **§5.4 (Parallax correction)** — Added a note that the closed-form correction is *parametric
  in h and unchanged*, but h = r_ball has grown ×3.56, so the correction's **systematic
  magnitude** scales by that factor. *(Stage-5 correction: the note's initial claim that the
  uncertainty contribution ALSO scales ×3.56 was overstated and was fixed after inspecting the
  budget — only the camera-position (σ_C) residual terms scale with h; the σ_h term is
  h-independent, and with the shipped σ_C = 0 placeholder the `parallax_residual_m` line is
  identical, 5.35 mm, at both radii. See the corrected §5.4/§7 notes.)* The camera-position
  cross-check becomes more load-bearing and the zero-h lowest-pixel fallback a comparatively
  stronger cross-check. *(D20.)*
- **§5.5 (Contact instant)** — The tennis-specific "of order a few ms … possibly zero or one
  true contact frames even at 480 fps" claim is **withdrawn, not transferred**. Replaced with:
  basketball contact duration has NOT been verified against a primary source, may span more
  frames at 480 fps, and must be confirmed empirically at commissioning rather than assumed. **No
  millisecond figure is invented.** The bracket/fit rationale is unchanged (first contact falls
  between samples regardless of contact span); the kink solve's frame margin and the §5.3
  `min_rise` window are flagged for re-examination on real footage. *(D21.)*
- **§6 (Simulator)** — "drawn ball … tennis-ball colour" → "basketball orange", noting the draw
  colour is held dead-centre of the config HSV band (the WO-OPT-1 Stage 6.5 invariant) so the
  §10 Phase-6a HSV-optimism caveat stays true after the substitution. *(D18.)*
- **§7 item 4 (Parallax residual)** — σ(r_ball surrogate = ball compression at contact) is now a
  basketball quantity and is **unmeasured**; it ships as a placeholder (`measured: false`) and
  must keep raising the `unmeasured_uncertainty_components` flag (§5.6) until measured at C6. No
  compression figure is invented; the old one is not rescaled. *(D20.)*
- **§10 (ML phase)** — The "tennis-ball tracking (TrackNet-family)" recollection is reworded to
  the general problem of ball tracking in sports video, with the existing "verify from a primary
  source; do not cite from memory" caveat **kept verbatim in force**. Recorded explicitly: **no
  verified basketball-tracking reference is known to this project and none was invented**;
  nothing in the design depends on that literature (§10's ML arm is zero-shot COCO "sports
  ball", not a tracking paper's method).

**Decisions D17–D21** (register text copied verbatim from `CHANGES_OPTICAL.md` §2, so the
register stays consistent across documents):

- **D17** — Adopt basketball as the optical target. `r_ball` 0.0335 → 0.1194 m, duplicated from
  the main D6 measured record (same physical ball; §12 forbids importing it).
- **D18** — HSV detection band retargeted yellow-green → orange. Shipped values are a
  **placeholder** (tune at C6). The synthetic draw colour is kept **dead-centre of the new orange
  band** to preserve the WO-OPT-1 Stage 6.5 invariant (so the Phase 6a HSV-optimism caveat stays
  accurate).
- **D19** — Detector **area band** re-derived from the *rendered* synthetic basketball size
  (~×12.7 area), not hardcoded. Provisional widening in Stage 1, finalised from measurement in
  Stage 4.
- **D20** — Parallax correction magnitude and its uncertainty component (§5.4, §7 item 4) grow
  ~×3.56. Correction remains parametric/exact; the σ(`r_ball` surrogate = contact compression)
  term is re-characterised for the basketball at C6 (not fabricated). *(Register text as
  drafted in CHANGES_OPTICAL.md §2; PRECISION-CORRECTED at Stage 5: only the correction's
  systematic magnitude and the σ_C residual terms scale ×3.56 — the σ_h residual term is
  h-independent, so with σ_C = 0 the measured `parallax_residual_m` is unchanged between radii.
  See the corrected §5.4/§7 amendment notes.)*
- **D21** — §5.5 contact-duration narrative re-examined: a basketball's contact is longer than a
  tennis ball's, so the "possibly zero or one true contact frames at 480 fps" statement may no
  longer hold (several contact frames now plausible). Duration to be **verified from a primary
  source** before any number is quoted; the reversal/kink solve margin is re-checked (Stage 5).

*(**D22** — optional, gated: Phase 6a ML ablation re-run on the orange synthetic library — is
recorded in the work order and applies only if Stage 6 is executed.)*

Per project convention, D17–D21 are appended to the design-decision register in
`IMPLEMENTATION_NOTES_OPTICAL.md` at work-order closeout (Stage 5), not to §15 at this stage.
**Open judgment call carried forward** (`CHANGES_OPTICAL.md` §5 item 5): the spec's own register
is the **O-series** (O1–O17) while WO-OPT-3/4 continue a **D-series**; which register D17–D21
ultimately live under is unresolved and is Hari's call at closeout.

**Scope guard (unchanged by this amendment):** the frozen `optical_gt.json` schema (O7) — `r_ball`
is a config constant, never a JSON key, so no key is added, renamed, or removed; the geometry /
homography / (r, θ) conversions — `r_ball` is a contact-height constant, not a projective
parameter; the reference protocol and gates — the three-tape multilateration reference, the §8
**15 mm GO/NO-GO gate**, `check_point_tol_m`, and the E_n statistic are untouched; and the main
project — WO-OPT-4 writes only inside the optical directory (§12).

### v1.6 — 2026-07-11 — PHASE 5 CLOSEOUT: PROJECT CLOSED, VERDICT NO-GO

**Trigger:** execution of Phase 5 physical commissioning (§14), the final planned phase of this
module. All of checklist C0–C7 (§8) was carried out in one field session. This is the project's
closeout amendment: it records the human GO/NO-GO decision (§14's own requirement) and closes the
module per §8's explicit negative-result path. Full as-executed detail, every measured number,
every code fix, and every diagnostic is in `IMPLEMENTATION_NOTES_OPTICAL.md` (Phase 5 entries)
and summarised in `Phase5_Commissioning_Report_2026-07-11.md`; this entry is the spec-level
record of the outcome, not a restatement of the fieldwork.

**[C0] Device.** Switched from the OnePlus 12R baseline to an **iPhone 15 Pro Max** — an
operator judgment call (simpler/more predictable file handling), not a criterion-2 win (the
iPhone's 240 fps slow-mo is objectively slower than the 12R's spec'd 480 fps mode). Per §3.1
device-agnosticism, only C1 (frame-rate) and C2 (intrinsics) needed redoing for the new device;
both passed. The iPhone has no 720p/480-equivalent second mode, so the §4 two-mode RMS
comparison **collapses to the single 1080p240 mode** for this device — recorded as a permanent
consequence of the C0 decision, not a v1 defect.

**[C1]–[C6]: PASS**, with two notable field-driven corrections folded in as real findings
(detailed in IMPLEMENTATION_NOTES, not restated here):
- **[C1]'s literal digit-reading PASS test is unworkable at 240 fps on any ordinary display**
  (no display refreshes fast enough) — an inter-frame pixel-difference (duplicate-buffer) test
  was substituted as a stronger, display-independent verification of genuine (non-interpolated)
  capture. This is a genuine, display-refresh-limited gap in §3.2's literal procedure, surfaced
  by real fieldwork rather than assumed away; not formally re-worded into §3.2 at this closeout
  (recorded here and in IMPLEMENTATION_NOTES as a carried-forward documentation item, since the
  project closes at this result).
- **[C5] was accepted with `check_point_fail` documented** (9.9 mm vs the 5 mm tolerance) — an
  explicit operator judgment call, on the reasoning that 5 mm is a strict intermediate integrity
  guard, distinct from the actual accept/reject gate at C7 (15 mm).
- **[C6] required a genuine code fix, not just a config retune:** the shipped HSV orange-band
  placeholder found ZERO detections on the real basketball, whose true colour is red and straddles
  OpenCV's hue wraparound (0°/180°) — `cv2.inRange` cannot express this in one call.
  `optical/detect.py`'s `HsvDetector` gained a second, optional hue range (`hsv_lower2`/
  `hsv_upper2`), OR'd into the mask; `simulator/render.py`'s synthetic-hue-centring invariant
  (WO-OPT-1 Stage 6.5) was extended to compute the correct wraparound-aware band centre. Both
  changes are additive/backward-compatible. `sigma_h_m` (ball-compression uncertainty) was
  measured via a documented physics model (half-cycle spring-contact) combining a literature
  contact-duration figure with this project's own real ultrasonic velocity data (34 sessions) —
  the two primary-source fetch attempts for that literature figure both returned HTTP 403, so it
  is recorded as a search-synthesised, not directly-verified, figure; this does NOT retire the
  separate D21 contact-duration-unverified item.

**[C7] — THE GATE — VERDICT: NO-GO.** Pre-registered criterion (§8/O9): RMS ≤ 15 mm over ≥ 8
static points, fixed before data, explicitly not renegotiable. **Achieved: RMS 64.4 mm
as-captured** (10 points; the accepted C5 homography applied as the pipeline actually runs),
**55.3 mm under a best-case diagnostic** (camera-drift removed via a per-clip re-derived
homography, plus the tape-measured rather than H-decomposed camera position for parallax). Both
exceed the gate by more than 3×.

A genuine detector bug was found and FIXED mid-gate (not a config issue): `HsvDetector`'s
circularity filter was measured on the raw contour, and a real basketball's dark seam lines plus
a shadowed underside notch the mask enough to crater circularity below the threshold on an
otherwise correctly-sized, correctly-positioned ball blob — rejecting the true ball in favour of
tiny background specks. First (buggy) gate run: RMS 1799.7 mm, one point off by 5.3 m. Fixed by
measuring circularity on the blob's **convex hull** instead of the raw contour, and raising
`detect.min_area_px` from a tennis-era 30 to a realistic 1000 (both in `optical/detect.py` /
`config.yaml`). Full core suite green after the fix (185 passed, 0 failed). This fix is real and
retained regardless of the gate outcome.

**Root-cause diagnosis of the residual NO-GO (§8's required "characterised negative result with
its diagnosis"), by contribution:**
1. **~17 mm homography/survey/planarity/intrinsics floor** (dominant) — a held-out FLAT floor
   marker (zero parallax) still maps 8.9–24.3 mm off under a fresh, contemporaneous homography.
   Sub-causes not separately deconvolved: marker-survey ABSOLUTE accuracy (`trilateration_
   survey.py` solves against the array's IDEAL/design reference geometry, never a physical survey
   of the real array — low trilateration residuals prove only tape-distance consistency, not
   absolute correctness); intrinsics (the C2 checkerboard's centrally-clustered pose coverage left
   k3 weakly constrained, worst at the frame periphery where far/off-axis points sit); outdoor
   paving non-planarity (the §3.1/§8 risk register's own named risk).
2. **~20–40 mm camera movement** between the C5 calibration and the C7 capture (~1 hour + a full
   C6 stage later) — measured directly (the fixed floor markers map 20–42 mm off through the C5
   homography, a coherent rigid shift, not per-marker noise). A §3.1c "camera must not move"
   field-procedure violation; the session's own automatic stability re-check could not run
   (`stability_unchecked` — the held-out marker was absent from the static clips' sampled frames).
3. **~7 mm** from the H-decomposed (vs tape-measured) camera position feeding the parallax
   correction — a minor contributor; the decomposed and tape positions were already within ~40 mm
   of each other.
4. **One outlier point** (135–152 mm regardless of method) isolated to a single static position,
   most likely a ball-placement/survey mismatch there, not a systematic optical error.

**None of the residual is a remaining software bug.** The detector bug was the only true bug in
the pipeline and is fixed and verified. Everything contributing to the NO-GO is physical:
absolute survey accuracy, intrinsics coverage, ground planarity, and camera stability discipline
— none of which a code change reaches.

**The gate was NOT renegotiated.** During closeout the operator initially proposed accepting the
~55 mm best-case result by relaxing `tolerances.rms_gate_m` from 0.015 to 0.05 — this was
declined: §8, O9, and the Phase 5 field checklist all state the gate is fixed before data and
explicitly not renegotiated after seeing results, and a 55 mm reference cannot usefully
cross-validate an ultrasonic system whose own predictions already carry ~20 mm uncertainty.
`tolerances.rms_gate_m` remains **0.015**, unchanged throughout this closeout. The honest NO-GO,
with this diagnosis, is what is recorded.

**Per §8: NO-GO in the only available mode = the module is reported as a characterised negative
result with its diagnosis. No campaign integration is attempted (§12's integration work order is
never written).** This is an explicitly valid outcome per this document's own Purpose statement
("a large [disagreement] is a characterised limitation... either outcome is a valid
measurement-engineering result").

**PROJECT STATUS: CLOSED at this result.** A path to a future GO is recorded (not executed, a
fresh field session): physically survey the real array reference geometry; re-shoot the C2
checkerboard with deliberate frame-corner pose coverage; use a flatter/planarity-mapped surface;
lock the camera and run the §5.1 stability re-check immediately after calibration AND after the
last capture. Software follow-ups surfaced but non-blocking (`scripts/validate_static.py`'s
whole-clip memory load crashed the operator's PC on this session's 10 real clips and needs a
streaming/sampled rework; the Phase 6a ML ablation should be re-run against the corrected ball
hue; the two real detector fixes this session have no synthetic regression test yet) are logged
in the project's task list, not in this spec.

**Files touched this closeout:** `CLAUDE.md` (this entry; header/status banner; §14 Phase 5
entry marked complete). `IMPLEMENTATION_NOTES_OPTICAL.md` (parallel closeout entry, all
per-stage measured detail). `Phase5_Commissioning_Report_2026-07-11.md` (new — the summary
sign-off document). No code file touched at this closeout stage (all code fixes were made and
verified during the C6/C7 fieldwork itself, per the entries above).
