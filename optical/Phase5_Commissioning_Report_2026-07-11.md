# Phase 5 Commissioning Report — Optical Ground-Truth Landing Module

**Project:** Optical Ground-Truth Landing Module (Optical.md v1.5), Politecnico di Milano,
Measurements for Mechanical Engineering, A.Y. 2025-26.
**Session date:** 2026-07-11.
**Venue:** outdoor paved area (overcast/daylight).
**Device:** iPhone 15 Pro Max, slow-motion 1080p @ 240 fps.
**Verdict:** **NO-GO** against the pre-registered 15 mm gate (§8/O9).

> This report is the §14 Phase-5 / checklist sign-off deliverable. The GO/NO-GO decision is a
> human decision, recorded here and in `IMPLEMENTATION_NOTES_OPTICAL.md`. The as-built per-stage
> detail, problems, and code changes are in `IMPLEMENTATION_NOTES_OPTICAL.md` (Phase 5 entries);
> this report is the summary.

---

## Executive summary

The automated optical ground-truth pipeline was commissioned end-to-end (video in ->
(r, theta) out, no operator measurement of the landing). Every checklist item C0-C7 was executed.
The pipeline is functional and, after a detector fix made this session, produces
physically-sensible landings. **However, the static-point validation gate returned NO-GO:**
measured RMS disagreement vs the tape reference was **64.4 mm as-captured** (55.3 mm under a
best-case camera-drift-removed diagnostic), against the **pre-registered 15 mm criterion**. The
gate tolerance was **not** renegotiated. The dominant error is physical (marker-survey absolute
accuracy, intrinsics, ground planarity, camera stability), **not** the software pipeline.

Per §8, no campaign integration is attempted; the module is reported as a **characterised
negative result with its diagnosis**. This is a valid measurement-engineering outcome: it
demonstrates the automation is achievable and quantifies how close it got (~5.5-6.5 cm), with a
clear, actionable list of what limits it.

---

## Checklist results

| Item | Result | Key numbers |
|------|--------|-------------|
| **[C0]** Phone re-verification | Switched OnePlus 12R -> **iPhone 15 Pro Max** | Genuine capture verified; single mode 1080p240; exposure lock available. Operator judgment call (see notes). |
| **[C1]** Frame-rate verification | **PASS** | 239.98 fps (container 239.976; 0/1013 near-duplicate frame pairs — genuine capture, not interpolated). Digit-reading test unworkable at 240 fps; inter-frame-MSE method used instead. |
| **[C2]** Checkerboard intrinsics | **PASS** | RMS reproj **0.52 px**, 18/18 views. Caveat: poses centre-clustered, k3 weakly constrained (relevant to C7). |
| **[C3]** Tripod geometry | **PASS** | Height 1.28 m, standoff 3 m, camera centre (-0.5892, 1.28, -2.9297) m, bearing 114.7 deg. Repositioned once before any calibration. |
| **[C4]** Marker survey | **PASS** | 8 ArUco (ids 0-7), survey residuals 0.2-6.0 mm; id 1 held-out (re-surveyed to 2.01 mm). survey_sigma 2.5 mm. |
| **[C5]** Homography calibration | Accepted **with `check_point_fail`** | Reproj RMS 2.63 px, held-out check-point **9.9 mm** (tol 5 mm). Required a manual-click tool for 2 undetected markers. calib_id `2026-07-11_E`. |
| **[C6]** Detector characterisation | **PASS** (required a code fix) | HSV band retuned to the real ball (red, hue wraparound — needed a two-range mask code change); pixel-localisation sigma **0.25 px** (100% detection at 3 static points); ball-compression sigma_h 2.97 mm (physics model + real ultrasonic velocities). |
| **[C7]** Static-point validation — **THE GATE** | **NO-GO** | RMS **64.4 mm** (as-captured) / 55.3 mm (best-case) vs **15 mm** gate, 10 points. |

---

## The gate (C7) in detail

- **Points:** 10 independent surveyed static positions (>= 8 required), spread across the FOV.
- **Procedure:** each clip run through the full optical pipeline (detect -> undistort -> map ->
  parallax-correct with r_ball), compared to the tape-trilateration survey.
- **Per-point error (as-captured, C5 homography):** 8.9, 11.5, 13.9, 14.9, 28.2, 39.0, 41.2,
  72.3, 92.2, **152.1** mm. RMS 64.4 mm, max 152.1 mm.
- **A real detector bug was found and fixed mid-gate:** the HSV mask's circularity was measured
  on the raw contour, which the basketball's dark seams + shadowed underside notch below the
  threshold — rejecting the true ball in favour of tiny background specks (first run: RMS
  1799 mm, one point off by 5.3 m). Fixed by measuring circularity on the convex hull and
  raising the area floor 30 -> 1000 px^2. Full core test suite green after the fix (185 passed).

### Diagnosis of the residual (why NO-GO)

1. **~17 mm floor-mapping floor** (dominant). A held-out FLAT floor marker (zero parallax) maps
   8.9-24.3 mm off even under a fresh, contemporaneous homography — already above the gate.
   Sub-causes (not separately deconvolved): marker-survey absolute accuracy (surveyed against the
   array's *ideal* geometry, not physically measured), weak k3 intrinsics at the frame periphery,
   outdoor paving non-planarity.
2. **~20-40 mm camera movement** between the C5 calibration and C7 capture (measured directly via
   the fixed markers mapping 20-42 mm off, coherent rigid shift). A §3.1c field-procedure
   violation; the drift-removed re-analysis drops RMS to 55.3 mm.
3. **~7 mm** parallax from the H-decomposed camera position (minor; decomposed C within ~40 mm
   of tape).
4. **Static-2** is a single 135-152 mm outlier regardless of method — likely a ball-placement vs
   survey mismatch at that point, not an optical error.

**None of the residual is a remaining software bug** — the detector bug was the only true bug and
is fixed. Everything left is physical.

---

## Mode decision

Only one high-fps mode exists on the iPhone 15 Pro Max (1080p @ 240 fps), so the §4 two-mode RMS
comparison collapses to a single mode. No mode choice to make.

---

## Path to a future GO (recorded, not executed — a fresh field session)

1. **Physically survey the real array reference geometry** (replace the ideal S1/S2/S3 positions
   used by `trilateration_survey.py`) — likely the single highest-value fix.
2. **Re-shoot the C2 checkerboard** with deliberate frame-corner pose coverage (better k3 /
   peripheral undistortion).
3. **Flatter / verified-level surface**, or map the floor planarity and correct for it.
4. **Lock the camera** and run the §5.1 stability re-check immediately after calibration AND
   after the last capture (this session's could not run — the held-out marker was absent from the
   static clips' frames).
5. **Re-check Static-2's** placement/survey.

None are software changes; the pipeline itself is validated end-to-end.

---

## Notes / caveats carried from the session

- **[C0]** The iPhone (240 fps) is objectively slower than the OnePlus 12R's spec'd 480 fps mode;
  the switch was an operator judgment call (container-handling convenience), not a criterion-2
  win. Recorded as such in `IMPLEMENTATION_NOTES_OPTICAL.md`.
- **[C6]** `sigma_h_m` (ball compression) used a physics model + literature contact-duration
  figure that could NOT be verified against a primary source directly (403-blocked); it is a
  documented engineering estimate, and the separate §5.5/D21 "contact duration unverified" item
  remains open.
- **Software follow-ups** (non-blocking): `validate_static.py` memory scalability (crashed on 10
  full clips); Phase-6a ML ablation should be re-run against the corrected ball hue; no synthetic
  regression test yet pins the two-range HSV mask / hull-circularity fixes.
- **Session-end stability re-check** was not completable (held-out marker absent from static
  frames) — a further reason the as-captured gate carries a camera-drift confound.

---

## Sign-off

- **Commissioning report produced:** yes (this document).
- **GO / NO-GO decision (human):** **NO-GO** — recorded here and in
  `IMPLEMENTATION_NOTES_OPTICAL.md`, 2026-07-11. Gate criterion (15 mm) preserved, not
  renegotiated.
- **Operator:** ______________________  **Date:** ______________
- **Reviewer:** ______________________  **Date:** ______________
